"""Тесты выбора ноги и перекладки квартальных контрактов. ./run.sh test"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import rollover as r  # noqa: E402


class TestRollover(unittest.TestCase):
    def setUp(self):
        self.day = dt.date(2026, 11, 23)
        self.contracts = {
            "RIZ6@RTSX": "2026-12-17",
            "RIH7@RTSX": "2027-03-18",
        }
        # VOL до 23.11 включительно: ликвидность ещё в Z6
        idx = pd.to_datetime(["2026-11-18", "2026-11-19", "2026-11-20",
                              "2026-11-21", "2026-11-22", "2026-11-23"])
        self.vol = pd.DataFrame({
            "RIZ6@RTSX": [100, 110, 105, 100, 95, 5],
            "RIH7@RTSX": [10, 12, 15, 20, 25, 900],
        }, index=idx)

    def test_days_to_expiry(self):
        self.assertEqual(r.days_to_expiry(self.day, "2026-12-17"), 24)
        self.assertEqual(r.days_to_expiry(self.day, "2027-03-18"), 115)

    def test_front_uses_only_prior_volume(self):
        # 23.11 у H7 огромный VOL, но он из будущего относительно решения
        self.assertEqual(r.front_on(self.day, self.contracts, self.vol),
                         "RIZ6@RTSX")
        nxt = dt.date(2026, 11, 24)
        self.assertEqual(r.front_on(nxt, self.contracts, self.vol),
                         "RIH7@RTSX")

    def test_front_fallback_nearest(self):
        self.assertEqual(r.front_on(self.day, self.contracts, None),
                         "RIZ6@RTSX")

    def test_no_roll_when_front_same(self):
        self.assertIsNone(r.roll_decision(
            self.day, "RIZ6@RTSX", 3, self.contracts, self.vol))

    def test_roll_on_volume_shift(self):
        nxt = dt.date(2026, 11, 24)
        dec = r.roll_decision(nxt, "RIZ6@RTSX", 3, self.contracts, self.vol)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.next_symbol, "RIH7@RTSX")
        self.assertEqual(dec.reason, "переход ликвидности")
        self.assertEqual(len(dec.roll_id), 12)

    def test_force_before_expiry(self):
        # за 3 дня до экспирации, VOL ещё в старой ноге
        day = dt.date(2026, 12, 14)
        dec = r.roll_decision(day, "RIZ6@RTSX", 2, self.contracts,
                              self.vol.iloc[:-1], force_before_expiry=5)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.next_symbol, "RIH7@RTSX")
        self.assertIn("экспирации", dec.reason)

    def test_perpetual_and_empty(self):
        self.assertIsNone(r.roll_decision(
            self.day, "CNYRUBF@RTSX", 32, self.contracts, policy="volume"))
        self.assertIsNone(r.roll_decision(
            self.day, "RIZ6@RTSX", 0, self.contracts, self.vol))
        self.assertIsNone(r.roll_decision(
            self.day, "RIZ6@RTSX", 3, self.contracts, policy="never"))

    def test_plan_roll_long(self):
        dec = r.roll_decision(dt.date(2026, 11, 24), "RIZ6@RTSX", 3,
                              self.contracts, self.vol)
        legs = r.plan_roll(dec, 89300.0, 89500.0)
        self.assertEqual(len(legs), 2)
        self.assertEqual(legs[0].symbol, "RIZ6@RTSX")
        self.assertEqual(legs[0].side, "sell")
        self.assertEqual(legs[1].symbol, "RIH7@RTSX")
        self.assertEqual(legs[1].side, "buy")
        self.assertEqual(legs[0].qty, legs[1].qty)
        self.assertEqual(legs[0].roll_id, legs[1].roll_id)

    def test_plan_roll_short_and_ratio(self):
        dec = r.roll_decision(dt.date(2026, 11, 24), "RIZ6@RTSX", -2,
                              self.contracts, self.vol)
        legs = r.plan_roll(dec, 89300.0, 89500.0, ratio=2.0)
        self.assertEqual(legs[0].side, "buy")
        self.assertEqual(legs[1].side, "sell")
        self.assertEqual(legs[1].qty, 4)


if __name__ == "__main__":
    unittest.main()
