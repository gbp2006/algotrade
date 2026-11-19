"""Перебор параметров Простушки с разделением train / test.

Train: 2023-2024, Test: 2025-2026. Отбор по train, проверка на test.
Метрика отбора — PF при условии >= 100 сделок (иначе шум).
"""

from __future__ import annotations

import itertools
import sys

import pandas as pd

sys.path.insert(0, ".")

from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

pd.set_option("display.width", 200)

m5 = load_cached("2026-11/CNYRUBF.txt", 5)
train = m5[(m5.index >= "2023-01-01") & (m5.index < "2025-01-01")]
test = m5[m5.index >= "2025-01-01"]

MA = [30, 35, 40, 45, 50, 55, 60]
ENTRY = ["13:30", "13:40", "13:50", "14:00", "14:10"]
FILTER = [0, 3, 6, 12]  # 0 = выключен
FRIDAY = [False, True]  # разрешён ли шорт в пятницу
COST = engine.Costs()


def metrics(data, **kw):
    r = engine.run(data, prostushka.targets(data, skip_weekend=True, **kw), COST)
    return r.stats


rows = []
for ma, et, fb, fr in itertools.product(MA, ENTRY, FILTER, FRIDAY):
    s = metrics(train, ma_period=ma, entry_time=et, filter_bars=fb or 3,
                use_filter_long=bool(fb), allow_short_friday=fr)
    if s["trades"] < 100:
        continue
    rows.append({
        "MA": ma, "вход": et, "фильтр": fb, "шорт_пт": int(fr),
        "сд": s["trades"], "net": s["net_profit"], "PF": s["profit_factor"],
        "DD": s["max_drawdown"],
    })

df = pd.DataFrame(rows)
df["net/DD"] = (df["net"] / df["DD"].abs()).round(2)
df = df.sort_values("PF", ascending=False)
print(f"вариантов прошло фильтр: {len(df)} из {len(MA) * len(ENTRY) * len(FILTER) * len(FRIDAY)}")
print("\n=== ТОП-10 по PF на train (2023-2024) ===")
print(df.head(10).to_string(index=False))

print("\n=== эти же 10 на test (2025-2026) ===")
out = []
for _, row in df.head(10).iterrows():
    s = metrics(test, ma_period=int(row["MA"]), entry_time=row["вход"],
                filter_bars=int(row["фильтр"]) or 3, use_filter_long=bool(row["фильтр"]),
                allow_short_friday=bool(row["шорт_пт"]))
    out.append({
        "MA": int(row["MA"]), "вход": row["вход"], "фильтр": int(row["фильтр"]),
        "шорт_пт": int(row["шорт_пт"]),
        "train PF": row["PF"], "train net": int(row["net"]),
        "test PF": s["profit_factor"], "test net": int(s["net_profit"]),
        "test DD": int(s["max_drawdown"]), "test сд": s["trades"],
    })
t = pd.DataFrame(out)
t["устойчив"] = ((t["test PF"] > 1.2) & (t["test net"] > 0)).astype(int)
print(t.to_string(index=False))

print(f"\nустойчивых из топ-10: {int(t['устойчив'].sum())}")
print("\n=== средние по сетке (train) ===")
print(df[["PF", "net", "net/DD"]].describe().loc[["mean", "50%", "min", "max"]].round(2).to_string())

for _, row in t.iterrows():
    results.record(
        "prostushka", "CNYRUBF", "train 2023-2024 / test 2025-2026",
        {"trades": int(row["test сд"]), "net_profit": int(row["test net"]),
         "profit_factor": row["test PF"], "max_drawdown": int(row["test DD"])},
        params={"ma": int(row["MA"]), "entry": row["вход"], "filter": int(row["фильтр"]),
                "short_friday": int(row["шорт_пт"])},
        note=f"train PF {row['train PF']}",
    )
