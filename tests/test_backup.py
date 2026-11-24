"""Тесты консистентного бэкапа БД: только *.db, 0700/0600, ретенция. ./run.sh test"""

from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("backup_db", ROOT / "scripts" / "95_backup_db.py")
backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup)


class TestBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.dbdir = base / "db"
        self.dest = base / "backups" / "db"
        self.state = base / "backup.json"
        self.dbdir.mkdir()
        self.dest.mkdir(parents=True)
        for name in backup.SOURCES:
            with sqlite3.connect(self.dbdir / name) as c:
                c.execute("CREATE TABLE t (x INTEGER)")
                c.execute("INSERT INTO t VALUES (1)")
        # секрет рядом с БД не должен попасть в бэкап
        (self.dbdir / ".env").write_text("FINAM_SECRET=test", encoding="utf-8")
        self.patches = [
            mock.patch.object(backup, "DB_DIR", self.dbdir),
            mock.patch.object(backup, "DEST", self.dest),
            mock.patch.object(backup, "STATE", self.state),
            mock.patch.object(backup, "ROOT", base),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_backup_is_clean_and_verified(self):
        self.assertEqual(backup.main(), 0)
        files = sorted(self.dest.glob("*.db"))
        self.assertEqual(len(files), len(backup.SOURCES))
        for f in files:
            self.assertEqual(f.stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(f"file:{f}?mode=ro", uri=True) as c:
                self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(c.execute("SELECT x FROM t").fetchone()[0], 1)
        self.assertEqual(self.dest.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.dest.glob("*env*")), [])
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        self.assertIn("no .env", self.state.read_text(encoding="utf-8"))

    def test_prune_keeps_recent_and_monthly(self):
        for day in ("20260101", "20260201", "20260301", "20261120", "20261121"):
            (self.dest / f"trades_{day}_030000.db").write_bytes(b"x")
        (self.dest / "trades_20250101_030000.db").write_bytes(b"x")
        with mock.patch.object(backup, "KEEP_MONTHLY", 4):
            removed = backup.prune()
        names = {p.name for p in self.dest.glob("*.db")}
        self.assertIn("trades_20260101_030000.db", names)  # первый месяца
        self.assertIn("trades_20261121_030000.db", names)  # свежий daily
        self.assertNotIn("trades_20250101_030000.db", names)
        self.assertGreater(removed, 0)


if __name__ == "__main__":
    unittest.main()
