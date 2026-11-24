"""Презентационный слой панели: общий словарь подписей и человекочитаемые шаблоны. ./run.sh test"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "web" / "templates"
STATIC = ROOT / "web" / "static"
PAGES = ("index", "trade", "robots", "accounts", "health")


class TestUILabels(unittest.TestCase):
    def test_helpers_defined(self):
        js = (STATIC / "ui-labels.js").read_text(encoding="utf-8")
        for name in ("orderStatus", "robotStatus", "mode", "health", "side",
                     "source", "humanName", "money", "qty", "instrumentGroup",
                     "byTypePhrase", "decision"):
            self.assertIn(name + ",", js, name)

    def test_every_page_loads_dictionary(self):
        for page in PAGES:
            html = (TEMPLATES / f"{page}.html").read_text(encoding="utf-8")
            self.assertIn('/static/ui-labels.js', html, page)

    def test_no_raw_json_status_in_templates(self):
        for page in PAGES:
            html = (TEMPLATES / f"{page}.html").read_text(encoding="utf-8")
            self.assertNotIn('JSON.stringify(r.by_type)', html, page)
            self.assertNotIn('JSON.stringify(s.counts)', html, page)

    def test_instrument_grouping(self):
        js = (STATIC / "ui-labels.js").read_text(encoding="utf-8")
        for group in ("Валютные фьючерсы", "Индексы", "Сырьё и золото",
                      "Акции", "Фонды и паи"):
            self.assertIn(group, js)

    def test_inline_scripts_parse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node недоступен")
        sources = [STATIC / "ui-labels.js", STATIC / "sidebar.js"]
        with tempfile.TemporaryDirectory() as tmp:
            for page in PAGES:
                html = (TEMPLATES / f"{page}.html").read_text(encoding="utf-8")
                blocks = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.S)
                js = "\n".join(b for b in blocks if b.strip())
                self.assertTrue(js, page)
                path = Path(tmp) / f"{page}.js"
                path.write_text(js, encoding="utf-8")
                sources.append(path)
            for path in sources:
                res = subprocess.run([node, "--check", str(path)],
                                     capture_output=True, text=True, timeout=20)
                self.assertEqual(res.returncode, 0, f"{path.name}: {res.stderr[:400]}")


if __name__ == "__main__":
    unittest.main()
