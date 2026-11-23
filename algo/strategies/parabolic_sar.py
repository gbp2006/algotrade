"""Parabolic SAR как тренд-провайдер (идея OsEngine ParabolicSarTrade).

Классический SAR с ускорением: AF растёт на каждом новом экстремуме тренда,
ограничен `af_max`. Цена выше SAR → long, ниже → short (или выход, если
шорты запрещены). Сигнал по close бара, исполнение — следующим open в движке.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sar_signal(df: pd.DataFrame, af_start: float = 0.02,
               af_step: float = 0.02, af_max: float = 0.2,
               allow_short: bool = True) -> pd.Series:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)
    if n < 3:
        return pd.Series(np.zeros(n), index=df.index, name="sar_signal")

    # старт: восходящий тренд от первого минимума
    trend = 1
    sar = low[0]
    ep = high[0]
    af = af_start
    out = np.zeros(n, dtype=int)
    out[0] = 1

    for i in range(1, n):
        prev_sar = sar
        sar = sar + af * (ep - sar)
        if trend == 1:
            sar = min(sar, low[i - 1], low[max(0, i - 2)])
            if low[i] < sar:
                trend = -1
                sar = ep
                ep = low[i]
                af = af_start
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af_max, af + af_step)
        else:
            sar = max(sar, high[i - 1], high[max(0, i - 2)])
            if high[i] > sar:
                trend = 1
                sar = ep
                ep = high[i]
                af = af_start
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af_max, af + af_step)
        out[i] = trend if (trend == 1 or allow_short) else 0
        _ = prev_sar  # SAR в исполнении используется для цены，这里只保留朝向
    return pd.Series(out, index=df.index, name="sar_signal")


def targets(df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02,
            af_max: float = 0.2, allow_short: bool = True) -> pd.Series:
    return sar_signal(df, af_start, af_step, af_max, allow_short)
