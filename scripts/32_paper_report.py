"""Отчёт по бумажной торговле: факт против ожидания из бэктеста.

Печатает одну строку на конфигурацию: дни, сделки, P&L, средняя сделка и расхождение
с тем, что та же конфигурация дала на истории за тот же период (tracking error).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.configs import CONFIGS  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.live import decision  # noqa: E402

PAPER = Path(__file__).resolve().parent.parent / "results" / "paper.csv"
MULT = 1000.0


def ledger(rows: list[dict]) -> tuple[int, float, int]:
    """P&L по записям журнала: (сделок, руб., дней)."""
    pnl = 0.0
    trades = 0
    pos = 0
    entry = 0.0
    days = set()
    for r in rows:
        days.add(r["date"])
        target = int(r["target"])
        price = float(r["price"])
        if target == pos:
            continue
        if pos != 0:
            pnl += (price - entry) * MULT * pos
            trades += 1
        if target != 0:
            entry = price
        pos = target
    return trades, pnl, len(days)


def expected(cfg, m5: pd.DataFrame, start: str, end: str) -> tuple[int, float]:
    """Что та же конфигурация дала бы на архиве за тот же период."""
    days = sorted({d for d in m5.index.date
                   if str(d) >= start and str(d) <= end and d.weekday() < 5})
    pos = 0
    entry = 0.0
    pnl = 0.0
    trades = 0
    for day in days:
        dec = decision(cfg, m5[m5.index.date <= day], day)
        if dec is None:
            continue
        if dec.target == pos:
            continue
        if pos != 0:
            pnl += (dec.price - entry) * MULT * pos
            trades += 1
        if dec.target != 0:
            entry = dec.price
        pos = dec.target
    return trades, pnl


def main() -> int:
    if not PAPER.exists():
        print("журнала нет")
        return 0
    with PAPER.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if "config" in r]
    if not rows:
        print("журнал пуст")
        return 0

    m5 = load_cached("2026-11/CNYRUBF.txt", 5)
    start, end = rows[0]["date"], rows[-1]["date"]
    print(f"бумажная торговля {start} .. {end}")
    print(f"{'config':10} {'дней':>5} {'сдел':>5} {'факт':>9} {'ожид':>9} {'ошибка':>8}")
    for cfg in CONFIGS:
        mine = [r for r in rows if r["config"] == cfg.id]
        if not mine:
            continue
        trades, pnl, days = ledger(mine)
        e_trades, e_pnl = expected(cfg, m5, start, end)
        print(f"{cfg.id:10} {days:>5} {trades:>5} {pnl:>9.0f} {e_pnl:>9.0f} {pnl - e_pnl:>8.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
