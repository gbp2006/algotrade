"""Тесты юнита постоянной торговли (без вызова systemctl)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import live_control as lc  # noqa: E402


class TestLiveControl(unittest.TestCase):
    def test_unit_sets_flag_and_arm(self):
        service, timer = lc.render_units()
        self.assertIn("FINAM_ALLOW_TRADING=1", service)
        self.assertIn("--arm", service)
        self.assertIn("34_live_execute.py", service)
        self.assertIn("OnCalendar=Mon..Fri 14:00:00", timer)


if __name__ == "__main__":
    unittest.main()
