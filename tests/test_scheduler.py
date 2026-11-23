"""Тесты расписания внутреннего планировщика (без запуска задач). ./run.sh test"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import scheduler as sch  # noqa: E402


class TestScheduler(unittest.TestCase):
    def test_due_times(self):
        task = next(t for t in sch.TASKS if t.name == "daily")
        wed = datetime(2026, 11, 25, 13, 55)
        self.assertTrue(sch.due(task, wed, {}))
        self.assertFalse(sch.due(task, datetime(2026, 11, 25, 13, 54), {}))
        self.assertFalse(sch.due(task, datetime(2026, 11, 28, 13, 55), {}))  # суббота
        self.assertFalse(sch.due(
            task, wed, {"daily": wed.strftime("%Y-%m-%d %H:%M")}))

    def test_every_ten_minutes(self):
        task = next(t for t in sch.TASKS if t.name == "update_live")
        self.assertTrue(sch.due(task, datetime(2026, 11, 25, 10, 10), {}))
        self.assertFalse(sch.due(task, datetime(2026, 11, 25, 10, 11), {}))

    def test_shadow_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(sch.shadow())
        with mock.patch.dict("os.environ", {"ALGO_SCHEDULER_SHADOW": "0"}):
            self.assertFalse(sch.shadow())

    def test_run_once_shadow_no_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, log = Path(tmp) / "state.json", Path(tmp) / "scheduler.log"
            with mock.patch.multiple(sch, STATE=state, LOG=log):
                fired = sch.run_once(datetime(2026, 11, 25, 13, 55), execute=False)
            self.assertIn("daily", fired)
            text = log.read_text(encoding="utf-8")
            self.assertIn("SHADOW daily", text)
            self.assertNotIn("RUN ", text)
            self.assertEqual(json.loads(state.read_text())["daily"], "2026-11-25 13:55")


if __name__ == "__main__":
    unittest.main()
