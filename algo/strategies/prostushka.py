"""«Трендовушка-простушка» (Примечание №6, 10.2024).

Логика:
  - SMA по close, период 40 (M5);
  - одно решение в сутки: первая свеча с временем >= 13:50;
  - close > MA -> лонг, close < MA -> шорт, иначе вне игры;
  - фильтр на вход: за последние 15 минут (3 свечи) не было закрытий против MA;
  - шорт в пятницу запрещён;
  - целевая позиция держится до следующего решения (ровно сутки).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import daily_first_bar


def targets(
    df: pd.DataFrame,
    ma_period: int = 40,
    entry_time: str = "13:50",
    filter_bars: int = 3,
    use_filter_long: bool = True,
    use_filter_short: bool = False,
    allow_short_friday: bool = False,
    skip_weekend: bool = False,
) -> pd.Series:
    close = df["close"]
    ma = close.rolling(ma_period).mean()
    weekday = df.index.day_of_week

    raw = pd.Series(0, index=df.index, dtype=int)
    raw[close > ma] = 1
    raw[close < ma] = -1
    raw[ma.isna()] = 0

    # фильтр: все последние filter_bars закрытий по свою сторону MA
    above = (close > ma).astype(int)
    below = (close < ma).astype(int)
    ok_long = above.rolling(filter_bars).min() == 1
    ok_short = below.rolling(filter_bars).min() == 1

    if use_filter_long:
        raw[(raw == 1) & ~ok_long] = 0
    if use_filter_short:
        raw[(raw == -1) & ~ok_short] = 0
    if not allow_short_friday:
        raw[(raw == -1) & (weekday == 4)] = 0

    decide = daily_first_bar(df, entry_time)
    if skip_weekend:
        # в субботу/воскресенье решения нет: позиция живёт с пятницы до понедельника
        decide = decide & (weekday < 5)
    daily = raw.where(decide)
    # держим позицию до следующего решения
    return daily.ffill().fillna(0).astype(int)
