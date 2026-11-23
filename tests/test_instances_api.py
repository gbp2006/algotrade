"""Тесты API управления инстансами (без HTTP-клиента). ./run.sh test"""

from __future__ import annotations

import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.robot_store import RobotStore  # noqa: E402
from web import app as web_app  # noqa: E402
from web import instances_api as api  # noqa: E402


class TestApiViews(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = RobotStore(Path(self.tmp.name) / "robots.db")
        self.store.init_db()

    def test_specs(self):
        specs = api.specs_view()
        self.assertTrue(any(s["id"] == "prostushka" for s in specs))
        self.assertIn("ma_window", specs[0]["schema"])

    def test_create_list_action_history(self):
        created = api.create_view(self.store, {
            "id": "p-api", "spec_id": "prostushka", "instrument": "CNY",
            "params": {"ma_window": 55}, "mode": "paper",
        })
        self.assertEqual(created["status"], "draft")
        rows = api.instances_view(self.store, mode="paper")
        self.assertEqual([r["id"] for r in rows], ["p-api"])
        api.action_view(self.store, "p-api", "start")
        api.action_view(self.store, "p-api", "pause")
        self.assertEqual(self.store.get_instance("p-api")["status"], "paused")
        self.assertGreaterEqual(len(api.history_view(self.store, "p-api")), 3)

    def test_update_with_version(self):
        created = api.create_view(self.store, {
            "id": "p-api", "spec_id": "prostushka", "mode": "paper"})
        upd = api.update_view(self.store, "p-api",
                              {"version": created["version"],
                               "params": {"ma_window": 77}, "reason": "тест"})
        self.assertEqual(upd["params"]["ma_window"], 77)
        self.assertEqual(upd["version"], 2)

    def test_brokers_list(self):
        self.assertIn("finam", [b["name"] for b in api.brokers()])

    def test_backtest_preview(self):
        r = api.backtest_preview_view({
            "spec_id": "prostushka", "instrument": "CNY",
            "params": {"ma_window": 48}, "days": 5,
        })
        self.assertTrue(r["ok"], r)
        self.assertIn("trades", r)
        bad = api.backtest_preview_view({"spec_id": "unknown"})
        self.assertFalse(bad["ok"])

    def test_live_views_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "live.csv"
            live.write_text(
                "ts,client_id,client_order_id,order_id,config,symbol,side,qty,price,"
                "multiplier,status,reason,response,account,pricing,order_type\n"
                "2026-11-23T13:57:22,p-base:1,abc,42,p-base,CNYRUBF@RTSX,buy,32,"
                "12.3,1000,sent,,{},A1,marketable,limit\n", encoding="utf-8")
            stop_real = root / "STOP_REAL"
            with mock.patch.multiple(
                    api, LIVE=live, PAPER=root / "paper.csv",
                    HEALTH=root / "health.json", SHADOW=root / "shadow.json",
                    ROLLOVER=root / "rollover.json", STOP=root / "STOP",
                    STOP_REAL=stop_real):
                orders = api.live_orders_view()
                self.assertEqual(len(orders), 1)
                self.assertEqual(orders[0]["config"], "p-base")
                state = api.live_state_view()
                self.assertFalse(state["stop_real"])
                self.assertEqual(state["shadow_days"], 0)  # в тесте только sent
                api.stop_real_view("set")
                self.assertTrue(api.live_state_view()["stop_real"])
                api.stop_real_view("clear")
                self.assertFalse(api.live_state_view()["stop_real"])


class TestPanelSafety(unittest.TestCase):
    def test_read_health_survives_broken_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "health.json"
            with mock.patch.object(web_app, "HEALTH", path):
                self.assertIsNone(web_app.read_health())
                path.write_text("{битый", encoding="utf-8")
                self.assertIsNone(web_app.read_health())
                path.write_text('{"ok": true}', encoding="utf-8")
                self.assertEqual(web_app.read_health(), {"ok": True})

    def test_paper_toggle_does_not_claim_live(self):
        html = (Path(__file__).resolve().parent.parent / "web" / "templates"
                / "index.html").read_text(encoding="utf-8")
        self.assertIn("Пауза бумаги", html)
        self.assertIn("Снять паузу", html)
        self.assertNotIn("○ Offline", html)
        self.assertNotIn("● Live", html)


if __name__ == "__main__":
    unittest.main()
