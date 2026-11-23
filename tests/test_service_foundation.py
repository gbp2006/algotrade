"""Тесты фундамента сервиса: адаптеры, библиотека, хранилище. ./run.sh test"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import robot_library as lib  # noqa: E402
from algo import robot_store as store  # noqa: E402
from algo.broker import registry  # noqa: E402
from algo.broker.base import OrderRequest  # noqa: E402
from algo.broker.finam_adapter import FinamAdapter  # noqa: E402


class TestBrokerRegistry(unittest.TestCase):
    def test_finam_registered(self):
        self.assertIn("finam", registry.available())
        with mock.patch.dict(os.environ, {"FINAM_SECRET": "test"}):
            a = registry.get_adapter("finam", account="A1")
        self.assertIsInstance(a, FinamAdapter)
        self.assertEqual(a.name, "finam")
        with self.assertRaises(ValueError):
            registry.get_adapter("unknown")

    def test_place_order_dispatch(self):
        with mock.patch.dict(os.environ, {"FINAM_SECRET": "test"}):
            adapter = FinamAdapter(account="A1")
        calls = []

        def fake_limit(*args):
            calls.append(("limit", args))
            return {"order_id": "42", "status": "NEW"}

        def fake_market(*args):
            calls.append(("market", args))
            return {"order_id": "43", "status": "NEW"}

        adapter.place_limit = fake_limit
        adapter.place_market = fake_market
        r = adapter.place_order(OrderRequest(
            symbol="CNYRUBF@RTSX", side="buy", qty=4, account="A1",
            order_type="market", client_order_id="abc"))
        self.assertEqual(calls[0][0], "market")
        self.assertEqual(r.order_id, "43")
        adapter.place_order(OrderRequest(
            symbol="CNYRUBF@RTSX", side="buy", qty=4, account="A1",
            price=12.3, order_type="limit", client_order_id="abc"))
        self.assertEqual(calls[1][0], "limit")


class TestLibrary(unittest.TestCase):
    def test_specs(self):
        names = {s.id for s in lib.list_specs()}
        self.assertIn("prostushka", names)
        self.assertIn("donchian", names)
        p = lib.get_spec("prostushka")
        self.assertIn("ma_window", p.defaults)
        self.assertGreaterEqual(len(p.examples), 1)

    def test_validate_params(self):
        merged = lib.validate_params("prostushka", {"ma_window": 55})
        self.assertEqual(merged["ma_window"], 55)
        with self.assertRaises(ValueError):
            lib.validate_params("prostushka", {"unknown": 1})
        with self.assertRaises(ValueError):
            lib.validate_params("prostushka", {"ma_window": "many"})


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = store.RobotStore(Path(self.tmp.name) / "robots.db")
        self.db.init_db()

    def test_create_and_read(self):
        self.db.create_account({"id": "A1", "capital": 200000})
        inst = self.db.create_instance({
            "id": "p-test", "spec_id": "prostushka", "instrument": "CNY",
            "params": {"ma_window": 55}, "mode": "paper",
        })
        self.assertEqual(inst["status"], "draft")
        self.assertEqual(inst["params"]["ma_window"], 55)
        self.assertEqual(inst["version"], 1)
        self.assertEqual(len(self.db.history("p-test")), 1)

    def test_lifecycle_and_audit(self):
        self.db.create_instance({"id": "p-test", "spec_id": "prostushka",
                                 "mode": "paper"})
        with self.assertRaises(store.StoreError):
            self.db.set_status("p-test", "paused")  # draft → paused запрещено
        self.db.set_status("p-test", "active")
        self.db.set_status("p-test", "paused")
        self.assertEqual(self.db.get_instance("p-test")["status"], "paused")
        self.db.set_status("p-test", "active")
        self.db.archive("p-test")
        self.assertEqual(self.db.get_instance("p-test")["status"], "archived")
        self.assertGreaterEqual(len(self.db.history("p-test")), 4)

    def test_live_requires_fields(self):
        self.db.create_account({"id": "A1", "capital": 200000})
        with self.assertRaises(store.StoreError):
            self.db.create_instance({"id": "live-bad", "spec_id": "prostushka",
                                     "mode": "live", "status": "active"})
        inst = self.db.create_instance({
            "id": "live-ok", "spec_id": "prostushka", "mode": "live",
            "status": "active", "account": "A1", "pricing": "marketable",
            "capital": 200000,
        })
        self.assertEqual(inst["status"], "active")

    def test_optimistic_lock_and_auto_pause(self):
        self.db.create_instance({"id": "p-test", "spec_id": "prostushka",
                                 "mode": "paper", "status": "active"})
        with self.assertRaises(store.ConflictError):
            self.db.update_instance("p-test", {"params": {"ma_window": 10}}, 99)
        upd = self.db.update_instance(
            "p-test", {"params": {"ma_window": 10}}, 1, reason="тест")
        self.assertEqual(upd["status"], "paused")   # правка активного → пауза
        self.assertEqual(upd["version"], 2)
        self.assertEqual(upd["params"]["ma_window"], 10)


if __name__ == "__main__":
    unittest.main()
