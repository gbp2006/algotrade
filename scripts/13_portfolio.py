"""Портфель: Простушка + Универсалка на одном инструменте (CNY)."""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import prostushka, universal  # noqa: E402

pd.set_option("display.width", 160)
CAPITAL = 1_000_000.0
GO = 984.55
NOTIONAL = 12_267.0

m5 = load_cached("2026-11/CNYRUBF.txt", 5)
data = m5[(m5.index >= "2023-01-01") & (m5.index < "2026-01-01")]
oos = m5[m5.index >= "2026-01-01"]


def run(d, t):
    return engine.run(d, t, engine.Costs())


def report(name, r, d):
    s = r.stats
    print(f"{name:24} {s['trades']:>4} сд  {s['net_profit']:>9} ₽  PF {s['profit_factor']:>5}  "
          f"DD {s['max_drawdown']:>8}  в рынке {s['in_market_pct']}%")
    results.record(name, "CNYRUBF", f"{d.index[0].date()}..{d.index[-1].date()}", s,
                   note="portfolio test")


print("=== 2023-2025 ===")
t1 = prostushka.targets(data, skip_weekend=True)
t2 = universal.targets(data, hold="daily", skip_weekend=True)
r1, r2 = run(data, t1), run(data, t2)
report("Простушка", r1, data)
report("Универсалка", r2, data)
rp = run(data, t1 + t2)
report("портфель (сумма)", rp, data)

# корреляция дневных приростов
d1 = r1.equity.resample("1D").last().dropna().diff().fillna(0)
d2 = r2.equity.resample("1D").last().dropna().diff().fillna(0)
common = d1.index.intersection(d2.index)
print(f"\nкорреляция дневных P&L: {np.corrcoef(d1.loc[common], d2.loc[common])[0, 1]:.2f}")
same = ((t1 > 0) & (t2 > 0)) | ((t1 < 0) & (t2 < 0))
opp = ((t1 > 0) & (t2 < 0)) | ((t1 < 0) & (t2 > 0))
flat = (t1 == 0) & (t2 == 0)
print(f"дни: обе в одну сторону {100 * same.mean():.0f}%, в противоположные {100 * opp.mean():.0f}%, "
      f"обе вне рынка {100 * flat.mean():.0f}%")

print("\n=== 2026 OOS ===")
o1 = prostushka.targets(oos, skip_weekend=True)
o2 = universal.targets(oos, hold="daily", skip_weekend=True)
r1o, r2o = run(oos, o1), run(oos, o2)
report("Простушка", r1o, oos)
report("Универсалка", r2o, oos)
report("портфель (сумма)", run(oos, o1 + o2), oos)

# --- размер позиции под 1 млн и 30% просадки
print("\n=== Размер под капитал 1 000 000 ₽ (2023-2025, DD x1.5) ===")
dd1 = abs(rp.stats["max_drawdown"]) * 1.5
for budget in (0.10, 0.20, 0.30):
    k = int(budget * CAPITAL // dd1)
    units = k  # 1 unit = 1 контракт Простушки + 1 контракт Универсалки
    net_y = rp.stats["net_profit"] / rp.stats["years"] * units
    margin = units * 2 * GO
    fund = (CAPITAL - margin) * 0.15
    total = net_y + fund
    print(f"бюджет DD {budget * 100:>2.0f}%: {units:>3} пар контрактов "
          f"(номинал {units * 2 * NOTIONAL / CAPITAL * 100:>3.0f}% капитала), "
          f"доходность {100 * total / CAPITAL:>5.1f}% ({100 * net_y / CAPITAL:.1f}% система + "
          f"{100 * fund / CAPITAL:.1f}% фонд), DD план {100 * units * dd1 / CAPITAL:.0f}%")
