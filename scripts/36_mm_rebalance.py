"""Задание расписания для фонда денежного рынка.

Тонкая оболочка над уже существующим API панели: `/api/money-market/{id}/rebalance`.
Не дублирует логику фонда, флаги ARM и лимиты — всё это в `position_ops` и
`arm_state`. Вызывается планировщиком по времени, заданному пользователем.

    .venv/bin/python scripts/36_mm_rebalance.py --instance money-market-fmmm
    .venv/bin/python scripts/36_mm_rebalance.py --instance money-market-fmmm --regime OnlyClose
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

PANEL = os.environ.get("ALGO_PANEL_URL", "http://127.0.0.1:8080")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True, help="id робота money_market")
    parser.add_argument("--regime", help="переопределить режим (Off/TwiceADay/OnlyClose)")
    args = parser.parse_args()

    payload = {} if not args.regime else {"regime": args.regime}
    request = urllib.request.Request(
        f"{PANEL}/api/money-market/{args.instance}/rebalance",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001 — ошибка пишется в лог планировщика
        print(f"ребаланс фонда недоступен: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
