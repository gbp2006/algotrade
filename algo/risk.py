"""Риск-модуль: волатильностная резка экспозиции и дневной лимит убытка.

Подготовлен 20.11.2026, **не включён в живой контур**: ADR от 19.11 требует
сначала чистый месяц без резки сайза. Реестр новых конфигураций —
`algo/risk_configs.py`; в `CONFIGS` они не попадают, пока не будет решения.

Логика повторяет правило автора: 200% → 100% → 50% → 20–30% по мере роста
волатильности. База — ATR(14) к медиане ATR(14) за последние 252 бара.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .portfolio import size_contracts


@dataclass(frozen=True)
class RiskLimits:
    atr_fast: int = 14
    atr_baseline: int = 252
    # (отношение ATR к медиане, экспозиция) — пороги по возрастанию
    ladder: tuple = ((1.10, 2.0), (1.25, 1.0), (1.50, 0.5), (float("inf"), 0.3))
    max_daily_loss_pct: float = 0.03
    max_qty: int = 200


DEFAULT_LIMITS = RiskLimits()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Средний истинный диапазон по OHLC."""
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def vol_ratio(df: pd.DataFrame, limits: RiskLimits = DEFAULT_LIMITS) -> float | None:
    """ATR(14) последнего бара / медиана ATR(14) за базовое окно."""
    a = atr(df, limits.atr_fast)
    if len(a) < limits.atr_baseline:
        return None
    base = float(a.iloc[-limits.atr_baseline:].median())
    if base <= 0:
        return None
    return float(a.iloc[-1]) / base


def exposure_for(ratio: float | None, limits: RiskLimits = DEFAULT_LIMITS) -> float:
    """Экспозиция по лестнице волатильности. Нет данных — полная база."""
    if ratio is None:
        return 2.0
    for threshold, exposure in limits.ladder:
        if ratio <= threshold:
            return float(exposure)
    return 0.3


def daily_loss_allowed(equity: float, day_start_equity: float,
                       limits: RiskLimits = DEFAULT_LIMITS) -> bool:
    """Запрет новых входов после дневного убытка сверх лимита."""
    if day_start_equity <= 0:
        return False
    return (day_start_equity - equity) <= limits.max_daily_loss_pct * day_start_equity


def size_with_risk(equity: float, price: float, mult: float,
                   base_exposure: float, ratio: float | None = None,
                   limits: RiskLimits = DEFAULT_LIMITS) -> int:
    """Лот с учётом резки по волатильности и потолка контрактов."""
    exp = min(float(base_exposure), exposure_for(ratio, limits))
    return min(size_contracts(equity, price, mult, exp), limits.max_qty)
