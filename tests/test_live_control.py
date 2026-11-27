"""Тесты разрешения реальной торговли через задания роботов (без systemd)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import live_control as lc  # noqa: E402
from algo.robot_store import RobotStore  # noqa: E402


class TestLiveControl(unittest.TestCase):
    def _store(self, tmp: str, *, with_live: bool = True) -> RobotStore:
        store = RobotStore(Path(tmp) / "robots.db")
        store.init_db()
        store.create_account({"id": "2102993", "label": "тест", "mode": "LIVE"})
        if with_live:
            store.create_instance({
                "id": "live-1", "spec_id": "prostushka", "mode": "live",
                "status": "active", "account": "2102993", "pricing": "marketable",
            })
            store.upsert_job({
                "id": "inst:live-1:schedule", "owner": "live-1",
                "command": "FINAM_ALLOW_TRADING=1 ./run.sh live --day {date}",
                "times": ["13:50"], "enabled": False,
            })
        return store

    def test_enable_and_disable_switch_live_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            with mock.patch.object(lc, "AUDIT_LOG", Path(tmp) / "audit.jsonl"):
                on = lc.enable(store)
                self.assertTrue(on["enabled"])
                self.assertEqual(on["next_run"], "13:50")
                self.assertEqual(on["mode"], "robots")
                self.assertEqual(on["live_robots"], 1)
                self.assertTrue(store.list_jobs()[0]["enabled"])
                off = lc.disable(store)
            self.assertFalse(off["enabled"])
            self.assertFalse(store.list_jobs()[0]["enabled"])

    def test_enable_requires_live_robot_and_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp, with_live=False)
            with mock.patch.object(lc, "AUDIT_LOG", Path(tmp) / "audit.jsonl"):
                with self.assertRaises(lc.LiveControlError):
                    lc.enable(store)
            store.create_instance({
                "id": "live-2", "spec_id": "prostushka", "mode": "live",
                "status": "active", "account": "2102993", "pricing": "marketable",
            })
            with self.assertRaises(lc.LiveControlError):
                lc.enable(store)

    def test_stop_real_blocks_enable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            stop = Path(tmp) / "STOP_REAL"
            stop.write_text("стоп", encoding="utf-8")
            with mock.patch.object(lc, "AUDIT_LOG", Path(tmp) / "audit.jsonl"), \
                 mock.patch.object(lc, "STOP_REAL", stop):
                with self.assertRaises(lc.LiveControlError):
                    lc.enable(store)


if __name__ == "__main__":
    unittest.main()
