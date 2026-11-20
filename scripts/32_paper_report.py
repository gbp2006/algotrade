"""Отчёт по бумажной торговле: факт против ожидания из бэктеста.

Печатает одну строку на конфигурацию: дни, сделки, P&L, средняя сделка и расхождение
с тем, что та же конфигурация дала на истории за тот же период (tracking error).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Живой контур читает .env (ALGO_EXPOSURE, ALGO_CAPITAL). Ожидание обязано
# считаться теми же деньгами, иначе tracking error показывает разницу лотности,
# а не расхождение сигнала с исполнением.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from algo.configs import CONFIGS  # noqa: E402
from algo.robot_configs import ROBOT_CONFIGS  # noqa: E402
from algo import store  # noqa: E402
from algo.data import load_cached, to_timeframe  # noqa: E402
from algo.instruments import DEFAULT, INSTRUMENTS  # noqa: E402
from algo.instruments import symbol as contract_symbol  # noqa: E402
from algo.live import decision  # noqa: E402
from algo.portfolio import (CAPITAL, drawdown_stats,  # noqa: E402
                            exposure_of, size_contracts)

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
             mult: float, capital: float, tick: float = 0.0) -> tuple[int, float]:
    """Что та же конфигурация дала бы на архиве за тот же период."""
    days = sorted({d for d in m5.index.date
                   if str(d) >= start and str(d) <= end and d.weekday() < 5})
    pos = 0
    entry = 0.0
    pnl = 0.0
    trades = 0
    decisions = 0
    for day in days:
        dec = decision(cfg, m5[m5.index.date <= day], day)
        if dec is None:
            continue
        decisions += 1
        contracts = size_contracts(capital + pnl, dec.price, mult,
                                              exposure_of(cfg)) if dec.target != 0 else 0
        target = dec.target * contracts
        if target != pos:
            if pos != 0:
                pnl += (dec.price - entry) * mult * pos
                trades += 1
            if target != 0:
                entry = dec.price
            pos = target
        # p-friday закрывается в 18:45 пятницы — ожидание обязано это моделировать,
        # иначе отчёт показывает ложный tracking error после срабатывания таймера.
        if cfg.params.get("close_friday") and day.weekday() == 4 and pos != 0:
            today = m5[m5.index.date == day]
            closed = today[(today.index.hour * 60 + today.index.minute) <= 18 * 60 + 45]
            if not closed.empty:
                # живое закрытие берёт котировку минус 1 тик проскальзывания
                exit_price = float(closed["close"].iloc[-1]) - tick * (1 if pos > 0 else -1)
                pnl += (exit_price - entry) * mult * pos
                trades += 1
                entry, pos = 0.0, 0
    if decisions == 0:
        return None, None          # архив не покрывает период — ожидания нет
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


def _symbol_of(inst) -> str:
    if inst.symbol:
        return inst.symbol
    try:
        return contract_symbol(inst)
    except Exception:  # нет сети/кэша ISS — имя не критично, вернём код
        return inst.code


def expected_bars(inst) -> pd.DataFrame | None:
    """Бары для ожидания: живые M5 из БД, потом CSV, потом архив."""
    if store.DB_PATH.exists():
        try:
            sym = _symbol_of(inst)
            df = store.read(sym, "M5", source="finam_live")
            if not df.empty:
                return df
            m1 = store.read(sym, "M1")
            if not m1.empty:
                return to_timeframe(m1, 5)
        except Exception:  # нет таблицы или прав — откатываемся к файлу
            pass
    live = ROOT / "results" / f"finam_m5_{inst.code}.csv"
    if live.exists():
        df = pd.read_csv(live, parse_dates=["dt"]).set_index("dt")
        return df[["open", "high", "low", "close", "vol"]]
    try:
        return load_cached(inst.file, 5) if inst.file else None
    except (FileNotFoundError, TypeError):
        return None


def build_rows() -> tuple[list[dict], str, str]:
    """Сводка факт/ожидание для отчёта и для стража (одна логика, без парсинга вывода)."""
    if not PAPER.exists():
        return [], "", ""
    with PAPER.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if "config" in r]
    if not rows:
        return [], "", ""

    start, end = rows[0]["date"], rows[-1]["date"]
    out: list[dict] = []
    cache: dict[str, pd.DataFrame] = {}
    for cfg in CONFIGS + ROBOT_CONFIGS:
        mine = [r for r in rows if r["config"] == cfg.id]
        if not mine:
            continue
        inst = instrument_of(cfg)
        mult, capital = inst.mult, capital_of(cfg)
        trades, pnl, days = ledger(mine, mult)
        if inst.code not in cache:
            cache[inst.code] = expected_bars(inst)
        e_pnl = None
        if cache[inst.code] is not None:
            e_trades, e_pnl = expected(cfg, cache[inst.code], start, end,
                                       mult, capital, tick=inst.tick)
        dd = _dd_stats(mine, mult, capital)
        out.append({"config": cfg.id, "instrument": inst.code, "days": days,
                    "trades": trades, "pnl": pnl, "expected": e_pnl,
                    "error": None if e_pnl is None else pnl - e_pnl,
                    "max_dd": dd["max_dd"], "max_dd_days": dd["max_dd_days"]})
    return out, start, end


COMPARE_IDS = [
    ("p-ma50", "p-base"), ("p-fast2", "p-base"),
    ("u-1340", "u-base"), ("p-train", "p-base"), ("cb-day", "p-base"),
]


def robot_compare(rows: list[dict]) -> list[dict]:
    """Новые роботы против базы на одном журнале и одном окне дат."""
    by_id = {r["config"]: r for r in rows}
    out = []
    for robot, base in COMPARE_IDS:
        a, b = by_id.get(robot), by_id.get(base)
        if a and b and a["days"] >= 2:
            out.append({
                "robot": robot, "base": base, "days": a["days"],
                "robot_pnl": round(a["pnl"], 0), "base_pnl": round(b["pnl"], 0),
                "delta": round(a["pnl"] - b["pnl"], 0),
                "robot_dd": round(a["max_dd"], 0), "base_dd": round(b["max_dd"], 0),
                "robot_trades": a["trades"], "base_trades": b["trades"],
            })
        else:
            out.append({"robot": robot, "base": base, "days": (a or {}).get("days", 0),
                        "status": "нет данных"})
    return out


def main() -> int:
    rows, start, end = build_rows()
    if not rows:
        print("журнала нет" if not PAPER.exists() else "журнал пуст")
        return 0
    print(f"бумажная торговля {start} .. {end}")
    print(f"{'config':11} {'инстр':6} {'дней':>5} {'сдел':>5} {'факт':>9} "
          f"{'ожид':>9} {'ошибка':>8} {'DD':>8} {'DDдн':>5}")
    for r in rows:
        exp_s = (f"{r['expected']:>9.0f} {r['error']:>8.0f}"
                 if r["expected"] is not None else f"{'—':>9} {'—':>8}")
        print(f"{r['config']:11} {r['instrument']:6} {r['days']:>5} {r['trades']:>5} "
              f"{r['pnl']:>9.0f} {exp_s} {r['max_dd']:>8.0f} {r['max_dd_days']:>5}")
    cmp = robot_compare(rows)
    ready = [r for r in cmp if "delta" in r]
    print(f"\n--- новые роботы против базы ({len(ready)}/{len(cmp)} с данными) ---")
    for r in cmp:
        if "delta" not in r:
            print(f"{r['robot']:11} ждём данных ({r['days']} дней)")
        else:
            print(f"{r['robot']:11} vs {r['base']:7} {r['days']:>2} дн. "
                  f"дельта {r['delta']:>+8.0f} ₽ "
                  f"(робот {r['robot_pnl']:>+8.0f} / база {r['base_pnl']:>+8.0f}), "
                  f"DD {r['robot_dd']:>7.0f}/{r['base_dd']:>7.0f}")
    (ROOT / "results" / "robot_compare.csv").write_text(
        pd.DataFrame(cmp).to_csv(index=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
