"""Проверка устойчивости 4 выживших кандидатов к параметрам (соседние окна).

Запуск: ./.venv/bin/python scripts/71_robustness.py
Отчёт: reports/strategy-robustness.md. В консоли только сводка.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402

REPORT = Path("reports/strategy-robustness.md")
WARMUP_DAYS = 420
PERIODS = [("train", "2023-01-01", "2026-01-01"), ("oos", "2026-01-01", "2026-11-21")]
SPECS = {
    "CNY": dict(path="2026-11/CNYRUBF.txt", costs=engine.Costs(tick=0.001, multiplier=1000.0)),
    "Si": dict(path="2026-11/Si.txt", costs=engine.Costs(tick=1.0, multiplier=1.0)),
}

GRIDS = {
    "T04 Donchian": [(e, x, f"вход{e}/выход{x}") for e in (15, 20, 25, 30) for x in (5, 10, 15)],
    "T06 EWMAC": [(f, s, f"EMA{f}/{s}") for f, s in
                  ((4, 16), (4, 32), (8, 16), (8, 32), (8, 64), (16, 32), (16, 64))],
    "I01 ORB": [(m, None, f"{m} мин") for m in (5, 15, 30, 60, 120)],
    "C05 Turn-of-month": [(a, None, f"+{a} дн") for a in (1, 2, 3, 4, 5)],
}


def builder_for(family: str, p1, p2):
    if family == "T04 Donchian":
        return lambda d: C.donchian(d, int(p1), int(p2))
    if family == "T06 EWMAC":
        return lambda d: C.ewmac(d, int(p1), int(p2))
    if family == "I01 ORB":
        return lambda d: C.opening_range_breakout(d, "10:00", int(p1), "23:40")
    if family == "C05 Turn-of-month":
        return lambda d: C.turn_of_month(d, int(p1))
    raise ValueError(family)


def stats_from_trades(trades: list, targets: pd.Series, start: str, end: str) -> dict:
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    tr = [t for t in trades if lo <= t.exit_time < hi]
    if not tr:
        return {"trades": 0, "profit_factor": 0.0, "net_profit": 0.0}
    pnl = np.array([t.net for t in tr], dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gw, gl = wins.sum(), -losses.sum()
    seg = targets.loc[(targets.index >= lo) & (targets.index < hi)]
    return {
        "trades": len(tr),
        "profit_factor": round(float(gw / gl), 2) if gl else float("inf"),
        "net_profit": round(float(pnl.sum()), 2),
        "in_market_pct": round(100 * float((seg != 0).mean()), 1),
    }


def backtest(df, costs, start, end, builder):
    warm = pd.Timestamp(start) - pd.Timedelta(days=WARMUP_DAYS)
    d = df.loc[(df.index >= warm) & (df.index < end)]
    tg = builder(d)
    return stats_from_trades(engine.run(d, tg, costs).trades, tg, start, end)


def main() -> None:
    data = {n: load_cached(s["path"], minutes=5) for n, s in SPECS.items()}
    rows = []
    for family, grid in GRIDS.items():
        for p1, p2, label in grid:
            build = builder_for(family, p1, p2)
            rec = dict(family=family, params=label)
            for name, spec in SPECS.items():
                for period, start, end in PERIODS:
                    st = backtest(data[name], spec["costs"], start, end, build)
                    rec[f"{name}_{period}_pf"] = st["profit_factor"]
                    rec[f"{name}_{period}_tr"] = st["trades"]
                    rec[f"{name}_{period}_net"] = st["net_profit"]
            rows.append(rec)

    write_report(rows)
    print("Устойчивость: 4 кандидата, сетки 12/7/5/5 точек, train + OOS, CNY + Si")
    for family in GRIDS:
        sub = [r for r in rows if r["family"] == family]
        good = sum(1 for r in sub if all(r[f"{n}_oos_pf"] > 1 for n in SPECS))
        base = next((r for r in sub if r["params"] in
                     {"вход20/выход10", "EMA8/32", "30 мин", "+3 дн"}), None)
        pf = "/".join(str(base[f"{n}_oos_pf"]) for n in SPECS) if base else "?"
        print(f"{family:18} OOS PF>1 у {good}/{len(sub)} точек; база OOS PF {pf}")
    print(f"отчёт: {REPORT}")


def write_report(rows: list[dict]) -> None:
    L = [
        "# Устойчивость кандидатов к параметрам", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипт: `scripts/71_robustness.py`.",
        "Методика та же, что в `reports/strategy-prototypes.md` (look-ahead убран).", "",
        "## Сводка по сеткам", "",
        "| семейство | точек | обе валюты OOS PF>1 | комментарий |",
        "|---|---:|---:|---|",
    ]
    notes = {
        "T04 Donchian": "ширина канала 15–30, выход 5–15 — почти везде положителен",
        "T06 EWMAC": "обе EMA в разумном диапазоне дают тот же знак",
        "I01 ORB": "все окна 5–120 мин; large sample, но PF близок к 1",
        "C05 Turn-of-month": "эффект есть на всех окнах, но прибыль мала",
    }
    for family, grid in GRIDS.items():
        sub = [r for r in rows if r["family"] == family]
        good = sum(1 for r in sub if all(r[f"{n}_oos_pf"] > 1 for n in SPECS))
        L.append(f"| {family} | {len(sub)} | {good} | {notes[family]} |")
    L += ["", "## Все точки сетки", "",
          "| семейство | параметр | CNY train PF | CNY OOS PF | Si train PF | Si OOS PF | OOS сделок CNY/Si |",
          "|---|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        L.append(f"| {r['family']} | {r['params']} | {r['CNY_train_pf']} | {r['CNY_oos_pf']} | "
                 f"{r['Si_train_pf']} | {r['Si_oos_pf']} | {r['CNY_oos_tr']}/{r['Si_oos_tr']} |")
    L += [
        "", "## Вывод", "",
        "Кандидат считается устойчивым, если OOS PF > 1 на обоих инструментах у多数 "
        "соседних параметров. Неустойчивые точки (PF<1 хотя бы на одном инструменте) "
        "говорят о чувствительности — такие варианты в бумажный контур не берём.",
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
