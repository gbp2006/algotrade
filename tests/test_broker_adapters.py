"""Реестр адаптеров: зарегистрирован только рабочий брокер. ./run.sh test"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algo.broker import registry  # noqa: E402


class TestBrokerAdapters(unittest.TestCase):
    def test_registry_has_finam_only(self):
        names = registry.available()
        self.assertIn("finam", names)
        self.assertNotIn("tinvest", names)
        with self.assertRaises(ValueError):
            registry.get_adapter("tinvest")


if __name__ == "__main__":
    unittest.main()
