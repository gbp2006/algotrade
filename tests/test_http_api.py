"""HTTP-слой панели без httpx: минимальный ASGI-клиент поверх FastAPI. ./run.sh test"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.robot_store import RobotStore  # noqa: E402
from web import app as web_app
from web import instances_api as api


def request(app, method: str, path: str, payload=None):
    """Прямой вызов ASGI-приложения: статус + разобранный JSON."""
    body = json.dumps(payload).encode() if payload is not None else b""
    headers = [(b"host", b"testserver"), (b"content-type", b"application/json"),
               (b"content-length", str(len(body)).encode())]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path.split("?")[0],
             "raw_path": path.split("?")[0].encode(),
             "query_string": path.split("?")[1].encode() if "?" in path else b"",
             "headers": headers, "client": ("127.0.0.1", 1234),
             "server": ("testserver", 80), "root_path": ""}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    messages: list[dict] = []

    async def send(msg):
        messages.append(msg)

    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = raw.decode("utf-8", "replace")
    return status, parsed


class TestHTTPApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.store = RobotStore(d / "robots.db")
        self.store.init_db()
        self.patches = [
            mock.patch.object(api, "_default_store", self.store),
            mock.patch.object(api, "LIVE", d / "live.csv"),
            mock.patch.object(api, "SHADOW_JOURNAL", d / "shadow.csv"),
            mock.patch.object(api, "SHADOW", d / "shadow.json"),
            mock.patch.object(api, "HEALTH", d / "health.json"),
            mock.patch.object(api, "STOP", d / "STOP"),
            mock.patch.object(api, "STOP_REAL", d / "STOP_REAL"),
            mock.patch.object(web_app, "ALERTS", d / "alerts_seen.json"),
            mock.patch.object(web_app, "HEALTH", d / "health.json"),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        web_app.app.dependency_overrides[api.get_store] = lambda: self.store
        self.addCleanup(web_app.app.dependency_overrides.clear)

    def test_archive_empty(self):
        status, data = request(web_app.app, "GET", "/api/archive")
        self.assertEqual(status, 200)
        self.assertEqual(data["items"], [])

    def test_accounts_analytics_shape(self):
        status, data = request(web_app.app, "GET", "/api/accounts/analytics")
        self.assertEqual(status, 200)
        self.assertIn("real", data)
        self.assertIn("virtual", data)

    def test_logs_limit_clamped(self):
        status, data = request(web_app.app, "GET", "/api/logs?limit=99999")
        self.assertEqual(status, 200)
        self.assertIn("items", data)

    def test_live_state(self):
        status, data = request(web_app.app, "GET", "/api/live-state")
        self.assertEqual(status, 200)
        for key in ("paper_days", "shadow_days", "stop_real", "allow_trading"):
            self.assertIn(key, data)

    def test_stop_real_bad_action(self):
        status, data = request(web_app.app, "POST", "/api/stop-real", {"action": "boom"})
        self.assertEqual(status, 400)

    def test_create_and_delete_instance_over_http(self):
        status, created = request(web_app.app, "POST", "/api/instances", {
            "id": "http-1", "spec_id": "prostushka", "instrument": "CNY",
            "mode": "paper"})
        self.assertEqual(status, 201, created)
        self.assertEqual(created["status"], "draft")
        status, rows = request(web_app.app, "GET", "/api/instances?mode=paper")
        self.assertEqual(status, 200)
        self.assertIn("http-1", [r["id"] for r in rows])
        status, _ = request(web_app.app, "DELETE", "/api/instances/http-1")
        self.assertEqual(status, 200)

    def test_alerts_ack_and_broken_file(self):
        (Path(self.tmp.name) / "health.json").write_text(json.dumps({
            "status": "PROBLEMS", "problems": ["нет решения"], "warnings": [],
        }), encoding="utf-8")
        status, data = request(web_app.app, "POST", "/api/alerts/ack")
        self.assertEqual(status, 200)
        self.assertTrue(data["dismissed"])
        self.assertEqual(web_app.alerts_seen(), data["digest"])
        # битый файл честно читается как «не прочитано»
        (Path(self.tmp.name) / "alerts_seen.json").write_text("{bad", encoding="utf-8")
        self.assertEqual(web_app.alerts_seen(), "")

    def test_digest_is_stable_and_text_sensitive(self):
        a = web_app.alerts_digest({"problems": ["p"], "warnings": ["w"]})
        b = web_app.alerts_digest({"warnings": ["w"], "problems": ["p"]})
        self.assertEqual(a, b)
        self.assertNotEqual(a, web_app.alerts_digest({"problems": ["другое"]}))

    def test_unknown_instance_is_404(self):
        status, _ = request(web_app.app, "GET", "/api/instances/does-not-exist")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
