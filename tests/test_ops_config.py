"""Конфиги обслуживания: ротация логов и лимиты journald. ./run.sh test"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestOpsConfig(unittest.TestCase):
    def test_logrotate_keeps_eight_weeks_and_copytruncate(self):
        text = (ROOT / "infra" / "logrotate" / "algotrading").read_text(encoding="utf-8")
        for directive in ("weekly", "rotate 8", "compress", "copytruncate",
                          "missingok", "notifempty"):
            self.assertIn(directive, text)
        self.assertIn("results/*.log", text)

    def test_journald_limits(self):
        text = (ROOT / "infra" / "systemd" / "journald-algo.conf").read_text(encoding="utf-8")
        self.assertIn("[Journal]", text)
        self.assertIn("SystemMaxUse=200M", text)
        self.assertIn("MaxRetentionSec=1month", text)

    def test_backup_timer_is_in_deploy_whitelist(self):
        script = (ROOT / "scripts" / "deploy_wsl.sh").read_text(encoding="utf-8")
        for pattern in ("infra/systemd/*.timer", "infra/logrotate/*"):
            self.assertIn(pattern, script)


if __name__ == "__main__":
    unittest.main()
