"""Бумажная торговля по всем конфигурациям на живых котировках Финама.

Две фазы, каждая со своим запуском:
  10:25 — закрытие позиций конфигураций с утренним выходом (u-morning);
  13:55 — решения по всем конфигурациям.

Инструмент задаётся конфигурацией (`algo/configs.py`): CNY — вечный том,
RTS/GOLD — ближайший квартальный контракт (резолв через MOEX ISS).
Журнал: results/paper.csv, строка на (дата, конфигурация). Деньги не тратятся.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

from algo import store  # noqa: E402
from algo.channel_live import channel_decision  # noqa: E402
from algo.broker.finam import FinamBroker  # noqa: E402
from algo.configs import CONFIGS, Config  # noqa: E402 (CONFIGS оставлен для тестовых подмен)
from algo.robot_configs import ROBOT_CONFIGS  # noqa: E402 (для тестовых подмен)
from algo.instruments import DEFAULT, INSTRUMENTS, margin, symbol  # noqa: E402
from algo.live import decision, decision_configs, morning_exit_price  # noqa: E402
from algo.portfolio import CAPITAL, exposure_of, ledger, size_contracts  # noqa: E402
from algo.instance_configs import active_configs, migrate_runtime_from_paper  # noqa: E402
from algo import instruments as inst_mod  # noqa: E402
from algo import rollover_integration  # noqa: E402

PAPER = Path(__file__).resolve().parent.parent / "results" / "paper.csv"
STOP = Path(__file__).resolve().parent.parent / "results" / "STOP"
FIELDS = ["date", "time", "config", "instrument", "symbol", "strategy", "price",
          "signal", "target", "contracts", "equity_before", "action",
          "position_after", "note"]
MSK = timezone(timedelta(hours=3))
ENTRY_MIN = 13 * 60 + 50
ALL_CONFIGS: list[Config] = []  # заполняется в main() из активных инстансов store


def now_msk() -> datetime:
    return datetime.now(MSK)


def instrument_of(cfg):
    return INSTRUMENTS.get(cfg.instrument, DEFAULT)


def capital_of(cfg) -> float:
    return float(cfg.capital or CAPITAL)


def ensure_schema() -> None:
    """Старый формат журнала — отложить или дописать недостающие колонки."""
    if not PAPER.exists():
        return
    with PAPER.open(encoding="utf-8") as f:
        header = f.readline().strip()
    if "config" not in header or "contracts" not in header:
        legacy = PAPER.with_name("paper-legacy.csv")
        PAPER.rename(legacy)
        print(f"старый журнал отложен в {legacy.name}")
        return
    if "instrument" in header and "symbol" in header:
        return
    # миграция: до 19.11.2026 всё торговалось на CNYRUBF
    with PAPER.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r.setdefault("instrument", "CNY")
        r.setdefault("symbol", f"CNYRUBF@RTSX")
    with PAPER.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print("журнал дополнен колонками instrument/symbol")


def read_rows() -> list[dict]:
    if not PAPER.exists():
        return []
    with PAPER.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if "config" in r]


def append(row: dict, rows: list[dict] | None = None) -> None:
    PAPER.parent.mkdir(parents=True, exist_ok=True)
    new = not PAPER.exists()
    with PAPER.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})
    if rows is not None:
        rows.append({k: str(row.get(k, "")) for k in FIELDS})


def position_of(rows: list[dict], config_id: str) -> int:
    pos = 0
    for r in rows:
        if r["config"] == config_id:
            pos = int(r["position_after"])
    return pos


def last_row(rows: list[dict], config_id: str) -> dict | None:
    mine = [r for r in rows if r["config"] == config_id]
    return mine[-1] if mine else None


def equity_of(rows: list[dict], cfg) -> float:
    inst = instrument_of(cfg)
    return ledger(rows, cfg.id, inst.mult, capital_of(cfg))["equity"]


def recorded(rows: list[dict], day: str, config_id: str, action: str) -> bool:
    return any(r["date"] == day and r["config"] == config_id and r["action"] == action
               for r in rows)


def bars_for(b: FinamBroker, sym: str, start: str, day, attempts: int = 7):
    end = (datetime.combine(day, datetime.min.time(), MSK) + timedelta(days=1)
           ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for _ in range(attempts):
        m5 = b.bars(sym, "TIME_FRAME_M5", start, end)
        if not m5.empty:
            return m5
        time.sleep(30)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="реплей дня, формат YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="ничего не записывать")
    ap.add_argument("--channel", action="store_true",
                    help="фаза внутридневного пробоя канала (отдельный таймер)")
    ap.add_argument("--time", help="время реплея HH:MM (только с --date)")
    ap.add_argument("--config", action="append", default=[],
                    help="id конфигурации (можно повторять); без значения — все")
    args = ap.parse_args()

    global ALL_CONFIGS
    if not ALL_CONFIGS:  # тесты подменяют список целиком — не перетираем его
        ALL_CONFIGS = active_configs("paper")
    if args.config:
        wanted = set(args.config)
        ALL_CONFIGS = [c for c in ALL_CONFIGS if c.id in wanted]
        if not ALL_CONFIGS:
            print(f"нет активных конфигураций из {sorted(wanted)}")
            return 0

    ensure_schema()
    if STOP.exists():
        print("стоп-флаг установлен: торговля остановлена (снять — кнопка на дашборде)")
        return 0
    b = FinamBroker()
    now = now_msk()
    replay = args.date is not None
    if replay:
        from datetime import date as _d
        y, m, d = (int(x) for x in args.date.split("-"))
        day = _d(y, m, d)
        now = datetime.combine(day, datetime.min.time(), MSK).replace(hour=14)
        if args.time:
            hh, mm = (int(x) for x in args.time.split(":"))
            now = now.replace(hour=hh, minute=mm)
    else:
        day = now.date()

    if day.weekday() >= 5:
        print(f"{day}: выходной, решений нет")
        return 0

    minutes = now.hour * 60 + now.minute
    if now.weekday() == 4 and minutes >= 18 * 60 + 40:
        phase = "friday"
    elif minutes < 12 * 60:
        phase = "morning"
    else:
        phase = "decision"

    # символы и бары — по одному разу на инструмент.
    # При ALGO_VOL_ROLLOVER=1 нога квартального контракта выбирается по VOL —
    # так же, как в бэктесте; без флага поведение прежнее (страховка бумаги).
    vols_by_inst: dict[str, object] = {}
    if rollover_integration.enabled():
        for inst in inst_mod.INSTRUMENTS.values():
            if inst.symbol or not inst.asset:
                continue
            contracts = inst_mod.active_contracts(inst, day)
            vols_by_inst[inst.code] = rollover_integration.volumes_for(
                b, list(contracts), day)
    symbols = {
        cfg.id: rollover_integration.front_symbol(
            instrument_of(cfg), day, vols_by_inst.get(instrument_of(cfg).code))
        for cfg in ALL_CONFIGS
    }
    start = (datetime.combine(day, datetime.min.time(), MSK) - timedelta(days=10)
             ).strftime("%Y-%m-%dT00:00:00Z")
    m5_by: dict[str, object] = {}
    for sym in dict.fromkeys(symbols.values()):
        m5 = bars_for(b, sym, start, day)
        if m5 is None or m5.empty:
            print(f"нет данных от брокера по {sym}")
            continue
        m5_by[sym] = m5
        # Те бары, по которым реально принимаются решения, — сразу в БД.
        store.init_db()
        store.upsert(m5, sym, "M5", "finam_live")
    if not m5_by:
        print("нет данных от брокера")
        return 2

    rows = read_rows()

    def quote_last(sym: str) -> float:
        return b.quote(sym).last

    # фаза канала: внутридневной пробой, запускается отдельным таймером.
    # Утренний выход (09:00) — тот же таймер, что и у всех: если позиция ещё
    # открыта, channel_decision вернёт 0 по границе start.
    channel_cfgs = [c for c in ALL_CONFIGS if c.strategy == "channel_break"]
    if channel_cfgs and args.channel:
        written = 0
        for cfg in channel_cfgs:
            inst = instrument_of(cfg)
            m5 = m5_by.get(symbols[cfg.id])
            if m5 is not None and replay:
                m5 = m5[m5.index <= pd.Timestamp(now).replace(tzinfo=None)]
            cur_pos = position_of(rows, cfg.id)
            entry = 0.0
            if cur_pos != 0:
                rr = last_row(rows, cfg.id)
                entry = float(rr["price"]) if rr else 0.0
            dec = channel_decision(cfg.params, m5, cur_pos, entry)
            if dec is None or recorded(rows, str(day), cfg.id, "канал"):
                continue
            pos = position_of(rows, cfg.id)
            equity = equity_of(rows, cfg)
            contracts = size_contracts(equity, dec.price, inst.mult, exposure_of(cfg))
            target = dec.target * contracts
            if args.dry_run:
                print(f"{cfg.id:9} {symbols[cfg.id]:13} {dec.ts:%H:%M} канал {dec.target:+d} "
                      f"-> {target:+d} контр.  [dry-run]")
                continue
            append({"date": str(day), "time": dec.ts.strftime("%H:%M"),
                    "config": cfg.id, "instrument": inst.code,
                    "symbol": symbols[cfg.id], "strategy": cfg.strategy,
                    "price": f"{dec.price:.{inst.digits}f}", "signal": dec.target,
                    "target": target, "contracts": contracts,
                    "equity_before": f"{equity:.0f}", "action": "канал",
                    "position_after": target,
                    "note": f"{dec.detail}; лот {contracts}, equity {equity:.0f}"}, rows)
            written += 1
            print(f"{cfg.id:9} {symbols[cfg.id]:13} {dec.ts:%H:%M} канал {dec.target:+d} "
                  f"-> {target:+d} контр.")
        print(f"{day}: канал записано {written}")
        return 0

    if phase == "friday":
        closed = 0
        for cfg in ALL_CONFIGS:
            if not cfg.params.get("close_friday"):
                continue
            inst = instrument_of(cfg)
            pos = position_of(rows, cfg.id)
            if pos == 0 or recorded(rows, str(day), cfg.id, "пятница"):
                continue
            price = quote_last(symbols[cfg.id])
            exit_price = price - (inst.tick * pos / abs(pos))
            append({"date": str(day), "time": now.strftime("%H:%M"), "config": cfg.id,
                    "instrument": inst.code, "symbol": symbols[cfg.id],
                    "strategy": cfg.strategy, "price": f"{exit_price:.{inst.digits}f}",
                    "signal": 0, "target": 0, "contracts": 0, "equity_before": "0",
                    "action": "пятница", "position_after": 0,
                    "note": f"закрытие перед выходными по {exit_price:.{inst.digits}f}"})
            closed += 1
        print(f"{day}: пятничное закрытие, позиций закрыто {closed}")
        return 0

    if phase == "morning":
        closed = 0
        for cfg in ALL_CONFIGS:
            if cfg.params.get("hold") != "morning":
                continue
            inst = instrument_of(cfg)
            m5 = m5_by.get(symbols[cfg.id])
            price = morning_exit_price(m5, day) if m5 is not None else None
            if price is None:
                continue
            pos = position_of(rows, cfg.id)
            if pos == 0 or recorded(rows, str(day), cfg.id, "закрыть"):
                continue
            append({"date": str(day), "time": "10:20", "config": cfg.id,
                    "instrument": inst.code, "symbol": symbols[cfg.id],
                    "strategy": cfg.strategy, "price": f"{price:.{inst.digits}f}",
                    "signal": 0, "target": 0, "contracts": 0, "equity_before": f"{pos}",
                    "action": "закрыть", "position_after": 0,
                    "note": "утренний выход 10:20"})
            closed += 1
        print(f"{day}: утренний выход, закрыто позиций {closed}")
        return 0

    # фаза решений
    if now.hour * 60 + now.minute < ENTRY_MIN:
        print(f"{now:%H:%M}: решения будут с 13:50")
        return 0

    written = 0
    for cfg in decision_configs(ALL_CONFIGS):
        # hold="morning" решает здесь же (вход 13:30), а выходит своей фазой в 10:25
        inst = instrument_of(cfg)
        sym = symbols[cfg.id]
        m5 = m5_by.get(sym)
        if m5 is None:
            print(f"{cfg.id}: нет баров по {sym}")
            continue

        dec = None
        for attempt in range(4):
            dec = decision(cfg, m5, day)
            if dec is not None:
                break
            time.sleep(30)
        if dec is None:
            print(f"{cfg.id}: решения ещё нет")
            continue
        if recorded(rows, str(day), cfg.id, "решение"):
            continue

        # ролл квартального контракта: закрыть старую ногу по последней цене
        last = last_row(rows, cfg.id)
        if (last and last.get("symbol") and last["symbol"] != sym
                and position_of(rows, cfg.id) != 0 and not args.dry_run):
            append({"date": str(day), "time": dec.ts.strftime("%H:%M"),
                    "config": cfg.id, "instrument": inst.code,
                    "symbol": last["symbol"], "strategy": cfg.strategy,
                    "price": last["price"], "signal": 0, "target": 0,
                    "contracts": 0, "equity_before": "",
                    "action": "ролл", "position_after": 0,
                    "note": f"экспирация {last['symbol']}, переходим на {sym}"},
                   rows)

        pos = position_of(rows, cfg.id)
        equity = equity_of(rows, cfg)
        contracts = (size_contracts(equity, dec.price, inst.mult, exposure_of(cfg))
                     if dec.target != 0 else 0)
        target = dec.target * contracts
        action = "держать" if target == pos else (
            "закрыть" if target == 0 else ("купить" if target > 0 else "продать"))
        msg = (f"{cfg.id:9} {sym:13} {dec.ts:%H:%M} сигнал {dec.target:+d} -> "
               f"{target:+d} контр. (лот {contracts}, equity {equity:.0f}) {action}")
        if args.dry_run:
            print(msg + "  [dry-run]")
            continue
        append({"date": str(day), "time": dec.ts.strftime("%H:%M"), "config": cfg.id,
                "instrument": inst.code, "symbol": sym,
                "strategy": cfg.strategy, "price": f"{dec.price:.{inst.digits}f}",
                "signal": dec.target, "target": target, "contracts": contracts,
                "equity_before": f"{equity:.0f}", "action": "решение",
                "position_after": target,
                "note": f"{dec.detail}; лот {contracts}, equity {equity:.0f}"}, rows)
        written += 1
        print(msg)

    spreads = []
    sym_inst: dict[str, object] = {}
    for cfg in ALL_CONFIGS:
        sym_inst[symbols[cfg.id]] = instrument_of(cfg)
    for sym, inst in sym_inst.items():
        try:
            q = b.quote(sym)
            spreads.append(f"{sym} {(q.ask - q.bid) / inst.tick:.0f} тик")
        except Exception:  # noqa: BLE001
            pass
    if not args.dry_run:
        try:
            migrate_runtime_from_paper()
        except Exception as exc:  # noqa: BLE001 — журнал важнее рантайм-зеркала
            print(f"runtime state: {type(exc).__name__}: {exc}")
    print(f"{day}: записано конфигураций {written}; спреды: {', '.join(spreads)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
