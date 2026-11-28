"""Контроли для пробоя канала: «просто лонг» и вариант с одним решением в сутки.

Проверяем, не объясняется ли результат top-кандидата общим бычьим трендом
2023–2026, и можно ли обойтись без утреннего таймера (格兰ица = время решения).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import DATA_ROOT, load_cached, load_txt  # noqa: E402
from algo.strategies import channel_break  # noqa: E402

SPECS = {
    "CNY": dict(path="2026-11/CNYRUBF.txt", m1=True,
                costs=engine.Costs(tick=0.001, multiplier=1000.0), tight=0.12),
    "Si": dict(path="2026-11/Si.txt", m1=True,
               costs=engine.Costs(tick=1.0, multiplier=1.0), tight=1000.0),
    "RTS": dict(path=DATA_ROOT.parent / "cache/iss/RTS_2026_M5_cont.txt", m1=False,
                costs=engine.Costs(tick=10.0, multiplier=1.644562), tight=1100.0),
    "GOLD": dict(path=DATA_ROOT.parent / "cache/iss/GOLD_2026_M5_cont.txt", m1=False,
                 costs=engine.Costs(tick=0.1, multiplier=82.2281), tight=150.0),
    "BR": dict(path=DATA_ROOT.parent / "cache/iss/BR_2026_M5_cont.txt", m1=False,
               costs=engine.Costs(tick=0.01, multiplier=822.281), tight=2.0),
}


def stats(trades, lo, hi, index):
    tr = [t for t in trades if lo <= t.exit_time < hi]
    if not tr:
        return dict(trades=0, net=0.0, PF=0.0, DD=0.0)
    pnl = np.array([t.net for t in tr], dtype=float)
    cum = np.cumsum(pnl)
    dd = cum - np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    w, l = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return dict(trades=len(tr), net=round(float(pnl.sum())),
                PF=round(float(w / l), 2) if l else 999.0,
                DD=round(float(dd.min())))


def main():
    rows = []
    for name, spec in SPECS.items():
        df = load_cached(spec["path"]) if spec["m1"] else load_txt(spec["path"])
        periods = ([("train", "2023-01-01", "2026-01-01")] if name in ("CNY", "Si")
                   else [("oos", "2026-01-01", "2026-11-21")])
        if name in ("CNY", "Si"):
            periods.append(("oos", "2026-01-01", "2026-11-21"))
        for period, start, end in periods:
            lo, hi = pd.Timestamp(start), pd.Timestamp(end)
            warm = lo - pd.Timedelta(days=30)
            d = df.loc[(df.index >= warm) & (df.index < hi)]

            # 1) контроль: лонг в том же окне 13:00→первая свеча следующего дня,
            #    но БЕЗ фильтра канала и направления (проверка «просто бычий тренд»)
            minutes = d.index.hour * 60 + d.index.minute
            sw_pos = np.flatnonzero(minutes.to_numpy() == 13 * 60)
            b_pos = np.flatnonzero(
                pd.Series(minutes >= (1 * 60), index=d.index)
                .groupby(d.index.normalize()).cummax()
                .groupby(d.index.normalize()).shift(1).fillna(False).to_numpy() == False  # noqa: E712
                & (minutes.to_numpy() >= 1 * 60)
            )
            ctrl = np.zeros(len(d), dtype=int)
            if len(sw_pos) and len(b_pos):
                for si in sw_pos:
                    if pd.Timestamp(d.index[si]).day_of_week >= 5:
                        continue
                    jx = int(np.searchsorted(b_pos, si, side="right"))
                    if jx < len(b_pos):
                        ctrl[si:int(b_pos[jx])] = 1
            s = stats(engine.run(d, pd.Series(ctrl, index=d.index),
                                 spec["costs"]).trades, lo, hi, d.index)
            rows.append(dict(instrument=name, period=period, variant="control-long", **s))

            # 2) топ-кандидат из сетки
            tg = channel_break.targets(
                d, start_time="01:00", switch_time="13:00", direction="long",
                sl=spec["tight"], channel_mode="day", boundary_mode="first_bar",
                skip_weekend=True, tick=spec["costs"].tick,
                slippage_ticks=spec["costs"].slippage_ticks)
            s = stats(engine.run(d, tg, spec["costs"]).trades, lo, hi, d.index)
            rows.append(dict(instrument=name, period=period, variant="channel-01-13", **s))

            # 3) без утреннего таймера: граница = время решения 13:00, канал 24ч
            tg = channel_break.targets(
                d, start_time="13:00", switch_time="13:00", direction="long",
                sl=spec["tight"], channel_mode="day", boundary_mode="exact",
                skip_weekend=True, tick=spec["costs"].tick,
                slippage_ticks=spec["costs"].slippage_ticks)
            s = stats(engine.run(d, tg, spec["costs"]).trades, lo, hi, d.index)
            rows.append(dict(instrument=name, period=period, variant="channel-13-13", **s))

    t = pd.DataFrame(rows)
    print(t.to_string(index=False))
    t.to_csv("reports/channel-break-controls.csv", index=False)
    Path("reports/channel-break-controls.md").write_text(
        "# Контроли пробоя канала\n\n" + t.to_string(index=False)
        + "\n\n`control-long` — постоянный лонг в том же окне; "
          "`channel-01-13` — лучший из сетки; `channel-13-13` — граница равна времени "
          "решения, чтобы не вводить утренний таймер на WSL.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
