"""Тесты общего SQLite-хранилища баров. Запуск: ./run.sh test"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def bars(times: list[str], close: list[float] | None = None) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(t) for t in times])
    c = np.arange(len(idx), dtype=float) if close is None else np.asarray(close, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                         "vol": np.ones(len(idx))}, index=idx)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = store.DB_PATH
        store.DB_PATH = Path(self.tmp.name) / "market.db"
        store.init_db()

    def tearDown(self):
        store.DB_PATH = self.old
        self.tmp.cleanup()

    def test_upsert_and_idempotence(self):
        df = bars(["2026-11-20 13:50", "2026-11-20 13:55"])
        self.assertEqual(store.upsert(df, "T@TEST", "M5", "finam_live",
                                      updated_at="2026-11-20 10:00:00"), 2)
        # более старая версия не перезаписывает более новую
        self.assertEqual(store.upsert(df, "T@TEST", "M5", "finam_live",
                                      updated_at="2026-11-20 09:00:00"), 0)
        got = store.read("T@TEST", "M5")
        self.assertEqual(len(got), 2)
        self.assertEqual(float(got["close"].iloc[-1]), 1.0)

    def test_source_is_part_of_key(self):
        df = bars(["2026-11-20 13:50"], [12.29])
        store.upsert(df, "T@TEST", "M5", "finam_live", updated_at="2026-11-20 10:00:00")
        store.upsert(df, "T@TEST", "M5", "iss", updated_at="2026-11-20 10:00:00")
        self.assertEqual(len(store.read("T@TEST", "M5", source="finam_live")), 1)
        self.assertEqual(len(store.read("T@TEST", "M5", source="iss")), 1)
        self.assertEqual(len(store.raw("T@TEST", "M5")), 2)

    def test_read_always_sorted_by_dt(self):
        # decision() берёт первый бар >= времени решения — порядок критичен
        df = bars(["2026-11-20 13:50", "2026-11-20 10:00", "2026-11-20 12:00"],
                  [3.0, 1.0, 2.0])
        store.upsert(df, "T@TEST", "M5", "finam_live", updated_at="2026-11-20 10:00:00")
        got = store.read("T@TEST", "M5")
        self.assertTrue(got.index.is_monotonic_increasing)
        self.assertEqual(float(got["close"].iloc[0]), 1.0)

    def test_newer_version_wins(self):
        t = "2026-11-20 13:50"
        store.upsert(bars([t], [10.0]), "T@TEST", "M5", "finam_live",
                     updated_at="2026-11-20 10:00:00")
        store.upsert(bars([t], [11.0]), "T@TEST", "M5", "finam_live",
                     updated_at="2026-11-20 11:00:00")
        self.assertEqual(float(store.read("T@TEST", "M5")["close"].iloc[0]), 11.0)

    def test_raw_export_has_transfer_columns(self):
        store.upsert(bars(["2026-11-20 13:50"]), "T@TEST", "M5", "iss",
                     updated_at="2026-11-20 10:00:00")
        cols = list(store.raw("T@TEST", "M5").columns)
        for name in ("symbol", "tf", "dt", "source", "o", "h", "l", "c", "v", "updated_at"):
            self.assertIn(name, cols)


class TestStoreCli(unittest.TestCase):
    def test_stats_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, ALGO_DB=str(Path(tmp) / "market.db"))
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "00_store.py"), "stats"],
                               env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("пусто", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
