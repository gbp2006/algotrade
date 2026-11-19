"""Шаг 2: корреляция дневных P&L «работающих» инструментов и портфель.

Берём Простушку (MA40, 13:50, фильтр 3, шорт в пятницу запрещён) на инструментах,
которые дали плюс в пуле, считаем дневную доходность на номинал и смотрим:
  - матрицу корреляций,
  - просадку равновесного портфеля,
  - экспозицию под бюджет просадки 30%.

Запуск: python scripts/17_portfolio_corr.py
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)

SPECS = {
    "Si":      dict(file="2026-11/Si.txt",      tick=1.0,    mult=1.0),
    "CNYRUBF": dict(file="2026-11/CNYRUBF.txt", tick=0.001,  mult=1000.0),
    "Eu":      dict(file="2025.12/Eu.txt",      tick=1.0,    mult=1.0),
    "RTS":     dict(file="2025.12/RTS.txt",     tick=10.0,   mult=1.644562),
    "MIX":     dict(file="2025.12/MIX.txt",     tick=25.0,   mult=1.0),
    "SBRF":    dict(file="2025.12/SBRF.txt",    tick=1.0,    mult=1.0),
    "GAZR":    dict(file="2025.12/GAZR.txt",    tick=1.0,    mult=1.0),
    "GOLD":    dict(file="2025.12/GOLD.txt",    tick=0.1,    mult=82.2281),
    "BR":      dict(file="2025.12/BR.txt",      tick=0.01,   mult=822.281),
}
BASE = dict(ma_period=40, entry_time="13:50", filter_bars=3,
            use_filter_long=True, allow_short_friday=False, skip_weekend=True)
START, END = "2013-01-01", "2025-12-19"
TARGET_DD = 0.30


def daily_ret(ticker: str, spec: dict) -> pd.Series:
    m5 = load_cached(spec["file"], 5)
    m5 = m5[(m5.index >= START) & (m5.index <= END)]
    costs = engine.Costs(tick=spec["tick"], slippage_ticks=1.0,
                         multiplier=1.0, commission_pct=0.0001)
    res = engine.run(m5, prostushka.targets(m5, **BASE), costs)
    eq = res.equity.resample("1D").last().dropna()
    ret = eq.diff().dropna() / float(m5["close"].mean())  # % на номинал
    return ret.rename(ticker)


def report(rets: pd.DataFrame, label: str) -> None:
    print(f"\n########## {label}: дней {len(rets):,} "
          f"({rets.index[0]:%Y-%m-%d}..{rets.index[-1]:%Y-%m-%d}) ##########")
    corr = rets.corr()
    print("\n=== Корреляция дневных P&L ===")
    print((corr * 100).round(0).astype(int).to_string())

    pairs = []
    for i, a in enumerate(rets.columns):
        for b in rets.columns[i + 1:]:
            pairs.append((a, b, round(corr.loc[a, b], 2)))
    pairs.sort(key=lambda x: x[2])
    print("\nсамые низкие пары:", ", ".join(f"{a}/{b} {c}" for a, b, c in pairs[:5]))
    print("самые высокие пары:", ", ".join(f"{a}/{b} {c}" for a, b, c in pairs[-5:]))

    port = rets.mean(axis=1)
    eq = port.cumsum()
    dd = (eq - eq.cummax()).min()
    print(f"\n=== Равновесный портфель {rets.shape[1]} инструментов ===")
    print(f"доходность {port.mean() * 252 * 100:.1f}% годовых на номинал, "
          f"волатильность {port.std() * np.sqrt(252) * 100:.1f}%, "
          f"макс. просадка {dd * 100:.1f}% номинала, "
          f"календарных лет в плюсе "
          f"{int((port.groupby(port.index.year).sum() > 0).sum())}/"
          f"{port.index.year.nunique()}")

    per_dd = {}
    for t in rets.columns:
        e = rets[t].cumsum()
        per_dd[t] = abs((e - e.cummax()).min())
    print("\n=== Экспозиция на инструмент под бюджет просадки 30% ===")
    rows = [{"тикер": t, "DD номинала %": round(per_dd[t] * 100, 1),
             "экспозиция": f"{min(1.0, TARGET_DD / per_dd[t]) * 100:.0f}%"} for t in rets.columns]
    print(pd.DataFrame(rows).to_string(index=False))


def main() -> None:
    all9 = pd.concat([daily_ret(t, s) for t, s in SPECS.items()],
                     axis=1, sort=True).dropna()
    report(all9, "9 инструментов (с CNY, короткое окно)")
    no_cny = pd.concat([daily_ret(t, s) for t, s in SPECS.items() if t != "CNYRUBF"],
                       axis=1, sort=True).dropna()
    report(no_cny, "8 инструментов без CNY (длинное окно)")

    all9.to_csv("reports/portfolio_corr_returns.csv")
    all9.corr().to_csv("reports/portfolio_corr.csv")


if __name__ == "__main__":
    main()
