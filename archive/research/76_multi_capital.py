"""7 кандидатов с капиталом 1 000 000 ₽ на каждом из 12 ликвидных фьючерсов.

Общее окно 2016-01-01…2025-12-19 (10 лет) — 10 инструментов с полной историей.
NG (с 2020) и CNY (с 2022) считаются на доступном окне и помечены отдельно.

Запуск: ./.venv/bin/python scripts/76_multi_capital.py
Отчёт: reports/strategy-multi-capital.md.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

def _load(name: str, path: str):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

cap = _load("cap", "archive/research/75_capital_10y.py")
c70 = cap.c70

from algo import engine, results  # noqa: E402

REPORT = Path("reports/strategy-multi-capital.md")
COMMON_START, COMMON_END = "2016-01-01", "2025-12-19"

SPECS = {
    "Si":   dict(file="2026-11/Si.txt",      tick=1.0,    mult=1.0,       cls="валюта"),
    "CNY":  dict(file="2026-11/CNYRUBF.txt", tick=0.001,  mult=1000.0,    cls="валюта"),
    "Eu":   dict(file="2025.12/Eu.txt",      tick=1.0,    mult=1.0,       cls="валюта"),
    "ED":   dict(file="2025.12/ED.txt",      tick=0.0001, mult=82228.1,   cls="валюта"),
    "RTS":  dict(file="2025.12/RTS.txt",     tick=10.0,   mult=1.644562,  cls="индекс"),
    "MIX":  dict(file="2025.12/MIX.txt",     tick=25.0,   mult=1.0,       cls="индекс"),
    "BR":   dict(file="2025.12/BR.txt",      tick=0.01,   mult=822.281,   cls="сырьё"),
    "GOLD": dict(file="2025.12/GOLD.txt",    tick=0.1,    mult=82.2281,   cls="сырьё"),
    "SILV": dict(file="2025.12/SILV.txt",    tick=0.01,   mult=822.281,   cls="сырьё"),
    "NG":   dict(file="2025.12/NG.txt",      tick=0.001,  mult=8222.81,   cls="сырьё"),
    "SBRF": dict(file="2025.12/SBRF.txt",    tick=1.0,    mult=1.0,       cls="акции"),
    "GAZR": dict(file="2025.12/GAZR.txt",    tick=1.0,    mult=1.0,       cls="акции"),
}

SHORT = ["Si", "Eu", "ED", "RTS", "MIX", "BR", "GOLD", "SILV", "SBRF", "GAZR"]
FULL_HISTORY = {k: ("2020-02-01", COMMON_END) if k == "NG" else
                   ("2022-04-26", COMMON_END) if k == "CNY" else
                   (COMMON_START, COMMON_END) for k in SPECS}


def main() -> None:
    data = {n: c70.load_cached(s["file"], 5) for n, s in SPECS.items()}
    rows = []
    for inst, spec in SPECS.items():
        start, end = FULL_HISTORY[inst]
        costs = engine.Costs(tick=spec["tick"], multiplier=spec["mult"],
                             slippage_ticks=1.0, commission_pct=0.0001)
        for label, key, builder in cap.STRATEGIES:
            st = cap.simulate(data[inst], costs, start, end, builder)
            rows.append(dict(instrument=inst, cls=spec["cls"], strategy=label, key=key,
                             start=start, end=end, **st))

    write_report(rows)
    # журнал: по одной строке на стратегию — сумма по 10 инструментам полной истории
    for label, key, _ in cap.STRATEGIES:
        sub = [r for r in rows if r["key"] == key and r["instrument"] in SHORT]
        results.record(strategy=f"multi10_{key}", instrument="PORTFOLIO10",
                       period="2016-2025", stats=dict(trades=sum(r["trades"] for r in sub),
                                                      net_profit=round(sum(r["profit"] for r in sub)),
                                                      profit_factor=0, max_drawdown=0),
                       params=dict(capital=cap.INITIAL, sizing="100% экспозиции на входе",
                                   instruments=",".join(SHORT)),
                       note="сумма 10 инструментов, по 1M на каждый")

    print("1 000 000 ₽ на инструмент, 100% экспозиции, 2016–2025 (10 инструментов)")
    pairs = []
    for label in [r["strategy"] for r in rows if r["instrument"] == "Si"]:
        sub = [r for r in rows if r["strategy"] == label and r["instrument"] in SHORT]
        cagr = np.mean([r["cagr"] for r in sub])
        profit = sum(r["profit"] for r in sub)
        pairs.append((label, f"{cagr:5.1f}% CAGR, {profit:>10,.0f} ₽"))
    for i in range(0, len(pairs), 2):
        print("  " + " | ".join(f"{n}: {t}" for n, t in pairs[i:i + 2]))
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict]) -> None:
    insts = list(SPECS)
    labels = [r["strategy"] for r in rows if r["instrument"] == "Si"]
    L = [
        "# 7 стратегий × 12 инструментов: капитал по 1 000 000 ₽", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/76_multi_capital.py`.", "",
        f"Общее окно {COMMON_START}…{COMMON_END} (10 лет) у инструментов {', '.join(SHORT)}. "
        "NG (2020–2025) и CNY (2022–2025) считаны на доступной истории и в средние "
        "по 10 инструментам не входят.",
        "Модель капитала и издержки — `reports/strategy-capital-10y.md`.", "",
        "## Финишный капитал с 1 000 000 ₽ (₽)", "",
        "| инструмент | " + " | ".join(labels) + " |",
        "|---|---|" + "---:|" * len(labels),
    ]
    for inst in insts:
        sub = {r["strategy"]: r for r in rows if r["instrument"] == inst}
        cells = []
        for label in labels:
            r = sub[label]
            cells.append(f"{r['final']:,.0f}")
        mark = "" if inst in SHORT else " *"
        L.append(f"| {inst}{mark} | " + " | ".join(cells) + " |")
    L += [
        "", "* — короткая история, в сводку ниже не включена.", "",
        "## Сводка по 10 инструментам полной истории", "",
        "| стратегия | сумма прибыли (10×1M) | средний CAGR | медианный CAGR | прибыльных | лучше базы |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    base = {r["instrument"]: r for r in rows if r["key"] == "base_ma48" and r["instrument"] in SHORT}
    for label in labels:
        sub = [r for r in rows if r["strategy"] == label and r["instrument"] in SHORT]
        cagr = np.array([r["cagr"] for r in sub])
        win = sum(1 for r in sub if r["profit"] > 0)
        beat = 0
        if label != "Простушка MA48 (база)":
            beat = sum(1 for r in sub if r["profit"] > base[r["instrument"]]["profit"])
        L.append(f"| {label} | {sum(r['profit'] for r in sub):,.0f} | {cagr.mean():.2f}% | "
                 f"{np.median(cagr):.2f}% | {win}/10 | {beat}/10 |")
    L += ["", "Вывод делается по среднему/медианному CAGR и числу инструментов, где "
          "стратегия обыгрывает базу на том же окне; сумма прибыли приведена для "
          "наглядности (10 независимых счетов по 1M)."]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
