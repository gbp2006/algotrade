"""Сверка двух файлов истории: старый (Finam до 2025-12) и новый (2026-11)."""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, ".")

from algo.data import DATA_ROOT, load_txt  # noqa: E402

pd.set_option("display.width", 160)

old = load_txt(DATA_ROOT / "2025.12" / "CNYRUBF.txt")
new = load_txt(DATA_ROOT / "2026-11" / "CNYRUBF.txt")

print(f"старый: {len(old):,} баров, {old.index[0]} .. {old.index[-1]}")
print(f"новый:  {len(new):,} баров, {new.index[0]} .. {new.index[-1]}")

# пересечение
lo, hi = old.index[0], old.index[-1]
a = old[(old.index >= lo) & (old.index <= hi)]
b = new[(new.index >= lo) & (new.index <= hi)]

print(f"\nв пересечении {lo.date()} .. {hi.date()}: старый {len(a):,}, новый {len(b):,}")
only_old = a.index.difference(b.index)
only_new = b.index.difference(a.index)
print(f"баров только в старом: {len(only_old):,}, только в новом: {len(only_new):,}")

common = a.index.intersection(b.index)
diff = (a.loc[common, "close"] - b.loc[common, "close"]).abs()
print(f"общих баров: {len(common):,}")
print(f"расхождение close: max {diff.max():.4f}, "
      f"доля расходящихся > 0.001: {100 * (diff > 0.001).mean():.4f}%")
if (diff > 0.001).any():
    worst = diff.nlargest(3)
    print("крупнейшие расхождения:")
    for ts, d in worst.items():
        print(f"  {ts}: старый {a.loc[ts, 'close']}, новый {b.loc[ts, 'close']}, Δ {d:.4f}")

# что появилось в 2026
y26 = new[new.index >= "2026-01-01"]
print(f"\n2026 год в новом файле: {len(y26):,} баров, "
      f"{y26.index.normalize().nunique()} дней, {y26.index[0]} .. {y26.index[-1]}")
per_day = y26.groupby(y26.index.normalize()).size()
print(f"баров в день: median {per_day.median():.0f}, min {per_day.min()}, max {per_day.max()}")
ret = y26["close"].pct_change().abs()
print(f"скачков >2% за минуту: {(ret > 0.02).sum()}, max {ret.max() * 100:.2f}%")
