"""Тест отчёта: ожидание учитывает пятничное закрытие p-friday."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
