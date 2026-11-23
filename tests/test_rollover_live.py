"""Тесты хелперов раннера перекладки (без сети). ./run.sh test"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import instruments as inst_mod  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rollover_live", ROOT / "scripts" / "35_rollover_live.py")
rl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rl)


class FakeBroker:
    def __init__(self, frames):
        self.frames = frames

    def bars(self, symbol, timeframe, start, end):
        return self.frames.get(symbol)


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

    def test_volumes_for(self):
        idx = pd.to_datetime(["2026-11-20", "2026-11-21", "2026-11-22"])
        frames = {
            "RIZ6@RTSX": pd.DataFrame({"vol": [100, 120, 110]}, index=idx),
            "RIH7@RTSX": pd.DataFrame({"vol": [10, 12, 15]}, index=idx),
        }
        v = rl.volumes_for(FakeBroker(frames), list(frames), dt.date(2026, 11, 23))
        self.assertEqual(list(v.columns), ["RIZ6@RTSX", "RIH7@RTSX"])
        self.assertEqual(len(v), 3)


if __name__ == "__main__":
    unittest.main()
