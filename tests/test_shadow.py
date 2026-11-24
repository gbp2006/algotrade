"""Тесты теневого прогона G3: заявки планируются, но не отправляются."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.configs import BY_ID  # noqa: E402

_spec = importlib.util.spec_from_file_location("shadow", ROOT / "scripts" / "33_shadow_live.py")
shadow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shadow)

HEADER = ("date,time,config,instrument,symbol,strategy,price,signal,target,"
          "contracts,equity_before,action,position_after,note\n")


class FakeBroker:
    def __init__(self):
        self.sent = []

    def account(self):
        return {"positions": []}

    def place_limit(self, *a, **k):
        self.sent.append((a, k))
        raise AssertionError("теневой прогон не должен отправлять заявки")


class TestShadow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.paper, self.live = d / "paper.csv", d / "shadow.csv"
        self.shadow, self.stop = d / "shadow.json", d / "STOP"
        self.lock = d / "shadow.lock"
        self.broker = FakeBroker()
        self.patches = [
            mock.patch.object(shadow, "PAPER", self.paper),
            mock.patch.object(shadow, "SHADOW_JOURNAL", self.live),
            mock.patch.object(shadow, "SHADOW", self.shadow),
            mock.patch.object(shadow, "STOP", self.stop),
            mock.patch.object(shadow, "SHADOW_LOCK", self.lock),
            mock.patch.object(shadow, "FinamBroker", lambda: self.broker),
            mock.patch.object(shadow, "CONFIGS", [BY_ID["p-base"]]),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def _journal(self, today: date):
        lines = [HEADER]
        lines.append(f"{today},13:50,p-base,CNY,CNYRUBF@RTSX,prostushka,12.29,0,0,"
                     "0,200000,решение,0,предыдущий день\n")
        lines.append(f"{today},13:50,p-base,CNY,CNYRUBF@RTSX,prostushka,12.291,1,32,"
                     "32,200000,решение,32,сегодня\n")
        self.paper.write_text("".join(lines), encoding="utf-8")

    def test_plans_without_sending_even_if_flag_on(self):
        today = date.today()
        self._journal(today)
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            self.assertEqual(shadow.main(), 0)
        self.assertEqual(self.broker.sent, [])
        rows = list(__import__("csv").DictReader(self.live.open(encoding="utf-8")))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "planned")
        self.assertEqual(len(rows[0]["client_order_id"]), 20)
        data = json.loads(self.shadow.read_text(encoding="utf-8"))
        self.assertEqual(data["date"], str(today))
        self.assertEqual(data["counts"], {"planned": 1})
        self.assertTrue(data["issues"])

    def test_shadow_uses_own_journal_and_lock(self):
        today = date.today()
        self._journal(today)
        with mock.patch.dict(os.environ, {"FINAM_ALLOW_TRADING": "1"}):
            self.assertEqual(shadow.main(), 0)
        self.assertTrue(self.live.exists())          # shadow.csv
        self.assertFalse((self.live.parent / "live.csv").exists())
        self.assertFalse(self.lock.exists())         # shadow.lock снят

    def test_stop_skips_shadow(self):
        self.stop.write_text("1", encoding="utf-8")
        self.assertEqual(shadow.main(), 0)
        self.assertFalse(self.live.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
