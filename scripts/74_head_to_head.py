"""Head-to-head: 7 кандидатов против базовой Простушки на одном окне и сайзинге.

Запуск: ./.venv/bin/python scripts/74_head_to_head.py
Отчёт: reports/strategy-head-to-head.md. В консоли — только сводка.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

spec = importlib.util.spec_from_file_location("c70", "scripts/70_candidates.py")
c70 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c70)

from algo import engine, results  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402
from algo.strategies import prostushka  # noqa: E402

REPORT = Path("reports/strategy-head-to-head.md")

CANDIDATES = [
    ("Простушка MA40 (база)", "base_ma40", lambda d: prostushka.targets(d, 40, skip_weekend=True)),
    ("Простушка MA48 (база)", "base_ma48", lambda d: prostushka.targets(d, 48, skip_weekend=True)),
    ("Donchian 20/10", "donchian20", lambda d: C.donchian(d, 20, 10)),
    ("EWMAC 8/32", "ewmac8", lambda d: C.ewmac(d, 8, 32)),
    ("SMA 10/30", "sma10", lambda d: C.sma_cross(d, 10, 30)),
    ("ROC(5)", "roc5", lambda d: C.roc(d, 5)),
    ("VMA 5/10", "vma5", lambda d: C.vma(d, 5, 10)),
    ("ORB 30 мин", "orb30", lambda d: C.opening_range_breakout(d, "10:00", 30, "23:40")),
    ("Turn-of-month", "tom", lambda d: C.turn_of_month(d, 3)),
]


def main() -> None:
    data = {n: c70.load_cached(s["path"], minutes=5) for n, s in c70.SPECS.items()}
    rows = []
    for name, spec in c70.SPECS.items():
        for label, key, builder in CANDIDATES:
            for period, start, end in c70.PERIODS:
                st = c70.backtest(data[name], spec, start, end, builder)
                rows.append(dict(instrument=name, strategy=label, key=key, period=period, **st))

    for r in rows:
        if not r["key"].startswith("base_") or r["period"] != "oos":
            continue
        results.record(strategy=f"h2h_{r['key']}", instrument=r["instrument"],
                       period="oos 2026", stats=r,
                       params=dict(comparison="head-to-head", prototype="74_head_to_head"),
                       note="база в том же прогоне, 1 контракт")

    write_report(rows)
    print("Head-to-head: 7 кандидатов + 2 базовых, 1 контракт, одинаковое окно")
    for name in c70.SPECS:
        base = next(r for r in rows if r["instrument"] == name
                    and r["strategy"] == "Простушка MA48 (база)" and r["period"] == "oos")
        cand = [r for r in rows if r["instrument"] == name and r["period"] == "oos"
                and not r["key"].startswith("base_")]
        win = [r for r in cand if r["profit_factor"] > base["profit_factor"]]
        print(f"{name}: база MA48 OOS PF {base['profit_factor']} ({base['net_profit']} ₽); "
              f"выиграли {len(win)}/{len(cand)} — "
              + ", ".join(f"{r['strategy']}={r['profit_factor']}" for r in win))
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict]) -> None:
    L = [
        "# Head-to-head: кандидаты против базовой Простушки", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/74_head_to_head.py`.", "",
        "Одинаковые данные (M5 Финама), издержки (0.01% + 1 тик), окна "
        "(train 2023–25 / OOS 2026), сайзинг (1 контракт). Разница: база решает "
        "в 13:50 и имеет фильтр/запрет пятничного шорта, кандидаты — в 13:55 "
        "(ORB — интрадей), без фильтров.", "",
        "| инструмент | стратегия | период | сделок | net | PF | DD | в рынке % |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        L.append(f"| {r['instrument']} | {r['strategy']} | {r['period']} | {r['trades']} | "
                 f"{r['net_profit']} | {r['profit_factor']} | {r['max_drawdown']} | "
                 f"{r['in_market_pct']} |")
    L += [
        "", "## Вывод", "",
        "Кандидат считается выигрывающим, если его OOS PF выше базы MA48 на том же "
        "инструменте. Один PF без учёта DD и числа сделок решение о включении в "
        "бумажный контур не заменяет.",
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
