"""Базовые тесты переиспользуемого ATR-модуля (по умолчанию выключен)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import atr as mod  # noqa: E402


def bars(spike: bool = False) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=300, freq="D")
    close = 100 + np.arange(len(idx), dtype=float) * 0.1
    high, low = close + 1.0, close - 1.0
    if spike:
        high[-1], low[-1] = close[-1] + 10.0, close[-1] - 10.0
    return pd.DataFrame({"open": close, "high": high, "low": low,
                         "close": close, "vol": 100.0}, index=idx)


class TestAtr(unittest.TestCase):
    def test_constant_range(self):
        self.assertAlmostEqual(float(mod.atr(bars()).iloc[-1]), 2.0, places=5)

    def test_ratio_and_spike(self):
        self.assertAlmostEqual(mod.vol_ratio(bars()), 1.0, places=5)
        self.assertGreater(mod.vol_ratio(bars(spike=True)), 1.5)

    def test_ladder(self):
        for ratio, expected in ((None, 2.0), (1.0, 2.0), (1.11, 1.0),
                                (1.26, 0.5), (1.51, 0.3)):
            self.assertEqual(mod.exposure_for(ratio), expected)

    def test_disabled_by_default(self):
        self.assertFalse(mod.enabled(None))
        self.assertFalse(mod.enabled({}))
        self.assertFalse(mod.enabled({"risk_vol": False}))
        self.assertTrue(mod.enabled({"risk_vol": True}))

    def test_size_cut_only_when_called(self):
        full = mod.size(200_000, 12.29, 1000.0, 2.0)
        cut = mod.size(200_000, 12.29, 1000.0, 2.0, ratio=2.0)
        self.assertGreater(full, cut)


if __name__ == "__main__":
    unittest.main()
