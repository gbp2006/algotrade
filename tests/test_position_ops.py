"""Ручные операции не работают с виртуальным счётом."""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.broker import position_ops as pos  # noqa: E402


class FakeStore:
    def __init__(self, mode: str):
        self.inst = {"id": "r-1", "mode": "live", "account": "A1",
                     "instrument": "CNY", "key_ref": "", "params_json": "{}"}
        self.acc = {"id": "A1", "mode": mode, "enabled": 1,
                    "max_exposure": 1.0, "max_qty": 100}

    def get_instance(self, iid):
        return self.inst if iid == self.inst["id"] else None

    def list_accounts(self):
        return [self.acc]

    def get_runtime(self, iid):
        return {}


class TestContext(unittest.TestCase):
    def test_virtual_account_rejected(self):
        with self.assertRaisesRegex(pos.OpError, "виртуальный или выключен"):
            pos._context(FakeStore("TEST"), "r-1")

    def test_live_account_passes_guard(self):
        # Дальше будет запрос equity брокера — проверяем, что guarded-часть пройдена.
        class LiveStore(FakeStore):
            def __init__(self):
                super().__init__("LIVE")

        with mock.patch.object(pos, "account_equity", return_value=100_000), \
             mock.patch.object(pos, "resolve_secret", return_value="x"), \
             mock.patch.object(pos, "FinamBroker") as broker:
            ctx = pos._context(LiveStore(), "r-1")
        self.assertEqual(ctx["acc_id"], "A1")
        broker.assert_called_once()


class FakeQuote:
    last, ask, bid = 12.29, 12.291, 12.289
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()


class FakeBroker:
    def __init__(self, positions: dict[str, int]):
        self.positions = positions
        self.sent: list[dict] = []
        self.fail_account = False

    def account(self, account=None):
        if self.fail_account:
            raise RuntimeError("брокер недоступен")
        return {"equity": 200_000.0,
                "positions": [{"symbol": s, "quantity": q}
                              for s, q in self.positions.items()]}

    def quote(self, symbol):
        return FakeQuote()

    def place_limit(self, symbol, side, qty, price, account, client_id):
        self.sent.append({"symbol": symbol, "side": side, "qty": qty,
                          "price": price, "account": account, "client_id": client_id})
        return {"order_id": "ord-1", "status": "NEW"}


class CloseStore:
    def __init__(self, accounts: list[dict], positions: dict[str, int],
                 instances: list[dict] | None = None):
        self.accounts = accounts
        self.instances = instances or []
        self.brokers = {a["id"]: FakeBroker(positions) for a in accounts}
        self.runtime: dict[str, dict] = {}

    def get_account(self, iid):
        return next((a for a in self.accounts if str(a["id"]) == str(iid)), None)

    def list_accounts(self):
        return self.accounts

    def get_instance(self, iid):
        return next((i for i in self.instances if i["id"] == iid), None)

    def get_runtime(self, iid):
        return {}

    def set_runtime(self, iid, data):
        self.runtime[iid] = data

    def list_instances(self, mode=None, status=None):
        return self.instances


@contextmanager
def close_env(store: CloseStore):
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(pos, "LIVE", Path(tmp) / "live.csv"), \
             mock.patch.object(pos, "resolve_secret", return_value="x"), \
             mock.patch.object(pos, "account_equity", return_value=200_000.0), \
             mock.patch.object(pos, "FinamBroker",
                               side_effect=lambda secret, account: store.brokers[account]):
            yield


def live_account(acc_id="A1", **extra):
    return {"id": acc_id, "mode": "LIVE", "enabled": 1, "max_exposure": 1.0,
            "max_qty": 100, "key_ref": f"acc:{acc_id}", **extra}


class TestCloseAll(unittest.TestCase):
    def test_closes_only_selected_account_and_skips_fund(self):
        store = CloseStore([live_account(), live_account("A2")],
                           {"CNYRUBF@RTSX": 3, "SiZ6@RTSX": -2, "FMMM@MISX": 5})
        with close_env(store):
            res = pos.close_all(store, "A1")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["account"], "A1")
        self.assertEqual(res["closed"], 2)
        self.assertEqual(res["errors"], [])
        self.assertEqual([i["symbol"] for i in res["skipped"]], ["FMMM@MISX"])
        self.assertEqual(len(store.brokers["A1"].sent), 2)
        self.assertEqual(store.brokers["A2"].sent, [])
        self.assertEqual({i["symbol"] for i in store.brokers["A1"].sent},
                         {"CNYRUBF@RTSX", "SiZ6@RTSX"})

    def test_stop_real_does_not_block_closing(self):
        store = CloseStore([live_account()], {"CNYRUBF@RTSX": 2})
        stopped = SimpleNamespace(exists=lambda: True)
        with close_env(store), mock.patch.object(pos, "STOP_REAL", stopped):
            res = pos.close_all(store, "A1")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["closed"], 1)
        self.assertEqual(len(store.brokers["A1"].sent), 1)

    def test_entry_limits_do_not_block_closing(self):
        store = CloseStore([live_account(max_exposure=0.01, max_qty=1)],
                           {"CNYRUBF@RTSX": 10})
        with close_env(store):
            res = pos.close_all(store, "A1")
        self.assertTrue(res["ok"], res)
        self.assertEqual(store.brokers["A1"].sent[0]["qty"], 10)

    def test_errors_are_visible_in_response(self):
        store = CloseStore([live_account()], {"CNYRUBF@RTSX": 2})
        store.brokers["A1"].fail_account = True
        with close_env(store):
            res = pos.close_all(store, "A1")
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("брокер недоступен", res["errors"][0]["reason"])

    def test_paper_account_rejected(self):
        store = CloseStore([live_account(mode="TEST")], {})
        with self.assertRaisesRegex(pos.OpError, "только на реальном"):
            pos.close_all(store, "A1")


class TestCloseAllEndpoint(unittest.TestCase):
    def test_account_is_required(self):
        from fastapi import HTTPException
        from web import instances_api as api

        with self.assertRaises(HTTPException):
            api.close_all_positions({}, FakeStore("LIVE"))

    def test_selected_account_is_passed_to_service(self):
        from web import instances_api as api

        store = FakeStore("LIVE")
        with mock.patch.object(api.pos, "close_all", return_value={"ok": True}) as service, \
             mock.patch.object(api, "invalidate_analytics"):
            result = api.close_all_positions({"account": "A1"}, store)
        service.assert_called_once_with(store, "A1")
        self.assertTrue(result["ok"])


class TestCloseInstance(unittest.TestCase):
    def test_closes_without_typeerror(self):
        inst = {"id": "r-1", "mode": "live", "account": "A1",
                "instrument": "CNY", "key_ref": "", "params_json": "{}"}
        store = CloseStore([live_account()], {"CNYRUBF@RTSX": 3}, [inst])
        with close_env(store):
            res = pos.close_instance(store, "r-1", dry_run=False)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["status"], "sent")
        self.assertEqual(len(store.brokers["A1"].sent), 1)
        self.assertEqual(store.runtime["r-1"]["position"], 0)

    def test_no_position_is_a_noop(self):
        inst = {"id": "r-1", "mode": "live", "account": "A1",
                "instrument": "CNY", "key_ref": "", "params_json": "{}"}
        store = CloseStore([live_account()], {}, [inst])
        with close_env(store):
            res = pos.close_instance(store, "r-1", dry_run=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["closed"], 0)
        self.assertEqual(store.brokers["A1"].sent, [])


if __name__ == "__main__":
    unittest.main()
