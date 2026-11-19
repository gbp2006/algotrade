"""Простушка на пуле самых ликвидных фьючерсов MOEX (по классам активов).

Один и тот же канонический набор параметров на всех инструментах:
  MA40 M5, вход 13:50, фильтр 3 бара, шорт в пятницу запрещён, skip_weekend.

Пересчёт: PnL считается в пунктах цены (multiplier=1), затем переводится
в рубли по спецификации контракта. Основная метрика для сравнения —
% годовых на номинал (не зависит от валюты котировки и множителя).

Запуск:  python scripts/16_prostushka_multi.py
"""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, ".")

from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)

# file, tick (в единицах файла), множитель ₽ за 1.0 цены, класс
SPECS: dict[str, dict] = {
    # валюта
    "Si":      dict(file="2026-11/Si.txt",      tick=1.0,    mult=1.0,       cls="валюта"),
    "CNYRUBF": dict(file="2026-11/CNYRUBF.txt", tick=0.001,  mult=1000.0,    cls="валюта"),
    "Eu":      dict(file="2025.12/Eu.txt",      tick=1.0,    mult=1.0,       cls="валюта"),
    "ED":      dict(file="2025.12/ED.txt",      tick=0.0001, mult=82228.1,   cls="валюта"),
    # индекс
    "RTS":     dict(file="2025.12/RTS.txt",     tick=10.0,   mult=1.644562,  cls="индекс"),
    "MIX":     dict(file="2025.12/MIX.txt",     tick=25.0,   mult=1.0,       cls="индекс"),
    # сырьё
    "BR":      dict(file="2025.12/BR.txt",      tick=0.01,   mult=822.281,   cls="сырьё"),
    "GOLD":    dict(file="2025.12/GOLD.txt",    tick=0.1,    mult=82.2281,   cls="сырьё"),
    "SILV":    dict(file="2025.12/SILV.txt",    tick=0.01,   mult=822.281,   cls="сырьё"),
    "NG":      dict(file="2025.12/NG.txt",      tick=0.001,  mult=8222.81,   cls="сырьё"),
    # акции
    "SBRF":    dict(file="2025.12/SBRF.txt",    tick=1.0,    mult=1.0,       cls="акции"),
    "GAZR":    dict(file="2025.12/GAZR.txt",    tick=1.0,    mult=1.0,       cls="акции"),
}

BASE = dict(ma_period=40, entry_time="13:50", filter_bars=3,
            use_filter_long=True, allow_short_friday=False, skip_weekend=True)
VARIANTS = {"MA40": dict(BASE), "MA48": dict(BASE, ma_period=48)}

COMMON_START, COMMON_END = "2013-01-01", "2025-12-19"


def one(m5: pd.DataFrame, spec: dict, variant: dict) -> tuple[dict, engine.Result]:
    costs = engine.Costs(tick=spec["tick"], slippage_ticks=1.0,
                         multiplier=1.0, commission_pct=0.0001)
    res = engine.run(m5, prostushka.targets(m5, **variant), costs)
    st = dict(res.stats)
    px = float(m5["close"].mean())
    yrs = st.get("years") or 0
    st["avg_price"] = px
    st["notional"] = px * spec["mult"]
    st["net_rub"] = st.get("net_profit", 0.0) * spec["mult"]
    st["dd_rub"] = st.get("max_drawdown", 0.0) * spec["mult"]
    st["ret_pct_yr"] = (st["net_profit"] / px / yrs * 100) if yrs and px else 0.0
    st["dd_pct"] = (abs(st["max_drawdown"]) / px * 100) if px else 0.0
    return st, res


def table(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return df[["тикер", "класс", "лет", "сд", "net ₽", "PF", "%год", "DD%",
               "винрейт", "в_рынке", "номинал ₽"]]


def main() -> None:
    full_rows, common_rows, yearly_rows, split_rows = [], [], [], []
    runs: dict[tuple[str, str], tuple[dict, engine.Result]] = {}

    for ticker, spec in SPECS.items():
        m5 = load_cached(spec["file"], 5)
        # контроль склейки: самый большой прыжок close за день
        dclose = m5["close"].resample("1D").last().dropna()
        jump = float((dclose.pct_change().abs() * 100).max())
        print(f"{ticker:8} {len(m5):>8,} баров  {m5.index[0]:%Y-%m-%d}..{m5.index[-1]:%Y-%m-%d}  "
              f"макс. дневной скачок {jump:5.1f}%", flush=True)

        for vname, variant in VARIANTS.items():
            st, res = one(m5, spec, variant)
            runs[(ticker, vname)] = (st, res)
            full_rows.append({
                "тикер": f"{ticker} {vname}", "класс": spec["cls"],
                "лет": st["years"], "сд": st["trades"], "net ₽": round(st["net_rub"]),
                "PF": st["profit_factor"], "%год": round(st["ret_pct_yr"], 1),
                "DD%": round(st["dd_pct"], 1), "винрейт": st["win_rate"],
                "в_рынке": st["in_market_pct"], "номинал ₽": round(st["notional"]),
            })
            results.record(
                "prostushka", ticker, f"{m5.index[0]:%Y-%m}..{m5.index[-1]:%Y-%m}",
                {"trades": st["trades"], "net_profit": round(st["net_rub"], 2),
                 "profit_factor": st["profit_factor"], "max_drawdown": round(st["dd_rub"], 2)},
                params=variant, note=f"multi-instrument, {vname}, {spec['cls']}")

            y = engine.yearly(res.trades)
            if len(y):
                for year, row in y.iterrows():
                    yearly_rows.append({"тикер": ticker, "вариант": vname, "год": year,
                                        "сд": int(row["trades"]),
                                        "net_pct": round(row["net"] / st["avg_price"] * 100, 2)})

        # общее окно 2013-2025 для честного сравнения
        cw = m5[(m5.index >= COMMON_START) & (m5.index <= COMMON_END)]
        if len(cw) > 10000:
            st, _ = one(cw, spec, dict(BASE))
            common_rows.append({
                "тикер": ticker, "класс": spec["cls"],
                "лет": st["years"], "сд": st["trades"], "net ₽": round(st["net_rub"]),
                "PF": st["profit_factor"], "%год": round(st["ret_pct_yr"], 1),
                "DD%": round(st["dd_pct"], 1), "винрейт": st["win_rate"],
                "в_рынке": st["in_market_pct"], "номинал ₽": round(st["notional"]),
            })

    # лонг/шорт и стабильность по годам (MA40, вся история)
    for ticker, spec in SPECS.items():
        st, res = runs[(ticker, "MA40")]
        longs = [t.net for t in res.trades if t.direction > 0]
        shorts = [t.net for t in res.trades if t.direction < 0]
        y = engine.yearly(res.trades)
        split_rows.append({
            "тикер": ticker, "класс": spec["cls"],
            "лонг сд": len(longs), "лонг ₽": round(sum(longs) * spec["mult"]),
            "шорт сд": len(shorts), "шорт ₽": round(sum(shorts) * spec["mult"]),
            "лет в плюсе": f"{int((y['net'] > 0).sum())}/{len(y)}",
        })

    full = table(full_rows)
    common = table(common_rows)
    split = pd.DataFrame(split_rows)
    print("\n=== Вся доступная история (1 контракт, издержки 0.01% + 1 тик) ===")
    print(full.to_string(index=False))
    print("\n=== Общее окно 2013-01 .. 2025-12 (MA40) ===")
    print(common.to_string(index=False))

    print("\n=== Лонг/шорт и стабильность по годам (MA40) ===")
    print(split.to_string(index=False))

    print("\n=== Средние по классам (общее окно) ===")
    print(common.groupby("класс")[["%год", "DD%", "PF"]].mean().round(2).to_string())

    full.to_csv("reports/prostushka_multi_full.csv", index=False)
    common.to_csv("reports/prostushka_multi_common.csv", index=False)
    split.to_csv("reports/prostushka_multi_split.csv", index=False)
    pd.DataFrame(yearly_rows).to_csv("reports/prostushka_multi_yearly.csv", index=False)
    print("\nфайлы: reports/prostushka_multi_{full,common,split,yearly}.csv")


if __name__ == "__main__":
    main()
