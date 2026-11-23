"""Тесты справочника инструментов: избранное и фильтрация ликвидных."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import instruments_catalog as cat  # noqa: E402


class TestCatalog(unittest.TestCase):
    def test_upsert_and_favorite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "inst.db"
            cat.upsert([
                {"symbol": "SBER@MISX", "ticker": "SBER", "type": "EQUITIES",
                 "name": "Сбербанк"},
                {"symbol": "RIH7@RTSX", "ticker": "RIH7", "type": "FUTURES",
                 "name": "RTS-3.27"},
            ], db)
            self.assertEqual(len(cat.search("SBER", scope="all", path=db)), 1)
            # без избранного и ликвидных выборка пуста
            self.assertEqual(cat.search("SBER", path=db), [])
            self.assertEqual(cat.toggle_favorite("SBER@MISX", "база", db)["favorite"], True)
            self.assertEqual(len(cat.search("SBER", path=db)), 1)
            self.assertEqual(len(cat.favorites(db)), 1)
            self.assertEqual(cat.toggle_favorite("SBER@MISX", "", db)["favorite"], False)
            self.assertEqual(cat.favorites(db), [])

    def test_liquid_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "inst.db"
            cat.upsert([{"symbol": "LQDT@MISX", "ticker": "LQDT",
                         "type": "FUNDS", "name": "Ликвидность"}], db)
            with cat.connect(db) as c:
                c.execute("UPDATE instruments SET liquid=1, rank=1 WHERE symbol=?",
                          ("LQDT@MISX",))
            self.assertEqual(len(cat.search("LQDT", path=db)), 1)
            self.assertEqual(cat.search("LQDT", scope="favorites", path=db), [])

    def test_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "inst.db"
            cat.upsert([{"symbol": "X@MISX", "ticker": "X"}], db)
            self.assertEqual(cat.stats(db)["total"], 1)


if __name__ == "__main__":
    unittest.main()
