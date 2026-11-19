"""Статистическая устойчивость Простушки: t-статистика, бутстрап, разбивка по годам."""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import DATA_ROOT, load_txt, to_timeframe  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

pd.set_option("display.width", 180)
rng = np.random.default_rng(42)

df = load_txt(DATA_ROOT / "2025.12" / "CNYRUBF.txt")
m5 = to_timeframe(df, 5)
base = m5[m5.index >= "2023-01-01"]


def run(data, **kw):
    return engine.run(data, prostushka.targets(data, **kw), engine.Costs())


print("=== Год за годом: MA 36 / 40 / 44 / 48 ===")
rows = []
for p in [36, 40, 44, 48]:
    r = run(base, ma_period=p)
    y = engine.yearly(r.trades)["net"].to_dict()
    rows.append({"MA": p, **{int(k): v for k, v in y.items()}, "итого": r.stats["net_profit"]})
print(pd.DataFrame(rows).to_string(index=False))

print("\n=== 2022 отдельно (данные грязные, только для полноты) ===")
y22 = m5[(m5.index >= "2022-05-01") & (m5.index < "2023-01-01")]
r22 = run(y22)
print(f"сделок {r22.stats['trades']}, net {r22.stats['net_profit']}, "
      f"PF {r22.stats['profit_factor']}, DD {r22.stats['max_drawdown']}")

print("\n=== Статистика сделок (2023-2025, MA40) ===")
r = run(base)
pnl = np.array([t.net for t in r.trades])
n = len(pnl)
se = pnl.std(ddof=1) / np.sqrt(n)
t_stat = pnl.mean() / se
print(f"сделок {n}, средняя {pnl.mean():.1f} руб., std {pnl.std(ddof=1):.0f}, "
      f"t-статистика {t_stat:.2f}")

boots = np.array([rng.choice(pnl, n, replace=True).sum() for _ in range(2000)])
lo, hi = np.percentile(boots, [5, 95])
print(f"бутстрап суммарного net: 5% {lo:.0f}, медиана {np.median(boots):.0f}, 95% {hi:.0f}")
print(f"доля бутстрап-выборок с убытком: {100 * (boots < 0).mean():.1f}%")

# то же без 5 лучших сделок
pnl_sorted = np.sort(pnl)[::-1]
rest = pnl_sorted[5:]
print(f"\nбез 5 лучших сделок: net {rest.sum():.0f} руб., "
      f"средняя {rest.mean():.1f}, t {rest.mean() / (rest.std(ddof=1) / np.sqrt(len(rest))):.2f}")

# худшая сделка и серия убытков
print(f"худшая сделка {pnl.min():.0f}, лучшая {pnl.max():.0f}")
streak = max_streak = 0
for x in pnl:
    streak = streak + 1 if x < 0 else 0
    max_streak = max(max_streak, streak)
print(f"максимальная серия убыточных сделок: {max_streak}")
