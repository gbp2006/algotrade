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
from algo import risk  # noqa: E402
from algo import store  # noqa: E402
from algo import metrics_store  # noqa: E402
from algo.data import load_cached, to_timeframe  # noqa: E402
from algo.instruments import DEFAULT, INSTRUMENTS  # noqa: E402
from algo.instruments import symbol as contract_symbol  # noqa: E402
from algo.instance_configs import active_configs, configs_at
from algo.live import decision, morning_exit_price  # noqa: E402
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


def expected(cfg, m5: pd.DataFrame, start: str, end: str,
             mult: float, capital: float, tick: float = 0.0,
             cfg_for=None) -> tuple[int, float]:
    """Что та же конфигурация дала бы на архиве за тот же период.

    Лот считается живым risk.contracts_for_config, включая ATR-резку сайза.
    `cfg_for(day)` возвращает конфиг, действовавший в этот день: параметры
    меняются из панели, и пересчёт всего периода по сегодняшним параметрам
    даёт ложный tracking error.
    """
    days = sorted({d for d in m5.index.date
                   if str(d) >= start and str(d) <= end and d.weekday() < 5})
    pos = 0
    entry = 0.0
    pnl = 0.0
    trades = 0
    decisions = 0
    for day in days:
        cur = cfg_for(day) if cfg_for else cfg
        # утренний выход 10:20 работает до дневного решения и тоже меняет P&L
        if cur.params.get("hold") == "morning" and pos != 0:
            exit_price = morning_exit_price(m5, day)
            if exit_price is not None:
                pnl += (exit_price - entry) * mult * pos
                trades += 1
                entry, pos = 0.0, 0
        dec = decision(cur, m5[m5.index.date <= day], day)
        if dec is None:
            continue
        decisions += 1
        if dec.target != 0:
            # Ожидание обязано повторять живой лот: новые роботы режут сайз по ATR,
            # иначе tracking error показывает разницу лотности, а не исполнения.
            risk_bars = m5[(m5.index.date <= day)
                           & (m5.index <= dec.ts + pd.Timedelta(minutes=5))]
            contracts, _ = risk.contracts_for_config(
                cur, capital + pnl, dec.price, mult, risk_bars, [], day, capital)
        else:
            contracts = 0
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
        if cur.params.get("close_friday") and day.weekday() == 4 and pos != 0:
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
    # Конфиг мог быть изменён в панели внутри периода: ожидание обязано
    # использовать параметры, действовавшие в день каждого решения.
    cfgs = {c.id: c for c in CONFIGS + ROBOT_CONFIGS}
    try:
        cfgs.update({c.id: c for c in active_configs("paper")})
    except Exception:  # noqa: BLE001 — без БД остаётся статический реестр
        pass
    day_cfgs: dict[str, dict[str, object]] = {}
    for day in sorted({r["date"] for r in rows}):
        try:
            day_cfgs[day] = {c.id: c for c in configs_at(day)}
        except Exception:  # noqa: BLE001 — нет БД → статический реестр
            day_cfgs[day] = {}
    for cfg in cfgs.values():
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
            # Окно ожидания — по датам самого конфигурации: новые роботы вошли
            # в журнал позже базы, и сравнение с её 3 днями давало ложный error.
            c_start, c_end = mine[0]["date"], mine[-1]["date"]
            by_day = day_cfgs
            e_trades, e_pnl = expected(
                cfg, cache[inst.code], c_start, c_end, mult, capital,
                tick=inst.tick,
                cfg_for=lambda d, cid=cfg.id: by_day.get(str(d), {}).get(cid, cfg))
        dd = _dd_stats(mine, mult, capital)
        n, wins, losses, gw, gl = trade_stats(mine, mult)
        last = mine[-1]
        position = int(last["target"])
        last_px = float(last["price"])
        notional = abs(position) * last_px * mult
        out.append({
            "config": cfg.id, "instrument": inst.code, "days": days,
            "trades": trades, "pnl": pnl, "expected": e_pnl,
            "error": None if e_pnl is None else pnl - e_pnl,
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


COMPARE_IDS = [
    ("p-ma50", "p-base"), ("p-fast2", "p-base"),
    ("u-1340", "u-base"), ("p-train", "p-base"),
    ("cb-day", "p-base"), ("cb-day-si", "p-base"),
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
    # История состояния счетов и метрик для панели/анализа (SQLite, не выкладывается)
    saved = metrics_store.save_snapshot(pd.Timestamp.now().strftime("%Y-%m-%d"), rows)
    print(f"снапшотов метрик в БД: {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
