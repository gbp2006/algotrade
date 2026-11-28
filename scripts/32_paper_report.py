"""Отчёт по бумажной торговле: дни, сделки, P&L и метрики из журнала.

Печатает одну строку на конфигурацию и сохраняет снимок метрик в SQLite.
Сверка факта с ожиданием вынесена из проекта (ADR 28.11): при необходимости
проверки расхождения считаются локально по журналам.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Живой контур читает .env (ALGO_EXPOSURE, ALGO_CAPITAL): отчёт считает
# капитал и экспозицию по тем же настройкам.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from algo import metrics_store  # noqa: E402
from algo.instruments import DEFAULT, INSTRUMENTS  # noqa: E402
from algo.instance_configs import active_configs  # noqa: E402
from algo.portfolio import CAPITAL, drawdown_stats  # noqa: E402

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


def trade_stats(rows: list[dict], mult: float) -> tuple[int, int, int, float, float]:
    """(сделок, побед, поражений, gross_win, gross_loss) по журналу конфигурации."""
    pos, entry, wins, losses, gw, gl, trades = 0, 0.0, 0, 0, 0.0, 0.0, 0
    for r in rows:
        target, price = int(r["target"]), float(r["price"])
        if target == pos:
            continue
        if pos != 0:
            pnl = (price - entry) * mult * pos
            trades += 1
            if pnl > 0:
                wins += 1
                gw += pnl
            elif pnl < 0:
                losses += 1
                gl -= pnl
        entry = price if target != 0 else 0.0
        pos = target
    return trades, wins, losses, gw, gl


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


def decision_times(rows: list[dict], day: str) -> dict[str, str]:
    """Время решения по конфигу — без закрытий 18:45 и утренних выходов."""
    last: dict[str, str] = {}
    for r in rows:
        if r["date"] == day and r.get("action") in {"решение", "канал"}:
            cid = r["config"]
            if r["time"] > last.get(cid, ""):
                last[cid] = r["time"]
    for r in rows:
        if r["date"] == day:
            cid = r["config"]
            if cid not in last and r["time"] > last.get(cid, ""):
                last[cid] = r["time"]
    return last


def build_rows() -> tuple[list[dict], str, str]:
    """Сводка по бумажному журналу: метрики конфигураций и окно дат."""
    if not PAPER.exists():
        return [], "", ""
    with PAPER.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if "config" in r]
    if not rows:
        return [], "", ""

    start, end = rows[0]["date"], rows[-1]["date"]
    out: list[dict] = []
    try:
        cfgs = {c.id: c for c in active_configs("paper")}
    except Exception:  # noqa: BLE001 — без БД отчёт пустой
        cfgs = {}
    for cfg in cfgs.values():
        mine = [r for r in rows if r["config"] == cfg.id]
        if not mine:
            continue
        inst = instrument_of(cfg)
        mult, capital = inst.mult, capital_of(cfg)
        trades, pnl, days = ledger(mine, mult)
        dd = _dd_stats(mine, mult, capital)
        n, wins, losses, gw, gl = trade_stats(mine, mult)
        last = mine[-1]
        position = int(last["target"])
        last_px = float(last["price"])
        notional = abs(position) * last_px * mult
        out.append({
            "config": cfg.id, "instrument": inst.code, "days": days,
            "trades": trades, "pnl": pnl,
            "max_dd": dd["max_dd"], "max_dd_days": dd["max_dd_days"],
            "capital": capital, "equity": capital + pnl, "realized": pnl,
            "dd_abs": dd["max_dd"],
            "dd_pct": round(100 * abs(dd["max_dd"]) / capital, 2) if capital else 0.0,
            "wins": wins, "losses": losses,
            "winrate": round(100 * wins / n, 1) if n else 0.0,
            "avg_trade": round(pnl / n, 2) if n else 0.0,
            "profit_factor": round(gw / gl, 2) if gl else None,
            "position": position, "notional": round(notional),
            "exposure_pct": round(100 * notional / capital, 1) if capital else 0.0,
            "pnl_pct": round(100 * pnl / capital, 2) if capital else 0.0,
        })
    return out, start, end


def main() -> int:
    rows, start, end = build_rows()
    if not rows:
        print("журнала нет" if not PAPER.exists() else "журнал пуст")
        return 0
    print(f"бумажная торговля {start} .. {end}")
    print(f"{'config':11} {'инстр':6} {'дней':>5} {'сдел':>5} {'P&L':>9} "
          f"{'DD':>8} {'DDдн':>5}")
    for r in rows:
        print(f"{r['config']:11} {r['instrument']:6} {r['days']:>5} {r['trades']:>5} "
              f"{r['pnl']:>9.0f} {r['max_dd']:>8.0f} {r['max_dd_days']:>5}")
    # История состояния счетов и метрик для панели/анализа (SQLite, не выкладывается)
    saved = metrics_store.save_snapshot(pd.Timestamp.now().strftime("%Y-%m-%d"), rows)
    print(f"снапшотов метрик в БД: {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
