"""Тесты предохранителей боевого контура. ./run.sh test"""

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
from algo.broker import live_guard as lg  # noqa: E402


class FakeBroker:
    def __init__(self, positions=None, fail=False):
        self.positions = positions if positions is not None else []
        self.fail = fail
        self.calls = []

    def account(self):
        if self.fail:
            raise RuntimeError("API down")
        return {"positions": self.positions}

    def place_limit(self, symbol, side, qty, price, account=None, client_order_id=None):
        self.calls.append((symbol, side, qty, client_order_id))
        return {"order_id": "1"}


class TestBattleLimits(unittest.TestCase):
    def test_from_capital(self):
        lim = lg.battle_limits(2_000_000, max_exposure=1.5, max_qty=40)
        self.assertEqual(lim.max_notional, 3_000_000)
        self.assertEqual(lim.max_daily_loss, 60_000)
        out = lim.as_limits()
        self.assertIsInstance(out, ex.Limits)
        self.assertEqual(out.max_qty, 40)

    def test_bad_capital(self):
        with self.assertRaises(ValueError):
            lg.battle_limits(0)


class TestClientId(unittest.TestCase):
    def test_unique_per_decision(self):
        a = lg.decision_client_id("p-base", "2026-11-23", "buy", "13:55", 0)
        b = lg.decision_client_id("p-base", "2026-11-23", "buy", "13:55", 1)
        c = lg.decision_client_id("p-base", "2026-11-23", "sell", "13:55", 0)
        self.assertEqual(len({a, b, c}), 3)
        self.assertEqual(len({ex.client_order_id(x) for x in (a, b, c)}), 3)
        self.assertLessEqual(len(ex.client_order_id(a)), 20)


class TestStop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stop = Path(self.tmp.name) / "STOP_REAL"

    def test_clear_then_raises(self):
        lg.assert_stop_clear(self.stop)
        self.stop.write_text("x", encoding="utf-8")
        with self.assertRaises(ex.ExecutionError):
            lg.assert_stop_clear(self.stop)

    def test_gateway_blocks_per_order(self):
        broker = FakeBroker()
        journal = Path(self.tmp.name) / "live.csv"
        lock = Path(self.tmp.name) / "live.lock"
        gw = ex.OrderGateway(broker, limits=lg.battle_limits(200_000).as_limits(),
                             journal=journal, lock=lock)
        order = ex.Order(client_id="p-base:2026-11-23:13:55:buy:0", config="p-base",
                         symbol="CNYRUBF@RTSX", side="buy", qty=32, price=12.29,
                         multiplier=1000.0)
        self.stop.write_text("x", encoding="utf-8")
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = gw.submit(order, stop=self.stop)
        self.assertEqual(res.status, "blocked")
        self.assertEqual(broker.calls, [])


class TestReconcileGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stop = Path(self.tmp.name) / "STOP_REAL"

    def test_match(self):
        broker = FakeBroker([{"symbol": "CNYRUBF@RTSX", "quantity": 32}])
        issues = lg.reconcile_guard(broker, {"CNYRUBF@RTSX": 32}, stop=self.stop)
        self.assertEqual(issues, [])
        self.assertFalse(self.stop.exists())

    def test_mismatch_sets_stop(self):
        broker = FakeBroker([{"symbol": "CNYRUBF@RTSX", "quantity": 0}])
        with self.assertRaises(ex.ExecutionError):
            lg.reconcile_guard(broker, {"CNYRUBF@RTSX": 32}, stop=self.stop)
        self.assertTrue(self.stop.exists())
        self.assertIn("CNYRUBF@RTSX", self.stop.read_text(encoding="utf-8"))

    def test_rehearsal_does_not_stop(self):
        broker = FakeBroker([{"symbol": "CNYRUBF@RTSX", "quantity": 0}])
        issues = lg.reconcile_guard(broker, {"CNYRUBF@RTSX": 32},
                                    stop=self.stop, enforce=False)
        self.assertEqual(len(issues), 1)
        self.assertFalse(self.stop.exists())


if __name__ == "__main__":
    unittest.main()
