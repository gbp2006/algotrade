"""Расчёт сигналов для живого бумажного контура по конфигурациям.

Вход: M5-бары от брокера (МСК). Выход: целевая позиция и пояснение.
Логика повторяет бэктест, но считается по живому потоку.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .configs import Config


@dataclass
class Decision:
    target: int
    price: float
    ts: pd.Timestamp
    detail: str


def _tf_bars(m5: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes <= 5:
        return m5
    return m5.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "vol": "sum"}
    ).dropna(subset=["close"])


def _first_at(df: pd.DataFrame, hhmm: str) -> pd.Timestamp | None:
    h, m = (int(x) for x in hhmm.split(":"))
    need = h * 60 + m
    mask = (df.index.hour * 60 + df.index.minute) >= need
    return df.index[mask][0] if mask.any() else None


def _last_closed_at(df: pd.DataFrame, hhmm: str, tf: int) -> pd.Timestamp | None:
    """Последний бар, который к указанному времени уже закрылся.

    Для таймфреймов больше M5 бар с меткой 12:00 (tf=60) закрывается в 13:00,
    поэтому в 13:50 решение принимается по нему, а не по ещё не закрытому 13:00.
    """
    h, m = (int(x) for x in hhmm.split(":"))
    need = h * 60 + m
    ends = df.index + pd.Timedelta(minutes=tf)
    mask = (ends.hour * 60 + ends.minute <= need) & (ends.date == df.index.date)
    return df.index[mask][-1] if mask.any() else None


def decision_configs(configs) -> list:
    """Конфигурации, которые входят в фазу решений.

    `hold="morning"` тоже решает (вход 13:30), просто выходит отдельной фазой
    в 10:25 — раньше её ошибочно пропускали и она не могла открыть позицию.
    """
    return [c for c in configs if c.strategy in ("prostushka", "universal")]


def decision(cfg: Config, m5: pd.DataFrame, day) -> Decision | None:
    """Целевая позиция по конфигурации на указанный день. None — решения ещё нет."""
    params = cfg.params
    today = m5[m5.index.date == day]
    if today.empty:
        return None

    if cfg.strategy == "prostushka":
        tf = int(params.get("timeframe", 5))
        df = _tf_bars(m5, tf)
        bars = max(3, round(params["ma_window"] / tf))
        ma = df["close"].rolling(bars).mean()
        if tf > 5:
            # H1 и старше: берём только закрытые бары, иначе подглядываем в будущее
            ts = _last_closed_at(df, params["entry"], tf)
        else:
            ts = _first_at(df[df.index.date == day], params["entry"])
        if ts is None:
            return None
        ma_val = float(ma.loc[ts])
        close = float(df.loc[ts, "close"])
        if pd.isna(ma_val):
            return None

        sig = 1 if close > ma_val else (-1 if close < ma_val else 0)
        # фильтр: за последние N баров не было закрытий против MA
        fbars = int(params.get("filter_bars", 0))
        if sig == 1 and fbars > 0:
            pos = list(df.index).index(ts)
            ok = all(
                df["close"].iloc[i] > ma.iloc[i]
                for i in range(max(0, pos - fbars + 1), pos + 1)
                if not pd.isna(ma.iloc[i])
            )
            if not ok:
                sig = 0
        if sig == -1 and day.weekday() == 4 and not params.get("short_friday", False):
            sig = 0
        return Decision(sig, close, ts, f"close {close:.3f} vs MA{bars} {ma_val:.4f}")

    if cfg.strategy == "universal":
        ts_ref = _first_at(today, params["ref"])
        ts = _first_at(today, params["entry"])
        if ts_ref is None or ts is None:
            return None
        ref = float(m5.loc[ts_ref, "close"])
        close = float(m5.loc[ts, "close"])
        sig = 0
        if close >= ref * (1 + params["long_off"]):
            sig = 1
        elif close <= ref * (1 - params["short_off"]):
            sig = -1
        if sig == -1 and day.weekday() == 4 and not params.get("short_friday", False):
            sig = 0
        return Decision(sig, close, ts,
                        f"репер {ref:.3f}, close {close:.3f}, "
                        f"порог +{params['long_off'] * 100:.1f}%/-{params['short_off'] * 100:.1f}%")

    return None


def morning_exit_price(m5: pd.DataFrame, day, at: str = "10:20") -> float | None:
    """Цена выхода для конфигураций с утренним выходом (следующий день, 10:20)."""
    today = m5[m5.index.date == day]
    ts = _first_at(today, at)
    return float(today.loc[ts, "close"]) if ts is not None else None
