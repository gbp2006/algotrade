"""Регрессия ожидания: закрытие по времени и общая формула сайзинга. ./run.sh test"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import expected as ex  # noqa: E402
from algo.configs import CONFIGS  # noqa: E402


class TestExpected(unittest.TestCase):
    def test_friday_close_waits_for_1845_bar(self):
        cfg = next(c for c in CONFIGS if c.id == "p-friday")
        day = datetime(2026, 11, 27, 13, 50)
        bars = pd.DataFrame([{"dt": day, "open": 12.3, "high": 12.4,
                              "low": 12.2, "close": 12.3, "vol": 1.0}]
                            ).set_index("dt")
        dec = lambda cfg, m5, day: SimpleNamespace(
            target=1, price=12.3, ts=pd.Timestamp("2026-11-27 13:50"))
        with mock.patch.object(ex, "decision", side_effect=dec):
            trades, pnl = ex.expected(cfg, bars, "2026-11-27", "2026-11-27",
                                      1000, 200000)
        self.assertEqual((trades, pnl), (0, 0))

    def test_sizing_uses_common_formula_without_atr(self):
        cfg = next(c for c in CONFIGS if c.id == "p-base")
        day = datetime(2026, 11, 19, 13, 50)
        bars = pd.DataFrame([{"dt": day, "open": 12.0, "high": 12.1,
                              "low": 11.9, "close": 12.0, "vol": 1.0}]
                            ).set_index("dt")
        dec = lambda cfg, m5, day: SimpleNamespace(
            target=1, price=12.0, ts=pd.Timestamp("2026-11-19 13:50"))
        with mock.patch.object(ex, "decision", side_effect=dec), \
             mock.patch.object(ex, "size_contracts", return_value=7) as sizing:
            ex.expected(cfg, bars, "2026-11-19", "2026-11-19", 1000, 200000)
        sizing.assert_called()
        self.assertNotIn("risk_vol", cfg.params)


if __name__ == "__main__":
    unittest.main()
