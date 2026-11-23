"""Три солдата с волатильностным фильтром (идея OsEngine).

Три подряд бычьих дневных бара, тело каждого больше `k` × ATR(14)/close → long.
Три медвежьих бара с тем же фильтром → выход (или short, если разрешён).
Порог нормирован на волатильность — адаптация без отдельного индикатора.
Сигнал дневной, публикуется на следующем дне в `at` — без look-ahead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .candidates import daily_bars, to_intraday


def soldiers_signal(d: pd.DataFrame, k: float = 0.5,
                    allow_short: bool = False) -> pd.Series:
    body = (d["close"] - d["open"]).abs() / d["close"].replace(0, np.nan)
    prev = d["close"].shift(1)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - prev).abs(),
        (d["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean() / d["close"].replace(0, np.nan)
    strong = body > k * atr
    bull = ((d["close"] > d["open"]) & strong).rolling(3).min() == 1
    bear = ((d["close"] < d["open"]) & strong).rolling(3).min() == 1

    pos = 0
    out = np.zeros(len(d), dtype=int)
    bv, sv = bull.to_numpy(), bear.to_numpy()
    for i in range(len(d)):
        if bool(bv[i]):
            pos = 1
        elif bool(sv[i]):
            pos = -1 if allow_short else 0
        out[i] = pos
    return pd.Series(out, index=d.index, name="soldiers_signal")


def targets(df: pd.DataFrame, k: float = 0.5, allow_short: bool = False,
            at: str = "13:55", skip_weekend: bool = True) -> pd.Series:
    d = daily_bars(df)
    return to_intraday(soldiers_signal(d, k, allow_short), df, at, skip_weekend)
