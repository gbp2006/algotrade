"""Тесты отдельного модуля расписания робота."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import robot_schedule as rs  # noqa: E402
from algo.robot_store import RobotStore  # noqa: E402


PAPER = {"id": "p-base", "spec_id": "prostushka", "mode": "paper",
         "params": {"entry": "13:50", "ma_window": 40}}
FUND = {"id": "fund-1", "spec_id": "money_market", "mode": "live",
        "params": {"time_buy": "23:00", "time_sell": "10:05",
                   "trade_mon": True, "trade_tue": True, "trade_wed": True,
                   "trade_thu": True, "trade_fri": True,
                   "trade_sat": False, "trade_sun": False}}


class TestDefaults(unittest.TestCase):
    def test_paper_entry_and_weekdays(self):
        default = rs.default_schedule(PAPER)
        self.assertEqual(default["times"], ["13:50"])
        self.assertEqual(default["weekdays"], [0, 1, 2, 3, 4])
        self.assertFalse(default["enabled"])
        self.assertIn("--config p-base", default["command"])

    def test_fund_buy_and_sell_times(self):
        default = rs.default_schedule(FUND)
        self.assertEqual(default["times"], ["23:00", "10:05"])
        self.assertEqual(default["weekdays"], [0, 1, 2, 3, 4])
        self.assertIn("36_mm_rebalance.py", default["command"])


class TestFundSlotRegime(unittest.TestCase):
    def test_morning_sells_evening_buys(self):
        self.assertEqual(rs.regime_for_slot(FUND, "10:05"), "OnlyClose")
        self.assertIsNone(rs.regime_for_slot(FUND, "23:00"))

    def test_empty_position_needs_no_order(self):
        # OnlyClose с fund == 0 возвращает «нечего закрывать» без заявки —
        # проверяется в algo.broker.position_ops.mm_rebalance.
        from algo.broker import position_ops as pos

        class FakeBroker:
            def account(self, account):
                return {"cash": [], "positions": []}

        ctx = {"broker": FakeBroker(), "acc_id": "2102993", "params": {},
               "inst": {"id": "fund-1", "instrument": "CASH"},
               "store": None, "capital": 50_000}
        from unittest import mock
        with mock.patch.object(pos, "_context", return_value=ctx):
            result = pos.mm_rebalance(None, "fund-1", dry_run=True, regime="OnlyClose")
        self.assertTrue(result["ok"])
        self.assertEqual(result["closed"], 0)


class TestNormalize(unittest.TestCase):
    def test_comma_times_and_days(self):
        value = rs.normalize({"times": "10:05, 23:00, 10:05",
                              "weekdays": "0,2,6", "command": "./run.sh test"})
        self.assertEqual(value["times"], ["10:05", "23:00"])
        self.assertEqual(value["weekdays"], [0, 2, 6])

    def test_bad_time_rejected(self):
        with self.assertRaises(ValueError):
            rs.normalize({"times": ["25:00"], "command": "./run.sh test"})

    def test_empty_command_rejected(self):
        with self.assertRaises(ValueError):
            rs.normalize({"times": ["10:00"], "command": "  "})


class TestStoreRoundTrip(unittest.TestCase):
    def test_toggle_keeps_editable_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RobotStore(Path(tmp) / "robots.db")
            store.init_db()
            store.create_instance({**PAPER, "account": "paper-p-base",
                                   "status": "active"})
            default = rs.default_schedule(PAPER)
            saved = rs.save_schedule(store, PAPER, {**default, "enabled": True,
                                                    "times": ["09:30", "18:45"],
                                                    "weekdays": [0, 2, 4]})
            self.assertTrue(saved["enabled"])
            self.assertEqual(saved["times"], ["09:30", "18:45"])
            disabled = rs.save_schedule(store, PAPER, {**saved, "enabled": False})
            self.assertFalse(disabled["enabled"])
            self.assertEqual(disabled["times"], ["09:30", "18:45"])
            self.assertFalse(rs.all_schedules(store)["p-base"]["enabled"])


if __name__ == "__main__":
    unittest.main()
