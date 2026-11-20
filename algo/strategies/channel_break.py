"""«Пробой временного канала» (OsEngine _TimeChannelBreak, И. Коваль-Зайцев).

Порт по правилам из папки ТС (`readme.txt`, `_TimeChannelBreak.cs`,
`разбор/TCBreakClaudeV3.cs`).

Канал и направление:
  - ``start_time`` — граница сессии (в оригинале 01:00: конец торгов и начало
    нового диапазона), ``switch_time`` — старт торгов (15:00);
  - ``channel_mode='night'`` (правила ТЗ): канал HH/LL = максимум/минимум
    баров от switch текущего предыдущего дня до границы start (ночная сессия),
    ``dir=+1`` если close на границе start текущего цикла >= close на границе
    предыдущего цикла;
  - ``channel_mode='day'`` (как на самом деле считает C# `LaunchCalc`): канал
    от ближайшей границы start до switch того же дня; ``dir`` — то же
    сравнение двух соседних границ. Расхождение ТЗ и C# зафиксировано в отчёте.
  - с switch до следующей границы start: close > HH при dir=+1 -> лонг,
    close < LL при dir=-1 -> шорт. Выход по границе start.

Стоп (V3): лонг ``max(LL, entry-SL)``, шорт ``min(HH, entry+SL)``.
Интрабарный stop-order на барах невоспроизводим: если low/high бара задел
уровень, целевая позиция обнуляется на этом баре и движок исполняет выход
по open следующего бара (консервативно — возможен проскальзывающий выход).

Внимание: в архивах MOEX нет баров 00:00–06:00 и меток 01:00, поэтому буквальные
параметры 01:00/15:00 на CNY/Si/RTS невоспроизводимы. Для прокси используется
граница 23:40 (последний час вечерней сессии) — см. `reports/channel-break-research.md`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import daily_first_bar


def _minutes(at: str) -> int:
    h, m = (int(x) for x in at.split(":"))
    return h * 60 + m


def targets(
    df: pd.DataFrame,
    start_time: str = "01:00",
    switch_time: str = "15:00",
    direction: str = "both",
    sl: float | None = None,
    trail_to_channel: bool = True,
    skip_weekend: bool = True,
    volume: int = 1,
    channel_mode: str = "night",
    boundary_mode: str = "exact",
    tick: float = 0.0,
    slippage_ticks: float = 1.0,
) -> pd.Series:
    """Целевая позиция для пробоя временного канала (совместима с `engine.run`).

    direction: "long", "short" или "both" — разрешённые стороны сделки;
    sl=None — стопа нет (только выход по времени), sl=0 с trail_to_channel=True
    даёт стоп по границе канала (поведение V3 при SL=0);
    channel_mode: "night" — канал previous switch -> start (правила ТЗ),
                  "day" — канал start -> switch (оригинальный C#).
    boundary_mode: "exact" — граница только по бару с меткой ровно start_time
                  (как в C#; буквальные 01:00 на MOEX дают 0 сделок),
                  "first_bar" — граница = первая свеча дня с t >= start_time
                  (молчаливая подстановка; на MOEX даёт утреннюю границу).
    """
    if direction not in ("long", "short", "both"):
        raise ValueError("direction must be long/short/both")
    if channel_mode not in ("night", "day"):
        raise ValueError("channel_mode must be night/day")
    if boundary_mode not in ("exact", "first_bar"):
        raise ValueError("boundary_mode must be exact/first_bar")

    out = np.zeros(len(df), dtype=int)
    if len(df) == 0:
        return pd.Series(out, index=df.index, name="channel_break_target")

    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    dates = df.index.normalize()
    date_arr = dates.to_numpy()
    tmin = df.index.hour.to_numpy() * 60 + df.index.minute.to_numpy()

    start_m, switch_m = _minutes(start_time), _minutes(switch_time)
    sw_mask = daily_first_bar(df, switch_time).to_numpy()
    if boundary_mode == "exact":
        b_mask = (tmin == start_m)
    else:
        b_mask = daily_first_bar(df, start_time).to_numpy()
    sw_pos = np.flatnonzero(sw_mask)
    b_pos = np.flatnonzero(b_mask)
    if len(sw_pos) < 2 or len(b_pos) < 2:
        return pd.Series(out, index=df.index, name="channel_break_target")

    sw_date = date_arr[sw_pos]
    slip = tick * slippage_ticks
    allow_long = direction in ("long", "both")
    allow_short = direction in ("short", "both")

    for k in range(len(sw_pos)):
        si = int(sw_pos[k])
        day = pd.Timestamp(sw_date[k])
        if skip_weekend and day.day_of_week >= 5:
            continue

        # первая граница start после switch — выход из сделки
        jx = int(np.searchsorted(b_pos, si, side="right"))
        if jx >= len(b_pos):
            continue
        exit_pos = int(b_pos[jx])

        if channel_mode == "night":
            # канал: от предыдущего switch до границы start, его завершающей
            jp = int(np.searchsorted(sw_pos, si, side="left")) - 1
            if jp < 0:
                continue
            ch_start = int(sw_pos[jp])
            ch_end = -1
            jb = int(np.searchsorted(b_pos, ch_start, side="right"))
            if jb < jx:
                ch_end = int(b_pos[jb])          # граница start предыдущего цикла
            if ch_end < 0:
                continue
            # dir: сравнение закрытий на двух соседних границах start
            jd = int(np.searchsorted(b_pos, ch_end, side="left"))
            b_cur, b_prev = ch_end, (int(b_pos[jd - 1]) if jd > 0 else -1)
        else:
            # канал: от ближайшей границы start до switch (как в C# LaunchCalc)
            jb = int(np.searchsorted(b_pos, si, side="left")) - 1
            if jb < 0:
                continue
            b_cur = int(b_pos[jb])
            ch_start, ch_end = b_cur, si
            jd = jb
            b_prev = int(b_pos[jd - 1]) if jd > 0 else -1

        if b_prev < 0 or ch_start > ch_end:
            continue
        hh = float(h[ch_start:ch_end + 1].max())
        ll = float(lo[ch_start:ch_end + 1].min())
        if not (hh > ll > 0):
            continue
        d = 1 if c[b_cur] >= c[b_prev] else -1
        if not (allow_long if d == 1 else allow_short):
            continue

        pos = 0
        stop = None
        stop_from = 0
        for i in range(si, exit_pos + 1):
            if pos == 0:
                if d == 1 and c[i] > hh:
                    entry = i + 1
                    if entry > exit_pos or entry >= len(df):
                        break
                    pos = 1
                    price_in = o[entry] + slip
                    if sl is None:
                        stop = None
                    elif trail_to_channel:
                        stop = max(ll, price_in - sl)
                    else:
                        stop = price_in - sl
                    stop_from = entry
                elif d == -1 and c[i] < ll:
                    entry = i + 1
                    if entry > exit_pos or entry >= len(df):
                        break
                    pos = -1
                    price_in = o[entry] - slip
                    if sl is None:
                        stop = None
                    elif trail_to_channel:
                        stop = min(hh, price_in + sl)
                    else:
                        stop = price_in + sl
                    stop_from = entry
            else:
                hit = (
                    (pos == 1 and lo[i] <= stop) or
                    (pos == -1 and h[i] >= stop)
                ) if stop is not None else False
                if i >= stop_from and hit:
                    pos = 0
            if i == exit_pos:
                pos = 0
            out[i] = pos * volume

    return pd.Series(out, index=df.index, name="channel_break_target")
