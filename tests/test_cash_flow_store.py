"""Новые таблицы в robots.db: потоки, влияние на лоты, снимки. ./run.sh test"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.cash_flow_store import CashFlowStore  # noqa: E402
from algo.cash_flows import (CashFlow, CashFlowType, RobotSizing,  # noqa: E402
                             preview_cash_flow)
from algo.robot_store import RobotStore  # noqa: E402


class TestCashFlowStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RobotStore(Path(self.tmp.name) / "robots.db")
        self.store.init_db()
        self.flows = CashFlowStore(self.store)
        self.flows.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_is_idempotent_with_impacts_and_events(self):
        flow = CashFlow.detect(CashFlowType.DEPOSIT, 100_000, 200_000,
                               client_key="virtual-1")
        bots = [RobotSizing("p-base", price=12.29, exposure=2.0)]
        preview = preview_cash_flow(flow, bots)

        first = self.flows.record_flow(flow, preview, "acc-1", source="VIRTUAL")
        second = self.flows.record_flow(flow, preview, "acc-1", source="VIRTUAL")
        self.assertTrue(first["recorded"])
        self.assertFalse(second["recorded"])
        self.assertEqual(len(self.flows.list_flows("acc-1")), 1)
        impacts = self.flows.list_impacts(first["id"])
        self.assertEqual(len(impacts), 1)
        self.assertEqual(impacts[0]["lots_before"], 32)
        self.assertEqual(impacts[0]["lots_after"], 48)
        with self.store._conn() as c:
            events = c.execute(
                "SELECT * FROM instance_events WHERE action='cash_flow'").fetchall()
        self.assertEqual(len(events), 1)

    def test_snapshots_are_unique_per_account_and_time(self):
        self.assertTrue(self.flows.add_snapshot("acc-1", 210_000, 200_000,
                                                timestamp="2026-11-24T10:00:00"))
        self.assertFalse(self.flows.add_snapshot("acc-1", 220_000, 200_000,
                                                 timestamp="2026-11-24T10:00:00"))
        self.assertTrue(self.flows.add_snapshot("acc-1", 230_000, 200_000,
                                                timestamp="2026-11-24T11:00:00"))
        rows = self.flows.list_snapshots("acc-1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.flows.latest_snapshot("acc-1")["equity"], 230_000)

    def test_apply_virtual_changes_capital_and_runtime_only(self):
        self.store.create_instance({"id": "paper-1", "spec_id": "prostushka",
                                    "instrument": "CNY", "mode": "paper",
                                    "capital": 200_000})
        self.store.set_runtime("paper-1", {"equity": 205_000, "position": 2})
        result = self.flows.apply_virtual("paper-1", 50_000, "пополнение")
        self.assertEqual(result["capital_after"], 250_000)
        inst = self.store.get_instance("paper-1")
        self.assertEqual(inst["capital"], 250_000)
        self.assertEqual(self.store.get_runtime("paper-1")["equity"], 255_000)
        with self.assertRaises(ValueError):
            self.flows.apply_virtual("paper-1", -999_999)

    def test_existing_account_and_instance_tables_untouched(self):
        self.store.create_account({"id": "КлФ-2102993", "label": "боевой"})
        with self.store._conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(accounts)")}
        self.assertIn("key_ref", cols)
        self.assertIn("trading_code", cols)


if __name__ == "__main__":
    unittest.main()
