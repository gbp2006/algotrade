"""Тест отчёта: ожидание учитывает пятничное закрытие p-friday."""

from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
from dataclasses import replace
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.configs import BY_ID  # noqa: E402

_spec = importlib.util.spec_from_file_location("paper_report", ROOT / "scripts" / "32_paper_report.py")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def m5() -> pd.DataFrame:
    parts = []
    for day in pd.date_range("2026-11-16", "2026-11-20", freq="D"):
        idx = pd.date_range(f"{day.date()} 10:00", f"{day.date()} 19:00", freq="5min")
        close = pd.Series(np.linspace(12.10, 12.30, len(idx)), index=idx)
        parts.append(pd.DataFrame({"open": close, "high": close, "low": close,
                                   "close": close, "vol": 1.0}, index=idx))
    return pd.concat(parts)


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


class TestVersionedExpectation(unittest.TestCase):
    def test_cfg_for_changes_expectation_from_given_day(self):
        bars = m5()
        # p-friday на этих барах даёт сделку; сдвиг времени входа меняет ожидание
        base = BY_ID["p-friday"]
        alt = replace(base, params={**base.params, "entry": "13:40"})
        args = (bars, "2026-11-16", "2026-11-20", 1000.0, 200_000)
        flat = report.expected(base, *args, cfg_for=lambda d: base)[1]
        switched = report.expected(
            base, *args,
            cfg_for=lambda d: alt if str(d) >= "2026-11-16" else base)[1]
        self.assertIsNotNone(flat)
        self.assertIsNotNone(switched)
        self.assertNotEqual(flat, switched)


class TestFridayExpectation(unittest.TestCase):
    def test_friday_close_modelled(self):
        bars = m5()
        base = report.expected(BY_ID["p-base"], bars, "2026-11-16", "2026-11-20",
                               1000.0, 200_000)
        friday = report.expected(BY_ID["p-friday"], bars, "2026-11-16", "2026-11-20",
                                 1000.0, 200_000)
        self.assertIsNotNone(base[1])
        self.assertIsNotNone(friday[1])
        self.assertGreater(friday[0], base[0], "ожидание должно включать закрытие в 18:45")
        with_tick = report.expected(BY_ID["p-friday"], bars, "2026-11-16", "2026-11-20",
                                    1000.0, 200_000, tick=0.001)
        self.assertLess(with_tick[1], friday[1], "проскальзывание на выходе должно учитываться")


class TestCompareWindow(unittest.TestCase):
    def _build(self, dates):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.csv"
            fields = ["date", "time", "config", "action", "price", "target"]
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for day in dates:
                    w.writerow({"date": day, "time": "13:50", "config": "p-base",
                                "action": "решение", "price": "12.29", "target": "1"})
            with mock.patch.object(report, "PAPER", path), \
                 mock.patch.object(report, "active_configs", return_value=[]), \
                 mock.patch.object(report, "configs_at", return_value=[]), \
                 mock.patch.object(report, "expected_bars", return_value=m5()), \
                 mock.patch.object(report, "expected",
                                   return_value=(1, 100.0)) as expected:
                rows, _, _ = report.build_rows()
        return rows, expected

    def test_old_dates_are_not_compared(self):
        rows, expected = self._build(["2026-11-19", "2026-11-20"])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["error"])
        self.assertIsNone(rows[0]["expected"])
        expected.assert_not_called()

    def test_new_dates_are_compared(self):
        rows, expected = self._build(["2026-11-28", "2026-11-29"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error"], -100.0)
        expected.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
