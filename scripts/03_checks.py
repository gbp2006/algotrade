"""Санити-чеки Простушки: одно решение в день, входы по времени, длительность позиций."""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import DATA_ROOT, daily_first_bar, load_txt, to_timeframe  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

df = load_txt(DATA_ROOT / "2025.12" / "CNYRUBF.txt")
m5 = to_timeframe(df, 5)
tg = prostushka.targets(m5)
res = engine.run(m5, tg, engine.Costs())

# 1. одно решение в день
dec = daily_first_bar(m5, "13:50")
print(f"дней с решением: {dec.sum()}  (уникальных дат: {m5.index.normalize().nunique()})")

# 2. первые сделки
print("\nпервые 10 сделок:")
rows = []
for t in res.trades[:10]:
    rows.append(
        {
            "вход": t.entry_time.strftime("%Y-%m-%d %H:%M"),
            "выход": t.exit_time.strftime("%Y-%m-%d %H:%M"),
            "напр": t.direction,
            "цена вх": round(t.entry_price, 3),
            "цена вых": round(t.exit_price, 3),
            "часы": round((t.exit_time - t.entry_time).total_seconds() / 3600, 1),
            "net": round(t.net, 1),
        }
    )
print(pd.DataFrame(rows).to_string(index=False))

# 3. время входов
entries = pd.Series([t.entry_time for t in res.trades])
minutes = entries.dt.hour * 60 + entries.dt.minute
print(f"\nвремя входов: min {minutes.min() // 60}:{minutes.min() % 60:02d}, "
      f"max {minutes.max() // 60}:{minutes.max() % 60:02d}, "
      f"median {int(minutes.median()) // 60}:{int(minutes.median()) % 60:02d}")

# 4. длительность
dur = pd.Series([(t.exit_time - t.entry_time).total_seconds() / 3600 for t in res.trades])
print(f"длительность позиции, ч: median {dur.median():.1f}, "
      f"p10 {dur.quantile(0.1):.1f}, p90 {dur.quantile(0.9):.1f}, max {dur.max():.1f}")

# 5. ручная сверка MA на одном дне
day = m5[m5.index.normalize() == m5.index.normalize()[len(m5) // 2]]
b = day[day.index.time >= pd.Timestamp("13:50").time()].iloc[0]
pos = m5.index.get_loc(b.name)
ma_manual = m5["close"].iloc[pos - 39 : pos + 1].mean()
print(f"\nсверка MA: бар {b.name}, close {b['close']:.3f}, "
      f"MA-40 вручную {ma_manual:.4f}, target={tg.iloc[pos]}")

# 6. сколько дней сигнал ноль / лонг / шорт
sig = tg[dec.values]
print("распределение сигналов в дни решения:",
      sig.value_counts().sort_index().to_dict())
