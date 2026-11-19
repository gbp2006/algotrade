"""MVP-логика: сигнал на сегодня и проверка качества данных."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .data import daily_first_bar, load_cached
from .strategies import prostushka

SECID = "CNYRUBF"
MA = 40
ENTRY = "13:50"
FILTER_BARS = 3
GO = 984.55
MULT = 1000.0


@dataclass
class Signal:
    last_bar: pd.Timestamp
    last_price: float
    ma: float
    signal: int
    target: int
    decision_time: pd.Timestamp | None
    decision_price: float
    ma_decision: float
    warnings: list[str]
    bars_last_day: int
    decided_today: bool


def compute(ma_period: int = MA, entry_time: str = ENTRY) -> Signal:
    m5 = load_cached(f"2026-11/{SECID}.txt", 5)
    tg = prostushka.targets(
        m5, ma_period=ma_period, entry_time=entry_time,
        filter_bars=FILTER_BARS, skip_weekend=True,
    )

    warnings: list[str] = []
    last_bar = m5.index[-1]
    age_days = (date.today() - last_bar.date()).days
    if age_days > 3:
        warnings.append(f"данные устарели на {age_days} дн.")

    last_day = m5[m5.index.normalize() == last_bar.normalize()]
    if last_bar.hour >= 19:
        median_bars = m5.groupby(m5.index.normalize()).size().median()
        if len(last_day) < 0.7 * median_bars:
            warnings.append(f"в последнем дне мало баров: {len(last_day)} из ~{median_bars:.0f}")
    ret = last_day["close"].pct_change().abs().max()
    if ret > 0.02:
        warnings.append(f"скачок {ret * 100:.1f}% за минуту")

    ma_series = m5["close"].rolling(ma_period).mean()
    ma = float(ma_series.iloc[-1])
    target = int(tg.iloc[-1])

    decide = daily_first_bar(m5, entry_time) & (m5.index.day_of_week < 5)
    today = m5.index.normalize() == last_bar.normalize()
    decided = m5.index[decide.to_numpy() & today]
    decision_time = decided[0] if len(decided) else None

    sig = 0
    decision_price = ma_decision = float("nan")
    if decision_time is not None and not pd.isna(ma):
        ma_decision = float(ma_series.loc[decision_time])
        decision_price = float(m5.loc[decision_time, "close"])
        sig = 1 if decision_price > ma_decision else (-1 if decision_price < ma_decision else 0)

    return Signal(
        last_bar=last_bar,
        last_price=float(m5["close"].iloc[-1]),
        ma=ma,
        signal=sig,
        target=target,
        decision_time=decision_time,
        decision_price=decision_price,
        ma_decision=ma_decision,
        warnings=warnings,
        bars_last_day=len(last_day),
        decided_today=decision_time is not None,
    )
