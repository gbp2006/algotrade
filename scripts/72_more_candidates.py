"""Вторая партия прототипов из каталога (ещё 8 правил), train → OOS.

Использует harness из 70_candidates.py. Отчёт: reports/strategy-more.md.
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

from algo import results  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402

REPORT = Path("reports/strategy-more.md")
BUILDERS = [
    ("T24 Turtle System 2", "turtle2", lambda d: C.donchian(d, 55, 20)),
    ("T19 SMA 10/30", "sma10", lambda d: C.sma_cross(d, 10, 30)),
    ("T20 SMA 20/60", "sma20", lambda d: C.sma_cross(d, 20, 60)),
    ("T27 ROC(5)", "roc5", lambda d: C.roc(d, 5)),
    ("T28 VMA 5/10", "vma5", lambda d: C.vma(d, 5, 10)),
    ("T29 MACD 5/10", "macd5", lambda d: C.macd(d, 5, 10)),
    ("M22 Halloween", "hallow", lambda d: C.halloween(d)),
    ("R10 RSI(14) reversal", "rsi14rev", lambda d: C.rsi_reversal(d, 14, 70, 30)),
]


def main() -> None:
    data = {n: c70.load_cached(s["path"], minutes=5) for n, s in c70.SPECS.items()}
    rows = []
    for name, spec in c70.SPECS.items():
        for label, key, builder in BUILDERS:
            for period, start, end in c70.PERIODS:
                try:
                    st = c70.backtest(data[name], spec, start, end, builder)
                    rows.append(dict(instrument=name, strategy=label, key=key,
                                     period=period, **st))
                except Exception as exc:
                    rows.append(dict(instrument=name, strategy=label, key=key,
                                     period=period, trades=0, net_profit=0.0,
                                     profit_factor=0.0, avg_trade=0.0,
                                     max_drawdown=0.0, win_rate=0.0,
                                     in_market_pct=0.0, error=str(exc)[:120]))

    for r in rows:
        if r["period"] != "oos" or r.get("error"):
            continue
        results.record(strategy=f"cand_{r['key']}", instrument=r["instrument"],
                       period="oos 2026", stats=r,
                       params=dict(source="strategy-catalog", prototype="72_more"),
                       note="вторая партия прототипов; без сайзинга")

    write_report(rows)
    print("Прогон: ещё 8 кандидатов x 2 инструмента x train/OOS")
    for name in c70.SPECS:
        oos = [r for r in rows if r["instrument"] == name and r["period"] == "oos"
               and r.get("trades", 0) > 0]
        good = [r for r in oos if r["profit_factor"] > 1]
        print(f"{name}: OOS PF>1 у {len(good)}/{len(oos)} — "
              + ", ".join(f"{r['strategy']}={r['profit_factor']}" for r in good))
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict]) -> None:
    L = [
        "# Вторая партия прототипов", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/72_more_candidates.py`.",
        "Методика — `reports/strategy-prototypes.md` (look-ahead убран).", "",
        "| инструмент | стратегия | период | сделок | net | PF | avg | DD | в рынке % |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        err = f" ОШИБКА: {r['error']}" if r.get("error") else ""
        L.append(f"| {r['instrument']} | {r['strategy']} | {r['period']} | {r['trades']} | "
                 f"{r['net_profit']} | {r['profit_factor']} | {r['avg_trade']} | "
                 f"{r['max_drawdown']} | {r['in_market_pct']}{err} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
