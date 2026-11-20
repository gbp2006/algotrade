"""Тесты клиента Finam: блокировка торгов, ретраи, разбор ответов. ./run.sh test"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.broker import finam as fb  # noqa: E402


class Resp:
    def __init__(self, status: int, payload=None, text: str = ""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def broker() -> fb.FinamBroker:
    return fb.FinamBroker(secret="test-secret", account="123")


class TestBrokerGuard(unittest.TestCase):
    def test_secret_required(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(fb.FinamError):
                fb.FinamBroker()

    def test_place_market_blocked_by_default(self):
        b = broker()
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "0"}), \
             mock.patch.object(b, "_call") as call:
            with self.assertRaisesRegex(fb.FinamError, "выключена"):
                b.place_market("X@RTSX", "buy", 1)
            call.assert_not_called()

    def test_place_market_payload(self):
        b = broker()
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}), \
             mock.patch.object(b, "_call", return_value={"orderId": "42"}) as call:
            out = b.place_market("X@RTSX", "sell", 3)
        self.assertEqual(out["orderId"], "42")
        method, path = call.call_args.args
        body = call.call_args.kwargs["body"]
        self.assertEqual((method, path), ("POST", "/v1/accounts/123/orders"))
        self.assertEqual(body["symbol"], "X@RTSX")
        self.assertEqual(body["quantity"], {"value": "3"})
        self.assertEqual(body["side"], "SIDE_SELL")
        self.assertEqual(body["type"], "ORDER_TYPE_MARKET")


class TestTransport(unittest.TestCase):
    def test_retry_on_429(self):
        b = broker()
        with mock.patch.object(fb.requests, "post", return_value=Resp(200, {"token": "t"})), \
             mock.patch.object(fb.requests, "request",
                               side_effect=[Resp(429), Resp(200, {"ok": 1})]) as req, \
             mock.patch.object(fb.time, "sleep"):
            self.assertEqual(b._call("GET", "/p"), {"ok": 1})
        self.assertEqual(req.call_count, 2)

    def test_reauth_on_401(self):
        b = broker()
        with mock.patch.object(fb.requests, "post",
                               return_value=Resp(200, {"token": "t"})) as auth, \
             mock.patch.object(fb.requests, "request",
                               side_effect=[Resp(401), Resp(200, {})]):
            b._call("GET", "/p")
        self.assertEqual(auth.call_count, 2, "после 401 токен должен обновиться")

    def test_quote_parsing(self):
        b = broker()
        payload = {"quote": {"bid": {"value": "12.230"}, "ask": 12.235,
                             "last": {"value": "12.234"}, "timestamp": "2026-11-20T14:00:00Z"}}
        with mock.patch.object(b, "_call", return_value=payload):
            q = b.quote("CNYRUBF@RTSX")
        self.assertEqual((q.bid, q.ask, q.last), (12.23, 12.235, 12.234))
        self.assertEqual(q.timestamp, "2026-11-20T14:00:00Z")

    def test_bars_shifted_to_msk(self):
        b = broker()
        payload = {"bars": [{"timestamp": "2026-11-20T10:00:00Z",
                             "open": {"value": "12.2"}, "high": {"value": "12.3"},
                             "low": {"value": "12.1"}, "close": {"value": "12.25"},
                             "volume": {"value": "7"}}]}
        with mock.patch.object(b, "_call", return_value=payload):
            df = b.bars("CNYRUBF@RTSX")
        self.assertEqual(str(df.index[0]), "2026-11-20 13:00:00")
        self.assertEqual(float(df["close"].iloc[0]), 12.25)
        self.assertEqual(float(df["vol"].iloc[0]), 7.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
