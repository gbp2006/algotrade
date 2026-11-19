"""Бумажная торговля по всем конфигурациям на живых котировках Финама.

Две фазы, каждая со своим запуском:
  10:25 — закрытие позиций конфигураций с утренним выходом (u-morning);
  13:55 — решения по всем конфигурациям.

Журнал: results/paper.csv, строка на (дата, конфигурация). Деньги не тратятся.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

from algo.broker.finam import FinamBroker  # noqa: E402
from algo.configs import CONFIGS  # noqa: E402
from algo.live import decision, morning_exit_price  # noqa: E402
from algo.portfolio import ledger, size_contracts  # noqa: E402

PAPER = Path(__file__).resolve().parent.parent / "results" / "paper.csv"
FIELDS = ["date", "time", "config", "strategy", "price", "signal", "target",
          "contracts", "equity_before", "action", "position_after", "note"]
SYMBOL = "CNYRUBF@RTSX"
MSK = timezone(timedelta(hours=3))
ENTRY_MIN = 13 * 60 + 50
MORNING_MIN = 10 * 60 + 20


def now_msk() -> datetime:
    return datetime.now(MSK)


def ensure_schema() -> None:
    """Если журнал старого формата (без колонки config) — отложить его."""
    if not PAPER.exists():
        return
    with PAPER.open(encoding="utf-8") as f:
        header = f.readline().strip()
    if "config" not in header or "contracts" not in header:
        legacy = PAPER.with_name("paper-legacy.csv")
        PAPER.rename(legacy)
        print(f"старый журнал отложен в {legacy.name}")


def read_rows() -> list[dict]:
    if not PAPER.exists():
        return []
    with PAPER.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def position_of(rows: list[dict], config_id: str) -> int:
    pos = 0
    for r in rows:
        if r["config"] == config_id:
            pos = int(r["position_after"])
    return pos


def equity_of(rows: list[dict], config_id: str) -> float:
    return ledger(rows, config_id)["equity"]


def recorded(rows: list[dict], day: str, config_id: str, action: str) -> bool:
    return any(r["date"] == day and r["config"] == config_id and r["action"] == action
               for r in rows)


def append(row: dict) -> None:
    PAPER.parent.mkdir(parents=True, exist_ok=True)
    new = not PAPER.exists()
    with PAPER.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="реплей дня, формат YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="ничего не записывать")
    args = ap.parse_args()

    ensure_schema()
    stop = Path(__file__).resolve().parent.parent / "results" / "STOP"
    if stop.exists():
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
    else:
        day = now.date()

    if day.weekday() >= 5:
        print(f"{day}: выходной, решений нет")
        return 0

    phase = "morning" if now.hour * 60 + now.minute < 12 * 60 else "decision"

    start = (datetime.combine(day, datetime.min.time(), MSK) - timedelta(days=10)
             ).strftime("%Y-%m-%dT00:00:00Z")
    m5 = None
    for attempt in range(7):
        end = (datetime.combine(day, datetime.min.time(), MSK) + timedelta(days=1)
               ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        m5 = b.bars(SYMBOL, "TIME_FRAME_M5", start, end)
        if not m5.empty:
            break
        time.sleep(30)
    if m5 is None or m5.empty:
        print("нет данных от брокера")
        return 2

    rows = read_rows()
    quote = b.quote(SYMBOL)

    if phase == "morning":
        price = morning_exit_price(m5, day)
        if price is None:
            print(f"{day}: бара 10:20 ещё нет")
            return 0
        closed = 0
        for cfg in CONFIGS:
            if cfg.params.get("hold") != "morning":
                continue
            pos = position_of(rows, cfg.id)
            if pos == 0 or recorded(rows, str(day), cfg.id, "закрыть"):
                continue
            append({"date": str(day), "time": "10:20", "config": cfg.id,
                    "strategy": cfg.strategy, "price": f"{price:.3f}", "signal": 0,
                    "target": 0, "contracts": 0, "equity_before": f"{pos}",
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
    for cfg in CONFIGS:
        if cfg.params.get("hold") == "morning":
            continue  # у него своя фаза выхода
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

        pos = position_of(rows, cfg.id)
        equity = equity_of(rows, cfg.id)
        contracts = size_contracts(equity, dec.price) if dec.target != 0 else 0
        target = dec.target * contracts
        action = "держать" if target == pos else (
            "закрыть" if target == 0 else ("купить" if target > 0 else "продать"))
        msg = (f"{cfg.id:9} {dec.ts:%H:%M} сигнал {dec.target:+d} -> {target:+d} контр. "
               f"(лот {contracts}, equity {equity:.0f}) {action}")
        if args.dry_run:
            print(msg + "  [dry-run]")
            continue
        append({"date": str(day), "time": dec.ts.strftime("%H:%M"), "config": cfg.id,
                "strategy": cfg.strategy, "price": f"{dec.price:.3f}", "signal": dec.target,
                "target": target, "contracts": contracts,
                "equity_before": f"{equity:.0f}", "action": "решение",
                "position_after": target,
                "note": f"{dec.detail}; лот {contracts}, equity {equity:.0f}"})
        written += 1
        print(msg)

    print(f"{day}: записано конфигураций {written}, спред {(quote.ask - quote.bid) * 1000:.0f} тиков")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
