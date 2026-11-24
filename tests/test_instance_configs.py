"""Тесты моста store ↔ раннеры: seed, активные инстансы, миграция состояния."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import instance_configs as ic  # noqa: E402
from algo.robot_store import RobotStore  # noqa: E402


HEADER = "date,time,config,instrument,symbol,strategy,price,signal,target,contracts,equity_before,action,position_after,note"


class TestInstanceConfigs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = RobotStore(Path(self.tmp.name) / "robots.db")
        self.db.init_db()

    def test_seed_idempotent(self):
        first = ic.seed_static_configs(self.db)
        second = ic.seed_static_configs(self.db)
        self.assertGreater(first, 0)
        self.assertEqual(second, 0)
        self.assertEqual(len(self.db.list_instances(mode="paper")), first)

    def test_active_respects_status(self):
        ic.seed_static_configs(self.db)
        all_active = ic.active_configs("paper", self.db)
        self.assertGreater(len(all_active), 0)
        self.db.set_status("p-base", "paused")
        ids = {c.id for c in ic.active_configs("paper", self.db)}
        self.assertNotIn("p-base", ids)
        self.assertIn("u-base", ids)

    def test_fallback_when_no_store(self):
        empty = RobotStore(Path(self.tmp.name) / "missing.db")
        self.assertEqual(ic.active_configs("paper", empty), ic.STATIC)
        self.assertEqual(ic.active_configs("live", empty), [])

    def test_migrate_runtime(self):
        ic.seed_static_configs(self.db)
        paper = Path(self.tmp.name) / "paper.csv"
        row = ("2026-11-23,13:50,p-base,CNY,CNYRUBF@RTSX,prostushka,"
               "12.300,1,32,32,200000,решение,32,тест")
        paper.write_text(HEADER + "\n" + row + "\n", encoding="utf-8")
        n = ic.migrate_runtime_from_paper(self.db, paper)
        self.assertEqual(n, 1)  # в журнале только p-base
        st = self.db.get_runtime("p-base")
        self.assertEqual(st["position"], 32)
        self.assertEqual(st["symbol"], "CNYRUBF@RTSX")
        self.assertIn("2026-11-23", st["last_decision"])

    def test_configs_at_uses_param_versions(self):
        ic.seed_static_configs(self.db)
        before = {c.id: c for c in ic.configs_at("2026-11-22", store=self.db)}
        self.assertNotIn("timeframe", before["p-base"].params)
        self.db.update_instance(
            "p-base", {"params": dict(before["p-base"].params, timeframe=60)}, 1,
            reason="H1", actor="test")
        self.db.set_status("p-base", "active")
        after = {c.id: c for c in ic.configs_at("2026-11-24", store=self.db)}
        self.assertEqual(after["p-base"].params["timeframe"], 60)
        again = {c.id: c for c in ic.configs_at("2026-11-22", store=self.db)}
        self.assertNotIn("timeframe", again["p-base"].params)
        self.assertEqual([v["version"] for v in self.db.param_history("p-base")],
                         [1, 2])

    def test_live_settings_from_store(self):
        self.db.create_account({"id": "A1"})
        self.db.create_instance({
            "id": "live-1", "spec_id": "prostushka", "mode": "live",
            "status": "active", "account": "A1", "pricing": "marketable",
            "source_config": "p-base", "exposure": 2.0,
        })
        s = ic.live_settings_from_store(self.db)
        self.assertEqual(list(s.robots), ["live-1"])
        self.assertEqual(s.robots["live-1"].pricing.value, "marketable")
        self.assertEqual(s.robots["live-1"].source_config, "p-base")
        self.assertEqual(s.robots["live-1"].exposure, 2.0)
        self.assertEqual(s.accounts["A1"].id, "A1")


if __name__ == "__main__":
    unittest.main()
