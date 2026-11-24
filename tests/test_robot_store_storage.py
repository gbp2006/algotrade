"""Режим БД роботов и индексы под запросы панели. ./run.sh test"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from algo.robot_store import RobotStore


class TestRobotStoreStorage(unittest.TestCase):
    def test_wal_busy_timeout_and_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "robots.db"
            store = RobotStore(db)
            store.init_db()
            with store._conn() as c:
                mode = c.execute("PRAGMA journal_mode").fetchone()[0]
                names = {r[0] for r in c.execute("PRAGMA index_list(param_versions)")}
                all_idx = {r[0] for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'")}
                timeout = c.execute("PRAGMA busy_timeout").fetchone()[0]
            self.assertEqual(mode, "wal")
            self.assertIn("ux_param_versions", names)
            for name in ("idx_instance_events_inst", "idx_scheduler_runs_status",
                         "idx_runtime_updated"):
                self.assertIn(name, all_idx)
            self.assertGreaterEqual(timeout, 3000)

    def test_migration_adds_columns_without_losing_data(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "old.db"
            with sqlite3.connect(db) as c:
                c.execute("CREATE TABLE instances (id TEXT PRIMARY KEY, spec_id TEXT, "
                          "instrument TEXT, params_json TEXT, mode TEXT, status TEXT, "
                          "account TEXT, pricing TEXT, capital REAL, exposure REAL, "
                          "max_qty INTEGER, trade_on_expiry INTEGER DEFAULT 0, "
                          "version INTEGER DEFAULT 1, note TEXT, "
                          "created_at TEXT, updated_at TEXT)")
                c.execute("INSERT INTO instances (id,spec_id,instrument,params_json,mode,status) "
                          "VALUES ('old','prostushka','CNY','{}','paper','active')")
                c.execute("CREATE TABLE accounts (id TEXT PRIMARY KEY, label TEXT, "
                          "capital REAL, max_exposure REAL)")
            store = RobotStore(db)
            store.init_db()
            with sqlite3.connect(db) as c:
                cols = {r[1] for r in c.execute("PRAGMA table_info(instances)")}
                acols = {r[1] for r in c.execute("PRAGMA table_info(accounts)")}
                kept = c.execute("SELECT id,status FROM instances").fetchone()
            self.assertIn("key_ref", cols)
            self.assertIn("source_config", cols)
            self.assertIn("key_ref", acols)
            self.assertIn("trading_code", acols)
            self.assertEqual(tuple(kept), ("old", "active"))

    def test_init_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "robots.db"
            store = RobotStore(db)
            store.init_db()
            store.init_db()
            with sqlite3.connect(db) as c:
                n = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
                              "AND name LIKE 'ux_%'").fetchone()[0]
            self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
