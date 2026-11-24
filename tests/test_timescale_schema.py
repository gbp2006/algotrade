"""Целевая схема PostgreSQL/TimescaleDB: статическая проверка DDL. ./run.sh test"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SCHEMA = ROOT / "infra" / "db" / "schema_timescale.sql"


class TestTimescaleSchema(unittest.TestCase):
    def test_required_tables_and_hypertables(self):
        sql = SCHEMA.read_text(encoding="utf-8")
        required = ("brokers", "accounts", "instrument_mappings", "algorithms",
                    "robots", "robot_account_switches", "orders", "trades",
                    "cash_flows", "cash_flow_lot_impacts", "audit_and_system_logs",
                    "market_candles", "equity_snapshots")
        tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql))
        self.assertTrue(set(required).issubset(tables), set(required) - tables)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS timescaledb", sql)
        self.assertEqual(sql.count("PERFORM create_hypertable("), 2)
        self.assertIn("pg_available_extensions", sql)

    def test_money_is_numeric_and_flows_unique(self):
        sql = SCHEMA.read_text(encoding="utf-8")
        for field in ("balance", "equity", "free_cash", "amount", "commission",
                      "realized_pnl", "lots", "net_trading_pnl"):
            self.assertRegex(sql, rf"\b{field}\s+NUMERIC\(")
        self.assertIn("broker_tx_id    TEXT UNIQUE", sql)
        self.assertIn("client_key      TEXT UNIQUE", sql)


if __name__ == "__main__":
    unittest.main()
