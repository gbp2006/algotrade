"""PostgreSQL-слой: безопасный no-op без DSN и чтение секрета из auth.json. ./run.sh test"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import pg_store  # noqa: E402


class TestPgStore(unittest.TestCase):
    def test_no_dsn_is_safe_noop(self):
        store = pg_store.PgStore(dsn="")
        self.assertFalse(store.enabled)
        self.assertFalse(store.init_schema())
        self.assertFalse(store.save_snapshot("acc", "2026-11-24T10:00:00", 100))
        self.assertEqual(store.list_snapshots("acc"), [])
        self.assertEqual(store.list_flows("acc"), [])

    def test_dsn_comes_from_auth_not_from_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = Path(tmp) / "auth.json"
            auth.write_text(json.dumps({"postgres": {"dsn": "postgresql://user@host/db"}}),
                            encoding="utf-8")
            with mock.patch.dict(os.environ, {"ALGO_AUTH": str(auth), "ALGO_PG_DSN": ""}):
                self.assertEqual(pg_store.dsn_from_auth(), "postgresql://user@host/db")
            auth.write_text(json.dumps({"postgres": {"dsn": "{env:CUSTOM_PG}"}}),
                            encoding="utf-8")
            with mock.patch.dict(os.environ,
                                 {"ALGO_AUTH": str(auth), "CUSTOM_PG": "postgresql://x/y"}):
                self.assertEqual(pg_store.dsn_from_auth(), "postgresql://x/y")


if __name__ == "__main__":
    unittest.main()
