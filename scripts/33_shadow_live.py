"""Теневой прогон G3: плановые заявки по решениям бумажного контура.

Работает после `paper-live`, берёт уже принятые решения из `results/paper.csv`
и прогоняет их через `OrderGateway(dry_run=True)`. Заявки НЕ отправляются даже
при включённом `FINAM_ALLOW_TRADING`. Результат — отдельные `results/shadow.csv`
(статус `planned`/`rejected`) и `results/shadow.lock`; боевой контур использует
`live.csv`/`live.lock` и не должен делить с тенью ни журнал, ни лок. Сводка —
`results/shadow.json`.

Запуск: ./run.sh shadow
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date
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
from algo.configs import CONFIGS  # noqa: E402
from algo.instruments import DEFAULT, INSTRUMENTS  # noqa: E402

PAPER = ROOT / "results" / "paper.csv"
SHADOW_JOURNAL = ROOT / "results" / "shadow.csv"
SHADOW_LOCK = ROOT / "results" / "shadow.lock"
SHADOW = ROOT / "results" / "shadow.json"
STOP = ROOT / "results" / "STOP"


def read_paper() -> list[dict]:
    if not PAPER.exists():
        return []
    with PAPER.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if "config" in r]


def plan_orders(rows: list[dict], day: date) -> list[Order]:
    orders: list[Order] = []
    for cfg in CONFIGS:
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
            client_id=f"{cfg.id}:{day}:{side}",
            config=cfg.id,
            symbol=last["symbol"],
            side=side,
            qty=abs(delta),
            price=float(last["price"]),
            multiplier=inst.mult,
            min_step=inst.tick,
        ))
    return orders


def main() -> int:
    if STOP.exists():
        print("стоп-флаг установлен: теневой прогон пропущен")
        return 0
    day = date.today()
    rows = read_paper()
    orders = plan_orders(rows, day)
    gateway = OrderGateway(FinamBroker(), journal=SHADOW_JOURNAL, lock=SHADOW_LOCK)
    results = [gateway.submit(o, os.environ.get("FINAM_ACCOUNT"), dry_run=True)
               for o in orders]

    expected: dict[str, int] = {}
    for cfg in CONFIGS:
        mine = [r for r in rows if r["config"] == cfg.id and r["date"] == str(day)]
        if mine:
            sym = mine[-1]["symbol"]
            expected[sym] = expected.get(sym, 0) + int(mine[-1]["target"])

    issues: list[str] = []
    try:
        account = FinamBroker().account()
        actual = positions_from_response(account.get("positions", account))
        issues = reconcile(expected, actual)
    except Exception as exc:  # noqa: BLE001 — сверка не обязательна для репетиции
        issues = [f"нет данных о позициях: {str(exc)[:80]}"]

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    SHADOW.parent.mkdir(parents=True, exist_ok=True)
    SHADOW.write_text(json.dumps({
        "date": str(day), "orders": len(orders), "counts": counts,
        "issues": issues,
        "reconcile_note": "бумажные позиции не уходят брокеру — расхождения с реальным счётом ожидаемы",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{day}: запланировано {len(orders)}, статусы {counts}, "
          f"расхождений позиций {len(issues)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
