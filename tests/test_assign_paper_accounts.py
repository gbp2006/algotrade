"""Разведение бумажных роботов по TEST-счетам. ./run.sh test"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.robot_store import RobotStore  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "assign_paper", ROOT / "scripts" / "98_assign_paper_accounts.py")
assign_paper = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(assign_paper)


class TestAssignPaper(unittest.TestCase):
    def test_assigns_once_and_ignores_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RobotStore(Path(tmp) / "robots.db")
            store.init_db()
            for rid, mode in (("p1", "paper"), ("p2", "paper"), ("live-1", "live")):
                store.create_instance({"id": rid, "spec_id": "prostushka",
                                       "instrument": "CNY", "mode": mode,
                                       "capital": 200_000})
            with mock.patch.object(assign_paper, "RobotStore", return_value=store):
                assign_paper.main()
                assign_paper.main()
            accounts = {a["id"]: a for a in store.list_accounts()}
            self.assertIn("paper-p1", accounts)
            self.assertIn("paper-p2", accounts)
            self.assertNotIn("paper-live-1", accounts)
            self.assertEqual(accounts["paper-p1"]["mode"], "TEST")
            self.assertEqual(accounts["paper-p1"]["capital"], 200_000)
            for rid in ("p1", "p2"):
                self.assertEqual(store.get_instance(rid)["account"], f"paper-{rid}")
            self.assertIsNone(store.get_instance("live-1")["account"])


if __name__ == "__main__":
    unittest.main()
