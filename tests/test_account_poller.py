"""Опрос счетов: снимки, порог дельты, потоки только из отчёта. ./run.sh test"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.account_poller import (finam_report, fresh_equity, poll_account,  # noqa: E402
                                 scalar, size_for_trade, sync_accounts,
                                 trigger_reason)
from algo.cash_flow_store import CashFlowStore  # noqa: E402
from algo.robot_store import RobotStore  # noqa: E402


class FakeBroker:
    def __init__(self, equity: float, balance: float | None = None,
                 fail: bool = False):
        self.equity = equity
        self.balance = balance if balance is not None else equity
        self.fail = fail
        self.calls = 0

    def account(self, account_id: str) -> dict:
        self.calls += 1
        if self.fail:
            raise RuntimeError("API недоступен")
        return {"equity": self.equity, "balance": self.balance}


class TestAccountPoller(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RobotStore(Path(self.tmp.name) / "robots.db")
        self.store.init_db()
        self.flows = CashFlowStore(self.store)
        self.flows.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_scalar_and_threshold(self):
        self.assertEqual(scalar({"value": "12.5"}), 12.5)
        self.assertEqual(scalar(None), 0.0)
        self.assertFalse(trigger_reason(500, 200_000, 1_000, 1.0))
        self.assertTrue(trigger_reason(2_000, 200_000, 1_000, 1.0))
        self.assertTrue(trigger_reason(500, 20_000, 1_000, 1.0))

    def test_first_poll_only_snapshot(self):
        broker = FakeBroker(200_000)
        result = poll_account("acc-1", broker, self.flows, reporter=lambda *args: [
            {"tx_id": "t1", "type": "DEPOSIT", "amount": 10_000}])
        self.assertTrue(result.ok)
        self.assertFalse(result.triggered)
        self.assertEqual(result.flows, ())
        self.assertEqual(len(self.flows.list_snapshots("acc-1")), 1)

    def test_report_confirms_flow_and_is_idempotent(self):
        broker = FakeBroker(200_000)
        poll_account("acc-1", broker, self.flows)
        broker.equity = 300_000
        calls: list[str] = []

        def reporter(account_id: str, since: str, broker: object) -> list[dict]:
            calls.append(account_id)
            return [{"tx_id": "tx-42", "type": "DEPOSIT",
                     "amount": 100_000, "timestamp": "2026-11-24T12:00:00"}]

        second = poll_account("acc-1", broker, self.flows, reporter=reporter)
        self.assertTrue(second.triggered)
        self.assertTrue(second.flows[0]["recorded"])
        third = poll_account("acc-1", broker, self.flows, reporter=reporter)
        self.assertFalse(third.flows[0]["recorded"])
        self.assertEqual(calls, ["acc-1", "acc-1"])
        rows = self.flows.list_flows("acc-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["broker_tx_id"], "tx-42")
        self.assertEqual(rows[0]["balance_after"], 300_000)

    def test_pnl_delta_without_report_is_not_a_flow(self):
        broker = FakeBroker(200_000)
        poll_account("acc-1", broker, self.flows)
        broker.equity = 205_000
        result = poll_account("acc-1", broker, self.flows, reporter=None)
        self.assertTrue(result.triggered)
        self.assertEqual(result.flows, ())
        self.assertEqual(self.flows.list_flows("acc-1"), [])

    def test_broker_error_keeps_old_snapshot(self):
        poll_account("acc-1", FakeBroker(200_000), self.flows)
        result = poll_account("acc-1", FakeBroker(0, fail=True), self.flows)
        self.assertFalse(result.ok)
        self.assertIn("API недоступен", result.error)
        self.assertEqual(len(self.flows.list_snapshots("acc-1")), 1)

    def test_forced_report_works_without_delta(self):
        broker = FakeBroker(200_000)
        poll_account("acc-1", broker, self.flows)
        calls: list[str] = []

        def reporter(account_id: str, since: str, broker: object) -> list[dict]:
            calls.append(account_id)
            return [{"tx_id": "tx-scheduled", "type": "DIVIDEND",
                     "amount": 1_500, "timestamp": "2026-11-24T12:30:00"}]

        result = poll_account("acc-1", broker, self.flows,
                              reporter=reporter, force_report=True)
        self.assertEqual(calls, ["acc-1"])
        self.assertTrue(result.flows[0]["recorded"])
        self.assertEqual(self.flows.list_flows("acc-1")[0]["type"], "DIVIDEND")

    def test_finam_report_filters_only_cash_transactions(self):
        class Broker:
            def _call(self, method, path, params=None):
                return {"transactions": [
                    {"id": "tx-1", "transaction_category": "DEPOSIT",
                     "change": {"units": "100000", "nanos": 0},
                     "timestamp": {"seconds": 1763985600, "nanos": 0}},
                    {"id": "tx-2", "transaction_category": "COMMISSION",
                     "change": {"units": "-12", "nanos": 0}},
                    {"id": "tx-3", "transaction_category": 2,
                     "change": {"units": "-50000", "nanos": 0}},
                ]}

        rows = finam_report()("acc-1", "", Broker())
        self.assertEqual([r["tx_id"] for r in rows], ["tx-1", "tx-3"])
        self.assertEqual(rows[0]["type"], "DEPOSIT")
        self.assertEqual(rows[0]["amount"], 100_000)
        self.assertEqual(rows[1]["type"], "WITHDRAWAL")

    def test_fresh_equity_before_trade(self):
        self.assertEqual(fresh_equity("acc-1", FakeBroker(210_000)), 210_000)
        self.assertIsNone(fresh_equity("acc-1", FakeBroker(0)))
        self.assertIsNone(fresh_equity("acc-1", FakeBroker(0, fail=True)))
        self.assertEqual(size_for_trade("acc-1", FakeBroker(200_000),
                                        12.29, 1000.0, 2.0), 32)
        self.assertEqual(size_for_trade("acc-1", FakeBroker(0, fail=True),
                                        12.29, 1000.0, 2.0), 0)

    def test_sync_skips_disabled_accounts(self):
        self.store.create_account({"id": "off-1", "label": "Выключенный",
                                   "key_ref": "acc:off-1", "enabled": False})
        calls: list[str] = []

        def factory(account: dict) -> FakeBroker:
            calls.append(account["id"])
            return FakeBroker(200_000)

        results = sync_accounts(self.store.list_accounts(), self.flows,
                                broker_factory=factory)
        self.assertEqual(calls, [])
        self.assertEqual(results, [])

    def test_sync_skips_accounts_without_keys(self):
        self.store.create_account({"id": "live-1", "label": "боевой",
                                   "key_ref": "acc:live-1"})
        self.store.create_account({"id": "no-key", "label": "без ключа"})
        factory_calls: list[str] = []

        def factory(account: dict) -> FakeBroker:
            factory_calls.append(account["id"])
            return FakeBroker(200_000)

        results = sync_accounts(self.store.list_accounts(), self.flows,
                                broker_factory=factory)
        self.assertEqual(factory_calls, ["live-1"])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)


if __name__ == "__main__":
    unittest.main()
