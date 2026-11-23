"""Общие хелперы перекладки для бумажного и боевого раннеров.

Включается флагом `ALGO_VOL_ROLLOVER=1`. Пока флаг снят, раннеры работают по
прежней схеме `instruments.symbol()` — это страхует идущий бумажный тест.
Логика выбора ноги и даты экспирации — в `algo/rollover.py`.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

import pandas as pd

from . import instruments, rollover

FLAG = "ALGO_VOL_ROLLOVER"


def enabled() -> bool:
    return os.environ.get(FLAG, "0") == "1"


def volumes_for(broker: Any, symbols: list[str], day: dt.date,
                lookback: int = 12) -> pd.DataFrame | None:
    """Дневные объёмы контрактов за окно до дня решения."""
    start = (day - dt.timedelta(days=lookback * 2)).isoformat() + "T00:00:00Z"
    end = day.isoformat() + "T23:59:59Z"
    cols: dict[str, pd.Series] = {}
    for sym in symbols:
        try:
            df = broker.bars(sym, "TIME_FRAME_D1", start, end)
        except Exception:  # noqa: BLE001 — нет баров → fallback по дате экспирации
            continue
        if df is None or df.empty or "vol" not in df:
            continue
        cols[sym] = df["vol"].resample("1D").sum()
    return pd.DataFrame(cols) if cols else None


def front_symbol(inst, day: dt.date, volumes: pd.DataFrame | None = None) -> str:
    """Рабочий символ инструмента на день: по VOL при флаге, иначе как раньше."""
    if not enabled() or inst.symbol:  # вечный контракт или старый режим
        return instruments.symbol(inst, day)
    contracts = instruments.active_contracts(inst, day)
    if not contracts:
        return instruments.symbol(inst, day)
    try:
        return rollover.front_on(day, contracts, volumes)
    except Exception:  # noqa: BLE001 — недоступные данные не должны ронять прогон
        return instruments.symbol(inst, day)


def decision_for_position(day: dt.date, held_symbol: str, qty: int,
                          inst, volumes: pd.DataFrame | None = None,
                          force_before_expiry: int = 7):
    """Решение о перекладке для удерживаемой позиции (или None)."""
    if not enabled() or not qty or rollover.is_perpetual(held_symbol):
        return None
    contracts = instruments.active_contracts(inst, day)
    if held_symbol not in contracts:
        return None
    return rollover.roll_decision(
        day, held_symbol, qty, contracts, volumes,
        policy="volume", force_before_expiry=force_before_expiry)
