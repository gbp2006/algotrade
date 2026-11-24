"""Доступ к целевой БД PostgreSQL (+ TimescaleDB при наличии расширения).

Строка подключения хранится только в `auth.json -> postgres -> dsn` или в
переменной окружения через `{env:...}`. Старая SQLite-панель продолжает
работать: при отсутствии DSN все методы становятся безопасными no-op.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
AUTH = Path(os.environ.get("ALGO_AUTH", str(ROOT / "auth.json")))
SCHEMA = ROOT / "infra" / "db" / "schema_timescale.sql"


def dsn_from_auth() -> str:
    """DSN только из auth.json (600) или env; в логах и API не появляется."""
    raw = os.environ.get("ALGO_PG_DSN", "")
    if raw.startswith("{env:") and raw.endswith("}"):
        raw = os.environ.get(raw[5:-1].strip(), "")
    if raw:
        return raw
    path = Path(os.environ.get("ALGO_AUTH", str(AUTH)))
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = (data.get("postgres") or {}).get("dsn", "")
    if isinstance(value, str) and value.startswith("{env:"):
        return os.environ.get(value[5:-1].strip(), "")
    return str(value or "")


class PgStore:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn if dsn is not None else dsn_from_auth()

    @property
    def enabled(self) -> bool:
        return bool(self.dsn)

    @contextmanager
    def conn(self) -> Iterator[object]:
        import psycopg2  # локальный импорт: без DSN библиотека не нужна

        connection = psycopg2.connect(self.dsn)
        connection.autocommit = True
        try:
            yield connection
        finally:
            connection.close()

    def init_schema(self) -> bool:
        if not self.enabled:
            return False
        sql = SCHEMA.read_text(encoding="utf-8")
        with self.conn() as connection:
            with connection.cursor() as cursor:  # type: ignore[attr-defined]
                cursor.execute(sql)
        return True

    def upsert_account(self, account_id: str, label: str,
                       mode: str = "LIVE", equity: float = 0) -> None:
        if not self.enabled:
            return
        with self.conn() as connection:
            with connection.cursor() as cursor:  # type: ignore[attr-defined]
                cursor.execute("""
                    INSERT INTO accounts (id, broker_code, name, mode, equity)
                    VALUES (%s, 'finam', %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      name=EXCLUDED.name, mode=EXCLUDED.mode, equity=EXCLUDED.equity
                """, (account_id, label, mode, equity))

    def save_snapshot(self, account_id: str, timestamp: str, equity: float,
                      balance: float = 0, cash_flow: float = 0,
                      drawdown_pct: float = 0) -> bool:
        if not self.enabled:
            return False
        with self.conn() as connection:
            with connection.cursor() as cursor:  # type: ignore[attr-defined]
                cursor.execute("""
                    INSERT INTO equity_snapshots
                        (account_id, time, equity, balance, net_trading_pnl, drawdown_pct)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (account_id, time) DO NOTHING
                """, (account_id, timestamp, equity, balance, 0, drawdown_pct))
                return bool(cursor.rowcount)

    def list_snapshots(self, account_id: str = "", limit: int = 500) -> list[dict]:
        if not self.enabled:
            return []
        where = "WHERE account_id=%s" if account_id else ""
        params: tuple = (account_id, limit) if account_id else (limit,)
        with self.conn() as connection:
            with connection.cursor() as cursor:  # type: ignore[attr-defined]
                cursor.execute(
                    f"SELECT account_id, time, equity, balance, drawdown_pct "
                    f"FROM equity_snapshots {where} ORDER BY time DESC LIMIT %s", params)
                columns = [d[0] for d in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def save_flow(self, account_id: str, flow_type: str, amount: float,
                  balance_before: float, balance_after: float,
                  created_at: str, broker_tx_id: str = "",
                  client_key: str = "", source: str = "BROKER") -> bool:
        if not self.enabled:
            return False
        with self.conn() as connection:
            with connection.cursor() as cursor:  # type: ignore[attr-defined]
                cursor.execute("""
                    INSERT INTO cash_flows (account_id, type, amount, balance_before,
                        balance_after, broker_tx_id, client_key, source, created_at)
                    VALUES (%s,%s,%s,%s,%s,NULLIF(%s,''),NULLIF(%s,''),%s,%s)
                    ON CONFLICT DO NOTHING
                """, (account_id, flow_type, amount, balance_before, balance_after,
                      broker_tx_id, client_key, source, created_at))
                return bool(cursor.rowcount)

    def list_flows(self, account_id: str = "", limit: int = 200) -> list[dict]:
        if not self.enabled:
            return []
        where = "WHERE account_id=%s" if account_id else ""
        params: tuple = (account_id, limit) if account_id else (limit,)
        with self.conn() as connection:
            with connection.cursor() as cursor:  # type: ignore[attr-defined]
                cursor.execute(
                    f"SELECT account_id, type, amount, balance_before, balance_after,"
                    f" source, created_at FROM cash_flows {where}"
                    f" ORDER BY created_at DESC LIMIT %s", params)
                columns = [d[0] for d in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
