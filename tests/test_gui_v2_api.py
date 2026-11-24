"""Тесты новых API GUI v2: архив, аналитика счетов, единый лог."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.robot_store import RobotStore  # noqa: E402
from web import instances_api as ia  # noqa: E402


class TestGuiV2Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = RobotStore(Path(self.tmp.name) / "robots.db")
        self.store.init_db()
        self.store.create_instance({
            "id": "old-bot", "spec_id": "prostushka", "mode": "paper",
            "status": "active", "instrument": "CNY", "params": {},
        })

    def test_archive_only_decommissioned(self):
        self.assertEqual(ia.archive_list(self.store), [])
        self.store.set_status("old-bot", "archived")
        items = ia.archive_list(self.store)
        self.assertEqual([x["id"] for x in items], ["old-bot"])
        self.assertEqual(items[0]["mode"], "paper")
        self.assertEqual(items[0]["status"], "archived")

    def test_account_analytics_virtual(self):
        self.store.set_runtime("old-bot", {"position": 3, "equity": 203000})
        data = ia.account_analytics(self.store)
        self.assertEqual(data["real"], [])
        virtual = {x["id"]: x for x in data["virtual"]}
        self.assertEqual(virtual["old-bot"]["position"], 3)
        self.assertEqual(virtual["old-bot"]["equity"], 203000)

    def test_logs_aggregate_has_instance_events(self):
        entries = ia.logs_aggregate(self.store)
        self.assertTrue(any(x["source"] == "instances" and "old-bot" in x["text"]
                            for x in entries))


if __name__ == "__main__":
    unittest.main()
