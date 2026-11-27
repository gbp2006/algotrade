"""Ручные операции не работают с виртуальным счётом."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
