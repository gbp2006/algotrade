"""Бэктест «Трендовушки-простушки» на CNY (непрерывная серия CNYRUBF)."""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import DATA_ROOT, load_txt, to_timeframe  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

pd.set_option("display.width", 160)


def run_one(m5: pd.DataFrame, title: str, **kw) -> engine.Result:
    tg = prostushka.targets(m5, **kw)
    res = engine.run(m5, tg, engine.Costs())
    print(f"\n--- {title} ---")
    for k, v in res.stats.items():
        print(f"{k:22} {v}")
    return res


if __name__ == "__main__":
    df = load_txt(DATA_ROOT / "2025.12" / "CNYRUBF.txt")
    m5 = to_timeframe(df, 5)
    print(f"M5: {len(m5):,} баров, {m5.index[0]} .. {m5.index[-1]}")

    full = run_one(m5, "Весь период 2022-04 .. 2025-12", ma_period=40)
    print("\nПо годам:")
    print(engine.yearly(full.trades))

    clean = m5[m5.index >= "2023-01-01"]
    r23 = run_one(clean, "2023-01 .. 2025-12 (без грязного 2022)", ma_period=40)
    print("\nПо годам:")
    print(engine.yearly(r23.trades))

    # вариации параметров (Тест 3 из ТЗ)
    variants = {
        "MA40, фильтр 3": dict(ma_period=40),
        "MA40, без фильтра": dict(ma_period=40, use_filter_long=False),
        "MA40, старый фильтр 12": dict(ma_period=40, filter_bars=12),
        "MA40, фильтр и шорт": dict(ma_period=40, use_filter_short=True),
        "MA42, фильтр 3": dict(ma_period=42),
        "MA50, фильтр 3": dict(ma_period=50),
    }
    print("\n=== Вариации параметров (2023-01 .. 2025-12) ===")
    rows = []
    for name, kw in variants.items():
        r = engine.run(clean, prostushka.targets(clean, **kw), engine.Costs())
        s = r.stats
        rows.append(
            {
                "вариант": name,
                "сделок": s["trades"],
                "net": s["net_profit"],
                "PF": s["profit_factor"],
                "avg": s["avg_trade"],
                "DD": s["max_drawdown"],
            }
        )
    print(pd.DataFrame(rows).to_string(index=False))

    full.equity.to_csv("reports/prostushka_equity.csv")
