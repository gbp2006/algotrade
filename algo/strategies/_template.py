"""Шаблон стратегии. Скопировать в algo/strategies/<имя>.py и переименовать.

Контракт: targets() возвращает ЦЕЛЕВУЮ позицию в контрактах после закрытия каждого
бара. Исполнение, издержки и метрики — в algo/engine.py, здесь их быть не должно.
"""

from __future__ import annotations

import pandas as pd


def targets(
    df: pd.DataFrame,
    period: int = 20,
    entry_time: str = "10:30",
    skip_weekend: bool = True,
) -> pd.Series:
    """Пример: лонг выше MA, шорт ниже, решение раз в сутки.

    df — бары нужного таймфрейма (индекс DatetimeIndex, колонки open/high/low/close/vol).
    Возвращаемое значение: Series[int] по индексу df, значения 0/±N.
    """
    close = df["close"]
    ma = close.rolling(period).mean()

    signal = pd.Series(0, index=df.index, dtype=int)
    signal[close > ma] = 1
    signal[close < ma] = -1
    signal[ma.isna()] = 0

    # одна точка решения в день (реализация — algo.data.daily_first_bar)
    from algo.data import daily_first_bar

    decide = daily_first_bar(df, entry_time)
    if skip_weekend:
        decide = decide & (df.index.day_of_week < 5)

    return signal.where(decide).ffill().fillna(0).astype(int)
