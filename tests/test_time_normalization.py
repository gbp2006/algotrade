"""Время версий параметров: МСК naive + нормализация UTC. ./run.sh test"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import instance_configs as ic  # noqa: E402
from algo.robot_store import RobotStore  # noqa: E402


class TestTimeNormalization(unittest.TestCase):
    def test_store_now_is_msk_naive(self):
        before = datetime.now(ic.MSK).replace(tzinfo=None)
        value = RobotStore._now()
        after = datetime.now(ic.MSK).replace(tzinfo=None) + timedelta(seconds=2)
        self.assertLessEqual(before.isoformat(timespec="seconds"), value)
        self.assertLessEqual(value, after.isoformat(timespec="seconds"))
        self.assertNotIn("+", value)

    def test_utc_and_z_are_converted_to_msk(self):
        expected = "2026-11-24T13:00:00"
        self.assertEqual(ic._msk_naive("2026-11-24T10:00:00+00:00"), expected)
        self.assertEqual(ic._msk_naive("2026-11-24T10:00:00Z"), expected)
        self.assertEqual(ic._msk_naive("2026-11-24T13:00:00"), expected)
        self.assertEqual(ic._msk_naive(""), "")

    def test_configs_at_compares_normalized_version_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RobotStore(Path(tmp) / "robots.db")
            store.init_db()
            store.create_instance({"id": "tz-1", "spec_id": "prostushka",
                                   "instrument": "CNY", "mode": "paper"})
            with store._conn() as c:
                c.execute("INSERT INTO param_versions(instance_id,version,params_json,"
                          "created_at) VALUES ('tz-1", 1, ?, ?)",
                          (json.dumps({"ma_window": 7}), "2026-11-24T10:00:00Z"))
            got = ic.configs_at("2026-11-24", at="13:50", store=store)
            self.assertEqual({c.id: c for c in got}["tz-1"].params["ma_window"], 7)
            got = ic.configs_at("2026-11-24", at="12:00", store=store)
            self.assertNotEqual({c.id: c for c in got}["tz-1"].params["ma_window"], 7)


if __name__ == "__main__":
    unittest.main()
