"""Риск-надстройки поверх сайзинга: ATR (переиспользуемый `algo.atr`) и дневной лимит.

ATR по умолчанию ВЫКЛЮЧЕН: включается только явным `risk_vol: true` в настройках
робота (ADR 27.11). `algo.atr` — отдельный модуль, его можно использовать в
любом роботе, не завися от конфигураций и стратегий.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import atr as atr_mod
from .portfolio import exposure_of, ledger


@dataclass(frozen=True)
class RiskLimits(atr_mod.AtrLimits):
    max_daily_loss_pct: float = 0.03

    @property
    def atr_fast(self) -> int:
        return self.fast

    @property
    def atr_baseline(self) -> int:
        return self.baseline


DEFAULT_LIMITS = RiskLimits()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Обратная совместимость: реализация живёт в `algo.atr`."""
    return atr_mod.atr(df, period)


def vol_ratio(df: pd.DataFrame, limits: RiskLimits = DEFAULT_LIMITS) -> float | None:
    return atr_mod.vol_ratio(df, limits)


def exposure_for(ratio: float | None, limits: RiskLimits = DEFAULT_LIMITS) -> float:
    return atr_mod.exposure_for(ratio, limits)


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
    return atr_mod.size(equity, price, mult, base_exposure, ratio, limits)


def day_start_equity(rows: list[dict], config_id: str, day,
                     mult: float, capital: float) -> float:
    """Equity счёта на начало дня по журналу (закрытый P&L предыдущих дней)."""
    before = [r for r in rows
              if r.get("config") == config_id and str(r.get("date", "")) < str(day)]
    if not before:
        return float(capital)
    return float(ledger(before, config_id, mult, capital)["equity"])


def contracts_for_config(cfg, equity: float, price: float, mult: float,
                         m5, rows: list[dict], day, capital: float) -> tuple[int, str]:
    """Лот конфигурации. Без явного `risk_vol` — обычный `size_contracts`."""
    notes = []
    ratio = None
    if (atr_mod.enabled(cfg.params) and m5 is not None
            and len(m5) >= DEFAULT_LIMITS.baseline):
        ratio = vol_ratio(m5)
        notes.append(f"ATR×{ratio:.2f}" if ratio is not None else "ATR: мало данных")
    if cfg.params.get("risk_daily_loss"):
        start = day_start_equity(rows, cfg.id, day, mult, capital)
        if not daily_loss_allowed(equity, start):
            return 0, f"дневной лимит {DEFAULT_LIMITS.max_daily_loss_pct * 100:.0f}%: вход запрещён"
        notes.append(f"старт дня {start:.0f}")
    n = size_with_risk(equity, price, mult, exposure_of(cfg), ratio)
    return n, "; ".join(notes)
