"""Хранение денежных потоков, снимков equity и влияния на лотность.

Новые таблицы добавляются в уже существующий `robots.db` через
``CREATE TABLE IF NOT EXISTS`` — схема счетов, инстансов и рантайма не меняется.
Старая панель продолжает работать с теми же виртуальными и боевыми счетами.
"""

from __future__ import annotations

import json
from pathlib import Path

from .cash_flows import CashFlow, CashFlowPreview
from .robot_store import RobotStore, _now


class CashFlowStore:
    def __init__(self, store: RobotStore | None = None):
        self.store = store or RobotStore()
        self.path = Path(self.store.path)

    def init_db(self) -> None:
        with self.store._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS cash_flows (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  account_id TEXT NOT NULL,
                  type TEXT NOT NULL,
                  amount REAL NOT NULL,
                  balance_before REAL NOT NULL DEFAULT 0,
                  balance_after REAL NOT NULL DEFAULT 0,
                  client_key TEXT NOT NULL DEFAULT '',
                  key TEXT NOT NULL UNIQUE,
                  source TEXT NOT NULL DEFAULT 'BROKER',
                  broker_tx_id TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  note TEXT DEFAULT '');
                CREATE INDEX IF NOT EXISTS idx_cash_flows_account_time
                  ON cash_flows(account_id, created_at);
                CREATE TABLE IF NOT EXISTS cash_flow_lot_impacts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cash_flow_id INTEGER NOT NULL,
                  instance_id TEXT NOT NULL,
                  lots_before INTEGER NOT NULL,
                  lots_after INTEGER NOT NULL,
                  effective_lots INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  reaction TEXT NOT NULL,
                  note TEXT DEFAULT '');
                CREATE INDEX IF NOT EXISTS idx_lot_impacts_flow
                  ON cash_flow_lot_impacts(cash_flow_id);
                CREATE TABLE IF NOT EXISTS equity_snapshots (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  account_id TEXT NOT NULL,
                  instance_id TEXT NOT NULL DEFAULT '',
                  timestamp TEXT NOT NULL,
                  balance REAL NOT NULL DEFAULT 0,
                  equity REAL NOT NULL DEFAULT 0,
                  net_trading_pnl REAL NOT NULL DEFAULT 0,
                  cash_flow REAL NOT NULL DEFAULT 0,
                  drawdown_pct REAL NOT NULL DEFAULT 0,
                  source TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS idx_equity_snapshots_account_time
                  ON equity_snapshots(account_id, timestamp);
            """)

    def record_flow(self, flow: CashFlow, preview: CashFlowPreview,
                    account_id: str, source: str = "BROKER") -> dict:
        """Идемпотентная запись потока и зафиксированного пересчёта лотов."""
        stamp = flow.created_at or _now()
        with self.store._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO cash_flows (account_id,type,amount,"
                "balance_before,balance_after,client_key,key,source,broker_tx_id,"
                "created_at,note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (account_id, flow.type.value, flow.amount, flow.balance_before,
                 flow.balance_after, flow.client_key, flow.key, source,
                 flow.broker_tx_id, stamp, flow.note))
            if cur.rowcount == 0:
                return {"recorded": False, "key": flow.key, "id": None}
            flow_id = cur.lastrowid
            for impact in preview.impacts:
                c.execute(
                    "INSERT INTO cash_flow_lot_impacts (cash_flow_id,instance_id,"
                    "lots_before,lots_after,effective_lots,status,reaction,note) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (flow_id, impact.robot_id, impact.lots_before, impact.lots_after,
                     impact.effective_lots, impact.status.value, impact.reaction.value,
                     impact.note))
                c.execute(
                    "INSERT INTO instance_events (instance_id,action,before_json,"
                    "after_json,reason,actor,created_at) VALUES (?,?,?,?,?,?,?)",
                    (impact.robot_id, "cash_flow",
                     json.dumps({"lots": impact.lots_before}),
                     json.dumps({"lots": impact.lots_after,
                                 "status": impact.status.value}),
                     f"{flow.type.value} {flow.amount:g}", source, stamp))
        return {"recorded": True, "key": flow.key, "id": flow_id}

    def list_flows(self, account_id: str | None = None, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        with self.store._conn() as c:
            if account_id:
                rows = c.execute(
                    "SELECT * FROM cash_flows WHERE account_id=? "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (account_id, limit)).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM cash_flows ORDER BY created_at DESC, id DESC LIMIT ?",
                    (limit,)).fetchall()
        return [dict(r) for r in rows]

    def list_impacts(self, cash_flow_id: int) -> list[dict]:
        with self.store._conn() as c:
            rows = c.execute(
                "SELECT * FROM cash_flow_lot_impacts WHERE cash_flow_id=? "
                "ORDER BY id", (cash_flow_id,)).fetchall()
        return [dict(r) for r in rows]

    def has_key(self, key: str) -> bool:
        with self.store._conn() as c:
            return c.execute("SELECT 1 FROM cash_flows WHERE key=? LIMIT 1",
                             (key,)).fetchone() is not None

    def add_snapshot(self, account_id: str, equity: float, balance: float,
                     timestamp: str | None = None, instance_id: str = "",
                     net_trading_pnl: float = 0.0, cash_flow: float = 0.0,
                     drawdown_pct: float = 0.0, source: str = "BROKER") -> bool:
        """Один снимок на (счёт, метка, источник) — повторный опрос не дублирует."""
        stamp = timestamp or _now()
        with self.store._conn() as c:
            exists = c.execute(
                "SELECT 1 FROM equity_snapshots WHERE account_id=? AND timestamp=? "
                "AND source=? AND instance_id=? LIMIT 1",
                (account_id, stamp, source, instance_id)).fetchone()
            if exists:
                return False
            c.execute(
                "INSERT INTO equity_snapshots (account_id,instance_id,timestamp,"
                "balance,equity,net_trading_pnl,cash_flow,drawdown_pct,source) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (account_id, instance_id, stamp, balance, equity,
                 net_trading_pnl, cash_flow, drawdown_pct, source))
        return True

    def latest_snapshot(self, account_id: str) -> dict | None:
        with self.store._conn() as c:
            row = c.execute(
                "SELECT * FROM equity_snapshots WHERE account_id=? "
                "ORDER BY timestamp DESC, id DESC LIMIT 1", (account_id,)).fetchone()
        return dict(row) if row else None

    def list_snapshots(self, account_id: str | None = None, limit: int = 200,
                       since: str = "") -> list[dict]:
        limit = max(1, min(int(limit), 2000))
        sql = "SELECT * FROM equity_snapshots WHERE 1=1"
        params: list[object] = []
        if account_id:
            sql += " AND account_id=?"
            params.append(account_id)
        if since:
            sql += " AND timestamp>=?"
            params.append(since)
        sql += " ORDER BY timestamp ASC, id ASC LIMIT ?"
        params.append(limit)
        with self.store._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def apply_virtual(self, instance_id: str, delta: float,
                      note: str = "") -> dict:
        """Пополнение/снятие виртуального депозита робота (только mode=paper).

        Меняем только `instances.capital` и сдвигаем runtime equity на ту же
        сумму — остальные поля и версии параметров остаются как есть.
        """
        with self.store._conn() as c:
            row = c.execute(
                "SELECT capital FROM instances WHERE id=? AND mode='paper'",
                (instance_id,)).fetchone()
            if row is None:
                raise ValueError("нет бумажного робота с таким id")
            old = float(row["capital"] or 0)
            new = old + float(delta)
            if new < 0:
                raise ValueError("недостаточно средств на виртуальном счёте")
            stamp = _now()
            c.execute("UPDATE instances SET capital=?, updated_at=? WHERE id=?",
                      (new, stamp, instance_id))
            c.execute(
                "UPDATE runtime_state SET equity=equity+?, updated_at=? "
                "WHERE instance_id=? AND equity IS NOT NULL",
                (delta, stamp, instance_id))
            c.execute(
                "INSERT INTO instance_events (instance_id,action,before_json,"
                "after_json,reason,actor,created_at) VALUES (?,?,?,?,?,?,?)",
                (instance_id, "cash_flow", json.dumps({"capital": old}),
                 json.dumps({"capital": new}), note or f"виртуальный поток {delta:+g}",
                 "panel", stamp))
        return {"instance_id": instance_id, "capital_before": old, "capital_after": new}
