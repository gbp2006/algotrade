"""Боевой раннер: сбой одного счёта не останавливает остальные. ./run.sh test"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import live_config as lc  # noqa: E402
from algo.broker import execution as ex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "live_runner_34", ROOT / "scripts" / "34_live_execute.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class FakeBroker:
    def account(self, account=None):
        return {"equity": 200_000.0, "positions": []}


class BrokerFactory:
    """Первый счёт без ключа, второй — доступен."""

    @staticmethod
    def service():
        return object()

    def __new__(cls, secret=None, account=None):
        if account == "A1":
            raise RuntimeError("нет ключа")
        return FakeBroker()


class FakeGateway:
    seen: list[str] = []

    def __init__(self, broker, limits=None, journal=None, **kw):
        pass

    def submit(self, order, account=None, **kw):
        self.seen.append(account or order.account)
        return ex.Result("sent", "", {"order_id": "o-1"}, "cid", "o-1")


class TestAccountIsolation(unittest.TestCase):
    def test_bad_key_skips_only_that_account(self):
        settings = lc.parse_settings({
            "defaults": {"pricing": "signal"},
            "accounts": {"A1": {}, "A2": {}},
            "robots": {"r1": {"account": "A1"}, "r2": {"account": "A2"}},
        })
        plan = {"target": 1, "price": 12.29, "robots": ["r1"],
                "pricings": {"signal"}, "expiry": True,
                "exposures": [2.0], "when": "13:50"}
        plans = {("A1", ""): {"CNYRUBF@RTSX": dict(plan, robots=["r1"])},
                 ("A2", ""): {"CNYRUBF@RTSX": dict(plan, robots=["r2"])}}
        FakeGateway.seen = []
        stopped = SimpleNamespace(exists=lambda: False)

        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "live_run.json"
            patches = (
                mock.patch.object(mod, "STOP", stopped),
                mock.patch.object(mod, "STOP_REAL", stopped),
                mock.patch.object(mod, "assert_stop_clear", lambda stop=None: None),
                mock.patch.object(mod, "live_settings_from_store", return_value=settings),
                mock.patch.object(mod, "collect_signals", return_value=(plans, [], [])),
                mock.patch.object(mod, "FinamBroker", BrokerFactory),
                mock.patch.object(mod, "account_equity", return_value=200_000.0),
                mock.patch.object(mod, "journal_positions", return_value=({}, 0)),
                mock.patch.object(mod, "reconcile_guard", return_value=[]),
                mock.patch.object(mod, "broker_positions", return_value={}),
                mock.patch.object(mod, "expiry_ok", return_value=True),
                mock.patch.object(mod.tj, "refresh_executions",
                                  return_value={"updated": 0, "checked": 0, "details": {}}),
                mock.patch.object(mod, "sync_live_runtime", return_value=[]),
                mock.patch.object(mod, "RobotStore",
                                  return_value=SimpleNamespace()),
                mock.patch.object(mod, "OrderGateway", FakeGateway),
                mock.patch.object(mod, "SUMMARY", summary),
            )
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                rc = mod.main([])
            data = json.loads(summary.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(FakeGateway.seen, ["A2"])  # первый счёт пропущен
        self.assertTrue(any("ключ счёта недоступен" in n for n in data["notes"]))


if __name__ == "__main__":
    unittest.main()
