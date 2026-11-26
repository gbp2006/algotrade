"""Тесты модели денежного рынка: свободный капитал, доход по паям, ребалансировка."""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.money_market import (  # noqa: E402
    FundConfig,
    MoneyMarket,
    apply_to_daily,
    daily_rate,
    free_capital,
    load_rate_csv,
)

D1 = dt.date(2026, 1, 1)
D2 = dt.date(2026, 1, 2)
D3 = dt.date(2026, 1, 3)  # суббота

FAST = FundConfig(annual_rate=0.365, min_balance=0.0, tolerance=0.0)


class TestFreeCapital(unittest.TestCase):
    def test_free_after_margin_and_reserve(self):
        self.assertEqual(free_capital(200_000, 31_520, 5_000), 163_480)

    def test_margin_buffer_reduces_free(self):
        self.assertEqual(free_capital(200_000, 31_520, 5_000, 2.0), 131_960)

    def test_never_negative(self):
        self.assertEqual(free_capital(10_000, 20_000, 5_000), 0.0)

    def test_daily_rate(self):
        self.assertAlmostEqual(daily_rate(0.365), 0.001)


class TestMoneyMarket(unittest.TestCase):
    def test_buy_then_accrue_income(self):
        mm = MoneyMarket(FAST)
        st1 = mm.step(D1, 100_000, 0)
        self.assertEqual(st1.action, "buy")
        self.assertEqual(st1.income_today, 0.0)
        self.assertGreater(st1.units, 0)

        st2 = mm.step(D2, 100_000, 0)
        self.assertAlmostEqual(st2.income_today, 100.0, places=6)
        self.assertAlmostEqual(mm.state.income_total, 100.0, places=6)

    def test_margin_growth_sells_units(self):
        mm = MoneyMarket(FAST)
        mm.step(D1, 100_000, 0)
        st = mm.step(D2, 100_000, 50_000)
        self.assertEqual(st.action, "sell")
        self.assertAlmostEqual(st.free, 50_000)
        self.assertAlmostEqual(st.value, 50_000, places=4)
        self.assertGreater(st.income_today, 0)  # паи работали весь день

    def test_reserve_stays_in_cash(self):
        cfg = FundConfig(annual_rate=0.0, min_balance=5_000, tolerance=0.0)
        st = MoneyMarket(cfg).step(D1, 100_000, 20_000)
        self.assertAlmostEqual(st.free, 75_000)
        self.assertAlmostEqual(st.value, 75_000)

    def test_no_free_capital_sells_everything(self):
        mm = MoneyMarket(FAST, initial_units=100)
        st = mm.step(D1, 10_000, 20_000)
        self.assertEqual(st.action, "sell")
        self.assertEqual(st.units, 0)
        self.assertEqual(mm.step(D2, 10_000, 20_000).income_today, 0)

    def test_t_plus_one_timing(self):
        """Паи дают доход со следующего дня и перестают давать после продажи."""
        mm = MoneyMarket(FAST)
        self.assertEqual(mm.step(D1, 100_000, 0).income_today, 0)
        self.assertGreater(mm.step(D2, 100_000, 0).income_today, 0)
        mm.step(D3, 100_000, 0)
        mm.step(dt.date(2026, 1, 5), 100_000, 200_000)  # продажа в конце дня
        st = mm.step(dt.date(2026, 1, 6), 100_000, 200_000)
        self.assertEqual(st.units, 0)
        self.assertEqual(st.income_today, 0)

    def test_fee_reduces_income(self):
        cfg = FundConfig(annual_rate=0.365, min_balance=0.0,
                         tolerance=0.0, fee_pct=0.01)
        st = MoneyMarket(cfg).step(D1, 100_000, 0)
        self.assertAlmostEqual(st.traded, 100_000)
        self.assertAlmostEqual(st.income_today, -1_000)

    def test_callable_rate_can_disable_weekend(self):
        rate = lambda day: 0.365 if day.weekday() < 5 else 0.0  # noqa: E731
        cfg = FundConfig(annual_rate=rate, min_balance=0.0, tolerance=0.0)
        mm = MoneyMarket(cfg, initial_units=100_000)
        self.assertAlmostEqual(mm.step(D1, 100_000, 0).income_today, 100.0,
                               places=6)
        self.assertEqual(mm.step(D3, 100_000, 0).income_today, 0.0)

    def test_tolerance_keeps_position(self):
        cfg = FundConfig(annual_rate=0.0, min_balance=0.0, tolerance=100.0)
        mm = MoneyMarket(cfg)
        mm.step(D1, 100_000, 0)
        st = mm.step(D2, 100_050, 0)
        self.assertEqual(st.action, "hold")
        self.assertEqual(st.traded, 0.0)

    def test_dates_must_increase(self):
        mm = MoneyMarket(FAST)
        mm.step(D2, 100_000, 0)
        with self.assertRaises(ValueError):
            mm.step(D1, 100_000, 0)

    def test_accepts_datetime(self):
        st = MoneyMarket(FAST).step(dt.datetime(2026, 1, 1, 23, 0), 100_000, 0)
        self.assertEqual(st.date, D1)


class TestSeries(unittest.TestCase):
    def test_apply_to_daily(self):
        dates = [D1, D2, D3]
        out = apply_to_daily(dates, [100_000] * 3, [0] * 3, FAST)
        self.assertEqual(len(out["income"]), 3)
        self.assertEqual(out["summary"]["days"], 3)
        self.assertEqual(out["summary"]["invested_days"], 3)
        self.assertAlmostEqual(out["equity_with_fund"][-1], 100_200.1, delta=2)
        self.assertGreater(out["summary"]["income"], 0)

    def test_length_mismatch(self):
        with self.assertRaises(ValueError):
            apply_to_daily([D1], [100_000, 100_000], [0], FAST)

    def test_rate_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "rate.csv"
            p.write_text("date,rate\n2026-01-01,8.7\n2026-01-03,12.0\n",
                         encoding="utf-8")
            rate = load_rate_csv(p)
            self.assertAlmostEqual(rate(dt.date(2025, 12, 31)), 0.087)
            self.assertAlmostEqual(rate(D1), 0.087)
            self.assertAlmostEqual(rate(D2), 0.087)
            self.assertAlmostEqual(rate(D3), 0.120)



class TestMmLimits(unittest.TestCase):
    """Лимиты фонда задаёт пользователь в карточке робота, а не счёт (ADR 26.11)."""

    def test_limits_come_from_robot_params(self):
        from algo.broker.position_ops import mm_limits

        ctx = {"capital": 50_000.0,
               "acc": {"max_qty": 100, "max_exposure": 0.5},
               "params": {"max_qty": 3043, "max_exposure": 0.9, "max_units": 100000}}
        limits = mm_limits(ctx)
        self.assertEqual(limits.max_qty, 3043)
        self.assertAlmostEqual(limits.max_notional, 45_000.0)

    def test_fallback_to_max_units_and_full_capital(self):
        from algo.broker.position_ops import mm_limits

        ctx = {"capital": 50_000.0, "acc": {},
               "params": {"max_units": 7000}}
        limits = mm_limits(ctx)
        self.assertEqual(limits.max_qty, 7000)
        self.assertAlmostEqual(limits.max_notional, 50_000.0)


if __name__ == "__main__":
    unittest.main()
