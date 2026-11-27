"""Боевой сигнал считается по своим барам и пишется в персональный журнал."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import live_signal as sig  # noqa: E402
from algo.instance_configs import live_settings_from_store  # noqa: E402
from algo.robot_store import RobotStore  # noqa: E402


class FakeBroker:
    def __init__(self, m5):
        self.m5 = m5
        self.calls = []

    def bars(self, symbol, timeframe, start=None, end=None):
        self.calls.append((symbol, timeframe))
        return self.m5


def rising_bars() -> pd.DataFrame:
    idx = pd.date_range("2026-11-25 00:00", "2026-11-27 14:00", freq="5min")
    close = 12.0 + (idx - idx[0]).total_seconds() / 3600 * 0.001
    return pd.DataFrame({"open": close, "high": close + 0.01,
                         "low": close - 0.01, "close": close, "vol": 1.0},
                        index=idx)


class TestLiveSignal(unittest.TestCase):
    def test_signal_without_paper_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RobotStore(Path(tmp) / "robots.db")
            store.init_db()
            store.create_account({"id": "acc-1", "mode": "LIVE"})
            store.create_instance({
                "id": "live-1", "spec_id": "prostushka", "mode": "live",
                "status": "active", "account": "acc-1", "pricing": "marketable",
                "instrument": "CNY", "exposure": 1.0,
                "params": {"ma_window": 200, "entry": "13:50",
                           "filter_bars": 0, "timeframe": 5},
            })
            settings = live_settings_from_store(store)
            broker = FakeBroker(rising_bars())
            with mock.patch.object(sig.market, "init_db"), \
                 mock.patch.object(sig.market, "upsert") as upsert:
                plans, notes, recorded = sig.collect(
                    store, settings, date(2026, 11, 27), broker)
            self.assertTrue(notes or plans)
            self.assertGreaterEqual(upsert.call_count, 1)
            self.assertEqual(upsert.call_args_list[0].args[2], "M5")
            self.assertEqual(len(recorded), 1)
            plan = next(iter(plans.values()))["CNYRUBF@RTSX"]
            self.assertEqual(plan["target"], 1)
            self.assertEqual(plan["when"], "13:50")
            rows = store.list_decisions("live-1")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["signal"], 1)
            self.assertEqual(rows[0]["symbol"], "CNYRUBF@RTSX")

    def test_repeated_collect_does_not_duplicate_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RobotStore(Path(tmp) / "robots.db")
            store.init_db()
            store.create_account({"id": "acc-1", "mode": "LIVE"})
            store.create_instance({
                "id": "live-1", "spec_id": "prostushka", "mode": "live",
                "status": "active", "account": "acc-1", "pricing": "marketable",
                "instrument": "CNY", "exposure": 1.0,
                "params": {"ma_window": 200, "entry": "13:50",
                           "filter_bars": 0, "timeframe": 5},
            })
            settings = live_settings_from_store(store)
            broker = FakeBroker(rising_bars())
            with mock.patch.object(sig.market, "init_db"), \
                 mock.patch.object(sig.market, "upsert"):
                sig.collect(store, settings, date(2026, 11, 27), broker)
                _, _, second = sig.collect(store, settings,
                                           date(2026, 11, 27), broker)
            self.assertEqual(second, [])
            self.assertEqual(len(store.list_decisions("live-1")), 1)


if __name__ == "__main__":
    unittest.main()
