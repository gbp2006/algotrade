"""Однократно развести бумажных роботов по отдельным TEST-счетам.

Для каждого paper-инстанса без `account` создаётся счёт `paper-<id>` с его
виртуальным капиталом. Повторный запуск ничего не меняет. Боевые инстансы
и счета не трогаются. Вывод — одна строка.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.robot_store import RobotStore  # noqa: E402


def main() -> int:
    store = RobotStore()
    store.init_db()
    created = 0
    with store._conn() as c:
        rows = c.execute(
            "SELECT id, note, capital FROM instances WHERE mode='paper' "
            "AND (account IS NULL OR account='')").fetchall()
        for row in rows:
            acc_id = f"paper-{row['id']}"
            exists = c.execute("SELECT 1 FROM accounts WHERE id=?", (acc_id,)).fetchone()
            if not exists:
                c.execute(
                    "INSERT INTO accounts (id, label, capital, mode, enabled, "
                    "created_at, updated_at) VALUES (?,?,?, 'TEST', 1,?,?)",
                    (acc_id, row["note"] or row["id"], float(row["capital"] or 0),
                     "2026-11-24T00:00:00", "2026-11-24T00:00:00"))
            c.execute("UPDATE instances SET account=? WHERE id=?", (acc_id, row["id"]))
            created += 1
    print(f"paper accounts assigned: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
