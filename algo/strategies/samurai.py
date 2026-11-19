"""«Путь Самурая» / Хитрушка-2: 3 SMA + рублёвые offset'ы, пул секций.

Секции по умолчанию — из INI v1.6 (юань), сайз 1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_SECTIONS = [
    dict(ma_fast=40, ma_mid=500, ma_slow=1800, off_in=0.005, off_out=-0.003),
    dict(ma_fast=20, ma_mid=500, ma_slow=1800, off_in=0.004, off_out=-0.002),
    dict(ma_fast=10, ma_mid=500, ma_slow=1800, off_in=0.003, off_out=-0.001),
    dict(ma_fast=30, ma_mid=500, ma_slow=1200, off_in=0.004, off_out=-0.002),
    dict(ma_fast=20, ma_mid=400, ma_slow=1200, off_in=0.003, off_out=-0.001),
    dict(ma_fast=10, ma_mid=400, ma_slow=1200, off_in=0.002, off_out=0.0),
]


def targets(
    df: pd.DataFrame,
    sections: list[dict] | None = None,
    trade_start: str = "10:30",
    trade_end: str = "18:49",
    skip_weekend: bool = False,
    offset_mode: str = "abs",
) -> pd.Series:
    """Суммарная целевая позиция пула секций (в контрактах).

    offset_mode: "abs" — offset'ы в рублях (как в INI), "pct" — в долях цены.
    """
    sections = sections or DEFAULT_SECTIONS
    close_s = df["close"]
    close = close_s.to_numpy(dtype=float)

    mas: dict[int, np.ndarray] = {}
    for s in sections:
        for p in (s["ma_fast"], s["ma_mid"], s["ma_slow"]):
            if p not in mas:
                mas[p] = close_s.rolling(p).mean().to_numpy()

    n = len(df)
    tmin = (df.index.hour * 60 + df.index.minute).to_numpy()
    h1, m1 = (int(x) for x in trade_start.split(":"))
    h2, m2 = (int(x) for x in trade_end.split(":"))
    window = (tmin >= h1 * 60 + m1) & (tmin <= h2 * 60 + m2)
    if skip_weekend:
        window &= (df.index.day_of_week < 5)

    total = np.zeros(n, dtype=int)
    pos = np.zeros(len(sections), dtype=int)

    for i in range(n):
        if window[i]:
            c = close[i]
            for k, s in enumerate(sections):
                f = mas[s["ma_fast"]][i]
                mid = mas[s["ma_mid"]][i]
                slow = mas[s["ma_slow"]][i]
                if np.isnan(f) or np.isnan(mid) or np.isnan(slow):
                    continue
                p = pos[k]
                if p == 0:
                    k_in = s["off_in"] * (c if offset_mode == "pct" else 1.0)
                    k_out = s["off_out"] * (c if offset_mode == "pct" else 1.0)
                    if mid > slow and c <= f - k_in:
                        pos[k] = 1
                    elif mid < slow and c >= f + k_in:
                        pos[k] = -1
                elif p == 1:
                    k_out = s["off_out"] * (c if offset_mode == "pct" else 1.0)
                    if c >= f + k_out:
                        pos[k] = 0
                else:
                    k_out = s["off_out"] * (c if offset_mode == "pct" else 1.0)
                    if c <= f - k_out:
                        pos[k] = 0
        total[i] = pos.sum()

    return pd.Series(total, index=df.index, name="samurai_target")
