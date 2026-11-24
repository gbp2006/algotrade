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
