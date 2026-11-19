"""Универсалка на CNYRUBF и Si: сравнение режимов и периодов."""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import DATA_ROOT, load_txt  # noqa: E402
from algo.strategies import universal  # noqa: E402

pd.set_option("display.width", 180)


def line(name, r):
    s = r.stats
    if not s["trades"]:
        print(f"{name:34} нет сделок")
        return s
    print(f"{name:34} сделок {s['trades']:>4}  net {s['net_profit']:>9}  PF {s['profit_factor']:>5}  "
          f"avg {s['avg_trade']:>7}  DD {s['max_drawdown']:>8}  в рынке {s['in_market_pct']}%")
    return s


def test(secid_file: str, costs: engine.Costs, periods: dict[str, tuple]):
    df = load_txt(DATA_ROOT / "2026-11" / secid_file)
    print(f"\n===== {secid_file}: {len(df):,} баров, {df.index[0]} .. {df.index[-1]} =====")

    def run(start, end, **kw):
        data = df[(df.index >= start) & (df.index < end)] if end else df[df.index >= start]
        return engine.run(data, universal.targets(data, skip_weekend=True, **kw), costs)

    for name, (a, b) in periods.items():
        line(name, run(a, b))

    print("--- вариации на всём периоде ---")
    line("Daily (сутки)", run("2022-04-26", None, hold="daily"))
    line("MorningExit 10:20", run("2022-04-26", None, hold="morning"))
    line("порог 0.1/0.1", run("2022-04-26", None, long_offset=0.001, short_offset=0.001))
    line("средние 10 мин", run("2022-04-26", None, avg_window=10))
    line("шорт в пятницу разрешён", run("2022-04-26", None, allow_short_friday=True))


test(
    "CNYRUBF.txt",
    engine.Costs(),
    {
        "2023-2025 (in-sample)": ("2023-01-01", "2026-01-01"),
        "2026 OOS": ("2026-01-01", None),
    },
)

test(
    "Si.txt",
    engine.Costs(tick=1.0, slippage_ticks=1.0, multiplier=1.0, commission_pct=0.0001),
    {
        "2009-2019": ("2009-01-01", "2020-01-01"),
        "2020-2022": ("2020-01-01", "2023-01-01"),
        "2023-2025": ("2023-01-01", "2026-01-01"),
        "2026 OOS": ("2026-01-01", None),
    },
)
