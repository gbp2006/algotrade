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
from algo.configs import CONFIGS, Config  # noqa: E402
from algo.live import decision  # noqa: E402
from algo.risk_configs import RISK_CONFIGS  # noqa: E402
from algo.robot_configs import ROBOT_CONFIGS  # noqa: E402


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

    def test_contracts_for_config_plain(self):
        cfg = Config("t-plain", "prostushka", dict(ma_window=200, entry="13:50"))
        from algo import portfolio
        n, note = risk.contracts_for_config(cfg, 200_000, 12.29, 1000.0,
                                            daily(), [], "2025-01-01", 200_000)
        # без флагов — базовый exposure из окружения (1.0 по умолчанию, 2.0 в .env)
        self.assertEqual(n, portfolio.size_contracts(200_000, 12.29, 1000.0,
                                                     portfolio.EXPOSURE))
        self.assertEqual(note, "")

    def test_contracts_for_config_vol_cut(self):
        cfg = Config("t-vol", "prostushka", dict(ma_window=200, entry="13:50", risk_vol=True))
        n, note = risk.contracts_for_config(cfg, 200_000, 12.29, 1000.0,
                                            daily(spike=True), [], "2025-01-01", 200_000)
        self.assertLess(n, 32)
        self.assertIn("ATR", note)

    def test_contracts_for_config_daily_loss(self):
        cfg = Config("t-loss", "prostushka",
                     dict(ma_window=200, entry="13:50", risk_daily_loss=True))
        rows = [{"config": "t-loss", "date": "2025-01-01", "target": 0, "price": "100"}]
        n, note = risk.contracts_for_config(cfg, 192_000, 12.29, 1000.0,
                                            daily(), rows, "2025-01-02", 200_000)
        self.assertEqual(n, 0)
        self.assertIn("дневной лимит", note)

    def test_new_configs_not_active_and_signal_compatible(self):
        live_ids = {c.id for c in CONFIGS}
        for cfg in RISK_CONFIGS:
            self.assertNotIn(cfg.id, live_ids)

    def test_robots_have_risk_and_unique_ids(self):
        ids = [c.id for c in ROBOT_CONFIGS]
        self.assertEqual(len(ids), 6)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(set(ids) & {c.id for c in CONFIGS})
        idx = pd.date_range("2026-11-18 09:00", "2026-11-20 14:00", freq="5min")
        m5 = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                           "close": 100.0, "vol": 1.0}, index=idx)
        for cfg in ROBOT_CONFIGS:
            self.assertTrue(cfg.params.get("risk_vol"), cfg.id)
            if cfg.strategy == "channel_break":
                from algo.channel_live import channel_decision
                self.assertIsNotNone(channel_decision(cfg.params, m5), cfg.id)
            else:
                self.assertIsNotNone(decision(cfg, m5, idx[0].date()), cfg.id)
        idx = pd.date_range("2026-11-20 10:00", "2026-11-20 14:00", freq="5min")
        close = pd.Series(np.linspace(12.20, 12.40, len(idx)), index=idx)
        m5 = pd.DataFrame({"open": close, "high": close, "low": close,
                           "close": close, "vol": 1.0}, index=idx)
        for cfg in RISK_CONFIGS:
            self.assertIsNotNone(decision(cfg, m5, idx[0].date()), cfg.id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
