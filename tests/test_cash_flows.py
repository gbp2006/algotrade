"""Тесты денежных потоков и предпросмотра лотности. ./run.sh test"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.cash_flows import (  # noqa: E402
    CashFlow, CashFlowType, InsufficientPolicy, Reaction, RobotSizing,
    stress_preview, preview_cash_flow, validate_cash_flow,
)
from algo.portfolio import GO  # noqa: E402


def robot(**kwargs) -> RobotSizing:
    base = dict(robot_id="p-base", name="Простушка", price=12.29, exposure=2.0)
    base.update(kwargs)
    return RobotSizing(**base)


class TestCashFlows(unittest.TestCase):
    def test_detect_and_delta(self):
        flow = CashFlow.detect(CashFlowType.DEPOSIT, 100_000, 200_000)
        self.assertEqual(flow.balance_after, 300_000)
        self.assertEqual(flow.delta, 100_000)
        withdrawal = CashFlow.detect(CashFlowType.WITHDRAWAL, 50_000, 200_000)
        self.assertEqual(withdrawal.balance_after, 150_000)
        self.assertEqual(withdrawal.delta, -50_000)

    def test_deposit_increases_lots_immediately(self):
        flow = CashFlow.detect(CashFlowType.DEPOSIT, 100_000, 200_000)
        preview = preview_cash_flow(flow, [robot()])
        impact = preview.impacts[0]
        self.assertEqual(impact.lots_before, 32)
        self.assertEqual(impact.lots_after, 48)
        self.assertEqual(impact.effective_lots, 48)
        self.assertEqual(impact.status.value, "INCREASED")
        self.assertEqual(preview.free_after, 300_000 - 48 * GO)
        self.assertTrue(preview.valid)

    def test_withdrawal_reduces_lots(self):
        flow = CashFlow.detect(CashFlowType.WITHDRAWAL, 100_000, 200_000)
        preview = preview_cash_flow(flow, [robot()])
        impact = preview.impacts[0]
        self.assertEqual(impact.lots_before, 32)
        self.assertEqual(impact.lots_after, 16)
        self.assertEqual(impact.status.value, "REDUCED")
        self.assertEqual(preview.free_after, 100_000 - 16 * GO)

    def test_withdrawal_above_balance_is_blocked(self):
        flow = CashFlow.detect(CashFlowType.WITHDRAWAL, 250_000, 200_000)
        preview = preview_cash_flow(flow, [robot()])
        self.assertFalse(preview.valid)
        self.assertTrue(any("недостаточно" in e for e in preview.validation.errors))
        self.assertEqual(preview.impacts[0].effective_lots, 0)

    def test_insufficient_margin_pauses_second_robot(self):
        bots = [robot(robot_id=f"r{i}", price=1.0, mult=1.0, exposure=2.0,
                      max_lots=2, margin_per_lot=90_000) for i in (1, 2)]
        preview = preview_cash_flow(
            CashFlow.detect(CashFlowType.DEPOSIT, 1_000, 200_000), bots)
        first, second = preview.impacts
        self.assertEqual(first.effective_lots, 2)
        self.assertEqual(first.status.value, "UNCHANGED")
        self.assertEqual(second.effective_lots, 0)
        self.assertEqual(second.status.value, "PAUSED")
        self.assertTrue(any("запрещены" in w for w in preview.validation.warnings))

    def test_min_lot_policy_and_zero_on_bad_data(self):
        bots = [robot(price=1.0, mult=1.0, margin_per_lot=120_000, max_lots=2,
                      on_insufficient=InsufficientPolicy.MIN_LOT, min_lots=1)]
        preview = preview_cash_flow(
            CashFlow.detect(CashFlowType.DEPOSIT, 1_000, 200_000), bots)
        self.assertEqual(preview.impacts[0].effective_lots, 1)
        empty = preview_cash_flow(
            CashFlow.detect(CashFlowType.WITHDRAWAL, 200_000, 200_000),
            [robot(min_lots=5)])
        self.assertEqual(empty.impacts[0].lots_after, 0)

    def test_after_close_defers_while_position_open(self):
        flow = CashFlow.detect(CashFlowType.WITHDRAWAL, 100_000, 200_000)
        bot = robot(reaction=Reaction.AFTER_CLOSE, position_lots=2)
        deferred = preview_cash_flow(flow, [bot]).impacts[0]
        self.assertEqual(deferred.lots_before, 32)
        self.assertEqual(deferred.lots_after, 32)
        self.assertEqual(deferred.status.value, "DEFERRED")
        self.assertEqual(deferred.effective_lots, 32)

        closed = preview_cash_flow(flow, [robot(reaction=Reaction.AFTER_CLOSE)]).impacts[0]
        self.assertEqual(closed.lots_after, 16)
        self.assertEqual(closed.status.value, "REDUCED")

    def test_smoothed_reaction_threshold(self):
        bot = robot(reaction=Reaction.SMOOTHED, smoothing_pct=10, sizing_base=200_000)
        small = preview_cash_flow(
            CashFlow.detect(CashFlowType.DEPOSIT, 5_000, 200_000), [bot]).impacts[0]
        self.assertEqual(small.status.value, "DEFERRED")
        self.assertEqual(small.lots_after, 32)

        big = preview_cash_flow(
            CashFlow.detect(CashFlowType.DEPOSIT, 30_000, 200_000), [bot]).impacts[0]
        self.assertEqual(big.status.value, "INCREASED")
        self.assertEqual(big.lots_after, 37)

    def test_idempotency_by_broker_tx_and_client_key(self):
        first = CashFlow.detect(CashFlowType.DEPOSIT, 10_000, 200_000,
                                broker_tx_id="tx-42")
        second = CashFlow.detect(CashFlowType.DEPOSIT, 10_000, 200_000,
                                 broker_tx_id="tx-42")
        self.assertEqual(first.key, second.key)
        preview = preview_cash_flow(first, known_keys=[second.key])
        self.assertFalse(preview.valid)
        self.assertTrue(any("повтор операции" in e for e in preview.validation.errors))
        local = CashFlow.detect(CashFlowType.DEPOSIT, 10_000, 200_000,
                                client_key="virtual-1")
        self.assertEqual(local.key, "client:virtual-1")

    def test_two_level_validation(self):
        bad = validate_cash_flow(
            CashFlow.detect(CashFlowType.DEPOSIT, 0, 200_000))
        self.assertFalse(bad.ok)
        self.assertTrue(any("положительной" in e for e in bad.errors))

        big = validate_cash_flow(
            CashFlow.detect(CashFlowType.DEPOSIT, 100_000, 200_000))
        self.assertTrue(big.ok)
        self.assertTrue(big.needs_confirmation)
        self.assertTrue(any("крупная" in w for w in big.warnings))

        live = validate_cash_flow(
            CashFlow.detect(CashFlowType.DEPOSIT, 1_000, 200_000), live=True)
        self.assertTrue(any("LIVE" in w for w in live.warnings))

    def test_virtual_reset_and_rows(self):
        flow = CashFlow.detect(CashFlowType.VIRTUAL_RESET, 150_000, 200_000)
        self.assertEqual(flow.balance_after, 150_000)
        preview = preview_cash_flow(flow, [robot()])
        self.assertTrue(preview.valid)
        self.assertEqual(preview.as_rows()[0]["lots_before"], 32)
        self.assertEqual(preview.as_rows()[0]["lots_after"], 24)

    def test_stress_preview_does_not_mutate_balance(self):
        preview = stress_preview(200_000, 30, [robot()])
        self.assertEqual(preview.flow.balance_after, 140_000)
        self.assertEqual(preview.impacts[0].lots_after, 22)
        self.assertEqual(preview.impacts[0].status.value, "REDUCED")

    def test_unknown_type_is_rejected(self):
        with self.assertRaises(ValueError):
            CashFlow.detect("BONUS", 100, 200_000)


if __name__ == "__main__":
    unittest.main()
