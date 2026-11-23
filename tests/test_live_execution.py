"""Тесты боевого контура без сети: цены, экспирация, настройки, счета. ./run.sh test"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.broker import execution as ex  # noqa: E402
from algo.broker import live_guard as lg  # noqa: E402
from algo import live_config as lc  # noqa: E402


class Quote:
    def __init__(self, bid, ask, last, age_sec=5):
        self.bid, self.ask, self.last = bid, ask, last
        self.timestamp = (datetime.now(timezone.utc) - timedelta(seconds=age_sec)).isoformat()


class FakeBroker:
    def __init__(self, positions=None):
        self.positions = positions or []
        self.calls = []

    def account(self, account=None):
        return {"positions": self.positions}

    def quote(self, symbol):
        return Quote(12.20, 12.30, 12.25)

    def place_limit(self, symbol, side, qty, price, account=None, client_order_id=None):
        self.calls.append(("limit", symbol, side, qty, price, account, client_order_id))
        return {"order_id": "1"}

    def place_market(self, symbol, side, qty, account=None, client_order_id=None):
        self.calls.append(("market", symbol, side, qty, account, client_order_id))
        return {"order_id": "2"}


class TestPricing(unittest.TestCase):
    def test_parse_and_round(self):
        self.assertIs(lg.parse_pricing("MARKET"), lg.PricingMode.MARKET)
        self.assertEqual(lg.round_to_tick(12.3004, 0.001), 12.3)
        self.assertEqual(lg.round_to_tick(89314.6, 1.0), 89315.0)
        with self.assertRaises(ex.ExecutionError):
            lg.parse_pricing("unknown")

    def test_three_modes(self):
        q = Quote(12.20, 12.30, 12.25)
        price, typ, _ = lg.price_for(lg.PricingMode.SIGNAL, 12.298, "buy", q, 0.001)
        self.assertEqual((price, typ), (12.298, "limit"))
        price, typ, _ = lg.price_for(lg.PricingMode.MARKETABLE, 12.298, "buy", q, 0.001)
        self.assertEqual((price, typ), (12.301, "limit"))
        price, typ, _ = lg.price_for(lg.PricingMode.MARKETABLE, 12.298, "sell", q, 0.001)
        self.assertEqual((price, typ), (12.199, "limit"))
        price, typ, _ = lg.price_for(lg.PricingMode.MARKET, 12.298, "buy", q, 0.001)
        self.assertEqual(typ, "market")

    def test_quote_age(self):
        self.assertLess(lg.quote_age_sec(Quote(1, 2, 1, age_sec=5)), 10)
        self.assertGreater(lg.quote_age_sec(Quote(1, 2, 1, age_sec=120)), 100)
        self.assertIsNone(lg.quote_age_sec(object()))


class TestExpiry(unittest.TestCase):
    def test_third_thursday(self):
        self.assertEqual(lg.third_thursday(2026, 3), date(2026, 3, 19))
        self.assertEqual(lg.third_thursday(2026, 6), date(2026, 6, 18))
        self.assertTrue(lg.is_expiry_day(date(2026, 3, 19)))
        self.assertFalse(lg.is_expiry_day(date(2026, 3, 12)))
        self.assertFalse(lg.is_expiry_day(date(2026, 3, 19), "CNYRUBF@RTSX"))

    def test_toggle(self):
        day, sym = date(2026, 3, 19), "RIZ6@RTSX"
        self.assertFalse(lg.expiry_allows(day, sym, 1, False))   # вход запрещён
        self.assertTrue(lg.expiry_allows(day, sym, -1, False))   # выход разрешён
        self.assertTrue(lg.expiry_allows(day, sym, 1, True))     # тумблер включён


class TestSettings(unittest.TestCase):
    DATA = {
        "defaults": {"pricing": "marketable"},
        "accounts": {"A1": {}},
        "robots": {"p-base": {"account": "A1", "pricing": "signal"}},
    }

    def test_valid(self):
        s = lc.parse_settings(self.DATA)
        self.assertEqual(s.robots["p-base"].pricing, lg.PricingMode.SIGNAL)
        self.assertEqual(s.accounts["A1"].max_exposure, 1.0)

    def test_whitelist_and_bad_account(self):
        bad = dict(self.DATA, robots={"x": {"account": "NOPE"}})
        with self.assertRaises(lc.SettingsError):
            lc.parse_settings(bad)

    def test_missing_file_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = lc.load_settings(Path(tmp) / "none.json")
        self.assertTrue(s.empty)

    def test_bad_pricing(self):
        bad = dict(self.DATA, robots={"p-base": {"account": "A1", "pricing": "x"}})
        with self.assertRaises(lc.SettingsError):
            lc.parse_settings(bad)


class TestSourceConfig(unittest.TestCase):
    def test_live_robot_follows_paper_config(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "live_exec", Path(__file__).resolve().parent.parent /
            "scripts" / "34_live_execute.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        settings = lc.parse_settings({
            "accounts": {"A1": {}},
            "robots": {"live-1": {"account": "A1", "pricing": "marketable",
                                  "source_config": "p-base", "exposure": 2.0}},
        })
        rows = [{"config": "p-base", "symbol": "CNYRUBF@RTSX",
                 "price": "12.3", "target": "32"}]
        plans = mod.plan_targets(rows, settings, date(2026, 11, 23))
        plan = plans[("A1", "")]["CNYRUBF@RTSX"]
        self.assertEqual(plan["target"], 32)
        self.assertEqual(plan["robots"], ["live-1"])
        self.assertEqual(plan["exposures"], [2.0])


class TestMarketOrderGateway(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.broker = FakeBroker()
        self.gw = ex.OrderGateway(
            self.broker, journal=Path(self.tmp.name) / "live.csv",
            lock=Path(self.tmp.name) / "live.lock")

    def test_market_uses_client_id(self):
        order = ex.Order(client_id="p-base:d:buy", config="p-base",
                         symbol="CNYRUBF@RTSX", side="buy", qty=4,
                         price=12.3, order_type="market", account="A1",
                         pricing="market")
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            res = self.gw.submit(order)
        self.assertTrue(res.sent)
        cid = ex.client_order_id("p-base:d:buy")
        self.assertEqual(self.broker.calls,
                         [("market", "CNYRUBF@RTSX", "buy", 4, "A1", cid)])
        row = self.gw._rows()[0]
        self.assertEqual(row["account"], "A1")
        self.assertEqual(row["order_type"], "market")

    def test_log_decision(self):
        order = ex.Order(client_id="p-base:d:buy", config="p-base",
                         symbol="CNYRUBF@RTSX", side="buy", qty=4, price=12.3)
        self.gw.log_decision(order, "skipped", "день экспирации")
        self.assertEqual(self.gw._rows()[0]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
