"""RU-03: система Резвякова на 10 фьючерсах, 2016–2025 + OOS 2026.

Проверка идеи из `reports/russian-market-ideas-2026.md`: вход в 10:00 по HH/LL
последних двух дней, выход 20:40 или трейлинг 2%. Сравнение — Простушка MA48
в том же прогоне. research-only, в контур ничего не добавляется.

Запуск: ./.venv/bin/python scripts/86_rezvyakov.py
Отчёт: reports/rezvyakov-prototype.md. В консоли — только сводка.
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
v79 = _load("v79", "archive/research/79_rigorous_validation.py")
c70 = cap.c70
from algo import engine, results  # noqa: E402
from algo.strategies import prostushka  # noqa: E402
from algo.strategies import rezvyakov as R  # noqa: E402

REPORT = Path("reports/rezvyakov-prototype.md")
N_TRIALS = 200
VARIANTS = [
    ("Резвяков long/short", "rez_ls", lambda d: R.rezvyakov_targets(d)),
    ("Резвяков long-only", "rez_long", lambda d: R.rezvyakov_targets(d, allow_short=False)),
]
BASE = [("Простушка MA48 (база)", "base_ma48",
         lambda d: prostushka.targets(d, 48, skip_weekend=True))]


def costs_for(inst: str) -> engine.Costs:
    s = multi.SPECS[inst]
    return engine.Costs(tick=s["tick"], multiplier=s["mult"],
                        slippage_ticks=1.0, commission_pct=0.0001)


def main() -> None:
    data = {n: c70.load_cached(s["file"], 5) for n, s in multi.SPECS.items()}
    rows = []
    for inst, spec in multi.SPECS.items():
        start, end = multi.FULL_HISTORY[inst]
        costs = costs_for(inst)
        for label, key, builder in VARIANTS + BASE:
            st = cap.simulate(data[inst], costs, start, end, builder)
            rows.append(dict(instrument=inst, cls=spec["cls"], strategy=label, key=key,
                             start=start, end=end, **st))

    short = [r for r in rows if r["instrument"] in multi.SHORT]
    oos = []
    for label, key, builder in VARIANTS + BASE:
        for inst, spec in c70.SPECS.items():
            st = c70.backtest(data[inst], spec, "2026-01-01", "2026-11-21", builder)
            oos.append(dict(strategy=label, key=key, instrument=inst, **st))
            if key.startswith("rez"):
                results.record(strategy=f"ru03_{key}", instrument=inst,
                               period="oos 2026", stats=st,
                               params=dict(source="smart-lab 1130044",
                                           entry="10:00", exit="20:40", trail=0.02),
                               note="RU-03 исследовательский прототип")

    gates = []
    for inst, (start, end) in v79.WINDOWS.items():
        for label, key, builder in VARIANTS:
            r = v79.trade_returns(data[inst], c70.SPECS[inst], start, end, builder)
            st = v79.stats(r)
            sk, ku = v79.moments(r)
            p, _ = v79.dsr(st["sr"], st["trades"], N_TRIALS, sk, ku)
            mc = v79.monte_carlo(r)
            bad = []
            if st["trades"] < 30:
                bad.append("мало сделок")
            if st["net"] <= 0:
                bad.append("убыточен")
            if mc["p_sign"] >= 0.05:
                bad.append("неотличим от случая")
            if p < 0.95:
                bad.append("DSR<0.95")
            gates.append(dict(instrument=inst, strategy=label, **st,
                              p_sign=mc["p_sign"], dsr=round(p, 3),
                              verdict="ПРОЙДЕН" if not bad else "; ".join(bad)))

    write_report(rows, short, oos, gates)
    print("RU-03: Резвяков, 10 фьючерсов 2016–2025 + OOS 2026")
    for label, key, _ in VARIANTS + BASE:
        sub = [r for r in short if r["key"] == key]
        print(f"  {label:22} CAGR {np.mean([r['cagr'] for r in sub]):5.2f}%, "
              f"DD {np.mean([r['max_dd_pct'] for r in sub]):6.1f}%, "
              f"прибыльных {sum(1 for r in sub if r['profit'] > 0)}/10")
    print(f"гейты: {sum(1 for g in gates if g['verdict'] == 'ПРОЙДЕН')}/{len(gates)}; отчёт: {REPORT}")


def write_report(rows, short, oos, gates) -> None:
    labels = [v[0] for v in VARIANTS + BASE]
    L = [
        "# RU-03: система Резвякова — прототип", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/86_rezvyakov.py`, "
        "код: `algo/strategies/rezvyakov.py`.", "",
        "Источник: [Smart-Lab 1130044](https://smart-lab.ru/blog/1130044.php). "
        "Вход в 10:00 по HH/LL последних двух завершённых дней, выход 20:40 или "
        "трейлинг 2% от лучшего/худшего закрытия. Исполнение по open следующего "
        "M5-бара, 0.01% + 1 тик, 1M на инструмент, 100% экспозиции.", "",
        "## CAGR по инструментам (2016–2025; CNY с 2022, NG с 2020)", "",
        "| инструмент | " + " | ".join(labels) + " |",
        "|---|---|" + "---:|" * len(labels),
    ]
    for inst in multi.SPECS:
        sub = {r["strategy"]: r for r in rows if r["instrument"] == inst}
        mark = "" if inst in multi.SHORT else " *"
        L.append(f"| {inst}{mark} | " + " | ".join(
            f"{sub[l]['cagr']:.2f}%" for l in labels) + " |")
    L += ["", "* — короткая история, в сводку не входит.", "",
          "## Сводка по 10 инструментам", "",
          "| стратегия | средний CAGR | медианный CAGR | средняя DD | прибыльных | лучше базы |",
          "|---|---:|---:|---:|---:|---:|"]
    base = {r["instrument"]: r for r in short if r["key"] == "base_ma48"}
    for label, key, _ in VARIANTS + BASE:
        sub = [r for r in short if r["key"] == key]
        cagr = np.array([r["cagr"] for r in sub])
        win = sum(1 for r in sub if r["profit"] > 0)
        beat = "—"
        if key != "base_ma48":
            beat = str(sum(1 for r in sub if r["profit"] > base[r["instrument"]]["profit"])) + "/10"
        L.append(f"| {label} | {cagr.mean():.2f}% | {np.median(cagr):.2f}% | "
                 f"{np.mean([r['max_dd_pct'] for r in sub]):.1f}% | {win}/10 | {beat} |")

    L += ["", "## OOS 2026 (1 контракт)", "",
          "| стратегия | инструмент | сделок | net | PF | DD |",
          "|---|---|---:|---:|---:|---:|"]
    for r in oos:
        L.append(f"| {r['strategy']} | {r['instrument']} | {r['trades']} | "
                 f"{r['net_profit']} | {r['profit_factor']} | {r['max_drawdown']} |")

    L += ["", "## Строгие гейты", "",
          f"Гейты: ≥30 сделок, net>0, p(знаки)<0.05, DSR>0.95 при N={N_TRIALS}.", "",
          "| инструмент | стратегия | сделок | net | PF | p(знаки) | DSR | вердикт |",
          "|---|---|---:|---:|---:|---:|---:|---|"]
    for g in gates:
        L.append(f"| {g['instrument']} | {g['strategy']} | {g['trades']} | {g['net']} | "
                 f"{g['pf']} | {g['p_sign']} | {g['dsr']} | {g['verdict']} |")
    ok = [g for g in gates if g["verdict"] == "ПРОЙДЕН"]
    L += ["", "## Вывод", "",
          f"Гейты прошли {len(ok)}/{len(gates)} пар. "
          + ("Кандидат требует отдельного решения и полного цикла проверок "
             "на независимом окне; в бумажный контур без решения не добавлять."
             if ok else
             "Рабочего варианта не найдено: система остаётся исследовательским "
             "модулем, конфиги и WSL не тронуты.")]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
