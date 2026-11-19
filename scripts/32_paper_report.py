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
from algo.instruments import DEFAULT, INSTRUMENTS  # noqa: E402
from algo.live import decision  # noqa: E402
from algo.portfolio import CAPITAL, drawdown_stats, size_contracts  # noqa: E402

PAPER = Path(__file__).resolve().parent.parent / "results" / "paper.csv"


def instrument_of(cfg):
    return INSTRUMENTS.get(cfg.instrument, DEFAULT)


def capital_of(cfg) -> float:
    return float(cfg.capital or CAPITAL)


def ledger(rows: list[dict], mult: float) -> tuple[int, float, int]:
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
            pnl += (price - entry) * mult * pos
            trades += 1
        if target != 0:
            entry = price
        pos = target
    return trades, pnl, len(days)


def expected(cfg, m5: pd.DataFrame, start: str, end: str,
             mult: float, capital: float) -> tuple[int, float]:
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
        contracts = size_contracts(capital + pnl, dec.price, mult) if dec.target != 0 else 0
        target = dec.target * contracts
        if target == pos:
            continue
        if pos != 0:
            pnl += (dec.price - entry) * mult * pos
            trades += 1
        if target != 0:
            entry = dec.price
        pos = target
    return trades, pnl


def _dd_stats(rows: list[dict], mult: float, capital: float) -> dict:
    pos, entry, acc = 0, 0.0, capital
    pts = []
    for r in rows:
        target, price = int(r["target"]), float(r["price"])
        if target != pos:
            if pos != 0:
                acc += (price - entry) * mult * pos
                pts.append((r["date"], acc))
            if target != 0:
                entry = price
            pos = target
    return drawdown_stats(pts)


def main() -> int:
    if not PAPER.exists():
        print("журнала нет")
        return 0
    with PAPER.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if "config" in r]
    if not rows:
        print("журнал пуст")
        return 0

    start, end = rows[0]["date"], rows[-1]["date"]
    print(f"бумажная торговля {start} .. {end}")
    print(f"{'config':11} {'инстр':6} {'дней':>5} {'сдел':>5} {'факт':>9} "
          f"{'ожид':>9} {'ошибка':>8} {'DD':>8} {'DDдн':>5}")
    cache: dict[str, pd.DataFrame] = {}
    for cfg in CONFIGS:
        mine = [r for r in rows if r["config"] == cfg.id]
        if not mine:
            continue
        inst = instrument_of(cfg)
        mult, capital = inst.mult, capital_of(cfg)
        trades, pnl, days = ledger(mine, mult)
        if inst.file not in cache:
            try:
                cache[inst.file] = load_cached(inst.file, 5)
            except FileNotFoundError:
                cache[inst.file] = None          # архива нет на этой машине
        e_pnl = None
        if cache[inst.file] is not None:
            e_trades, e_pnl = expected(cfg, cache[inst.file], start, end, mult, capital)
        dd = _dd_stats(mine, mult, capital)
        exp_s = f"{e_pnl:>9.0f} {pnl - e_pnl:>8.0f}" if e_pnl is not None else f"{'—':>9} {'—':>8}"
        print(f"{cfg.id:11} {inst.code:6} {days:>5} {trades:>5} {pnl:>9.0f} "
              f"{exp_s} {dd['max_dd']:>8.0f} {dd['max_dd_days']:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
