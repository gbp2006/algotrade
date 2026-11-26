"""Задание расписания фонда денежного рынка: вечер купить, утром продать.

Тонкая оболочка над уже существующим API панели `/api/money-market/{id}/rebalance`.
Логику покупки/продажи, лимиты и ARM не дублирует — всё это в `position_ops`,
`arm_state` и `robot_schedule`. Если паёв нет, утренний `OnlyClose` просто
вернёт «нечего закрывать» и заявки не отправит.

    .venv/bin/python scripts/36_mm_rebalance.py --instance money-market-fmmm --slot-time 10:05
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.robot_schedule import regime_for_slot  # noqa: E402

PANEL = os.environ.get("ALGO_PANEL_URL", "http://127.0.0.1:8080")


def request(path: str) -> dict:
    with urllib.request.urlopen(PANEL + path, timeout=15) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True, help="id робота money_market")
    parser.add_argument("--slot-time", default="", help="время слота планировщика HH:MM")
    parser.add_argument("--regime", help="явно переопределить режим")
    args = parser.parse_args()

    regime = args.regime
    if not regime and args.slot_time:
        try:
            instance = request(f"/api/instances/{args.instance}")
            regime = regime_for_slot(instance, args.slot_time)
        except Exception as exc:  # noqa: BLE001 — без параметров работаем как обычно
            print(f"не удалось прочитать параметры робота: {type(exc).__name__}: {exc}")

    payload = {} if not regime else {"regime": regime}
    req = urllib.request.Request(
        f"{PANEL}/api/money-market/{args.instance}/rebalance",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001 — ошибка уйдёт в лог планировщика
        print(f"ребаланс фонда недоступен: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps({**result, "regime": regime or "обычный"}, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
