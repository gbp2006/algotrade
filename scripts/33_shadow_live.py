"""Теневой прогон G3: плановые заявки по решениям бумажного контура.

Работает после `paper-live`, берёт уже принятые решения из `results/paper.csv`
и прогоняет их через `OrderGateway(dry_run=True)` — заявки НЕ отправляются.
Результат — отдельный `results/shadow.csv` (статус `planned`/`rejected`); боевой
контур пишет в `live.csv`. Локи убраны (ADR 27.11). Сводка — `results/shadow.json`.

Запуск: ./run.sh shadow
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from algo.broker.execution import (  # noqa: E402
    Order, OrderGateway, positions_from_response, reconcile,
)
from algo.broker.finam import FinamBroker  # noqa: E402
from algo.broker.live_guard import decision_client_id  # noqa: E402
from algo.instance_configs import active_configs  # noqa: E402
from algo.instruments import DEFAULT, INSTRUMENTS  # noqa: E402

PAPER = ROOT / "results" / "paper.csv"
SHADOW_JOURNAL = ROOT / "results" / "shadow.csv"
SHADOW_LOCK = ROOT / "results" / "shadow.lock"
SHADOW = ROOT / "results" / "shadow.json"
STOP = ROOT / "results" / "STOP"
MSK = timezone(timedelta(hours=3))


def _configs() -> list:
    """Тень видит те же инстансы, что и бумага; при пустом store — ничего."""
    try:
        return active_configs("paper")
    except Exception:  # noqa: BLE001 — store может быть ещё не проинициализирован
        return []


def read_paper() -> list[dict]:
    if not PAPER.exists():
        return []
    with PAPER.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if "config" in r]


def plan_orders(rows: list[dict], day: date, configs: list | None = None) -> list[Order]:
    orders: list[Order] = []
    for cfg in (configs if configs is not None else _configs()):
        mine = [r for r in rows if r["config"] == cfg.id]
        if len(mine) < 1 or mine[-1]["date"] != str(day):
            continue
        last = mine[-1]
        prev = int(mine[-2]["position_after"]) if len(mine) > 1 else 0
        target = int(last["target"])
        delta = target - prev
        if delta == 0:
            continue
        inst = INSTRUMENTS.get(cfg.instrument, DEFAULT)
        side = "buy" if delta > 0 else "sell"
        orders.append(Order(
            # детерминированный ключ: время решения из paper.csv, а не запуска
            client_id=decision_client_id(cfg.id, str(day), side,
                                         last.get("time", ""), abs(delta)),
            config=cfg.id,
            symbol=last["symbol"],
            side=side,
            qty=abs(delta),
            price=float(last["price"]),
            multiplier=inst.mult,
            min_step=inst.tick,
        ))
    return orders


def main(day: date | None = None) -> int:
    if STOP.exists():
        print("стоп-флаг установлен: теневой прогон пропущен")
        return 0
    day = day or datetime.now(MSK).date()  # бумага пишет решения в МСК
    rows = read_paper()
    configs = _configs()
    orders = plan_orders(rows, day, configs)
    gateway = OrderGateway(FinamBroker(), journal=SHADOW_JOURNAL, lock=SHADOW_LOCK)
    results = [gateway.submit(o, os.environ.get("FINAM_ACCOUNT"), dry_run=True)
               for o in orders]

    expected: dict[str, int] = {}
    for cfg in configs:
        mine = [r for r in rows if r["config"] == cfg.id and r["date"] == str(day)]
        if mine:
            sym = mine[-1]["symbol"]
            expected[sym] = expected.get(sym, 0) + int(mine[-1]["target"])

    issues: list[str] = []
    reconcile_error = ""
    try:
        account = FinamBroker().account()
        actual = positions_from_response(account.get("positions", account))
        issues = reconcile(expected, actual)
    except Exception as exc:  # noqa: BLE001 — сверка не обязательна для репетиции
        # Недоступность API — не расхождение позиций: иначе transient 404
        # засоряет метрику G3 и выглядит как реальная ошибка робота.
        reconcile_error = str(exc)[:200]

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    SHADOW.parent.mkdir(parents=True, exist_ok=True)
    SHADOW.write_text(json.dumps({
        "date": str(day), "orders": len(orders), "counts": counts,
        "issues": issues,
        "reconcile_error": reconcile_error,
        "reconcile_note": "бумажные позиции не уходят брокеру — расхождения с реальным счётом ожидаемы",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{day}: запланировано {len(orders)}, статусы {counts}, "
          f"расхождений позиций {len(issues)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Теневой прогон G3")
    parser.add_argument("--day", help="YYYY-MM-DD, по умолчанию сегодня в МСК")
    args = parser.parse_args()
    raise SystemExit(main(date.fromisoformat(args.day) if args.day else None))
