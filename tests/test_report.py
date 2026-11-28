"""Тест отчёта по бумажному журналу: метрики и время решений. ./run.sh test"""

from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fixtures_configs import BY_ID  # noqa: E402

_spec = importlib.util.spec_from_file_location("paper_report", ROOT / "scripts" / "32_paper_report.py")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


class TestDecisionTimes(unittest.TestCase):
    def test_later_closure_does_not_shift_decision_time(self):
        rows = [
            {"date": "2026-11-20", "time": "13:50", "config": "p-friday", "action": "решение"},
            {"date": "2026-11-20", "time": "18:45", "config": "p-friday", "action": "пятница"},
            {"date": "2026-11-20", "time": "10:20", "config": "u-morning", "action": "закрыть"},
        ]
        got = report.decision_times(rows, "2026-11-20")
        self.assertEqual(got["p-friday"], "13:50")
        self.assertEqual(got["u-morning"], "10:20")


class TestRolloverAccounting(unittest.TestCase):
    def test_current_roll_behaviour_is_documented(self):
        """Характеризация текущего учёта, а не одобрение: P&L старой ноги
        признаётся, но строка ролла увеличивает счётчик сделок. Менять без
        сличения с transfer-отчётом брокера нельзя (ADR 24.11, F11)."""
        rows = [
            {"date": "2026-03-18", "time": "13:50", "config": "r",
             "symbol": "RIZ6@RTSX", "price": "100", "target": "2", "action": "решение"},
            {"date": "2026-03-19", "time": "13:50", "config": "r",
             "symbol": "RIZ6@RTSX", "price": "101", "target": "0", "action": "ролл"},
            {"date": "2026-03-19", "time": "13:50", "config": "r",
             "symbol": "RIH6@RTSX", "price": "102", "target": "2", "action": "решение"},
        ]
        trades, pnl, days = report.ledger(rows, 1000.0)
        self.assertEqual(pnl, 2000.0)   # (101-100) × 2 × 1000
        self.assertEqual(trades, 1)     # закрытие старой ноги
        self.assertEqual(days, 2)
        stats = report.trade_stats(rows, 1000.0)
        self.assertEqual(stats[0], 1)


class TestJournalSummary(unittest.TestCase):
    def test_build_rows_reports_journal_only(self):
        """Отчёт считает метрики из журнала, без второго расчёта «ожидания»."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.csv"
            fields = ["date", "time", "config", "action", "price", "target"]
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for day, price, target in (("2026-11-28", "12.29", "1"),
                                           ("2026-11-29", "12.40", "0")):
                    w.writerow({"date": day, "time": "13:50", "config": "p-base",
                                "action": "решение", "price": price, "target": target})
            with mock.patch.object(report, "PAPER", path), \
                 mock.patch.object(report, "active_configs", return_value=[BY_ID["p-base"]]):
                rows, start, end = report.build_rows()
        self.assertEqual((start, end), ("2026-11-28", "2026-11-29"))
        row = next(r for r in rows if r["config"] == "p-base")
        self.assertNotIn("expected", row)
        self.assertNotIn("error", row)
        self.assertEqual(row["trades"], 1)
        self.assertEqual(row["days"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
