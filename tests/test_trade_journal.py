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

    def test_mark_execution_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            csv_path = Path(tmp) / "live.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=tj.FIELDS)
                w.writeheader()
                w.writerow(row("a", "sent"))
            tj.append(row("a", "sent"), db)
            self.assertTrue(tj.mark_execution(
                "a", status="filled", executed_qty=1, price=12.35,
                ts="2026-11-24T14:00:24", detail="filled:1@12.35",
                path=db, csv_path=str(csv_path)))
            self.assertFalse(tj.mark_execution(
                "a", status="filled", executed_qty=1, price=12.35,
                detail="filled:1@12.35", path=db, csv_path=csv_path))
            rec = tj.records(limit=10, path=db)[0]
            self.assertEqual(rec["status"], "filled")
            with tj.connect(db) as c:
                trades = [dict(x) for x in c.execute("SELECT * FROM trades")]
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["price"], 12.35)
            with csv_path.open(encoding="utf-8") as f:
                mirror = list(csv.DictReader(f))
            self.assertEqual(mirror[0]["status"], "filled")

    def test_refresh_executions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            tj.append(row("a", "sent"), db)

            class Broker:
                def orders(self, account):
                    return [{"order_id": "ord-1", "status": "ORDER_STATUS_FILLED",
                             "executed_quantity": {"value": "1"},
                             "transact_at": "2026-11-24T14:00:24",
                             "order": {"client_order_id": "a",
                                       "limit_price": {"value": "12.35"}}}]

            result = tj.refresh_executions(Broker(), "2102993", path=db)
            self.assertEqual((result["checked"], result["updated"]), (1, 1))
            self.assertEqual(result["details"]["a"]["price"], 12.35)
            self.assertEqual(tj.records(limit=10, path=db)[0]["status"], "filled")

    def test_corrected_price_does_not_duplicate_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            tj.append(row("cid-price", "sent"), db)
            kw = dict(status="filled", executed_qty=5,
                      ts="2026-11-24T14:00:24", path=db)
            self.assertTrue(tj.mark_execution("cid-price", price=12.28, **kw))
            self.assertFalse(tj.mark_execution("cid-price", price=12.30, **kw))
            self.assertEqual(tj.executed_qty("cid-price", db), 5)
            with tj.connect(db) as c:
                fills = [dict(x) for x in c.execute(
                    "SELECT qty,price FROM trades WHERE client_order_id='cid-price'")]
            self.assertEqual(len(fills), 1)
            self.assertEqual(fills[0]["price"], 12.30)

    def test_full_broker_response_is_preserved_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            response = {"order_id": "42", "status": "ORDER_STATUS_FILLED",
                        "payload": {"nested": ["x" * 400, {"a": 1}]}}
            self.assertTrue(tj.store_response("cid-full", response, db))
            self.assertFalse(tj.store_response("cid-full", response, db))
            self.assertEqual(tj.full_response("cid-full", db), [response])
            self.assertEqual(tj.full_response("unknown", db), [])

    def test_confirmed_uncertain_is_refreshed_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            tj.append(row("unc-1", "uncertain"), db)

            class Broker:
                def orders(self, account):
                    return [{"order_id": "ord-1", "status": "ORDER_STATUS_FILLED",
                             "executed_quantity": {"value": "1"},
                             "transact_at": "2026-11-24T14:00:24",
                             "order": {"client_order_id": "unc-1",
                                       "limit_price": {"value": "12.35"}}}]

            result = tj.refresh_executions(Broker(), "2102993", path=db)
            self.assertEqual((result["checked"], result["updated"]), (1, 1))
            self.assertEqual(tj.records(limit=10, path=db)[0]["status"], "filled")
            self.assertEqual(tj.executed_qty("unc-1", db), 1)

    def test_backup_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "trades.db"
            tj.append(row("a"), db)
            dst = tj.backup(Path(tmp) / "backup.db", db)
            self.assertTrue(tj.exists("a", dst))


if __name__ == "__main__":
    unittest.main()
