"""Одновременный ручной прогон боя: второй запрос получает 409. ./run.sh test"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from web import instances_api as api  # noqa: E402


class TestLiveRunGuard(unittest.TestCase):
    def test_second_runner_is_rejected_while_first_holds_lock(self):
        entered = threading.Event()
        release = threading.Event()
        results: list[str | int] = []

        def first():
            try:
                with api._live_run_guard():
                    entered.set()
                    release.wait(3)
                results.append("ok")
            except HTTPException as exc:
                results.append(exc.status_code)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(api, "LIVE_RUN_LOCK", Path(tmp) / "live_run.lock"):
                worker = threading.Thread(target=first)
                worker.start()
                self.assertTrue(entered.wait(3), "первый прогон не захватил лок")
                try:
                    with api._live_run_guard():
                        results.append("unexpected")
                except HTTPException as exc:
                    results.append(exc.status_code)
                release.set()
                worker.join(3)

        self.assertCountEqual(results, ["ok", 409])

    def test_lock_is_free_after_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(api, "LIVE_RUN_LOCK", Path(tmp) / "live_run.lock"):
                with self.assertRaises(RuntimeError):
                    with api._live_run_guard():
                        raise RuntimeError("раннер упал")
                with api._live_run_guard():
                    pass  # лок освобождён в finally


if __name__ == "__main__":
    unittest.main()
