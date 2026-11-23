"""Система Резвякова «восходящий/нисходящий range» — исследовательский порт.

Источник: https://smart-lab.ru/blog/1130044.php (видео «5-6 идей для построения
прибыльной торговой системы на фьючерсах», 2024; код на Python в статье).

Правила автора:
  - вход строго в 10:00;
  - лонг, если максимум и минимум каждого из последних двух дней выше
    предыдущих; шорт — если оба ниже;
  - выход в 20:40 по времени;
  - трейлинг 2% от лучшего закрытия сделки (лонг) / худшего (шорт).

Уровни последних двух дней берутся по завершённым дневным барам, поэтому
решение в 10:00 не подглядывает в текущий день. Исполнение — по open следующего
M5-бара, как в остальном движке. research-only, конфигов нет.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .candidates import daily_bars

DEFAULT_ENTRY = "10:00"
DEFAULT_EXIT = "20:40"


def rezvyakov_targets(
    df: pd.DataFrame, entry: str = DEFAULT_ENTRY, exit_time: str = DEFAULT_EXIT,
    trail: float = 0.02, allow_short: bool = True, skip_weekend: bool = True,
) -> pd.Series:
    """Целевая позиция на M5-барах: +1/-1 с 10:00 до 20:40, затем 0."""
    d = daily_bars(df)
    hi1, lo1 = d["high"].shift(1), d["low"].shift(1)
    hi2, lo2 = d["high"].shift(2), d["low"].shift(2)
    flags = pd.DataFrame({
        "up": (hi1 > hi2) & (lo1 > lo2),
        "down": (hi1 < hi2) & (lo1 < lo2),
    }, index=d.index)

    eh, em = (int(x) for x in entry.split(":"))
    xh, xm = (int(x) for x in exit_time.split(":"))
    e_min, x_min = eh * 60 + em, xh * 60 + xm

    out = np.zeros(len(df), dtype=int)
    pos = 0
    best = 0.0          # максимум close с входа (лонг)
    worst = 0.0         # минимум close с входа (шорт)
    for date, day in df.groupby(df.index.normalize()):
        idx = df.index.get_indexer(day.index)
        tm = day.index.hour.to_numpy() * 60 + day.index.minute.to_numpy()
        close = day["close"].to_numpy(dtype=float)
        flag = flags.loc[date] if date in flags.index else None
        prev = np.concatenate([[np.nan], close[:-1]])  # закрытие предыдущего бара

        if skip_weekend and date.day_of_week >= 5:
            out[idx] = 0
            pos, best, worst = 0, 0.0, 0.0
            continue

        entry_i = np.flatnonzero(tm >= e_min)
        entry_i = int(entry_i[0]) if len(entry_i) else len(day)

        for j in range(len(day)):
            if tm[j] >= x_min or j < entry_i:
                pos = 0
                out[idx[j]] = 0
            else:
                if pos == 0 and j == entry_i and flag is not None:
                    if bool(flag["up"]):
                        pos, best = 1, float(prev[j]) if np.isfinite(prev[j]) else close[j]
                    elif allow_short and bool(flag["down"]):
                        pos, worst = -1, float(prev[j]) if np.isfinite(prev[j]) else close[j]
                if pos != 0 and np.isfinite(prev[j]):
                    if pos == 1:
                        if prev[j] < best * (1.0 - trail):
                            pos = 0
                        else:
                            best = max(best, float(prev[j]))
                    else:
                        if prev[j] > worst * (1.0 + trail):
                            pos = 0
                        else:
                            worst = min(worst, float(prev[j]))
                out[idx[j]] = pos
            # лучше/худшее закрытие текущего бара понадобится на следующем
            if pos == 1:
                best = max(best, close[j])
            elif pos == -1:
                worst = min(worst, close[j])

        if tm[-1] >= x_min:
            pos, best, worst = 0, 0.0, 0.0

    return pd.Series(out, index=df.index, name="rezvyakov_target")
