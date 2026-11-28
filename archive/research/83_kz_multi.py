"""KZ-02 с замороженными параметрами на 10 ликвидных фьючерсах, 2016–2025.

Проверка обобщаемости после `reports/kz02-prototype.md`: те же правила, никакой
подгонки под инструмент. Сравнение — с базой MA48 на том же окне и сайзинге.

Запуск: ./.venv/bin/python scripts/83_kz_multi.py
Отчёт: reports/kz02-multi-futures.md. В консоли — только сводка.
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
multi = _load("multi76", "archive/research/76_multi_capital.py")
from algo import engine, results  # noqa: E402
from algo.strategies import kz_breakout as K  # noqa: E402

REPORT = Path("reports/kz02-multi-futures.md")
VARIANTS = [
    ("KZ-02 intraday long/short", "kz02_intra_ls",
     lambda d: K.kz_intraday(d, use_filters=True, allow_short=True)),
    ("KZ-02 intraday long", "kz02_intra",
     lambda d: K.kz_intraday(d, use_filters=True)),
    ("KZ-02 день long", "kz02_day",
     lambda d: K.kz_daily(d, use_filters=True)),
]
BASE = [r for r in cap.STRATEGIES if r[1] == "base_ma48"]


def main() -> None:
    data = {n: c70_load(s["file"]) for n, s in multi.SPECS.items()}
    rows = []
    for inst, spec in multi.SPECS.items():
        start, end = multi.FULL_HISTORY[inst]
        costs = engine.Costs(tick=spec["tick"], multiplier=spec["mult"],
                             slippage_ticks=1.0, commission_pct=0.0001)
        for label, key, builder in VARIANTS + BASE:
            st = cap.simulate(data[inst], costs, start, end, builder)
            rows.append(dict(instrument=inst, cls=spec["cls"], strategy=label, key=key,
                             start=start, end=end, **st))

    for label, key, _ in VARIANTS:
        sub = [r for r in rows if r["key"] == key and r["instrument"] in multi.SHORT]
        results.record(strategy=f"kzmulti_{key}", instrument="PORTFOLIO10",
                       period="2016-2025",
                       stats=dict(trades=sum(r["trades"] for r in sub),
                                  net_profit=round(sum(r["profit"] for r in sub)),
                                  profit_factor=0, max_drawdown=0),
                       params=dict(capital=int(cap.INITIAL),
                                   sizing="100% экспозиции на входе",
                                   parameters="frozen ma30/bb14/dev2/koef0.15",
                                   instruments=",".join(multi.SHORT)),
                       note="10 инструментов, по 1M на каждый, без подгонки")

    write_report(rows)
    print(f"KZ-02: 10 фьючерсов, 2016–2025, 1M на инструмент, параметры заморожены")
    for label, key, _ in VARIANTS + BASE:
        sub = [r for r in rows if r["key"] == key and r["instrument"] in multi.SHORT]
        cagr = np.mean([r["cagr"] for r in sub])
        win = sum(1 for r in sub if r["profit"] > 0)
        print(f"  {label:26} CAGR {cagr:5.2f}%  прибыльных {win}/10")
    print(f"отчёт: {REPORT}")


def c70_load(path: str):
    return cap.c70.load_cached(path, 5)


def write_report(rows: list[dict]) -> None:
    labels = [v[0] for v in VARIANTS] + [BASE[0][0]]
    L = [
        "# KZ-02 на 10 ликвидных фьючерсах (замороженные параметры)", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/83_kz_multi.py`.", "",
        "Параметры не подгонялись: SMA30, BB14/2σ, koef 0.15, выход по prevLL; "
        "интрадей-вариант исполняется по open следующего M5-бара. Окно 2016-01-01…2025-12-19, "
        "капитал 1 000 000 ₽ на инструмент, 100% экспозиции, реинвестирование, "
        "0.01% + 1 тик. Сравнение — база MA48 в том же прогоне.", "",
        "## CAGR по инструментам (%)", "",
        "| инструмент | " + " | ".join(labels) + " |",
        "|---|---|" + "---:|" * len(labels),
    ]
    for inst in multi.SPECS:
        sub = {r["strategy"]: r for r in rows if r["instrument"] == inst}
        cells = [f"{sub[l]['cagr']:.2f}" for l in labels]
        mark = "" if inst in multi.SHORT else " *"
        L.append(f"| {inst}{mark} | " + " | ".join(cells) + " |")
    L += ["", "* — короткая история (CNY с 2022, NG с 2020), в сводку не входит.", "",
          "## Сводка по 10 инструментам полной истории", "",
          "| стратегия | средний CAGR | медианный CAGR | прибыльных | лучше базы | сумма прибыли |",
          "|---|---:|---:|---:|---:|---:|"]
    base = {r["instrument"]: r for r in rows
            if r["key"] == "base_ma48" and r["instrument"] in multi.SHORT}
    for label, key, _ in VARIANTS + BASE:
        sub = [r for r in rows if r["key"] == key and r["instrument"] in multi.SHORT]
        cagr = np.array([r["cagr"] for r in sub])
        win = sum(1 for r in sub if r["profit"] > 0)
        beat = "—"
        if key != "base_ma48":
            beat = str(sum(1 for r in sub
                           if r["profit"] > base[r["instrument"]]["profit"])) + "/10"
        L.append(f"| {label} | {cagr.mean():.2f}% | {np.median(cagr):.2f}% | "
                 f"{win}/10 | {beat} | {sum(r['profit'] for r in sub):,.0f} ₽ |")

    best = None
    for label, key, _ in VARIANTS:
        sub = [r for r in rows if r["key"] == key and r["instrument"] in multi.SHORT]
        m = float(np.mean([r["cagr"] for r in sub]))
        if best is None or m > best[1]:
            best = (label, m)
    bmean = float(np.mean([r["cagr"] for r in rows
                           if r["key"] == "base_ma48" and r["instrument"] in multi.SHORT]))
    L += ["", "## Вывод", "",
          f"Лучший KZ-вариант: {best[0]} со средним CAGR {best[1]:.2f}% против "
          f"{bmean:.2f}% у базы MA48. "
          + ("KZ не подтвердил превосходство на 10 инструментах — тему закрываем, "
             "исследовательский модуль остаётся только как архив идеи."
             if best[1] <= bmean else
             "KZ подтвердил превосходство на выборке; нужно отдельное решение о "
             "дальнейшей проверке, но робот по-прежнему не добавляется без гейтов."),
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
