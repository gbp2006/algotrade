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

    def test_single_source_of_strategy_names(self):
        from algo import strategy_descriptions as sd
        self.assertEqual(sd.name("prostushka"), "Простушка")
        self.assertEqual(sd.name("unknown"), "unknown")
        specs = {s["id"]: s for s in api.specs_view()}
        self.assertEqual(specs["donchian"]["title"], "Donchian 20/10")
        api.create_view(self.store, {"id": "name-1", "spec_id": "prostushka",
                                     "instrument": "CNY", "mode": "paper"})
        row = api.instances_view(self.store)[0]
        self.assertEqual(row["strategy_name"], "Простушка")
        self.assertTrue(row["about"].startswith("Простушка"))

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

    def test_archive_includes_stopped(self):
        created = api.create_view(self.store, {"id": "stopped-1", "spec_id": "prostushka",
                                               "instrument": "CNY", "mode": "paper"})
        api.action_view(self.store, "stopped-1", "start")
        self.store.set_status("stopped-1", "stopping", "тест")
        api.action_view(self.store, "stopped-1", "stop")
        self.assertEqual(created["status"], "draft")
        self.assertIn("stopped-1", [x["id"] for x in api.archive_list(self.store)])

    def test_delete_paper_draft(self):
        api.create_view(self.store, {"id": "draft-1", "spec_id": "prostushka",
                                     "instrument": "CNY", "mode": "paper"})
        self.assertIsNotNone(api.delete_instance("draft-1", store=self.store))
        self.assertIsNone(self.store.get_instance("draft-1"))

    def test_analytics_cache_ttl_and_invalidation(self):
        api.invalidate_analytics()
        with mock.patch.object(api, "account_analytics",
                               side_effect=lambda store: {"n": 1}) as fake:
            first = api.cached_analytics(self.store)
            second = api.cached_analytics(self.store)
            self.assertEqual((first, second), ({"n": 1}, {"n": 1}))
            self.assertEqual(fake.call_count, 1)
            api.invalidate_analytics()
            api.cached_analytics(self.store)
            self.assertEqual(fake.call_count, 2)

    def test_real_account_analytics_hides_secret(self):
        self.store.create_account({"id": "acc-1", "label": "Тест", "capital": 100000,
                                "max_exposure": 1.0, "key_ref": "acc:acc-1"})
        class Broker:
            def __init__(self, *a, **k): pass
            def account(self, acc):
                return {"equity": {"value": "123456"},
                        "positions": [{"symbol": "CNYRUBF@RTSX",
                                       "quantity": {"value": "-2"},
                                       "unrealized_pnl": {"value": "15"}}]}
        with mock.patch.object(api, "FinamBroker", Broker), \
             mock.patch.object(api, "resolve_secret", lambda ref: "super-secret"):
            data = api.account_analytics(self.store)
        row = data["real"][0]
        self.assertEqual(row["equity"], 123456.0)
        self.assertEqual(row["positions"][0]["qty"], -2.0)
        self.assertEqual(row["status"], "ok")
        self.assertNotIn("super-secret", str(data))
        self.assertNotIn("key_ref", str(data))

    def test_mutations_invalidate_analytics(self):
        created = api.create({"id": "p-cache", "spec_id": "prostushka",
                              "instrument": "CNY", "mode": "paper"}, store=self.store)
        with mock.patch.object(api, "invalidate_analytics") as inv:
            api.update("p-cache", {"version": created["version"],
                                   "params": {"ma_window": 77}}, store=self.store)
            api.action("p-cache", "start", store=self.store)
            api.action("p-cache", "pause", store=self.store)
            api.action("p-cache", "archive", store=self.store)
            api.delete_instance("p-cache", store=self.store)
        self.assertEqual(inv.call_count, 5)

    def test_brokers_list(self):
        self.assertIn("finam", [b["name"] for b in api.brokers()])

    def test_generated_id_from_name(self):
        payload = {"name": "База на юане", "spec_id": "prostushka",
                   "instrument": "CNY", "mode": "paper"}
        first = api.create_view(self.store, payload)
        self.assertEqual(first["id"], "baza-na-yuane")
        self.assertEqual(first["note"], "База на юане")
        second = api.create_view(self.store, payload)
        self.assertEqual(second["id"], "baza-na-yuane-2")

    def test_account_lifecycle(self):
        created = api.create_account(
            {"id": "paper-2", "label": "Второй виртуальный", "mode": "TEST",
             "capital": 200_000}, self.store)
        self.assertEqual(created["id"], "paper-2")
        acc = next(a for a in api.accounts(self.store) if a["id"] == "paper-2")
        self.assertEqual(acc["mode"], "TEST")
        self.assertEqual(acc["capital"], 200_000)
        self.assertEqual(acc["enabled"], 1)

        api.update_account("paper-2", {"label": "Переименован",
                                       "enabled": False}, self.store)
        acc = next(a for a in api.accounts(self.store) if a["id"] == "paper-2")
        self.assertEqual(acc["label"], "Переименован")
        self.assertEqual(acc["enabled"], 0)

        self.assertEqual(api.delete_account("paper-2", self.store)["deleted"], True)
        self.assertNotIn("paper-2", [a["id"] for a in api.accounts(self.store)])

    def test_account_delete_guarded_by_robots(self):
        api.create_account({"id": "acc-1", "label": "Счёт"}, self.store)
        api.create_view(self.store, {"id": "r-1", "spec_id": "prostushka",
                                     "instrument": "CNY", "mode": "paper",
                                     "account": "acc-1"})
        with self.assertRaises(Exception) as ctx:
            api.delete_account("acc-1", self.store)
        self.assertIn("робот", str(ctx.exception))
        self.assertIn("acc-1", [a["id"] for a in api.accounts(self.store)])

    def test_generated_id_fallback(self):
        inst = api.create_view(self.store, {"spec_id": "prostushka",
                                            "instrument": "CNY", "mode": "paper"})
        self.assertEqual(inst["id"], "prostushka-cny")

    def test_form_uses_name_and_toggles(self):
        src = (Path(__file__).resolve().parent.parent / "webui" / "src"
               / "sections" / "Robots.tsx").read_text(encoding="utf-8")
        self.assertIn("register('name')", src)
        self.assertNotIn("register('id')", src)
        self.assertIn("z.enum", src)  # валидация Zod вместо ручного ввода id

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

    def test_ui_does_not_claim_live_when_only_paper(self):
        src = (Path(__file__).resolve().parent.parent / "webui" / "src"
               / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("TEST", src)
        self.assertIn("LIVE", src)
        self.assertIn("Тестовые", src)
        self.assertIn("Боевые", src)


if __name__ == "__main__":
    unittest.main()
