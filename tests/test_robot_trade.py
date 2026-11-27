"""Тесты простого управления «Старт/Стоп» с сохранением пользовательского расписания."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import robot_trade  # noqa: E402
from algo.robot_store import RobotStore  # noqa: E402


class TestRobotTrade(unittest.TestCase):
    def test_start_and_stop_keep_schedule_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RobotStore(Path(tmp) / "robots.db")
            store.init_db()
            store.create_instance({"id": "r-1", "spec_id": "prostushka",
                                   "mode": "paper", "params": {"entry": "13:50"}})
            job = store.upsert_job({
                "id": "inst:r-1:schedule", "owner": "r-1",
                "command": "./run.sh paper-live --config r-1",
                "times": ["09:15", "18:30"], "weekdays": [0, 2], "enabled": False,
            })
            started = robot_trade.start(store, "r-1")
            self.assertEqual(started["status"], "active")
            self.assertTrue(started["scheduled"])
            saved = store.get_instance("r-1")
            self.assertEqual(saved["status"], "active")
            after = next(j for j in store.list_jobs(owner="r-1"))
            self.assertTrue(after["enabled"])
            self.assertEqual(after["times"], job["times"])
            self.assertEqual(after["weekdays"], [0, 2])

            stopped = robot_trade.stop(store, "r-1")
            self.assertEqual(stopped["status"], "paused")
            self.assertFalse(store.get_instance("r-1")["status"] == "active")
            after = next(j for j in store.list_jobs(owner="r-1"))
            self.assertFalse(after["enabled"])
            self.assertEqual(after["times"], ["09:15", "18:30"])

    def test_live_start_enables_timer_with_store(self):
        from unittest import mock
        from algo import arm_state, live_control

        with tempfile.TemporaryDirectory() as tmp:
            store = RobotStore(Path(tmp) / "robots.db")
            store.init_db()
            store.create_instance({"id": "fund-1", "spec_id": "money_market",
                                   "mode": "live", "account": "2102993"})
            with mock.patch.object(live_control, "enable", return_value={"ok": True}) as enable, \
                 mock.patch.object(live_control, "disable", return_value={"ok": True}) as disable, \
                 mock.patch.object(arm_state, "ARM_STATE", Path(tmp) / "arm.json"):
                result = robot_trade.start(store, "fund-1")
                robot_trade.stop(store, "fund-1")
            enable.assert_called_once_with(store)
            disable.assert_called_once_with(store)
            self.assertTrue(result["armed_mm"])


if __name__ == "__main__":
    unittest.main()
