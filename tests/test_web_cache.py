"""Тесты кэша тяжёлых вызовов панели (systemd-состояния)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import web.app as app  # noqa: E402


class TestWebCache(unittest.TestCase):
    def test_timer_state_cached(self):
        app._cache.clear()
        self.addCleanup(app._cache.clear)
        with patch.object(app.subprocess, "run",
                          return_value=Mock(stdout="active\n")) as run:
            self.assertEqual(app.timer_state("algotrading-web.service"), "active")
            self.assertEqual(app.timer_state("algotrading-web.service"), "active")
            self.assertEqual(run.call_count, 1)

    def test_different_units_have_separate_cache(self):
        app._cache.clear()
        self.addCleanup(app._cache.clear)
        with patch.object(app.subprocess, "run",
                          return_value=Mock(stdout="inactive\n")) as run:
            app.timer_state("one.timer")
            app.timer_state("two.timer")
            self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
