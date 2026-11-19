"""Углублённый анализ Простушки: лонг/шорт, издержки, устойчивость параметра,
утренний выход, сценарии капитала."""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import DATA_ROOT, daily_first_bar, load_txt, to_timeframe  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

CAPITAL = 50_000.0
pd.set_option("display.width", 180)

df = load_txt(DATA_ROOT / "2025.12" / "CNYRUBF.txt")
m5 = to_timeframe(df, 5)
base = m5[m5.index >= "2023-01-01"]


def run(data, **kw):
    return engine.run(data, prostushka.targets(data, **kw), engine.Costs())


res = run(base)
print("=== Базовый вариант 2023-2025 ===")
print(f"net {res.stats['net_profit']:>9} руб.  за {res.stats['years']} лет")
print(f"доходность на капитал {CAPITAL:,.0f}: "
      f"{100 * res.stats['net_profit'] / CAPITAL / res.stats['years']:.1f}% годовых")
print(f"макс. просадка: {res.stats['max_drawdown']:>9} руб. "
      f"= {100 * abs(res.stats['max_drawdown']) / CAPITAL:.1f}% капитала")

# --- лонг / шорт
print("\n=== Лонг и шорт по отдельности ===")
rows = []
for d, name in [(1, "лонг"), (-1, "шорт")]:
    tr = [t for t in res.trades if t.direction == d]
    net = sum(t.net for t in tr)
    wins = sum(1 for t in tr if t.net > 0)
    rows.append(
        {
            "направление": name,
            "сделок": len(tr),
            "net": round(net),
            "доля профита, %": round(100 * net / res.stats["net_profit"]),
            "винрейт": round(100 * wins / len(tr), 1),
        }
    )
print(pd.DataFrame(rows).to_string(index=False))

# --- концентрация прибыли
pnl = np.array(sorted((t.net for t in res.trades), reverse=True))
print(f"\nтоп-5 сделок дают {100 * pnl[:5].sum() / pnl.sum():.0f}% прибыли, "
      f"топ-20 — {100 * pnl[:20].sum() / pnl.sum():.0f}%")

# --- чувствительность к проскальзыванию
print("\n=== Проскальзывание (тиков) ===")
rows = []
for s in [0, 1, 2, 3, 5]:
    r = engine.run(base, prostushka.targets(base), engine.Costs(slippage_ticks=s))
    rows.append({"тиков": s, "net": r.stats["net_profit"], "PF": r.stats["profit_factor"],
                 "avg": r.stats["avg_trade"]})
print(pd.DataFrame(rows).to_string(index=False))

# --- устойчивость периода MA
print("\n=== Период MA (2023-2025) ===")
rows = []
for p in range(20, 61, 4):
    r = run(base, ma_period=p)
    rows.append({"MA": p, "сделок": r.stats["trades"], "net": r.stats["net_profit"],
                 "PF": r.stats["profit_factor"], "DD": r.stats["max_drawdown"]})
print(pd.DataFrame(rows).to_string(index=False))

# --- утренний выход вместо суточного решения
def targets_morning_exit(data, morning: str = "10:20", **kw) -> pd.Series:
    tg_base = prostushka.targets(data, **kw)
    decide = daily_first_bar(data, kw.get("entry_time", "13:50"))
    exit_bars = daily_first_bar(data, morning)
    dec_pos = np.flatnonzero(decide.to_numpy())
    ex_pos = np.flatnonzero(exit_bars.to_numpy())
    out = np.zeros(len(data), dtype=int)
    for p in dec_pos:
        q = ex_pos[ex_pos > p]
        if len(q) == 0:
            continue
        out[p : q[0]] = tg_base.iloc[p]
    return pd.Series(out, index=data.index)


me = engine.run(base, targets_morning_exit(base), engine.Costs())
print("\n=== Суточное решение vs утренний выход 10:20 ===")
print(f"суточное:  сделок {res.stats['trades']:4}, net {res.stats['net_profit']:>9}, "
      f"PF {res.stats['profit_factor']}, в рынке {res.stats['in_market_pct']}%")
print(f"утренний:  сделок {me.stats['trades']:4}, net {me.stats['net_profit']:>9}, "
      f"PF {me.stats['profit_factor']}, в рынке {me.stats['in_market_pct']}%")

# --- сценарии капитала
print(f"\n=== Сценарии капитала {CAPITAL:,.0f} руб. (базовый вариант) ===")
rows = []
for k in [1, 2, 3, 5]:
    net = res.stats["net_profit"] * k
    dd = res.stats["max_drawdown"] * k
    rows.append(
        {
            "контрактов": k,
            "номинал, тыс.": round(k * 11_300 / 1000),
            "% капитала": round(100 * k * 11_300 / CAPITAL),
            "net за 3 года, тыс.": round(net / 1000, 1),
            "% годовых": round(100 * net / CAPITAL / res.stats["years"], 1),
            "макс. DD, % кап.": round(100 * abs(dd) / CAPITAL, 1),
        }
    )
print(pd.DataFrame(rows).to_string(index=False))
