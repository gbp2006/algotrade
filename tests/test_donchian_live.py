"""Тест живого сигнала Donchian: совпадение с бэктестом и protect от look-ahead."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.configs import Config  # noqa: E402
from algo.live import decision, decision_configs  # noqa: E402
from algo.strategies.candidates import donchian  # noqa: E402


def series() -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    days = pd.bdate_range("2026-09-01", periods=40)
    idx = pd.DatetimeIndex([d + pd.Timedelta(hours=13, minutes=55) for d in days])
    close = pd.Series(np.linspace(10.0, 20.0, len(idx)), index=idx)
    df = pd.DataFrame({"open": close, "high": close, "low": close,
                       "close": close, "vol": 100.0}, index=idx)
    return df, days


class TestDonchianLive(unittest.TestCase):
    def setUp(self):
        self.df, self.days = series()
        self.cfg = Config("d20-test", "donchian",
                          dict(entry=20, exit=10, entry_time="13:55",
                               allow_short=True),
                          "test", "test", instrument="CNY")

    def test_decision_matches_backtest(self):
        targets = donchian(self.df)
        for n in (25, 30, 35):
            day = self.days[n].date()
            ts = pd.Timestamp(day) + pd.Timedelta(hours=13, minutes=55)
            dec = decision(self.cfg, self.df, day)
            self.assertIsNotNone(dec)
            self.assertEqual(dec.target, int(targets.loc[ts]))
        self.assertEqual(decision(self.cfg, self.df, self.days[30].date()).target, 1)

    def test_no_future_day_used(self):
        # отрезаем все бары после дня решения — результат не должен измениться
        day = self.days[30].date()
        full = decision(self.cfg, self.df, day)
        cut = self.df[self.df.index.normalize() <= pd.Timestamp(day)]
        self.assertEqual(decision(self.cfg, cut, day).target, full.target)

    def test_in_decision_configs(self):
        self.assertIn(self.cfg, decision_configs([self.cfg]))


if __name__ == "__main__":
    unittest.main()
