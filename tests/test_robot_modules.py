"""Модули сайзинга и выхода: чистые функции, контур не меняют. ./run.sh test"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.robot_modules import (ExitConfig, ExitReason, SizingConfig,  # noqa: E402
                                SizingMode, exit_reason, reduce_only_allowed,
                                sizing_lots)


class TestRobotModules(unittest.TestCase):
    def test_sizing_modes(self):
        fixed = SizingConfig(SizingMode.FIXED, value=5, max_lots=10)
        self.assertEqual(sizing_lots(200_000, 12.29, fixed), 5)
        percent = SizingConfig(SizingMode.PERCENT, value=200)
        self.assertEqual(sizing_lots(200_000, 12.29, percent), 32)
        stepped = SizingConfig(SizingMode.STEPPED,
                               steps=((0, 1), (100_000, 2), (200_000, 4)))
        self.assertEqual(sizing_lots(150_000, 12.29, stepped), 2)
        self.assertEqual(sizing_lots(250_000, 12.29, stepped), 4)
        self.assertEqual(sizing_lots(0, 12.29, stepped), 0)
        self.assertEqual(sizing_lots(200_000, 0, percent), 0)

    def test_exit_priority(self):
        cfg = ExitConfig(stop_loss_pct=3, take_profit_pct=5,
                         trailing_pct=2, close_time="18:45")
        self.assertEqual(exit_reason(cfg, 100, 96, 1), ExitReason.STOP)
        self.assertEqual(exit_reason(cfg, 100, 106, 1), ExitReason.TAKE)
        self.assertEqual(exit_reason(cfg, 100, 103, 1, extreme=108), ExitReason.TRAIL)
        self.assertEqual(exit_reason(cfg, 100, 100, 1, now="2026-11-24T18:50:00"),
                         ExitReason.TIME)
        self.assertEqual(exit_reason(cfg, 100, 101, 1), ExitReason.HOLD)

    def test_breakeven_and_reduce_only(self):
        cfg = ExitConfig(breakeven_after_pct=5, partial_close_pct=4)
        self.assertEqual(exit_reason(cfg, 100, 100.5, 1, extreme=106),
                         ExitReason.BREAKEVEN)
        self.assertTrue(reduce_only_allowed("EXIT", 3))
        self.assertTrue(reduce_only_allowed("ENTER_LONG", -2))
        self.assertFalse(reduce_only_allowed("ENTER_LONG", 2))
        self.assertFalse(reduce_only_allowed("ENTER_SHORT", -2))


if __name__ == "__main__":
    unittest.main()
