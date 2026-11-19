"""Самурай: пул секций против одной секции, CNY M1."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import samurai  # noqa: E402

df = load_cached("2026-11/CNYRUBF.txt")
print(f"M1: {len(df):,} баров, {df.index[0]} .. {df.index[-1]}")

periods = {
    "2023-2025": ("2023-01-01", "2026-01-01"),
    "2026 OOS": ("2026-01-01", None),
    "весь": ("2022-04-26", None),
}
variants = {
    "пул 6 секций": None,
    "секция 1 (40/500/1800)": samurai.DEFAULT_SECTIONS[:1],
    "секции 1-3": samurai.DEFAULT_SECTIONS[:3],
}

for pname, (a, b) in periods.items():
    data = df[(df.index >= a) & (df.index < b)] if b else df[df.index >= a]
    print(f"\n--- {pname} ---")
    for vname, secs in variants.items():
        r = engine.run(data, samurai.targets(data, sections=secs, skip_weekend=True))
        print(results.line(vname, r.stats))
        results.record("samurai", "CNYRUBF", pname, r.stats,
                       params={"variant": vname, "skip_weekend": True})
