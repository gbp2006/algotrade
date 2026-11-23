"""Доходность 7 кандидатов с капиталом 1 000 000 ₽ за 10 лет.

Базовый период: 2016-01-01 … 2026-01-01 (10 полных лет) на Si — единственном
инструменте с такой историей. Дополнительно CNY за всё доступное время
(с 2022-04). Масштабирование: на входе контрактов = floor(капитал / номинал),
то есть 100% экспозиции; прибыль каждой сделки реинвестируется.

Запуск: ./.venv/bin/python scripts/75_capital_10y.py
Отчёт: reports/strategy-capital-10y.md. В консоли только сводка.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

spec = importlib.util.spec_from_file_location("c70", "scripts/70_candidates.py")
c70 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c70)

from algo import engine, results  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

REPORT = Path("reports/strategy-capital-10y.md")
INITIAL = 1_000_000.0
WINDOWS = {
    "Si": ("2016-01-01", "2026-01-01"),      # 10 полных лет
    "CNY": ("2022-04-26", "2026-11-21"),     # вся доступная история
}
STRATEGIES = [
    ("Donchian 20/10", "donchian20", lambda d: C.donchian(d, 20, 10)),
    ("EWMAC 8/32", "ewmac8", lambda d: C.ewmac(d, 8, 32)),
    ("SMA 10/30", "sma10", lambda d: C.sma_cross(d, 10, 30)),
    ("ROC(5)", "roc5", lambda d: C.roc(d, 5)),
    ("VMA 5/10", "vma5", lambda d: C.vma(d, 5, 10)),
    ("ORB 30 мин", "orb30", lambda d: C.opening_range_breakout(d, "10:00", 30, "23:40")),
    ("Turn-of-month", "tom", lambda d: C.turn_of_month(d, 3)),
    ("Простушка MA48 (база)", "base_ma48", lambda d: prostushka.targets(d, 48, skip_weekend=True)),
]


def simulate(df: pd.DataFrame, costs: engine.Costs, start: str, end: str, builder) -> dict:
    warm = pd.Timestamp(start) - pd.Timedelta(days=c70.WARMUP_DAYS)
    d = df.loc[(df.index >= warm) & (df.index < end)]
    tg = builder(d)
    res = engine.run(d, tg, costs)
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    trades = [t for t in res.trades if lo <= t.exit_time < hi]

    capital = INITIAL
    peak = capital
    max_dd = 0.0
    yearly: dict[int, float] = {}
    used = 0
    for t in trades:
        entry_price = t.entry_price            # цена исполнения (уже с проскальзыванием)
        notional = abs(entry_price) * costs.multiplier
        if notional <= 0:
            continue
        size = int(capital // notional)        # 100% экспозиции, целые контракты
        if size < 1:
            continue
        net = t.net * size                     # pnl и комиссия масштабируются линейно
        capital += net
        peak = max(peak, capital)
        max_dd = min(max_dd, capital - peak)
        yearly[t.exit_time.year] = yearly.get(t.exit_time.year, 0.0) + net
        used += 1

    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    cagr = (capital / INITIAL) ** (1 / years) - 1 if capital > 0 else -1.0
    return dict(
        final=round(capital, 2), profit=round(capital - INITIAL, 2),
        cagr=round(100 * cagr, 2), trades=used, all_trades=len(trades),
        max_dd=round(max_dd, 2), max_dd_pct=round(100 * max_dd / peak, 1),
        yearly={y: round(v, 2) for y, v in sorted(yearly.items())},
    )


def main() -> None:
    data = {n: c70.load_cached(s["path"], minutes=5) for n, s in c70.SPECS.items()}
    rows = []
    for inst, (start, end) in WINDOWS.items():
        for label, key, builder in STRATEGIES:
            st = simulate(data[inst], c70.SPECS[inst]["costs"], start, end, builder)
            rows.append(dict(instrument=inst, strategy=label, key=key,
                             start=start, end=end, **st))
            if key != "base_ma48":
                results.record(strategy=f"capital10y_{key}", instrument=inst,
                               period=f"{start[:4]}-{end[:4]}",
                               stats=dict(trades=st["trades"], net_profit=st["profit"],
                                          max_drawdown=st["max_dd"], profit_factor=0),
                               params=dict(capital=INITIAL, sizing="100% экспозиции на входе"),
                               note="реинвестирование; 1M стартовый капитал")

    write_report(rows)
    print("Капитал 1 000 000 ₽, 100% экспозиции, реинвестирование")
    for inst, (start, end) in WINDOWS.items():
        print(f"{inst} {start[:4]}–{end[:4]}:")
        for r in [x for x in rows if x["instrument"] == inst]:
            print(f"  {r['strategy']:22} итог {r['final']:>12,.0f} ₽  "
                  f"прибыль {r['profit']:>12,.0f} ₽  CAGR {r['cagr']:>6}%  DD {r['max_dd_pct']}%")
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict]) -> None:
    L = [
        "# Доходность 7 стратегий с капиталом 1 000 000 ₽", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/75_capital_10y.py`.", "",
        "## Модель капитала", "",
        "- Старт: 1 000 000 ₽ на каждую стратегию отдельно (не портфель).",
        "- Размер позиции на входе: `floor(капитал / номинал)` контрактов = 100% экспозиции.",
        "  Прибыль/убыток и комиссия каждой сделки масштабируются линейно, капитал",
        "  реинвестируется. Внутри сделки сайз не меняется.",
        "- Издержки те же: 0.01% за сторону + 1 тик, сигнал по close, исполнение по open.",
        "- Si: 10 полных лет 2016-01-01…2026-01-01. CNY: вся история с 2022-04-26.",
        "- Просадка считается по капиталу после закрытия сделок (без внутридневного mark-to-market).",
        "", "## Итог", "",
        "| инструмент | стратегия | старт | финал | прибыль | CAGR | сделок | DD | DD % |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        L.append(f"| {r['instrument']} | {r['strategy']} | {INITIAL:,.0f} | {r['final']:,.0f} | "
                 f"{r['profit']:,.0f} | {r['cagr']}% | {r['trades']} | {r['max_dd']:,.0f} | {r['max_dd_pct']}% |")
    L += ["", "## Прибыль по годам (₽, по году выхода сделки)", "",
          "| год | " + " | ".join(r["strategy"] for r in rows if r["instrument"] == "Si") + " |",
          "|---|" + "---:|" * len([r for r in rows if r["instrument"] == "Si"])]
    si_rows = [r for r in rows if r["instrument"] == "Si"]
    years = sorted({y for r in si_rows for y in r["yearly"]})
    for y in years:
        L.append(f"| {y} | " + " | ".join(f"{r['yearly'].get(y, 0):,.0f}" for r in si_rows) + " |")
    L += ["", "## Оговорки", "",
          "100% экспозиции — агрессивный режим: результат сильно зависит от размера "
          "контракта и фазы рынка. Это не прогноз и не индивидуальная инвестиционная "
          "рекомендация; для проекта сравнение с базой в `reports/strategy-head-to-head.md` "
          "остаётся основным."]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
