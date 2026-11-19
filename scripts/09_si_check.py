"""Проверка Простушки на Si: длинная история 2009-2026 (кросс-инструментальный тест).

Si: шаг цены 1.0, стоимость шага 1 руб., 1 контракт ≈ 1000 USD.
"""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import DATA_ROOT, load_txt, to_timeframe  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

pd.set_option("display.width", 180)

df = load_txt(DATA_ROOT / "2026-11" / "Si.txt")
print(f"Si: {len(df):,} минутных баров, {df.index[0]} .. {df.index[-1]}")
m5 = to_timeframe(df, 5)
print(f"M5: {len(m5):,} баров")

costs = engine.Costs(tick=1.0, slippage_ticks=1.0, multiplier=1.0, commission_pct=0.0001)


def run(start: str, end: str | None, **kw):
    data = m5[(m5.index >= start) & (m5.index < end)] if end else m5[m5.index >= start]
    return engine.run(data, prostushka.targets(data, skip_weekend=True, **kw), costs)


def line(name, r):
    s = r.stats
    if s["trades"] == 0:
        print(f"{name:28} нет сделок")
        return s
    print(f"{name:28} сделок {s['trades']:>5}  net {s['net_profit']:>10}  "
          f"PF {s['profit_factor']:>5}  avg {s['avg_trade']:>7}  DD {s['max_drawdown']:>9}")
    return s

print("\n=== Si: MA40, без выходных ===")
line("2009-2014", run("2009-01-01", "2015-01-01"))
line("2015-2019", run("2015-01-01", "2020-01-01"))
line("2020-2022", run("2020-01-01", "2023-01-01"))
line("2023-2025", run("2023-01-01", "2026-01-01"))
line("2026 OOS", run("2026-01-01", None))
line("весь 2009-2026", run("2009-01-01", None))

print("\n=== Si по годам (весь период) ===")
rows = []
for y in range(2009, 2027):
    r = run(f"{y}-01-01", f"{y+1}-01-01")
    s = r.stats
    if s["trades"]:
        rows.append({"год": y, "сделок": s["trades"], "net": s["net_profit"], "PF": s["profit_factor"]})
print(pd.DataFrame(rows).to_string(index=False))

print("\n=== Вариации на всём периоде ===")
line("MA40 (базовый)", run("2009-01-01", None))
line("MA48", run("2009-01-01", None, ma_period=48))
line("MA30", run("2009-01-01", None, ma_period=30))
line("без фильтра", run("2009-01-01", None, use_filter_long=False))
line("фильтр и шорт", run("2009-01-01", None, use_filter_short=True))
