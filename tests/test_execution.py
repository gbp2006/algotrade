"""Тесты шлюза исполнения G3: предохранители без реальных заявок. ./run.sh test"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.broker import execution as ex  # noqa: E402


class FakeBroker:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple] = []
        self.fail = fail

    def place_limit(self, symbol, side, qty, price, account=None):
        self.calls.append((symbol, side, qty, price, account))
        if self.fail:
            raise RuntimeError("API 500")
        return {"orderId": "42"}


def order(**kw):
    base = ex.Order(client_id="p-base:2026-11-20:buy", config="p-base",
                    symbol="CNYRUBF@RTSX", side="buy", qty=32, price=12.29,
                    multiplier=1000.0)
    return replace(base, **kw)


class TestGateway(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal = Path(self.tmp.name) / "live.csv"
        self.lock = Path(self.tmp.name) / "live.lock"
        self.broker = FakeBroker()
        self.gw = ex.OrderGateway(self.broker, journal=self.journal, lock=self.lock)

    def test_blocked_without_flag(self):
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "0"}):
            res = self.gw.submit(order())
        self.assertEqual(res.status, "blocked")
        self.assertEqual(self.broker.calls, [])
        self.assertEqual(len(self.gw._rows()), 1)

    def test_sent_with_flag(self):
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = self.gw.submit(order(), account="2102993")
        self.assertTrue(res.sent)
        self.assertEqual(self.broker.calls,
                         [("CNYRUBF@RTSX", "buy", 32, 12.29, "2102993")])
        self.assertFalse(self.lock.exists())

    def test_duplicate_not_sent_twice(self):
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            first = self.gw.submit(order())
            second = self.gw.submit(order())
        self.assertEqual((first.status, second.status), ("sent", "duplicate"))
        self.assertEqual(len(self.broker.calls), 1)

    def test_limits(self):
        cases = [
            (ex.Limits(max_qty=10), {}),
            (ex.Limits(max_notional=1000), {}),
            (ex.Limits(max_daily_loss=1000), {"daily_pnl": -2000}),
            (ex.Limits(allowed_symbols=frozenset({"OTHER"})), {}),
            (ex.Limits(), {"qty": 0}),
            (ex.Limits(), {"price": -1}),
            (ex.Limits(), {"side": "hold"}),
        ]
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            for i, (limits, kw) in enumerate(cases):
                gw = ex.OrderGateway(self.broker, limits, self.journal, self.lock)
                res = gw.submit(order(client_id=f"case-{i}", **kw))
                self.assertEqual(res.status, "rejected", (limits, kw, res))
        self.assertEqual(self.broker.calls, [])

    def test_lock_blocks_second_launcher(self):
        self.lock.write_text("другой процесс", encoding="utf-8")
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = self.gw.submit(order())
        self.assertEqual(res.status, "rejected")
        self.assertIn("другая заявка", res.reason)
        self.assertEqual(self.broker.calls, [])

    def test_transport_error_journaled_and_lock_released(self):
        gw = ex.OrderGateway(FakeBroker(fail=True), journal=self.journal, lock=self.lock)
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = gw.submit(order())
        self.assertEqual(res.status, "error")
        self.assertIn("API 500", res.reason)
        self.assertFalse(self.lock.exists())
        self.assertEqual(gw._rows()[0]["status"], "error")


class TestReconcile(unittest.TestCase):
    def test_positions_parsing(self):
        resp = {"positions": [
            {"symbol": "CNYRUBF@RTSX", "quantity": {"value": "32"}},
            {"symbol": "RIZ6@RTSX", "qty": "-1"},
        ]}
        self.assertEqual(ex.positions_from_response(resp),
                         {"CNYRUBF@RTSX": 32, "RIZ6@RTSX": -1})

    def test_unknown_format_is_loud(self):
        with self.assertRaises(ex.ExecutionError):
            ex.positions_from_response({"unexpected": 1})

    def test_reconcile_mismatches(self):
        problems = ex.reconcile({"A": 1, "B": -1}, {"A": 1, "B": 0, "C": 2})
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("B" in p for p in problems))
        self.assertTrue(any("C" in p for p in problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
