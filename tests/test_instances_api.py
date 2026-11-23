"""Тесты API управления инстансами (без HTTP-клиента). ./run.sh test"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.robot_store import RobotStore  # noqa: E402
from web import instances_api as api  # noqa: E402


class TestApiViews(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = RobotStore(Path(self.tmp.name) / "robots.db")
        self.store.init_db()

    def test_specs(self):
        specs = api.specs_view()
        self.assertTrue(any(s["id"] == "prostushka" for s in specs))
        self.assertIn("ma_window", specs[0]["schema"])

    def test_create_list_action_history(self):
        created = api.create_view(self.store, {
            "id": "p-api", "spec_id": "prostushka", "instrument": "CNY",
            "params": {"ma_window": 55}, "mode": "paper",
        })
        self.assertEqual(created["status"], "draft")
        rows = api.instances_view(self.store, mode="paper")
        self.assertEqual([r["id"] for r in rows], ["p-api"])
        api.action_view(self.store, "p-api", "start")
        api.action_view(self.store, "p-api", "pause")
        self.assertEqual(self.store.get_instance("p-api")["status"], "paused")
        self.assertGreaterEqual(len(api.history_view(self.store, "p-api")), 3)

    def test_update_with_version(self):
        created = api.create_view(self.store, {
            "id": "p-api", "spec_id": "prostushka", "mode": "paper"})
        upd = api.update_view(self.store, "p-api",
                              {"version": created["version"],
                               "params": {"ma_window": 77}, "reason": "тест"})
        self.assertEqual(upd["params"]["ma_window"], 77)
        self.assertEqual(upd["version"], 2)

    def test_brokers_list(self):
        self.assertIn("finam", [b["name"] for b in api.brokers()])


if __name__ == "__main__":
    unittest.main()
