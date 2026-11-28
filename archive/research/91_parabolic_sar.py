"""Строгая проверка прототипа Pivot Points (идея OsEngine) по нашей практике.

Тот же gating, что в scripts/79/80: своё время входа, walk-forward по годам,
1000 bootstrap/перестановок, DSR с учётом числа попыток, порог 30 сделок.
В контур ничего не добавляется — только отчёт.
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


v79 = _load("v79", "archive/research/79_rigorous_validation.py")
c70 = v79.c70
from algo.strategies import parabolic_sar  # noqa: E402

REPORT = Path("reports/parabolic-sar-validation.md")
N_TRIALS = 171  # 169 после three-soldiers + 2 новых варианта
MIN_TRADES = 30

EXTRA = [
    ("Parabolic SAR long", "sar_long",
     lambda d: parabolic_sar.targets(d, allow_short=False),
     "13:55 следующего дня", "OsEngine ParabolicSarTrade: crossing SAR, только лонг"),
    ("Parabolic SAR long+short", "sar_ls",
     lambda d: parabolic_sar.targets(d, allow_short=True),
     "13:55 следующего дня", "тот же SAR с разрешённым шортом"),
]


def main() -> None:
    data = {n: c70.load_cached(s["path"], 5) for n, s in c70.SPECS.items()}
    results, wf = [], []
    for inst, (start, end) in v79.WINDOWS.items():
        for label, key, builder, natural, rationale in EXTRA:
            r = v79.trade_returns(data[inst], c70.SPECS[inst], start, end, builder)
            st = v79.stats(r)
            sk, ku = v79.moments(r)
            prob, _ = v79.dsr(st["sr"], st["trades"], N_TRIALS, sk, ku)
            prob8, _ = v79.dsr(st["sr"], st["trades"], 8, sk, ku)
            mc = v79.monte_carlo(r)
            bad = []
            if st["trades"] < MIN_TRADES:
                bad.append(f"сделок <{MIN_TRADES}")
            if st["net"] <= 0:
                bad.append("убыточен")
            if mc["p_sign"] >= 0.05:
                bad.append("неотличим от случая")
            if prob < 0.95:
                bad.append("DSR<0.95")
            results.append(dict(instrument=inst, strategy=label, **st,
                                dsr=round(prob, 3), dsr8=round(prob8, 3),
                                p_sign=mc["p_sign"],
                                verdict="ПРОЙДЕН" if not bad else "; ".join(bad)))
            for year in range(v79.WF_START, v79.WF_END + 1):
                ys, ye = f"{year}-01-01", f"{year+1}-01-01"
                if pd.Timestamp(ys) < pd.Timestamp(start):
                    continue
                if pd.Timestamp(ye) > pd.Timestamp(end):
                    ye = end
                roos = v79.trade_returns(data[inst], c70.SPECS[inst], ys, ye, builder)
                wf.append(dict(instrument=inst, strategy=label, year=year,
                               **v79.stats(roos)))

    lines = [
        "# Parabolic SAR: строгая проверка", "",
        "Прототип по идее OsEngine `ParabolicSarTrade`. Gating как в "
        "`scripts/79_rigorous_validation.py`, N trials = "
        f"{N_TRIALS}, порог {MIN_TRADES} сделок.", "",
        "| Инструмент | Стратегия | Сделок | Net | PF | DSR | p-sign | Вердикт |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['instrument']} | {r['strategy']} | {r['trades']} | "
            f"{r['net']:.0f} | {r['pf']:.2f} | {r['dsr']} | {r['p_sign']:.3f} | "
            f"{r['verdict']} |")
    lines += ["", "## Walk-forward по годам", "",
              "| Инструмент | Стратегия | Год | Сделок | Net | PF |",
              "|---|---|---:|---:|---:|---:|"]
    for w in wf:
        lines.append(
            f"| {w['instrument']} | {w['strategy']} | {w['year']} | "
            f"{w['trades']} | {w['net']:.0f} | {w['pf']:.2f} |")
    passed = [r for r in results if r["verdict"] == "ПРОЙДЕН"]
    lines += ["", f"Прошли все гейты: {len(passed)} из {len(results)}.",
              "В контур не добавляется до отдельного решения пользователя.", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"sar: {len(results)} проверок, прошли {len(passed)}; отчёт {REPORT}")


if __name__ == "__main__":
    main()
