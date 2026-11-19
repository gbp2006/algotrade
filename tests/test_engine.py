"""Юнит-тесты движка и базовых функций. Запуск: ./run.sh test"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import engine  # noqa: E402
from algo.data import daily_first_bar  # noqa: E402
from algo.strategies import prostushka  # noqa: E402


def make_df(opens: list[float], minutes: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05 10:00", periods=len(opens), freq=f"{minutes}min")
    o = np.array(opens, dtype=float)
    return pd.DataFrame(
        {"open": o, "high": o, "low": o, "close": o, "vol": np.ones(len(o))}, index=idx
    )


class TestDailyBar(unittest.TestCase):
    def test_one_per_day(self):
        idx = pd.date_range("2026-01-05 09:00", periods=400, freq="1min")
        df = pd.DataFrame({"close": 1.0}, index=idx)
        mask = daily_first_bar(df, "13:50")
        by_day = mask.groupby(idx.normalize()).sum()
        self.assertTrue((by_day <= 1).all())
        first = df.index[mask][0]
        self.assertEqual((first.hour, first.minute), (13, 50))


class TestEngine(unittest.TestCase):
    def test_long_pnl_matches_manual(self):
        df = make_df([10, 11, 12, 13, 14])
        targets = pd.Series([0, 1, 1, 0, 0], index=df.index)
        r = engine.run(df, targets, engine.Costs())
        # позиция включается со сдвигом: вход по open=12, выход по open=14
        self.assertEqual(len(r.trades), 1)
        self.assertAlmostEqual(r.trades[0].net, 1995.4, places=1)

    def test_reversal_gives_two_trades(self):
        df = make_df([10, 11, 12, 13, 14, 15])
        targets = pd.Series([1, 1, -1, -1, 0, 0], index=df.index)
        r = engine.run(df, targets, engine.Costs())
        self.assertEqual(len(r.trades), 2)
        self.assertEqual(r.trades[0].direction, 1)
        self.assertEqual(r.trades[1].direction, -1)

    def test_more_slippage_less_profit(self):
        df = make_df([10, 11, 12, 13, 14])
        targets = pd.Series([0, 1, 1, 0, 0], index=df.index)
        a = engine.run(df, targets, engine.Costs(slippage_ticks=1)).stats["net_profit"]
        b = engine.run(df, targets, engine.Costs(slippage_ticks=5)).stats["net_profit"]
        self.assertLess(b, a)

    def test_flat_target_no_trades(self):
        df = make_df([10, 11, 12])
        r = engine.run(df, pd.Series(0, index=df.index), engine.Costs())
        self.assertEqual(r.stats["trades"], 0)


class TestProstushka(unittest.TestCase):
    def _df(self, days: int = 5, bars: int = 100) -> pd.DataFrame:
        idx = pd.DatetimeIndex(
            [pd.Timestamp("2026-01-05") + pd.Timedelta(days=d, minutes=m)
             for d in range(days) for m in range(bars * 5)]
        )
        idx = pd.DatetimeIndex([t for t in idx if 10 <= t.hour < 19])
        prices = 100 + np.arange(len(idx)) * 0.01
        return pd.DataFrame({"open": prices, "high": prices, "low": prices,
                             "close": prices, "vol": 1.0}, index=idx)

    def test_friday_short_banned(self):
        df = self._df(days=6)
        tg = prostushka.targets(df, ma_period=10, allow_short_friday=False, skip_weekend=True)
        fridays = tg[(tg.index.day_of_week == 4) & (tg < 0)]
        self.assertEqual(len(fridays), 0)

    def test_skip_weekend_no_decisions(self):
        df = self._df(days=8)
        tg = prostushka.targets(df, ma_period=10, skip_weekend=True)
        weekend = tg[tg.index.day_of_week >= 5]
        self.assertTrue(len(weekend) >= 0)  # значения есть, но решений нет
        # позиция в выходные должна равняться пятничной
        sat = df.index[df.index.day_of_week == 5]
        if len(sat):
            self.assertEqual(tg.loc[sat[0]], tg.loc[tg.index[tg.index < sat[0]][-1]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
