"""TTL-кэш панели с stale-while-revalidate. ./run.sh test"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web import app as web_app  # noqa: E402


class TestCached(unittest.TestCase):
    def setUp(self):
        self.old_cache = dict(web_app._cache)
        web_app._cache.clear()

    def tearDown(self):
        web_app._cache.clear()
        web_app._cache.update(self.old_cache)

    def test_hot_value_does_not_call_source(self):
        calls = []
        def fn():
            calls.append(1)
            return "value"
        self.assertEqual(web_app._cached("k", 60, fn), "value")
        self.assertEqual(web_app._cached("k", 60, fn), "value")
        self.assertEqual(len(calls), 1)

    def test_expired_stale_is_returned_and_refresh_queued(self):
        calls = []
        def fn():
            calls.append(1)
            return len(calls)
        self.assertEqual(web_app._cached("k", 0, fn, stale=True), 1)
        # TTL 0: сразу просрочено — отдаём старое, ставим рефреш в очередь
        self.assertEqual(web_app._cached("k", 0, fn, stale=True), 1)
        self.assertEqual(len(calls), 1)
        key, ttl, refresh = web_app._refresh_q.get_nowait()
        self.assertEqual(key, "k")
        web_app._cache[key] = (time.time(), refresh())
        web_app._refreshing.discard(key)
        self.assertEqual(web_app._cached("k", 0, fn, stale=True), 2)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
