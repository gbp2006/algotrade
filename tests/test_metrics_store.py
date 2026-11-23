"""Тесты хранилища метрик счёта (SQLite). ./run.sh test"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import metrics_store as ms  # noqa: E402


class TestMetricsStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = ms.DB_PATH
        ms.DB_PATH = Path(self.tmp.name) / "metrics.db"
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        ms.DB_PATH = self.old
        self.tmp.cleanup()

    def test_snapshot_roundtrip(self):
        rows = [
            {"config": "p-base", "instrument": "CNY", "day": "2026-11-20",
             "capital": 200000, "equity": 205000, "realized": 5000,
             "pnl_pct": 2.5, "dd_abs": -1200, "dd_pct": 0.6, "dd_days": 3,
             "trades": 12, "winrate": 58.3, "avg_trade": 416.7,
             "profit_factor": 1.8, "position": 32, "notional": 390000,
             "exposure_pct": 195.0, "unrealized": 0, "wins": 7, "losses": 5,
             "max_dd": -1200, "max_dd_days": 3},
        ]
        self.assertEqual(ms.save_snapshot("2026-11-20", rows), 1)
        latest = ms.latest()
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["config"], "p-base")
        self.assertEqual(latest[0]["dd_pct"], 0.6)
        self.assertEqual(ms.latest("p-base")[0]["equity"], 205000)
        self.assertEqual(ms.equity_curve("p-base"), [["11-20", 205000]])

    def test_idempotent_and_history(self):
        base = {"config": "d20-cn", "instrument": "CNY", "capital": 200000,
                "equity": 200000, "realized": 0, "pnl_pct": 0, "dd_abs": 0,
                "dd_pct": 0, "dd_days": 0, "trades": 0, "winrate": 0,
                "avg_trade": 0, "profit_factor": None, "position": 0,
                "notional": 0, "exposure_pct": 0, "unrealized": 0,
                "wins": 0, "losses": 0, "max_dd": 0, "max_dd_days": 0}
        ms.save_snapshot("2026-11-20", [base])
        base2 = {**base, "equity": 201000, "realized": 1000, "pnl_pct": 0.5}
        ms.save_snapshot("2026-11-20", [base2])   # тот же день — перезапись
        ms.save_snapshot("2026-11-21", [base2])   # новый день
        self.assertEqual(len(ms.latest()), 1)
        self.assertEqual(ms.latest()[0]["equity"], 201000)
        self.assertEqual(len(ms.history("d20-cn")), 2)
        self.assertEqual([d[0] for d in ms.equity_curve("d20-cn")],
                         ["11-20", "11-21"])


if __name__ == "__main__":
    unittest.main()
