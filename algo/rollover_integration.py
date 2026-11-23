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
    """Дневные объёмы контрактов за окно до дня решения.

    Фinam не отдаёт D1-бары для квартальных контрактов, поэтому сначала
    пробуем D1, а при пустом ответе Aggregate из M5 (он же используется
    бумажным контуром). Без объёмов front_on молча упадёт к ближайшей
    экспирации — это не то, что мы хотим проверять перед December roll.
    """
    end = day.isoformat() + "T23:59:59Z"
    cols: dict[str, pd.Series] = {}
    for sym in symbols:
        for tf, span in (("TIME_FRAME_D1", lookback * 2),
                         ("TIME_FRAME_M5", lookback)):
            start = (day - dt.timedelta(days=span)).isoformat() + "T00:00:00Z"
            try:
                df = broker.bars(sym, tf, start, end)
            except Exception:  # noqa: BLE001 — пробуем следующий таймфрейм
                continue
            if df is None or df.empty or "vol" not in df:
                continue
            series = df["vol"].resample("1D").sum()
            if series.fillna(0).sum() > 0:
                cols[sym] = series
                break
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
