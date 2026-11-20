"""Юнит-тесты стратегии «пробой временного канала». Запуск: ./run.sh test"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algo.strategies import channel_break  # noqa: E402


def evening_df(baselines: list[float], surprise: dict | None = None) -> pd.DataFrame:
    """Синтетика: бары 07:00..23:50, вечерний канал 15:00..23:40."""
    rows = []
    days = pd.date_range("2026-01-05", periods=len(baselines), freq="D")
    surprise = surprise or {}
    for d, base in zip(days, baselines):
        for t in pd.date_range(d + pd.Timedelta(hours=7), periods=102, freq="10min"):  # 07:00..23:50
            mod = t.hour * 60 + t.minute
            high, low, close = base + 1, base - 1, base
            if mod == 15 * 60:
                high, low = base + 10, base - 10
            if mod == 16 * 60:
                high, low = base + 12, base - 12
            if t in surprise:
                close, high, low = surprise[t]
            rows.append((t, base, high, low, close))
    df = pd.DataFrame(rows, columns=["dt", "open", "high", "low", "close"]).set_index("dt")
    df["vol"] = 1.0
    return df


class TestChannelBreak(unittest.TestCase):
    def test_night_channel_direction_and_time_exit(self):
        df = evening_df([100, 105, 110, 115])
        sig = pd.Timestamp("2026-01-08 17:00")
        df.loc[sig, ["close", "high", "low"]] = [130, 130, 130]
        t = channel_break.targets(df, start_time="23:40", switch_time="15:00")
        # канал предыдущего вечера: HH=122 LL=98, dir=+1 (110 >= 105)
        self.assertEqual(t.loc["2026-01-08 16:50"], 0)
        self.assertEqual(t.loc[sig], 1)                    # close 130 > HH 122
        self.assertEqual(t.loc["2026-01-08 23:30"], 1)
        self.assertEqual(t.loc["2026-01-08 23:40"], 0)     # выход по границе start

    def test_short_and_direction_filter(self):
        df = evening_df([110, 100, 95, 90])
        sig = pd.Timestamp("2026-01-08 17:00")
        df.loc[sig, ["close", "high", "low"]] = [80, 80, 80]
        t = channel_break.targets(df, start_time="23:40", switch_time="15:00")
        # dir=-1 (95 < 100), канал LL=83 -> шорт
        self.assertEqual(t.loc[sig], -1)
        self.assertEqual(t.loc["2026-01-08 23:30"], -1)
        only_long = channel_break.targets(
            df, start_time="23:40", switch_time="15:00", direction="long"
        )
        self.assertTrue((only_long == 0).all())

    def test_stop_approximation(self):
        df = evening_df([100, 105, 110, 115])
        sig = pd.Timestamp("2026-01-08 17:00")
        df.loc[sig, ["close", "high", "low"]] = [130, 130, 130]
        breach = pd.Timestamp("2026-01-08 18:00")
        df.loc[breach, "low"] = 100.0   # стоп max(LL=98, 115-10=105) пробит
        no_sl = channel_break.targets(df, start_time="23:40", switch_time="15:00")
        with_sl = channel_break.targets(
            df, start_time="23:40", switch_time="15:00", sl=10.0, trail_to_channel=False
        )
        self.assertEqual(no_sl.loc[breach], 1)
        self.assertEqual(with_sl.loc[breach], 0)  # выход на open следующего бара

    def test_literal_0100_channel(self):
        rows = []
        for d in pd.date_range("2026-01-05", periods=3, freq="D"):
            for t in pd.date_range(d, periods=24, freq="1h"):
                base = {0: 90.0, 1: 100.0, 2: 100.0}[(t - pd.Timestamp("2026-01-05")).days]
                high, low, close = base + 1, base - 1, base
                if t.day == 6 and t.hour >= 15:
                    high, low = base + 20, base - 20
                if t == pd.Timestamp("2026-01-06 00:00"):
                    high, low = base + 25, base - 25
                if t == pd.Timestamp("2026-01-06 16:00"):
                    close = 130.0
                rows.append((t, base, high, low, close))
        df = pd.DataFrame(rows, columns=["dt", "open", "high", "low", "close"]).set_index("dt")
        df["vol"] = 1.0
        # буквальный режим: метка 01:00 есть -> канал 15:00 дня 1 -> 01:00 дня 2
        t = channel_break.targets(df)  # start=01:00, switch=15:00 (как в ТЗ)
        # HH=125 LL=70; dir=+1 (100 >= 90)
        self.assertEqual(t.loc["2026-01-06 16:00"], 1)
        self.assertEqual(t.loc["2026-01-07 00:00"], 1)
        self.assertEqual(t.loc["2026-01-07 01:00"], 0)  # выход в 01:00 дня 3
        # если данных 01:00 нет (MOEX), OsEngine не нашёл бы границу -> 0 сделок
        no_night = df.loc[df.index.hour >= 7]
        self.assertTrue((channel_break.targets(no_night) == 0).all())
        self.assertTrue((channel_break.targets(
            no_night, boundary_mode="first_bar") != 0).any())  # молчаливая подстановка


if __name__ == "__main__":
    unittest.main()
