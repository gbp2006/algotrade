"""Есть ли смысл тестировать кандидатов как добавку к базе, а не замену.

Для каждого кандидата: корреляция годовых доходностей с базой, доходность в
худших для базы инструмент-годах (нижняя квартиль). Если корреляция низкая, а
в худших годах кандидат положителен — это диверсификатор.

Запуск: ./.venv/bin/python scripts/77_diversifier_check.py
Отчёт: reports/strategy-diversifiers.md.
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

d76 = _load("d76", "archive/research/76_multi_capital.py")
cap = d76.cap
c70 = cap.c70

REPORT = Path("reports/strategy-diversifiers.md")


def main() -> None:
    data = {n: c70.load_cached(s["file"], 5) for n, s in d76.SPECS.items()}
    panel = {}
    for inst, spec in d76.SPECS.items():
        start, end = d76.FULL_HISTORY[inst]
        if inst not in d76.SHORT:
            continue   # только полная история, 10 инструментов
        costs = c70.engine.Costs(tick=spec["tick"], multiplier=spec["mult"],
                                 slippage_ticks=1.0, commission_pct=0.0001)
        for label, key, builder in cap.STRATEGIES:
            st = cap.simulate(data[inst], costs, start, end, builder)
            for year, profit in st["yearly"].items():
                panel[(inst, year, label)] = profit / cap.INITIAL

    df = pd.DataFrame([(i, y, s, v) for (i, y, s), v in panel.items()],
                      columns=["inst", "year", "strategy", "ret"])
    base = df[df.strategy == "Простушка MA48 (база)"].set_index(["inst", "year"])["ret"]
    worst = base[base <= base.quantile(0.25)].index
    rows = []
    for label in df.strategy.unique():
        if label == "Простушка MA48 (база)":
            continue
        s = df[df.strategy == label].set_index(["inst", "year"])["ret"].reindex(base.index)
        corr = s.corr(base)
        in_worst = s.reindex(worst)
        rows.append(dict(strategy=label, corr=round(float(corr), 3),
                         worst_mean=round(100 * float(in_worst.mean()), 2),
                         worst_pos=round(100 * float((in_worst > 0).mean()), 0),
                         all_mean=round(100 * float(s.mean()), 2)))

    write_report(rows)
    rows_sorted = sorted(rows, key=lambda r: (r["corr"], -r["worst_mean"]))
    print("Диверсификаторы: корреляция с базой и доход в её худших годах")
    for r in rows_sorted:
        print(f"  {r['strategy']:22} corr {r['corr']:+.2f}  худшие годы {r['worst_mean']:+.2f}% "
              f"в плюсе {r['worst_pos']:.0f}%")
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict]) -> None:
    L = [
        "# Кандидаты как диверсификаторы к базе", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/77_diversifier_check.py`.",
        "Годовые доходности = прибыль / 1 000 000 ₽, 10 инструментов × 10 лет (2016–2025).", "",
        "| стратегия | корреляция с базой | средняя в худшей квартили базы | доля плюса в худшие годы | средняя за все годы |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in rows:
        L.append(f"| {r['strategy']} | {r['corr']:+.3f} | {r['worst_mean']:+.2f}% | "
                 f"{r['worst_pos']:.0f}% | {r['all_mean']:+.2f}% |")
    L += ["", "Низкая/отрицательная корреляция + положительный результат в худшие для "
          "базы годы = кандидат на отдельный маленький параллельный тест, но не на замену базы."]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
