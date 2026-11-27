"""Регрессия: ожидание считает сайзинг по барам daily-прогона (13:55)."""

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
    def test_risk_uses_bars_up_to_daily_slot(self):
        bars = []
        for day in (19, 20):
            for hour, minute in ((12, 0), (13, 0), (13, 55), (14, 0)):
                bars.append({"dt": datetime(2026, 11, day, hour, minute),
                             "open": 12.0, "high": 12.1, "low": 11.9,
                             "close": 12.0, "vol": 1.0})
        m5 = pd.DataFrame(bars).set_index("dt")
        cfg = next(c for c in CONFIGS if c.id == "p-base")
        cfg = cfg.__class__(**{**cfg.__dict__,
                               "params": {**cfg.params, "risk_vol": True}})
        def dec(cfg, m5, day):
            return SimpleNamespace(target=-1, price=12.0,
                                   ts=pd.Timestamp(f"{day} 12:00"))
        captured = []

        def fake_contracts(cfg, equity, price, mult, risk_bars, rows, day, capital):
            captured.append(risk_bars.index.max())
            return 1, "тест"

        with mock.patch.object(ex, "decision", side_effect=dec), \
             mock.patch.object(ex.risk, "contracts_for_config", side_effect=fake_contracts):
            ex.expected(cfg, m5, "2026-11-19", "2026-11-20", 1000, 200000)

        self.assertEqual(len(captured), 2)
        self.assertTrue(all(ts.hour == 13 and ts.minute == 55 for ts in captured))

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


if __name__ == "__main__":
    unittest.main()
