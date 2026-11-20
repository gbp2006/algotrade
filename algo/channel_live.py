"""Живой расчёт «пробоя канала» для бумажного контура.

В бэктесте `channel_break.targets()` строит всю траекторию сделки от входа до
утренней границы; на живых барах будущей границы ещё нет, поэтому здесь считается
только текущее решение по уже закрытому бару:
  - если позиции нет: после switch ждём пробоя HH и открываем лонг (только long);
  - если позиция есть: держим до утренней границы start или до стопа.
Исполнение — по открытию следующего бара с 1 тиком (как в движке).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .strategies.channel_break import _minutes


@dataclass
class ChannelDecision:
    target: int
    price: float
    ts: pd.Timestamp
    detail: str


def _first_at(df: pd.DataFrame, hhmm: str, after=None):
    need = _minutes(hhmm)
    d = df if after is None else df[df.index > after]
    if d.empty:
        return None, None
    minutes = d.index.hour * 60 + d.index.minute
    mask = minutes >= need
    if not mask.any():
        return None, None
    pos = int(np.argmax(mask)) if hasattr(mask, "__len__") else 0
    return d.index[pos], float(d["close"].iloc[pos])


def channel_decision(params: dict, m5: pd.DataFrame, position: int = 0,
                     entry_price: float | None = None) -> ChannelDecision | None:
    if m5 is None or len(m5) < 200:
        return None
    end = m5.index[-1]
    if end.day_of_week >= 5:
        return None

    start = params.get("start", "01:00")
    switch = params.get("switch", "13:00")
    sl = params.get("sl")
    direction = params.get("direction", "long")
    if direction != "long":
        return None  # текущий робот только лонг

    today = m5[m5.index.date == end.date()]
    if today.empty:
        return None
    price = float(today["close"].iloc[-1])

    # утренняя граница: первая свеча дня >= start (в архиве — 09:00)
    b_time, _ = _first_at(today, start)
    if position != 0 and b_time is not None and end >= b_time and b_time == today.index[0]:
        return ChannelDecision(0, price, end, "выход по утренней границе канала")

    # канал: от утренней границы до switch; направление — по закрытиям границ двух дней
    sw_time, _ = _first_at(today, switch)
    if b_time is None or sw_time is None:
        return None
    ch = today[(today.index >= b_time) & (today.index <= sw_time)]
    if ch.empty:
        return None
    hh = float(ch["high"].max())
    ll = float(ch["low"].min())
    if not (hh > ll > 0):
        return None

    prev_days = m5[m5.index.date < end.date()]
    prev_boundary = None
    for day in sorted(set(prev_days.index.date))[-5:]:
        dd = prev_days[prev_days.index.date == day]
        t, c = _first_at(dd, start)
        if t is not None:
            prev_boundary = c
    if prev_boundary is None or price <= 0:
        return None
    b_close = float(today.loc[b_time, "close"])
    up = b_close >= prev_boundary

    if position != 0:
        if sl is not None and entry_price:
            stop = max(ll, entry_price - sl)
            low = float(today["low"].iloc[-1])
            if low <= stop:
                return ChannelDecision(0, price, end,
                                       f"стоп {stop:.3f} (LL/entry-SL)")
        return ChannelDecision(1, price, end, "удержание канала")

    if up and end >= sw_time and price > hh:
        return ChannelDecision(1, price, end, f"пробой HH {hh:.3f}, выход в {start}")
    return ChannelDecision(0, price, end, "ожидание пробоя")
