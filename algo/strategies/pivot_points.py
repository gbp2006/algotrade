"""Pivot Points R1/S1 от вчерашнего дня (идея OsEngine PivotPointsRobot).

Дневной сигнал:
  P  = (H + L + C) / 3 предыдущего дня;
  R1 = 2P − L, S1 = 2P − H;
  закрытие выше R1 → long, ниже S1 → short (если разрешён);
  возврат к P → выход.
Сигнал публикуется на следующем дне в `at` (по умолчанию 13:55) — без look-ahead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .candidates import daily_bars, to_intraday


def pivot_signal(d: pd.DataFrame, allow_short: bool = True,
                 use_r3: bool = False) -> pd.Series:
    prev = d.shift(1)
    p = (prev["high"] + prev["low"] + prev["close"]) / 3.0
    r1 = 2.0 * p - prev["low"]
    s1 = 2.0 * p - prev["high"]
    if use_r3:
        rng = (prev["high"] - prev["low"]).abs()
        r1 = p + rng
        s1 = p - rng

    pos = 0
    out = np.zeros(len(d), dtype=int)
    close = d["close"].to_numpy(dtype=float)
    pv, up, dn = p.to_numpy(dtype=float), r1.to_numpy(dtype=float), s1.to_numpy(dtype=float)
    for i in range(len(d)):
        if not np.isfinite(close[i]) or not np.isfinite(pv[i]):
            out[i] = pos
            continue
        if pos == 0:
            if close[i] > up[i]:
                pos = 1
            elif allow_short and close[i] < dn[i]:
                pos = -1
        elif pos == 1 and close[i] < pv[i]:
            pos = 0
        elif pos == -1 and close[i] > pv[i]:
            pos = 0
        out[i] = pos
    return pd.Series(out, index=d.index, name="pivot_signal")


def targets(df: pd.DataFrame, allow_short: bool = True, use_r3: bool = False,
            at: str = "13:55", skip_weekend: bool = True) -> pd.Series:
    d = daily_bars(df)
    return to_intraday(pivot_signal(d, allow_short, use_r3), df, at, skip_weekend)
