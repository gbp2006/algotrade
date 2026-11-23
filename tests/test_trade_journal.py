"""Тесты долгосрочного журнала сделок (SQLite + зеркало CSV)."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo import trade_journal as tj  # noqa: E402


def row(cid: str, status: str = "planned") -> dict:
    return {"ts": "2026-11-23T13:55:00", "client_id": cid,
            "client_order_id": cid, "order_id": "", "config": "p-base", "symbol": "CNYRUBF@RTSX",
            "side": "buy", "qty": 1, "price": 12.3, "multiplier": 1000.0,
            "status": status, "reason": "", "response": "", "account": "2102993",
            "pricing": "marketable", "order_type": "limit"}


class TestTradeJournal(unittest.TestCase):
    def test_append_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            self.assertTrue(tj.append(row("a"), db))
            self.assertFalse(tj.append(row("a"), db))
            self.assertTrue(tj.exists("a", db))
            self.assertEqual(len(tj.records(limit=10, path=db)), 1)

    def test_records_filtered_by_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            tj.append(row("a"), db)
            r = row("b")
            r["account"] = "other"
            tj.append(r, db)
            self.assertEqual(len(tj.records(limit=10, account="2102993", path=db)), 1)

    def test_events_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            tj.append(row("a", "planned"), db)
            tj.append(row("a", "sent"), db)  # дубль — событие не добавится
            with tj.connect(db) as c:
                events = [dict(x) for x in c.execute(
                    "SELECT status FROM order_events WHERE client_order_id='a'")]
            self.assertEqual([e["status"] for e in events], ["planned"])

    def test_migrate_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "live.csv"
            db = Path(tmp) / "trades.db"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=tj.FIELDS)
                w.writeheader()
                w.writerow(row("old"))
            self.assertEqual(tj.migrate_csv(csv_path, db), 1)
            self.assertEqual(tj.migrate_csv(csv_path, db), 0)

    def test_backup_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            tj.append(row("a"), db)
            dst = tj.backup(Path(tmp) / "backup.db", db)
            self.assertTrue(tj.exists("a", dst))


if __name__ == "__main__":
    unittest.main()
