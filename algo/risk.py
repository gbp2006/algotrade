"""Риск-надстройки поверх сайзинга: ATR (переиспользуемый `algo.atr`).

ATR по умолчанию ВЫКЛЮЧЕН: включается только явным `risk_vol: true` в настройках
робота (ADR 27.11). `algo.atr` — отдельный модуль, его можно использовать в
любом роботе, не завися от конфигураций и стратегий. Дневной лимит убытка
удалён (ADR 27.11).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import atr as atr_mod
from .portfolio import exposure_of


@dataclass(frozen=True)
class RiskLimits(atr_mod.AtrLimits):
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


def size_with_risk(equity: float, price: float, mult: float,
                   base_exposure: float, ratio: float | None = None,
                   limits: RiskLimits = DEFAULT_LIMITS) -> int:
    """Лот с учётом резки по волатильности и потолка контрактов."""
    return atr_mod.size(equity, price, mult, base_exposure, ratio, limits)


def contracts_for_config(cfg, equity: float, price: float, mult: float,
                         m5, rows: list[dict] | None = None, day=None,
                         capital: float = 0.0) -> tuple[int, str]:
    """Лот конфигурации. Без явного `risk_vol` — обычный `size_contracts`.

    `rows/day/capital` оставлены в сигнатуре для совместимости вызовов бумажного
    раннера и отчёта: дневной лимит убран, эти аргументы не используются.
    """
    notes = []
    ratio = None
    if (atr_mod.enabled(cfg.params) and m5 is not None
            and len(m5) >= DEFAULT_LIMITS.baseline):
        ratio = vol_ratio(m5)
        notes.append(f"ATR×{ratio:.2f}" if ratio is not None else "ATR: мало данных")
    n = size_with_risk(equity, price, mult, exposure_of(cfg), ratio)
    return n, "; ".join(notes)
