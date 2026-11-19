"""Полная сетка на train и test + краевые эффекты (вход, MA, фильтр, пятница)."""

from __future__ import annotations

import itertools
import sys

import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

pd.set_option("display.width", 200)

m5 = load_cached("2026-11/CNYRUBF.txt", 5)
train = m5[(m5.index >= "2023-01-01") & (m5.index < "2025-01-01")]
test = m5[m5.index >= "2025-01-01"]
COST = engine.Costs()

MA = [30, 40, 50, 60]
ENTRY = ["13:30", "13:40", "13:50", "14:00", "14:10"]
FILTER = [0, 3, 6, 12]
FRIDAY = [False, True]

rows = []
for ma, et, fb, fr in itertools.product(MA, ENTRY, FILTER, FRIDAY):
    kw = dict(ma_period=ma, entry_time=et, filter_bars=fb or 3,
              use_filter_long=bool(fb), allow_short_friday=fr, skip_weekend=True)
    a = engine.run(train, prostushka.targets(train, **kw), COST).stats
    b = engine.run(test, prostushka.targets(test, **kw), COST).stats
    if a.get("trades", 0) < 100:
        continue
    rows.append({
        "MA": ma, "вход": et, "фильтр": fb, "шорт_пт": int(fr),
        "train PF": a["profit_factor"], "train net": a["net_profit"],
        "test PF": b["profit_factor"], "test net": b["net_profit"],
    })

df = pd.DataFrame(rows)
print(f"вариантов: {len(df)}")
print(f"train: медиана PF {df['train PF'].median():.2f}, "
      f"доля PF>1 {100 * (df['train PF'] > 1).mean():.0f}%")
print(f"test : медиана PF {df['test PF'].median():.2f}, "
      f"доля PF>1 {100 * (df['test PF'] > 1).mean():.0f}%")
print(f"корреляция train/test PF: {df['train PF'].corr(df['test PF']):.2f}")

for col, name in [("вход", "время входа"), ("MA", "период MA"),
                  ("фильтр", "фильтр (баров)"), ("шорт_пт", "шорт в пятницу")]:
    g = df.groupby(col)[["train PF", "test PF", "test net"]].mean().round(2)
    print(f"\n--- {name} (среднее по остальным параметрам) ---")
    print(g.to_string())
