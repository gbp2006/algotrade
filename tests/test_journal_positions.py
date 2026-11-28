"""Общая модель позиций по журналу заявок для сверки с брокером. ./run.sh test"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import trade_journal as tj  # noqa: E402
from algo.journal_positions import journal_positions


class TestJournalPositions(unittest.TestCase):
    def test_model_and_uncertain_from_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.csv"
            base = {"ts": "2026-11-27T13:50:00", "client_id": "r:d",
                    "order_id": "1", "config": "r", "symbol": "CNYRUBF@RTSX",
                    "price": 12.3, "multiplier": 1000.0, "reason": "",
                    "response": "", "pricing": "marketable", "order_type": "limit"}
            rows = [
                dict(base, client_order_id="c1", side="buy", qty=2,
                     status="sent", account="A1"),
                dict(base, client_order_id="c2", side="sell", qty=2,
                     status="filled", account="A1"),
                dict(base, client_order_id="c3", side="buy", qty=9,
                     status="uncertain", account="A1"),
                dict(base, client_order_id="c4", side="buy", qty=5,
                     status="sent", account="A2"),
            ]
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=tj.FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            # Исполнение накопительное: filled с qty=2 в CSV может значить 3 контракта.
            with mock.patch.object(tj, "executed_qty", return_value=3):
                model, uncertain = journal_positions("A1", path)
        self.assertEqual(model, {"CNYRUBF@RTSX": -1})
        self.assertEqual(uncertain, 1)

    def test_missing_journal_is_empty_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            model, uncertain = journal_positions("A1", Path(tmp) / "live.csv")
        self.assertEqual((model, uncertain), ({}, 0))


if __name__ == "__main__":
    unittest.main()
