"""Рабочий путь фонда денежного рынка: лимиты робота и свежесть котировки.

Исследовательская модель `algo/money_market.py` удалена 28.11; здесь остались
проверки того, что реально участвует в ребалансировке (`position_ops`).
./run.sh test
"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.broker import position_ops as pos  # noqa: E402
from algo.broker.position_ops import OpError, mm_limits  # noqa: E402


class TestMmLimits(unittest.TestCase):
    """Лимиты фонда задаёт пользователь в карточке робота, а не счёт (ADR 26.11)."""

    def test_limits_come_from_robot_params(self):
        ctx = {"capital": 50_000.0,
               "acc": {"max_qty": 100, "max_exposure": 0.5},
               "params": {"max_qty": 3043, "max_exposure": 0.9, "max_units": 100000}}
        limits = mm_limits(ctx)
        self.assertEqual(limits.max_qty, 3043)
        self.assertAlmostEqual(limits.max_notional, 45_000.0)

    def test_fallback_to_max_units_and_full_capital(self):
        ctx = {"capital": 50_000.0, "acc": {},
               "params": {"max_units": 7000}}
        limits = mm_limits(ctx)
        self.assertEqual(limits.max_qty, 7000)
        self.assertAlmostEqual(limits.max_notional, 50_000.0)


class TestFundQuoteAge(unittest.TestCase):
    """Паи котируются реже фьючерсов — лимит возраста настраивается роботом."""

    def test_custom_age_allows_six_minute_quote(self):
        stamp = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=6)).isoformat()
        broker = SimpleNamespace(quote=lambda symbol: SimpleNamespace(
            timestamp=stamp, bid=14.211, ask=14.212, last=14.212))
        with self.assertRaises(OpError):
            pos._quote(broker, "FMMM@MISX", 0.0001)
        quote = pos._quote(broker, "FMMM@MISX", 0.0001, max_age=3600)
        self.assertEqual(quote.ask, 14.212)


if __name__ == "__main__":
    unittest.main()
