"""Однократная миграция служебных данных SQLite → PostgreSQL.

Источник — рабочие `robots.db`/`trades.db`, приёмник — БД из
`auth.json -> postgres -> dsn`. Ничего не удаляет и не меняет в SQLite;
повторный запуск идемпотентен. Вывод — одна строка сводки.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.pg_store import PgStore  # noqa: E402

DB = ROOT / "infra" / "db"


def _rows(path: Path, sql: str) -> list[sqlite3.Row]:
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def main() -> int:
    pg = PgStore()
    if not pg.enabled:
        print("миграция пропущена: DSN PostgreSQL не настроен")
        return 0
    pg.init_schema()
    robots = DB / "robots.db"

    with pg.conn() as connection:
        with connection.cursor() as cursor:  # type: ignore[attr-defined]
            for code, name in (("finam", "Финам"), ("tinvest", "Т-Инвестиции"),
                               ("virtual", "Виртуальный")):
                cursor.execute("INSERT INTO brokers (code, display_name) VALUES (%s,%s) "
                               "ON CONFLICT (code) DO NOTHING", (code, name))
            cursor.execute("INSERT INTO accounts (id, broker_code, name, mode, equity) "
                           "VALUES ('virtual','virtual','Виртуальные','TEST',0) "
                           "ON CONFLICT (id) DO NOTHING")

    accounts = _rows(robots, "SELECT * FROM accounts")
    for row in accounts:
        pg.upsert_account(row["id"], row["label"] or row["id"], "LIVE", 0)

    instances = _rows(robots,
        "SELECT id, spec_id, instrument, mode, status, note, account FROM instances")
    with pg.conn() as connection:
        with connection.cursor() as cursor:  # type: ignore[attr-defined]
            for row in instances:
                cursor.execute("""
                    INSERT INTO algorithms (id, code, name) VALUES (%s,%s,%s)
                    ON CONFLICT (id) DO NOTHING
                """, (row["spec_id"], row["spec_id"], row["spec_id"]))
                cursor.execute("""
                    INSERT INTO robots (id, name, algorithm_id, account_id, symbol, status)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,
                      account_id=EXCLUDED.account_id, status=EXCLUDED.status
                """, (row["id"], row["note"] or row["id"], row["spec_id"],
                      row["account"] or "virtual", row["instrument"],
                      "RUNNING" if row["status"] == "active" else "STOPPED"))

    flows = _rows(robots, "SELECT * FROM cash_flows")
    for row in flows:
        pg.save_flow(row["account_id"], row["type"], row["amount"],
                     row["balance_before"], row["balance_after"],
                     row["created_at"], row["broker_tx_id"], row["client_key"],
                     row["source"])

    snapshots = _rows(robots,
        "SELECT * FROM equity_snapshots ORDER BY timestamp")
    migrated = 0
    for row in snapshots:
        migrated += int(pg.save_snapshot(
            row["account_id"], row["timestamp"], row["equity"],
            row["balance"], row["cash_flow"], row["drawdown_pct"]))

    print(f"accounts={len(accounts)} robots={len(instances)} "
          f"flows={len(flows)} snapshots={migrated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
