"""Тесты стража бумажного контура: свежесть данных и алерты. ./run.sh test"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("watchdog", ROOT / "scripts" / "40_watchdog.py")
wd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wd)


class TestWatchdog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "results").mkdir()
        self.paper = self.dir / "results" / "paper.csv"
        self.stop = self.dir / "results" / "STOP"
        self.addCleanup(self.tmp.cleanup)

    def _journal(self, day: str | None = None):
        day = day or str(date.today())
        header = "date,time,config,instrument,symbol,strategy,price,signal,target,contracts,equity_before,action,position_after,note\n"
        lines = [header]
        for cfg in wd.DECISION_CONFIGS:
            lines.append(f"{day},13:50,{cfg},CNY,CNYRUBF@RTSX,prostushka,12.29,0,0,0,200000,решение,0,тест\n")
        self.paper.write_text("".join(lines), encoding="utf-8")

    def _patches(self, data_date="2026-11-20"):
        return [
            mock.patch.object(wd, "ROOT", self.dir),
            mock.patch.object(wd, "PAPER", self.paper),
            mock.patch.object(wd, "STOP", self.stop),
            mock.patch.object(wd, "STOP_REAL", self.dir / "results" / "STOP_REAL"),
            mock.patch.object(wd, "BACKUP_STATE", self.dir / "results" / "backup.json"),
            mock.patch.object(wd, "data_freshness", lambda: data_date),
            mock.patch.object(wd, "decision_configs",
                              lambda rows: list(wd.DECISION_CONFIGS)),
        ]

    def test_decision_configs_follow_active_instances(self):
        rows = [{"config": "p-new"}, {"config": "gone-old"}]
        with mock.patch("algo.instance_configs.active_configs",
                        return_value=[mock.Mock(id="p-new")]):
            self.assertEqual(wd.decision_configs(rows), ["p-new"])
        with mock.patch("algo.instance_configs.active_configs",
                        side_effect=RuntimeError("нет store")):
            self.assertEqual(wd.decision_configs(rows), wd.DECISION_CONFIGS)

    def test_new_config_not_expected_on_old_days(self):
        today, old = date.today(), date.today() - timedelta(days=1)
        header = ("date,time,config,instrument,symbol,strategy,price,signal,target,"
                  "contracts,equity_before,action,position_after,note\n")
        lines = [header]
        for d in (old, today):
            for cfg in wd.DECISION_CONFIGS:
                lines.append(f"{d},13:50,{cfg},CNY,CNYRUBF@RTSX,prostushka,12.29,0,0,0,200000,решение,0,тест\n")
        lines.append(f"{today},13:50,p-new,CNY,CNYRUBF@RTSX,prostushka,12.29,0,0,0,200000,решение,0,новый\n")
        self.paper.write_text("".join(lines), encoding="utf-8")
        patches = self._patches()[:-1] + [
            mock.patch.object(wd, "decision_configs",
                              lambda rows: list(wd.DECISION_CONFIGS) + ["p-new"])]
        for p in patches:
            p.start()
        try:
            res = wd.check()
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertFalse(any(str(old) in p for p in res["problems"]), res["problems"])

    def test_check_ok_when_all_present(self):
        self._journal()
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            res = wd.check()
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["data_date"], "2026-11-20")

    def test_stale_data_is_warning(self):
        self._journal()
        patches = self._patches(data_date="2026-11-01")
        for p in patches:
            p.start()
        try:
            res = wd.check()
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertTrue(any("устарели" in w for w in res["warnings"]), res)

    def test_stop_real_is_warning(self):
        self._journal()
        (self.dir / "results" / "STOP_REAL").write_text("установлен из панели\n", encoding="utf-8")
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            res = wd.check()
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertTrue(res["stop_real"])
        self.assertTrue(any("STOP_REAL" in w for w in res["warnings"]), res)

    def test_backup_freshness_is_warning(self):
        self._journal()
        state = self.dir / "results" / "backup.json"
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            state.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds")}),
                             encoding="utf-8")
            fresh = wd.check()
            old = datetime.now() - timedelta(hours=48)
            state.write_text(json.dumps({"at": old.isoformat(timespec="seconds")}),
                             encoding="utf-8")
            stale = wd.check()
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertFalse(any("бэкапы: последний снимок" in w for w in fresh["warnings"]), fresh)
        self.assertTrue(any("бэкапы: последний снимок" in w for w in stale["warnings"]), stale)

    def test_data_freshness_reads_live_csv(self):
        csv_text = "dt,open,high,low,close,vol\n2026-11-19 13:45:00,1,1,1,1,1\n2026-11-19 13:50:00,2,2,2,2,2\n"
        (self.dir / "results" / "finam_m5_CNY.csv").write_text(csv_text, encoding="utf-8")
        with mock.patch.object(wd, "ROOT", self.dir):
            self.assertEqual(wd.data_freshness(), "2026-11-19")


if __name__ == "__main__":
    unittest.main(verbosity=2)
