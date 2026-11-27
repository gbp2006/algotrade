"""Переиспользуемый ATR-модуль резки экспозиции.

По умолчанию **выключен**: робот должен явно включить `risk_vol` в своих
настройках (ADR 27.11). Модуль не знает ни о стратегиях, ни о счетах: на входе
бары и базовая экспозиция, на выходе — множитель из лестницы волатильности.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .portfolio import size_contracts

# (ATR14 / медиана ATR14 за 252 бара) → потолок экспозиции
DEFAULT_LADDER: tuple = ((1.10, 2.0), (1.25, 1.0), (1.50, 0.5), (float("inf"), 0.3))


@dataclass(frozen=True)
class AtrLimits:
    fast: int = 14
    baseline: int = 252
    ladder: tuple = DEFAULT_LADDER
    max_qty: int = 200


DEFAULT_LIMITS = AtrLimits()


def enabled(params: dict | None) -> bool:
    """Явное согласие робота; отсутствие ключа = выключено."""
    return bool((params or {}).get("risk_vol", False))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Средний истинный диапазон по OHLC."""
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def vol_ratio(df: pd.DataFrame, limits: AtrLimits = DEFAULT_LIMITS) -> float | None:
    """ATR(14) последнего бара / медиана ATR(14) за базовое окно."""
    a = atr(df, limits.fast)
    if len(a) < limits.baseline:
        return None
    base = float(a.iloc[-limits.baseline:].median())
    if base <= 0:
        return None
    return float(a.iloc[-1]) / base


def exposure_for(ratio: float | None, limits: AtrLimits = DEFAULT_LIMITS) -> float:
    """Экспозиция по лестнице; нет данных — полная база."""
    if ratio is None:
        return 2.0
    for threshold, exposure in limits.ladder:
        if ratio <= threshold:
            return float(exposure)
    return 0.3


def size(equity: float, price: float, mult: float, base_exposure: float,
         ratio: float | None = None, limits: AtrLimits = DEFAULT_LIMITS) -> int:
    """Лот с резкой по волатильности и потолком контрактов."""
    exp = min(float(base_exposure), exposure_for(ratio, limits))
    return min(size_contracts(equity, price, mult, exp), limits.max_qty)
