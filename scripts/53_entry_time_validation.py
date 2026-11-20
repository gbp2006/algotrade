"""Проверка гипотезы «вход 13:40 лучше 13:50» на независимых периодах.

Обе стратегии в сетке 52 выбрали 13:40 как лучшее время входа. здесь тот же
сдвиг проверяется на Si 2009–2022 (псевдо-OOS) и по годам CNY/Si.
"""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import prostushka, universal  # noqa: E402

pd.set_option("display.width", 200)

ENTRIES = ["13:20", "13:30", "13:40", "13:50", "14:00", "14:10"]
COST_CNY = engine.Costs()
COST_SI = engine.Costs(tick=1.0, slippage_ticks=1.0, multiplier=1.0,
                       commission_pct=0.0001)
PERIODS = {
    "2009-2019": ("2009-01-01", "2020-01-01"),
    "2020-2022": ("2020-01-01", "2023-01-01"),
    "2023-2025": ("2023-01-01", "2026-01-01"),
    "2026": ("2026-01-01", None),
}


def cut(df, period):
    a, b = period
    return df[(df.index >= a) & (df.index < b)] if b else df[df.index >= a]


def one(df, fn, costs, **kw):
    st = engine.run(df, fn(df, skip_weekend=True, **kw), costs).stats
    pf = st.get("profit_factor", 0)
    return st["trades"], st["net_profit"], 999.0 if pf == float("inf") else pf


def main():
    si5 = load_cached("2026-11/Si.txt", 5)
    cny5 = load_cached("2026-11/CNYRUBF.txt", 5)
    cny1 = load_cached("2026-11/CNYRUBF.txt")

    rows = []
    for instrument, data, costs in [("Si", si5, COST_SI), ("CNY", cny5, COST_CNY)]:
        for pname, period in PERIODS.items():
            if instrument == "CNY" and pname in ("2009-2019", "2020-2022"):
                continue
            d = cut(data, period)
            if d.empty:
                continue
            for ma in (40, 50):
                for et in ENTRIES:
                    tr, net, pf = one(d, prostushka.targets, costs, ma_period=ma,
                                      entry_time=et, filter_bars=3,
                                      use_filter_long=True, allow_short_friday=False)
                    rows.append({"стратегия": "Простушка", "инструмент": instrument,
                                 "период": pname, "MA": ma, "вход": et,
                                 "сд": tr, "net": net, "PF": pf})

    si1 = load_cached("2026-11/Si.txt")
    for instrument, data, costs in [("CNY", cny1, COST_CNY), ("Si", si1, COST_SI)]:
        for pname, period in PERIODS.items():
            d = cut(data, period)
            if d.empty:
                continue
            for et in ENTRIES:
                tr, net, pf = one(d, universal.targets, costs, ref_time="10:05",
                                  entry_time=et, long_offset=0.004,
                                  short_offset=0.002, hold="daily")
                rows.append({"стратегия": "Универсалка", "инструмент": instrument,
                             "период": pname, "MA": 0, "вход": et,
                             "сд": tr, "net": net, "PF": pf})

    df = pd.DataFrame(rows)
    df.to_csv("reports/entry-time-validation.csv", index=False)

    parts = ["# Время входа: проверка на независимых периодах", "",
             "Издержки 0.01% + 1 тик, skip_weekend=True. 13:40 выбрано сеткой 52 по train 2023–25;",
             "ниже — тот же вход на Si 2009–2022 (данных CNY до 2023 нет) и на CNY 2026.", ""]
    for (strat, inst), g in df.groupby(["стратегия", "инструмент"], sort=False):
        parts.append(f"## {strat} · {inst}")
        parts.append("")
        for (period, ma), sub in g.groupby(["период", "MA"], sort=False):
            t = sub[["вход", "сд", "net", "PF"]].copy()
            parts.append(f"### {period}" + (f" · MA{ma}" if ma else ""))
            parts.append("")
            parts.append("| вход | сд | net ₽ | PF |")
            parts.append("|---|---:|---:|---:|")
            for _, r in t.iterrows():
                parts.append(f"| {r['вход']} | {int(r['сд'])} | {r['net']:.0f} | {r['PF']:.2f} |")
            parts.append("")
    parts.append("## Оговорки")
    parts.append("")
    parts.append("- Si 2009–2022 — псевдо-OOS по отношению к отбору на CNY 2023–25, но другая серия и другая валюта; совпадение эффекта не гарантирует перенос на CNY.")
    parts.append("- Хороший вход 13:40 может быть артефактом конкретного бара; проверка по годам и инструментам нужна до изменения конфигураций.")
    open("reports/entry-time-validation.md", "w", encoding="utf-8").write("\n".join(parts) + "\n")

    p = df[(df["стратегия"] == "Простушка")]
    a = p[(p["инструмент"] == "Si") & (p["период"] == "2009-2019") & (p["MA"] == 40)]
    b = p[(p["инструмент"] == "Si") & (p["период"] == "2026") & (p["MA"] == 40)]
    print(f"1) строк: {len(df)}; отчёт reports/entry-time-validation.md")
    print(f"2) Si 2009-19 MA40: PF 13:50={a[a['вход']=='13:50']['PF'].iloc[0]:.2f} "
          f"vs 13:40={a[a['вход']=='13:40']['PF'].iloc[0]:.2f}")
    print(f"3) Si 2026 MA40: PF 13:50={b[b['вход']=='13:50']['PF'].iloc[0]:.2f} "
          f"vs 13:40={b[b['вход']=='13:40']['PF'].iloc[0]:.2f}")
    u = df[(df["стратегия"] == "Универсалка")]
    for pname in ("2009-2019", "2026"):
        g = u[(u["инструмент"] == "Si") & (u["период"] == pname)]
        if not g.empty:
            g = g.set_index("вход")
            print(f"4) Si {pname} Uni: 13:30 PF {g.loc['13:30', 'PF']:.2f} / "
                  f"13:40 {g.loc['13:40', 'PF']:.2f} / 14:00 {g.loc['14:00', 'PF']:.2f}")
    print(f"5) CSV: reports/entry-time-validation.csv")


if __name__ == "__main__":
    main()
