"""«Трендовушка-универсалка» — тайминговая система без MA.

Реперная цена в 10:05, вход в 13:30 по порогам от репера:
  цена >= репер * (1 + long_offset)  -> лонг
  цена <= репер * (1 - short_offset) -> шорт
  иначе — вне игры.
Держим до 10:20 следующего дня (MorningExit) или до следующего решения (Daily).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import daily_first_bar


def targets(
    df: pd.DataFrame,
    ref_time: str = "10:05",
    entry_time: str = "13:30",
    long_offset: float = 0.004,
    short_offset: float = 0.002,
    allow_short_friday: bool = False,
    hold: str = "daily",
    exit_time: str = "10:20",
    avg_window: int = 0,
    skip_weekend: bool = False,
) -> pd.Series:
    close = df["close"]
    avg = close.rolling(avg_window).mean() if avg_window > 1 else close

    ref_mask = daily_first_bar(df, ref_time)
    dec_mask = daily_first_bar(df, entry_time)
    dates = df.index.normalize()

    ref_by_day = avg[ref_mask.values].groupby(dates[ref_mask.values]).first()
    ref = pd.Series(dates.map(ref_by_day).astype(float), index=df.index)

    price = avg
    raw = pd.Series(0, index=df.index, dtype=int)
    valid = ref.notna() & price.notna()
    raw[valid & (price >= ref * (1 + long_offset))] = 1
    raw[valid & (price <= ref * (1 - short_offset))] = -1

    if not allow_short_friday:
        raw[(raw == -1) & (df.index.day_of_week == 4)] = 0

    decide = dec_mask & valid
    if skip_weekend:
        decide = decide & (df.index.day_of_week < 5)

    daily = raw.where(decide)

    if hold == "daily":
        return daily.ffill().fillna(0).astype(int)

    # MorningExit: держим от бара решения до 10:20 следующего дня
    exit_mask = daily_first_bar(df, exit_time)
    dec_pos = np.flatnonzero(decide.to_numpy())
    ex_pos = np.flatnonzero(exit_mask.to_numpy())
    out = np.zeros(len(df), dtype=int)
    vals = daily.to_numpy()
    for p in dec_pos:
        q = ex_pos[ex_pos > p]
        if len(q) == 0:
            continue
        out[p : q[0]] = vals[p]
    return pd.Series(out, index=df.index)
