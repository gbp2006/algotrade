"""Журнал прогонов: одна строка на результат, чтобы не держать цифры в чате."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / "results" / "runs.csv"
FIELDS = [
    "ts", "strategy", "instrument", "period", "params", "trades",
    "net", "pf", "avg", "dd", "in_market", "note",
]


def record(
    strategy: str,
    instrument: str,
    period: str,
    stats: dict,
    params: dict | None = None,
    note: str = "",
) -> None:
    """Добавляет результат прогона в results/runs.csv."""
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    new = not RUNS.exists()
    row = {
        "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "strategy": strategy,
        "instrument": instrument,
        "period": period,
        "params": ";".join(f"{k}={v}" for k, v in (params or {}).items()),
        "trades": stats.get("trades", ""),
        "net": stats.get("net_profit", ""),
        "pf": stats.get("profit_factor", ""),
        "avg": stats.get("avg_trade", ""),
        "dd": stats.get("max_drawdown", ""),
        "in_market": stats.get("in_market_pct", ""),
        "note": note,
    }
    with RUNS.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def line(name: str, stats: dict) -> str:
    """Компактная строка для консоли."""
    if not stats or not stats.get("trades"):
        return f"{name:30} нет сделок"
    return (
        f"{name:30} {stats['trades']:>4} сд  {stats['net_profit']:>9} ₽  "
        f"PF {stats['profit_factor']:>5}  DD {stats['max_drawdown']:>8}"
    )
