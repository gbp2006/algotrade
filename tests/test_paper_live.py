"""Тесты фаз бумажного контура на живых котировках. ./run.sh test"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.configs import BY_ID  # noqa: E402

_spec = importlib.util.spec_from_file_location("paper_live", ROOT / "scripts" / "31_paper_live.py")
pl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)

MSK = timezone(timedelta(hours=3))
DAY = "2026-11-20"


def m5() -> pd.DataFrame:
    idx = pd.date_range(f"{DAY} 10:00", f"{DAY} 19:00", freq="5min")
    close = pd.Series(np.linspace(12.20, 12.40, len(idx)), index=idx)
    return pd.DataFrame({"open": close, "high": close, "low": close,
                         "close": close, "vol": 100.0}, index=idx)


class FakeBroker:
    def __init__(self):
        self.df = m5()

    def bars(self, sym, tf, start, end):
        return self.df.copy()

    def quote(self, sym):
        return SimpleNamespace(last=12.30, bid=12.299, ask=12.301, timestamp="")


class TestPaperPhases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paper = Path(self.tmp.name) / "paper.csv"
        self.stop = Path(self.tmp.name) / "STOP"
        self.now = datetime(2026, 11, 20, 13, 55, tzinfo=MSK)
        self.patches = [
            mock.patch.object(pl, "PAPER", self.paper),
            mock.patch.object(pl, "STOP", self.stop),
            mock.patch.object(pl, "FinamBroker", FakeBroker),
            mock.patch.object(pl.store, "init_db", lambda: None),
            mock.patch.object(pl.store, "upsert", lambda *a, **k: 0),
            mock.patch.object(pl, "now_msk", lambda: self.now),
            mock.patch.object(sys, "argv", ["paper_live"]),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _configs(self, *ids):
        cfgs = [BY_ID[i] for i in ids]
        p = mock.patch.object(pl, "CONFIGS", cfgs)
        p.start()
        self.addCleanup(p.stop)
        # контур берёт ALL_CONFIGS, посчитанный на импорте, — подменяем и его,
        # иначе в тест попадают все роботы и каждый ненайденный сигнал ждёт 4×30 с
        p2 = mock.patch.object(pl, "ALL_CONFIGS", cfgs)
        p2.start()
        self.addCleanup(p2.stop)

    def _seed(self, config_id: str, strategy: str, pos: int = 32):
        self.assertTrue(not self.paper.exists() or pl.read_rows())
        pl.append({"date": DAY, "time": "13:50", "config": config_id,
                   "instrument": "CNY", "symbol": "CNYRUBF@RTSX", "strategy": strategy,
                   "price": "12.300", "signal": 1, "target": pos, "contracts": pos,
                   "equity_before": "200000", "action": "решение",
                   "position_after": pos, "note": "тест"})

    def test_decision_writes_one_row_per_config(self):
        self._configs("p-base")
        self.assertEqual(pl.main(), 0)
        rows = pl.read_rows()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["config"], "p-base")
        self.assertEqual(r["action"], "решение")
        self.assertEqual(r["date"], DAY)
        self.assertGreater(int(r["position_after"]), 0)

    def test_duplicate_decision_not_written_twice(self):
        self._configs("p-base")
        self._seed("p-base", "prostushka")
        self.assertEqual(pl.main(), 0)
        self.assertEqual(len(pl.read_rows()), 1)

    def test_morning_phase_closes_position(self):
        self.now = datetime(2026, 11, 20, 10, 25, tzinfo=MSK)
        self._configs("u-morning")
        self._seed("u-morning", "universal")
        self.assertEqual(pl.main(), 0)
        rows = pl.read_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["action"], "закрыть")
        self.assertEqual(int(rows[-1]["position_after"]), 0)

    def test_friday_phase_closes_only_flagged_config(self):
        self.now = datetime(2026, 11, 20, 18, 45, tzinfo=MSK)
        self._configs("p-friday", "p-base")
        self._seed("p-friday", "prostushka")
        self._seed("p-base", "prostushka")
        self.assertEqual(pl.main(), 0)
        closes = [r for r in pl.read_rows() if r["action"] == "пятница"]
        self.assertEqual([r["config"] for r in closes], ["p-friday"])

    def test_stop_flag_blocks_everything(self):
        self.stop.write_text("1")
        self._configs("p-base")
        self.assertEqual(pl.main(), 0)
        self.assertFalse(self.paper.exists())

    def test_weekend_no_decisions(self):
        self.now = datetime(2026, 11, 21, 13, 55, tzinfo=MSK)
        self._configs("p-base")
        self.assertEqual(pl.main(), 0)
        self.assertFalse(self.paper.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
