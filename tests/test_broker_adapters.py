"""Мультиброкерный контур: адаптер Т‑Инвестиций и маппинг инструментов. ./run.sh test"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.broker import registry  # noqa: E402
from algo.broker.base import OrderRequest  # noqa: E402
from algo.broker.instrument_map import InstrumentMap, InstrumentMapping  # noqa: E402
from algo.broker.tinvest_adapter import NotConfiguredError, TInvestAdapter  # noqa: E402


class TestBrokerAdapters(unittest.TestCase):
    def test_registry_has_finam_and_tinvest(self):
        names = registry.available()
        self.assertIn("finam", names)
        self.assertIn("tinvest", names)
        adapter = registry.get_adapter("tinvest", sandbox=True)
        self.assertEqual(adapter.mode, "TEST")

    def test_tinvest_without_token_is_inert(self):
        adapter = TInvestAdapter()
        status = adapter.check_connection()
        self.assertFalse(status.ok)
        self.assertIn("не настроен", status.detail)
        with self.assertRaises(NotConfiguredError):
            adapter.account("A1")
        with self.assertRaises(NotConfiguredError):
            adapter.place_order(OrderRequest("SBER@MISX", "buy", 1))

    def test_instrument_mapping(self):
        mapping = InstrumentMap()
        mapping.register(InstrumentMapping("SBER", "SBER@MISX", figi="BBG004730N88",
                                          uid="uid-1", board="TQBR"))
        self.assertEqual(mapping.resolve("sber", "finam"), "SBER@MISX")
        self.assertEqual(mapping.resolve("SBER", "tinvest"), "uid-1")
        self.assertEqual(mapping.resolve("UNKNOWN"), "UNKNOWN")
        self.assertEqual(len(mapping.all()), 1)
        self.assertEqual(mapping.get("SBER").figi, "BBG004730N88")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
