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

from algo import trade_journal as tj  # noqa: E402
from algo.broker import execution as ex  # noqa: E402


class FakeBroker:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple] = []
        self.fail = fail

    def place_limit(self, symbol, side, qty, price, account=None, client_order_id=None):
        self.calls.append((symbol, side, qty, price, account, client_order_id))
        if self.fail:
            raise RuntimeError("API 500")
        return {"order_id": "42"}

    def find_order(self, client_order_id, account=None):
        return None


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
        self.stop = Path(self.tmp.name) / "STOP_REAL"
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
        cid = ex.client_order_id(order().client_id)
        self.assertEqual(self.broker.calls,
                         [("CNYRUBF@RTSX", "buy", 32, 12.29, "2102993", cid)])
        self.assertEqual(len(cid), 20)
        self.assertEqual(self.gw._rows()[0]["order_id"], "42")
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
            (ex.Limits(), {"min_step": 0.001, "price": 12.2905}),
        ]
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            for i, (limits, kw) in enumerate(cases):
                gw = ex.OrderGateway(self.broker, limits, self.journal, self.lock)
                res = gw.submit(order(client_id=f"case-{i}", **kw))
                self.assertEqual(res.status, "rejected", (limits, kw, res))
        self.assertEqual(self.broker.calls, [])

    def test_reversal_checks_resulting_position_notional(self):
        # ADR 25.11: −2 → +2 требует заявку на 4 контракта (49 308 ₽), но итог
        # +2 = 24 654 ₽ укладывается в потолок счёта 24 967 ₽.
        gw = ex.OrderGateway(self.broker, ex.Limits(max_qty=10, max_notional=24_967),
                             self.journal, self.lock)
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = gw.submit(order(client_id="rev-result", side="buy", qty=4,
                                  price=12.327, multiplier=1000.0, result_qty=2))
        self.assertTrue(res.sent, res.reason)
        self.assertEqual(self.broker.calls[0][2], 4)
        self.assertEqual(self.broker.calls[0][3], 12.327)

    def test_reversal_without_result_qty_still_rejected(self):
        gw = ex.OrderGateway(self.broker, ex.Limits(max_qty=10, max_notional=24_967),
                             self.journal, self.lock)
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = gw.submit(order(client_id="rev-plain", side="buy", qty=4,
                                  price=12.327, multiplier=1000.0))
        self.assertEqual(res.status, "rejected")
        self.assertIn("номинал", res.reason)
        self.assertEqual(self.broker.calls, [])

    def test_close_to_flat_checks_zero_notional(self):
        gw = ex.OrderGateway(self.broker, ex.Limits(max_qty=10, max_notional=24_967),
                             self.journal, self.lock)
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = gw.submit(order(client_id="close-flat", side="sell", qty=8,
                                  price=12.327, multiplier=1000.0, result_qty=0))
        self.assertTrue(res.sent, res.reason)
        self.assertEqual(self.broker.calls[0][2], 8)

    def test_lock_blocks_second_launcher(self):
        self.lock.write_text("другой процесс", encoding="utf-8")
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = self.gw.submit(order())
        self.assertEqual(res.status, "rejected")
        self.assertIn("другая заявка", res.reason)
        self.assertEqual(self.broker.calls, [])

    def test_gateway_keeps_full_response_beside_short_csv_field(self):
        class VerboseBroker(FakeBroker):
            def place_limit(self, *a, **k):
                return {"order_id": "42", "payload": {"x": "y" * 400}}

        gw = ex.OrderGateway(VerboseBroker(), journal=self.journal,
                             lock=self.lock, journal_db=self.journal.with_suffix(".db"))
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = gw.submit(order(client_id="verbose"))
        cid = ex.client_order_id("verbose")
        self.assertTrue(res.sent)
        self.assertLessEqual(len(gw._rows()[0]["response"]), 300)
        self.assertEqual(tj.full_response(cid, gw.journal_db)[0]["payload"]["x"],
                         "y" * 400)

    def test_stop_appearing_mid_session_blocks_second_order(self):
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            first = self.gw.submit(order(client_id="mid-1"), stop=self.stop)
            self.stop.write_text("1", encoding="utf-8")
            second = self.gw.submit(order(client_id="mid-2"), stop=self.stop)
        self.assertTrue(first.sent)
        self.assertEqual(second.status, "blocked")
        self.assertEqual(len(self.broker.calls), 1)
        self.assertEqual([r["status"] for r in self.gw._rows()], ["sent", "blocked"])

    def test_stale_lock_from_dead_process_is_cleared(self):
        self.lock.write_text("99999999:old-order", encoding="utf-8")
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = self.gw.submit(order())
        self.assertTrue(res.sent)
        self.assertFalse(self.lock.exists())

    def test_legacy_lock_expires_by_age(self):
        self.lock.write_text("old-order", encoding="utf-8")
        old = __import__("time").time() - ex.LOCK_MAX_AGE_SEC - 10
        os.utime(self.lock, (old, old))
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = self.gw.submit(order())
        self.assertTrue(res.sent)

    def test_live_pid_lock_still_blocks(self):
        self.lock.write_text(f"{os.getpid()}:current-order", encoding="utf-8")
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = self.gw.submit(order())
        self.assertEqual(res.status, "rejected")

    def test_transport_error_journaled_and_lock_released(self):
        gw = ex.OrderGateway(FakeBroker(fail=True), journal=self.journal, lock=self.lock)
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = gw.submit(order())
        self.assertEqual(res.status, "error")
        self.assertIn("API 500", res.reason)
        self.assertFalse(self.lock.exists())
        self.assertEqual(gw._rows()[0]["status"], "error")


    def test_dry_run_validates_without_flag(self):
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "0"}):
            ok = self.gw.submit(order(client_id="dry-ok", min_step=0.001),
                                dry_run=True)
            bad = self.gw.submit(order(client_id="dry-bad", price=12.2905,
                                       min_step=0.001), dry_run=True)
        self.assertEqual(ok.status, "planned")
        self.assertEqual(bad.status, "rejected")
        self.assertIn("кратна", bad.reason)
        self.assertEqual(self.broker.calls, [])
        self.assertEqual([r["status"] for r in self.gw._rows()][:2],
                         ["planned", "rejected"])

    def test_lost_response_found_on_server_is_uncertain(self):
        class LostBroker(FakeBroker):
            def place_limit(self, *a, **k):
                raise RuntimeError("connection lost")

            def find_order(self, client_order_id, account=None):
                return {"order_id": "77", "status": "ORDER_STATUS_NEW",
                        "executed_quantity": {"value": "0"}}

        gw = ex.OrderGateway(LostBroker(), journal=self.journal, lock=self.lock)
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = gw.submit(order())
        self.assertEqual(res.status, "uncertain")
        self.assertEqual(res.order_id, "77")
        self.assertEqual(gw._rows()[0]["status"], "uncertain")

    def test_order_state_parsing(self):
        state = ex.order_state({
            "status": "ORDER_STATUS_PARTIALLY_FILLED",
            "executed_quantity": {"value": "3"},
            "remaining_quantity": {"value": "7"},
        })
        self.assertEqual(state, {"status": "ORDER_STATUS_PARTIALLY_FILLED",
                                 "executed": 3, "remaining": 7})


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
