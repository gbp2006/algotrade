"""Тесты ссылок на ключи счетов: секрет не должен попадать в код и журналы."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.broker.secrets import SecretError, resolve_secret  # noqa: E402


class TestResolveSecret(unittest.TestCase):
    def test_from_auth_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            path.write_text(json.dumps({"finam": {"КлФ-2102993": "tapi_sk_test"}}),
                            encoding="utf-8")
            self.assertEqual(resolve_secret("КлФ-2102993", auth_path=path), "tapi_sk_test")

    def test_from_env(self):
        os.environ["FINAM_SECRET_TEST"] = "tapi_sk_env"
        try:
            self.assertEqual(resolve_secret("{env:FINAM_SECRET_TEST}"), "tapi_sk_env")
        finally:
            os.environ.pop("FINAM_SECRET_TEST", None)

    def test_empty_ref(self):
        with self.assertRaises(SecretError) as ctx:
            resolve_secret("")
        self.assertIn("key_ref", str(ctx.exception))

    def test_missing_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            path.write_text(json.dumps({"finam": {"other": "x"}}), encoding="utf-8")
            with self.assertRaises(SecretError):
                resolve_secret("КлФ-2102993", auth_path=path)

    def test_error_does_not_leak_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            path.write_text(json.dumps({"finam": {"a": "tapi_sk_SECRET_VALUE"}}),
                            encoding="utf-8")
            with self.assertRaises(SecretError) as ctx:
                resolve_secret("b", auth_path=path)
            self.assertNotIn("SECRET_VALUE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
