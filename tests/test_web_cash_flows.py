"""Новые API поверх работающей панели: предпросмотр, виртуальные потоки, sync. ./run.sh test"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.cash_flow_store import CashFlowStore  # noqa: E402
from algo.robot_store import RobotStore  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from web.cash_flows_api import (apply_view, equity_view, history_view,  # noqa: E402
                                portfolio_analytics_view, preview_view, sync_view)


class TestWebCashFlows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RobotStore(Path(self.tmp.name) / "robots.db")
        self.store.init_db()
        self.flows = CashFlowStore(self.store)
        self.flows.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_for_live_does_not_write_anything(self):
        payload = {
            "account_id": "КлФ-2102993", "live": True,
            "type": "DEPOSIT", "amount": 100_000, "balance_before": 200_000,
            "robots": [{"robot_id": "p-base", "price": 12.29, "exposure": 2.0}],
        }
        result = preview_view(payload, self.store)
        self.assertTrue(result["valid"])
        self.assertEqual(result["impact"][0]["lots_before"], 32)
        self.assertEqual(result["impact"][0]["lots_after"], 48)
        self.assertTrue(any("LIVE" in w for w in result["validation"]["warnings"]))
        self.assertEqual(self.flows.list_flows(), [])

    def test_apply_virtual_changes_deposit_and_sizing(self):
        self.store.create_instance({"id": "paper-1", "spec_id": "prostushka",
                                    "instrument": "CNY", "mode": "paper",
                                    "capital": 200_000})
        payload = {"instance_id": "paper-1", "type": "DEPOSIT", "amount": 100_000,
                   "client_key": "deposit-1",
                   "robots": [{"robot_id": "paper-1", "price": 12.29,
                               "exposure": 2.0}]}
        first = apply_view(payload, self.store, self.flows)
        self.assertTrue(first["applied"])
        self.assertEqual(first["capital_after"], 300_000)
        self.assertEqual(first["impact"][0]["lots_after"], 48)
        second = apply_view(payload, self.store, self.flows)
        self.assertFalse(second["applied"])
        self.assertEqual(second["reason"], "duplicate")
        self.assertEqual(self.store.get_instance("paper-1")["capital"], 300_000)

    def test_apply_to_live_is_forbidden(self):
        self.store.create_instance({"id": "live-1", "spec_id": "prostushka",
                                    "instrument": "CNY", "mode": "live"})
        with self.assertRaises(HTTPException) as ctx:
            apply_view({"instance_id": "live-1", "type": "DEPOSIT",
                        "amount": 10_000}, self.store, self.flows)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_withdrawal_above_virtual_deposit_is_blocked(self):
        self.store.create_instance({"id": "paper-1", "spec_id": "prostushka",
                                    "instrument": "CNY", "mode": "paper",
                                    "capital": 100_000})
        with self.assertRaises(HTTPException):
            apply_view({"instance_id": "paper-1", "type": "WITHDRAWAL",
                        "amount": 200_000, "client_key": "withdraw-1"},
                       self.store, self.flows)
        self.assertEqual(self.store.get_instance("paper-1")["capital"], 100_000)

    def test_sync_snapshots_and_history(self):
        self.store.create_account({"id": "live-1", "label": "боевой",
                                   "key_ref": "acc:live-1"})
        class FakeBroker:
            equity = 210_000

            def account(self, account_id):
                return {"equity": self.equity, "balance": self.equity}

        sync_view({}, self.store, self.flows,
                  broker_factory=lambda acc: FakeBroker())
        self.assertEqual(len(equity_view("live-1", 100, "", self.flows)["snapshots"]), 1)
        self.assertEqual(self.flows.list_flows("live-1"), [])
        history = history_view("live-1", 10, self.flows)
        self.assertEqual(history["items"], [])
        analytics = portfolio_analytics_view("live-1", self.store, self.flows)
        self.assertIn("virtual", analytics)  # старые поля на месте
        self.assertEqual(analytics["portfolio"]["account_id"], "live-1")


if __name__ == "__main__":
    unittest.main()
