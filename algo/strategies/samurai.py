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


# --- авторская вариация по docx 2019 -------------------------------------
# В документе примеры секций даны для Si (offset'ы в рублях) и BR (в единицах цены).
AUTHOR_SECTIONS_SI = [
    dict(ma_fast=90, ma_mid=200, ma_slow=900, off_in=25.0, off_out=-15.0,
         size_long=1, size_short=1),
    dict(ma_fast=80, ma_mid=100, ma_slow=900, off_in=50.0, off_out=-30.0,
         size_long=1, size_short=1),
]
AUTHOR_SECTIONS_BR = [
    dict(ma_fast=90, ma_mid=200, ma_slow=900, off_in=0.025, off_out=-0.025,
         size_long=1, size_short=1),
    dict(ma_fast=80, ma_mid=100, ma_slow=900, off_in=0.050, off_out=-0.030,
         size_long=1, size_short=1),
]


def _minutes(at: str) -> int:
    h, m = (int(x) for x in at.split(":"))
    return h * 60 + m


def targets_author(
    df: pd.DataFrame,
    sections: list[dict],
    trade_start: str = "10:02",
    trade_end: str = "18:45",
    ma_start: str = "10:00",
    ma_end: str = "18:45",
    skip_weekend: bool = True,
    friday_exit: str | None = None,
    offset_mode: str = "abs",
    session_ma: bool = True,
) -> pd.Series:
    """Авторская логика из `20.08.19 Описание Хитрушка.docx`.

    Отличия от `targets`: SMA считаются только по барам внутри `TIME_MA`
    (как в роботе QUIK), сигнал — по последней цене бара (прокси тика),
    есть пятничный принудительный выход и размеры лонга/шорта по секции.
    Модель исполнения движка не меняется: сделка по open следующего бара.
    """
    close_s = df["close"]
    close = close_s.to_numpy(dtype=float)
    tmin = (df.index.hour * 60 + df.index.minute).to_numpy()
    dow = df.index.dayofweek.to_numpy()
    weekend = dow >= 5 if skip_weekend else np.zeros(len(df), dtype=bool)

    a_ma, b_ma = _minutes(ma_start), _minutes(ma_end)
    in_ma = (tmin >= a_ma) & (tmin <= b_ma) & ~weekend
    periods = sorted({p for s in sections for p in (s["ma_fast"], s["ma_mid"], s["ma_slow"])})
    mas: dict[int, np.ndarray] = {}
    if session_ma:
        session_close = close_s.where(in_ma)
        for p in periods:
            # rolling по сжатому ряду внутрисессионных баров, затем назад на полный индекс
            vals = session_close.dropna().rolling(p).mean()
            mas[p] = vals.reindex(df.index).to_numpy()
    else:
        for p in periods:
            mas[p] = close_s.rolling(p).mean().to_numpy()

    a_tr, b_tr = _minutes(trade_start), _minutes(trade_end)
    window = (tmin >= a_tr) & (tmin <= b_tr) & ~weekend
    friday_min = _minutes(friday_exit) if friday_exit else None

    total = np.zeros(len(df), dtype=int)
    pos = np.zeros(len(sections), dtype=int)
    locked_day = None

    for i in range(len(df)):
        day = df.index[i].date()
        if day != locked_day:
            locked_day = day
            locked = False
        if friday_min is not None and dow[i] == 4 and tmin[i] >= friday_min:
            pos[:] = 0
            locked = True

        if window[i] and not locked:
            c = close[i]
            for k, s in enumerate(sections):
                f, mid, slow = (mas[s[key]][i] for key in ("ma_fast", "ma_mid", "ma_slow"))
                if np.isnan(f) or np.isnan(mid) or np.isnan(slow):
                    continue
                scale = c if offset_mode == "pct" else 1.0
                off_in = s["off_in"] * scale
                off_out = s["off_out"] * scale
                p = pos[k]
                if p == 0:
                    if mid > slow and s.get("size_long", 1) and c <= f - off_in:
                        pos[k] = s.get("size_long", 1)
                    elif mid < slow and s.get("size_short", 1) and c >= f + off_in:
                        pos[k] = -s.get("size_short", 1)
                elif p > 0:
                    if c >= f + off_out:
                        pos[k] = 0
                else:
                    if c <= f - off_out:
                        pos[k] = 0
        total[i] = pos.sum()

    return pd.Series(total, index=df.index, name="samurai_author_target")
