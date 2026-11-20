"""Тесты риск-модуля: лестница ATR, дневной лимит, новые id. ./run.sh test"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo import risk  # noqa: E402
from algo.configs import CONFIGS  # noqa: E402
from algo.live import decision  # noqa: E402
from algo.risk_configs import RISK_CONFIGS  # noqa: E402


def daily(spike: bool = False) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=300, freq="D")
    close = 100 + np.arange(len(idx), dtype=float) * 0.1
    high = close + 1.0
    low = close - 1.0
    if spike:
        high[-1] = close[-1] + 10.0
        low[-1] = close[-1] - 10.0
    return pd.DataFrame({"open": close, "high": high, "low": low,
                         "close": close, "vol": 100.0}, index=idx)


class TestRisk(unittest.TestCase):
    def test_atr_constant(self):
        df = daily()
        self.assertAlmostEqual(float(risk.atr(df).iloc[-1]), 2.0, places=5)

    def test_vol_ratio_and_spike(self):
        self.assertAlmostEqual(risk.vol_ratio(daily()), 1.0, places=5)
        self.assertGreater(risk.vol_ratio(daily(spike=True)), 1.5)

    def test_ladder_boundaries(self):
        limits = risk.RiskLimits()
        cases = [(None, 2.0), (1.0, 2.0), (1.10, 2.0), (1.11, 1.0),
                 (1.25, 1.0), (1.26, 0.5), (1.50, 0.5), (1.51, 0.3), (3.0, 0.3)]
        for ratio, expected in cases:
            self.assertEqual(risk.exposure_for(ratio, limits), expected, ratio)

    def test_daily_loss_guard(self):
        self.assertTrue(risk.daily_loss_allowed(197_000, 200_000))
        self.assertFalse(risk.daily_loss_allowed(192_000, 200_000))
        self.assertFalse(risk.daily_loss_allowed(200_000, 0))

    def test_size_with_risk(self):
        full = risk.size_with_risk(200_000, 12.29, 1000.0, 2.0)
        cut = risk.size_with_risk(200_000, 12.29, 1000.0, 2.0, ratio=2.0)
        self.assertEqual(full, 32)
        self.assertEqual(cut, 4)
        capped = risk.size_with_risk(200_000, 12.29, 1000.0, 2.0,
                                     limits=risk.RiskLimits(max_qty=3))
        self.assertEqual(capped, 3)

    def test_new_configs_not_active_and_signal_compatible(self):
        live_ids = {c.id for c in CONFIGS}
        for cfg in RISK_CONFIGS:
            self.assertNotIn(cfg.id, live_ids)
        idx = pd.date_range("2026-11-20 10:00", "2026-11-20 14:00", freq="5min")
        close = pd.Series(np.linspace(12.20, 12.40, len(idx)), index=idx)
        m5 = pd.DataFrame({"open": close, "high": close, "low": close,
                           "close": close, "vol": 1.0}, index=idx)
        for cfg in RISK_CONFIGS:
            self.assertIsNotNone(decision(cfg, m5, idx[0].date()), cfg.id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
