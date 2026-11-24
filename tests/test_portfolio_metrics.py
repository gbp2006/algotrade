"""Тесты метрик портфеля: потоки не считаются доходностью. ./run.sh test"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.portfolio_metrics import (  # noqa: E402
    EquityPoint, Trade, METRICS_NA, clean_equity, display, drawdown,
    expectancy, mwr, net_trading_result, profit_factor, sharpe, sortino,
    streaks, summarize, twr, winrate,
)


def with_flow() -> list[EquityPoint]:
    return [
        EquityPoint("2026-01-01", 200_000),
        EquityPoint("2026-01-02", 210_000),
        EquityPoint("2026-01-03", 310_000, cash_flow=100_000),
        EquityPoint("2026-01-04", 320_000),
    ]


class TestPortfolioMetrics(unittest.TestCase):
    def test_clean_equity_removes_deposit(self):
        self.assertEqual(clean_equity(with_flow()), [200_000, 210_000, 210_000, 220_000])
        self.assertEqual(net_trading_result(with_flow()), 20_000)

    def test_twr_ignores_flow(self):
        self.assertAlmostEqual(twr(with_flow()), 0.10, places=6)

    def test_net_trading_pnl_from_source_wins(self):
        points = with_flow()
        points[-1] = EquityPoint("2026-01-04", 320_000, net_trading_pnl=19_500)
        self.assertEqual(net_trading_result(points), 19_500)

    def test_mwr_plain_and_with_deposit(self):
        plain = [EquityPoint("2026-01-01", 200_000),
                 EquityPoint("2027-01-01", 220_000)]
        self.assertAlmostEqual(mwr(plain), 0.10, places=3)

        contributed = [
            EquityPoint("2026-01-01", 200_000),
            EquityPoint("2026-07-01", 320_000, cash_flow=100_000),
            EquityPoint("2027-01-01", 340_000),
        ]
        self.assertIsNotNone(mwr(contributed))
        self.assertGreater(mwr(contributed), 0.10)
        self.assertLess(mwr(contributed), 0.25)

    def test_withdrawal_does_not_look_like_drawdown(self):
        points = [
            EquityPoint("2026-01-01", 200_000),
            EquityPoint("2026-01-10", 220_000),
            EquityPoint("2026-01-20", 170_000, cash_flow=-50_000),
            EquityPoint("2026-01-30", 180_000),
        ]
        stats = drawdown(points)
        self.assertEqual(stats["max_dd"], 0)
        self.assertEqual(clean_equity(points), [200_000, 220_000, 220_000, 230_000])

    def test_drawdown_depth_duration(self):
        points = [
            EquityPoint("2026-01-01", 200_000),
            EquityPoint("2026-01-10", 220_000),
            EquityPoint("2026-01-20", 198_000),
            EquityPoint("2026-01-30", 210_000),
        ]
        stats = drawdown(points)
        self.assertEqual(stats["max_dd"], -22_000)
        self.assertEqual(stats["current_dd"], -10_000)
        self.assertEqual(stats["max_dd_pct"], -10.0)
        self.assertEqual(stats["max_dd_days"], 10)

    def test_short_history_gives_na(self):
        points = [EquityPoint(f"2026-01-0{i+1}", 200_000 + i * 100)
                  for i in range(5)]
        self.assertIsNone(sharpe(points))
        self.assertIsNone(sortino(points))
        self.assertEqual(display(sharpe(points)), METRICS_NA)

        oscillated = [EquityPoint(f"2026-01-{i+1:02d}",
                                  200_000 * (1 + 0.01 * math.sin(i)))
                      for i in range(40)]
        self.assertIsNotNone(sharpe(oscillated))
        self.assertIsNotNone(sortino(oscillated))

    def test_trade_metrics(self):
        trades = [Trade(100), Trade(-50), Trade(200), Trade(-100), Trade(0)]
        self.assertEqual(winrate(trades), 40.0)
        self.assertEqual(profit_factor(trades), 2.0)
        self.assertEqual(expectancy(trades), 30.0)
        self.assertEqual(streaks(trades), {"max_win_streak": 1, "max_loss_streak": 1})
        self.assertIsNone(profit_factor([Trade(10), Trade(20)]))
        self.assertIsNone(expectancy([]))

    def test_summarize_dict(self):
        metrics = summarize(with_flow(), [Trade(100), Trade(-50)])
        data = metrics.to_dict()
        self.assertEqual(data["equity"], 320_000)
        self.assertEqual(data["net_pnl"], 50)
        self.assertAlmostEqual(data["twr"], 0.10, places=6)
        self.assertEqual(data["max_dd"], 0)
        self.assertEqual(data["trades"], 2)
        self.assertEqual(data["winrate"], 50.0)

    def test_display_formatting(self):
        self.assertEqual(display(None), "н/д")
        self.assertEqual(display(1_234.5, digits=1), "1 234.5")
        self.assertEqual(display(12.34, percent=True), "12.34 %")


if __name__ == "__main__":
    unittest.main()
