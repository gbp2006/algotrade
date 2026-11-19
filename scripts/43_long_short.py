"""Асимметрия лонг/шорт: юань 2022-2026 против Si 2009-2026.

Проверяем утверждение из дайджеста: у автора шорты не хуже лонгов,
а наша модель может тянуть всё в лонг.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import engine  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import prostushka  # noqa: E402


def split(trades) -> dict:
    out = {}
    for name, d in (("лонг", 1), ("шорт", -1)):
        t = [x for x in trades if x.direction == d]
        if not t:
            out[name] = "нет сделок"
            continue
        net = sum(x.net for x in t)
        wins = sum(1 for x in t if x.net > 0)
        out[name] = (f"{len(t):>4} сд  net {net:>9.0f}  винрейт {100 * wins / len(t):>5.1f}%  "
                     f"средняя {net / len(t):>7.1f}")
    return out


def run(secid: str, start: str, costs: engine.Costs) -> None:
    m5 = load_cached(f"2026-11/{secid}.txt", 5)
    data = m5[m5.index >= start]
    r = engine.run(data, prostushka.targets(data, skip_weekend=True), costs)
    s = r.stats
    print(f"\n{secid} с {start}: {s['trades']} сделок, net {s['net_profit']:.0f}, PF {s['profit_factor']}")
    for k, v in split(r.trades).items():
        print(f"  {k:5} {v}")


if __name__ == "__main__":
    run("CNYRUBF", "2022-04-26", engine.Costs())
    run("Si", "2009-01-01",
        engine.Costs(tick=1.0, slippage_ticks=1.0, multiplier=1.0, commission_pct=0.0001))
    run("Si", "2022-01-01",
        engine.Costs(tick=1.0, slippage_ticks=1.0, multiplier=1.0, commission_pct=0.0001))
