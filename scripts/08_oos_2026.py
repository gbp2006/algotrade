"""Out-of-sample: 2026 год на новых данных (не участвовавших в выборе параметров)."""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import DATA_ROOT, load_txt, to_timeframe  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

pd.set_option("display.width", 180)
CAPITAL = 50_000.0

df = load_txt(DATA_ROOT / "2026-11" / "CNYRUBF.txt")
m5 = to_timeframe(df, 5)
print(f"M5: {len(m5):,} баров, {m5.index[0]} .. {m5.index[-1]}")

y26 = m5[m5.index >= "2026-01-01"]
base = m5[(m5.index >= "2023-01-01") & (m5.index < "2026-01-01")]


def run(data, **kw):
    return engine.run(data, prostushka.targets(data, **kw), engine.Costs())


def line(name, r):
    s = r.stats
    print(f"{name:26} сделок {s['trades']:>4}  net {s['net_profit']:>9}  "
          f"PF {s['profit_factor']:>5}  avg {s['avg_trade']:>7}  DD {s['max_drawdown']:>8}  "
          f"в рынке {s['in_market_pct']}%")
    return s


print("\n=== 2023-2025 (in-sample, на чём выбирали MA) ===")
r_base = run(base)
line("MA40", r_base)
line("MA48", run(base, ma_period=48))

print("\n=== 2026 YTD (out-of-sample) ===")
r26 = run(y26)
line("MA40, все дни", r26)
line("MA48, все дни", run(y26, ma_period=48))
line("MA40, без выходных", run(y26, skip_weekend=True))
line("MA40, без фильтра", run(y26, use_filter_long=False))
line("MA40, фильтр и шорт", run(y26, use_filter_short=True))

print("\n=== 2026 по месяцам (MA40, без выходных) ===")
r26w = run(y26, skip_weekend=True)
tr = pd.DataFrame([{"m": t.exit_time.strftime("%Y-%m"), "net": t.net} for t in r26w.trades])
print(tr.groupby("m")["net"].agg(["count", "sum", "mean"]).round(1).to_string())

print("\n=== 2026: лонг / шорт ===")
for d, name in [(1, "лонг"), (-1, "шорт")]:
    t = [x for x in r26w.trades if x.direction == d]
    net = sum(x.net for x in t)
    print(f"{name:6} сделок {len(t):>3}  net {net:>8.0f}  винрейт {100 * sum(1 for x in t if x.net > 0) / len(t):.1f}%")

print("\n=== Доходность на капитал 50 тыс. ===")
for name, r in [("2023-2025 MA40", r_base), ("2026 MA40 (без вых.)", r26w)]:
    s = r.stats
    print(f"{name:22} {s['net_profit']:>9} руб. за {s['years']:.2f} лет = "
          f"{100 * s['net_profit'] / CAPITAL / s['years']:.1f}% годовых, "
          f"DD {100 * abs(s['max_drawdown']) / CAPITAL:.1f}% капитала")

# статистика сделок 2026
pnl = np.array([t.net for t in r26w.trades])
if len(pnl) > 2:
    se = pnl.std(ddof=1) / np.sqrt(len(pnl))
    print(f"\n2026: средняя {pnl.mean():.1f} руб., std {pnl.std(ddof=1):.0f}, "
          f"t = {pnl.mean() / se:.2f}, лучшая {pnl.max():.0f}, худшая {pnl.min():.0f}")
