"""Сетка устойчивости для второй партии: SMA, ROC, VMA (train + OOS).

Запуск: ./.venv/bin/python scripts/73_robustness_more.py
Отчёт: reports/strategy-robustness-more.md.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

spec = importlib.util.spec_from_file_location("c70", "archive/research/70_candidates.py")
c70 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c70)

from algo.strategies import candidates as C  # noqa: E402

REPORT = Path("reports/strategy-robustness-more.md")

GRIDS = {
    "T19 SMA": [
        (f, s, f"SMA{f}/{s}") for f, s in ((5, 15), (10, 20), (10, 30), (15, 45), (20, 60))
    ],
    "T27 ROC": [(n, None, f"ROC({n})") for n in (3, 5, 10, 15, 20)],
    "T28 VMA": [
        (f, s, f"VMA{f}/{s}") for f, s in ((3, 6), (5, 10), (8, 16), (10, 20), (15, 30))
    ],
}


def builder(family, p1, p2):
    if family == "T19 SMA":
        return lambda d: C.sma_cross(d, int(p1), int(p2))
    if family == "T27 ROC":
        return lambda d: C.roc(d, int(p1))
    if family == "T28 VMA":
        return lambda d: C.vma(d, int(p1), int(p2))
    raise ValueError(family)


def main() -> None:
    data = {n: c70.load_cached(s["path"], minutes=5) for n, s in c70.SPECS.items()}
    rows = []
    for family, grid in GRIDS.items():
        for p1, p2, label in grid:
            build = builder(family, p1, p2)
            rec = dict(family=family, params=label)
            for name, spec in c70.SPECS.items():
                for period, start, end in c70.PERIODS:
                    st = c70.backtest(data[name], spec, start, end, build)
                    rec[f"{name}_{period}_pf"] = st["profit_factor"]
                    rec[f"{name}_{period}_tr"] = st["trades"]
            rows.append(rec)

    write_report(rows)
    print("Устойчивость второй партии: SMA / ROC / VMA, по 5 точек, train + OOS")
    for family in GRIDS:
        sub = [r for r in rows if r["family"] == family]
        good = sum(1 for r in sub if all(r[f"{n}_oos_pf"] > 1 for n in c70.SPECS))
        print(f"{family:10} OOS PF>1 у {good}/{len(sub)} точек; "
              + ", ".join(f"{r['params']}={r['CNY_oos_pf']}/{r['Si_oos_pf']}" for r in sub))
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict]) -> None:
    L = [
        "# Устойчивость второй партии", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/73_robustness_more.py`.",
        "Методика — `reports/strategy-prototypes.md`.", "",
        "| семейство | параметр | CNY train PF | CNY OOS PF | Si train PF | Si OOS PF | OOS сделок CNY/Si |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        L.append(f"| {r['family']} | {r['params']} | {r['CNY_train_pf']} | {r['CNY_oos_pf']} | "
                 f"{r['Si_train_pf']} | {r['Si_oos_pf']} | {r['CNY_oos_tr']}/{r['Si_oos_tr']} |")
    L += ["", "Кандидат устойчив, если OOS PF > 1 на обоих инструментах у большинства соседних параметров."]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
