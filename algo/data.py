"""Загрузка исторических данных MOEX в формате TSLab/OsEngine.

Формат файла: `<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>`
DATE = YYYYMMDD, TIME = HHMMSS, PER = 1 (минутки).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import os

# Папка с историей: переменная ALGO_DATA или локальный data/ (симлинк/копия)
DATA_ROOT = Path(os.environ.get("ALGO_DATA", Path(__file__).resolve().parent.parent / "data"))


def load_txt(path: str | Path, tz: str = "Europe/Moscow") -> pd.DataFrame:
    """Читает файл истории и возвращает DataFrame с DatetimeIndex и колонками ohlcv."""
    path = Path(path)
    if not path.is_absolute():
        path = DATA_ROOT / path

    raw = pd.read_csv(path)
    raw.columns = [c.strip().strip("<>").lower() for c in raw.columns]

    ts = (
        raw["date"].astype(str).str.zfill(8)
        + raw["time"].astype(str).str.zfill(6)
    )
    idx = pd.to_datetime(ts, format="%Y%m%d%H%M%S")

    df = pd.DataFrame(
        {
            "open": raw["open"].to_numpy(dtype=float),
            "high": raw["high"].to_numpy(dtype=float),
            "low": raw["low"].to_numpy(dtype=float),
            "close": raw["close"].to_numpy(dtype=float),
            "vol": raw["vol"].to_numpy(dtype=float),
        },
        index=idx,
    )
    df.index.name = "dt"
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.attrs["ticker"] = str(raw["ticker"].iloc[0]) if "ticker" in raw else path.stem
    return df


def to_timeframe(df: pd.DataFrame, minutes: int = 5) -> pd.DataFrame:
    """Строит бары заданного таймфрейма из минуток.

    Бин закрыт слева, метка — начало бина: бин [10:00, 10:05) помечен 10:00.
    Пустые бины (нет сделок) отбрасываются.
    """
    rule = f"{minutes}min"
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "vol": "sum"}
    )
    return out.dropna(subset=["close"])


def daily_first_bar(df: pd.DataFrame, at: str) -> pd.Series:
    """Маска: первая свеча дня с временем >= `at` (формат 'HH:MM')."""
    hh, mm = (int(x) for x in at.split(":"))
    minutes_of_day = df.index.hour * 60 + df.index.minute
    after = minutes_of_day >= hh * 60 + mm
    dates = df.index.normalize()
    first = pd.Series(after, index=df.index).groupby(dates).cummax()
    # первая True в каждом дне
    prev = first.groupby(dates).shift(1).fillna(False)
    return first & ~prev.astype(bool)


CACHE = Path(__file__).resolve().parent.parent / ".cache"


def load_cached(path: str | Path, minutes: int | None = None) -> pd.DataFrame:
    """Загрузка с кэшем в pickle: повторные прогоны не парсят txt заново.

    minutes=None — возвращает минутки, иначе агрегирует до T-минутных баров.
    """
    p = Path(path)
    if not p.is_absolute():
        p = DATA_ROOT / p
    key = f"{p.stem}_{p.stat().st_mtime_ns}_{p.stat().st_size}_{minutes or 'm1'}"
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{key}.pkl"
    if cached.exists():
        return pd.read_pickle(cached)
    df = load_txt(p)
    if minutes:
        df = to_timeframe(df, minutes)
    df.to_pickle(cached)
    return df
