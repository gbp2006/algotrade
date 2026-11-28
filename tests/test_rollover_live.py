"""Тесты хелперов раннера перекладки (без сети). ./run.sh test"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import sys
import unittest
from unittest import mock
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import instruments as inst_mod  # noqa: E402
from algo import rollover_integration as ri  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rollover_live", ROOT / "scripts" / "35_rollover_live.py")
rl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rl)


class FakeBroker:
    def __init__(self, frames):
        self.frames = frames

    def bars(self, symbol, timeframe, start, end):
        return self.frames.get(symbol)


class TestRolloverRunnerSafety(unittest.TestCase):
    def test_no_equity_skips_roll(self):
        import json
        import tempfile
        from algo import live_config as lc
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            settings = lc.parse_settings({
                "accounts": {"A1": {}},
                "robots": {"r1": {"account": "A1", "pricing": "marketable"}}})

            class Broker:
                def account(self, acc=None):
                    return {"positions": []}

            patches = [
                mock.patch.object(rl, "LIVE", d / "live.csv"),
                mock.patch.object(rl, "SUMMARY", d / "rollover_run.json"),
                mock.patch.object(rl, "STOP", d / "STOP"),
                mock.patch.object(rl, "STOP_REAL", d / "STOP_REAL"),
                mock.patch.object(rl, "journal_positions",
                                  lambda account, journal=None: ({}, 0)),
                mock.patch.object(rl, "FinamBroker", lambda: Broker()),
                mock.patch.object(rl, "live_settings_from_store", lambda: settings),
                mock.patch.object(rl, "account_equity", lambda broker, acc: 0),
            ]
            for p in patches:
                p.start()
            try:
                self.assertEqual(rl.main([]), 0)
            finally:
                for p in reversed(patches):
                    p.stop()
            data = json.loads((d / "rollover_run.json").read_text(encoding="utf-8"))
            self.assertTrue(any("нет equity" in n for n in data["notes"]))
            self.assertEqual(data["results"], {})
            self.assertFalse((d / "live.lock").exists())

    def test_reconcile_uses_journal_model_not_broker(self):
        import json
        import tempfile
        from algo import live_config as lc
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            settings = lc.parse_settings({
                "accounts": {"A1": {}},
                "robots": {"r1": {"account": "A1", "pricing": "marketable"}},
            })

            class Broker:
                def account(self, acc=None):
                    return {"positions": []}

            seen = []

            def guard(broker, model, **kw):
                seen.append((dict(model), kw))
                return ["расхождение CNY"]

            patches = [
                mock.patch.object(rl, "LIVE", d / "live.csv"),
                mock.patch.object(rl, "SUMMARY", d / "rollover_run.json"),
                mock.patch.object(rl, "STOP", d / "STOP"),
                mock.patch.object(rl, "STOP_REAL", d / "STOP_REAL"),
                mock.patch.object(rl, "journal_positions",
                                  lambda account, journal=None: ({"CNYRUBF@RTSX": 2}, 0)),
                mock.patch.object(rl, "reconcile_guard", side_effect=guard),
                mock.patch.object(rl, "FinamBroker", lambda: Broker()),
                mock.patch.object(rl, "live_settings_from_store", lambda: settings),
                mock.patch.object(rl, "account_equity", lambda broker, acc: 0),
            ]
            for p in patches:
                p.start()
            try:
                self.assertEqual(rl.main([]), 0)
            finally:
                for p in reversed(patches):
                    p.stop()
            data = json.loads((d / "rollover_run.json").read_text(encoding="utf-8"))

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], {"CNYRUBF@RTSX": 2})
        self.assertFalse(seen[0][1]["enforce"])  # перекладка не выставляет STOP
        self.assertTrue(any("расхождение CNY" in n for n in data["notes"]))


class TestActiveContracts(unittest.TestCase):
    def test_perpetual(self):
        out = inst_mod.active_contracts(inst_mod.INSTRUMENTS["CNY"], dt.date(2026, 11, 23))
        self.assertEqual(list(out), ["CNYRUBF@RTSX"])
        self.assertEqual(out["CNYRUBF@RTSX"], "2099-12-31")

    def test_quarterly_from_iss(self):
        rows = [
            {"ASSETCODE": "RTS", "SECID": "RIZ6", "LASTTRADEDATE": "2026-12-17"},
            {"ASSETCODE": "RTS", "SECID": "RIH7", "LASTTRADEDATE": "2027-03-18"},
            {"ASSETCODE": "RTS", "SECID": "RIH6", "LASTTRADEDATE": "2026-03-19"},
        ]
        orig = inst_mod._fetch
        inst_mod._fetch = lambda: rows
        try:
            out = inst_mod.active_contracts(
                inst_mod.INSTRUMENTS["RTS"], dt.date(2026, 11, 23))
            self.assertEqual(set(out), {"RIZ6@RTSX", "RIH7@RTSX"})
        finally:
            inst_mod._fetch = orig

    def test_instrument_for(self):
        by_inst = {inst_mod.INSTRUMENTS["CNY"]: {"CNYRUBF@RTSX": "2099-12-31"},
                   inst_mod.INSTRUMENTS["RTS"]: {"RIZ6@RTSX": "2026-12-17"}}
        self.assertIs(rl.instrument_for("RIZ6@RTSX", by_inst),
                      inst_mod.INSTRUMENTS["RTS"])
        self.assertIsNone(rl.instrument_for("UNKNOWN", by_inst))

    def test_flag_gate(self):
        day = dt.date(2026, 11, 23)
        inst = inst_mod.INSTRUMENTS["RTS"]
        with mock.patch.dict(os.environ, {ri.FLAG: "0"}):
            self.assertEqual(ri.front_symbol(inst, day), inst_mod.symbol(inst, day))
            self.assertIsNone(ri.decision_for_position(
                day, "RIZ6@RTSX", 2, inst))
        with mock.patch.dict(os.environ, {ri.FLAG: "1"}):
            self.assertTrue(ri.enabled())

    def test_volumes_for(self):
        idx = pd.to_datetime(["2026-11-20", "2026-11-21", "2026-11-22"])
        frames = {
            "RIZ6@RTSX": pd.DataFrame({"vol": [100, 120, 110]}, index=idx),
            "RIH7@RTSX": pd.DataFrame({"vol": [10, 12, 15]}, index=idx),
        }
        v = rl.volumes_for(FakeBroker(frames), list(frames), dt.date(2026, 11, 23))
        self.assertEqual(list(v.columns), ["RIZ6@RTSX", "RIH7@RTSX"])
        self.assertEqual(len(v), 3)

    def test_volumes_fallback_to_m5(self):
        idx = pd.to_datetime(["2026-11-21", "2026-11-22"])
        frames = {"RIZ6@RTSX": pd.DataFrame({"vol": [100, 120]}, index=idx)}

        class Broker:
            def bars(self, symbol, timeframe, start, end):
                if timeframe == "TIME_FRAME_D1":
                    return pd.DataFrame()
                return frames.get(symbol)

        v = ri.volumes_for(Broker(), ["RIZ6@RTSX"], dt.date(2026, 11, 23))
        self.assertIsNotNone(v)
        self.assertEqual(int(v["RIZ6@RTSX"].sum()), 220)


if __name__ == "__main__":
    unittest.main()
