"""Кандидаты из каталога `reports/strategy-catalog.md` (первая партия прототипов).

Все функции возвращают целевую позицию (Series[int]) по индексу переданных баров,
совместимую с `algo.engine.run`. Дневные стратегии считают сигнал по дневным
барам (агрегация M5→день), а решение публикуют на баре `DECIDE_TIME` —income
исполнение остаётся прежним: сделка по open следующего бара.

Индексы: T01 TSMOM 12-1, T02 TSMOM 6-1, T04 Donchian, T06 EWMAC,
T08 SMA-cross, M04 Bollinger-reversion, M05 RSI(2), I01 ORB, C05 turn-of-month.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import daily_first_bar

DECIDE_TIME = "13:55"


def daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Агрегация OHLCV intraday-баров в дневные (день = календарная дата)."""
    d = df.groupby(df.index.normalize()).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "vol": "sum"}
    )
    d.index.name = "date"
    return d


def to_intraday(
    daily_signal: pd.Series,
    df: pd.DataFrame,
    at: str = DECIDE_TIME,
    skip_weekend: bool = True,
) -> pd.Series:
    """Разворачивает дневной сигнал в целевую позицию на intra-day барах.

    ВАЖНО: дневной close агрегируется по всем барам календарной даты, включая
    вечернюю сессию (~23:50). Поэтому сигнал за дату D публикуется только на
    решении 13:55 даты D+1 — `shift(1)`. Без сдвига был бы look-ahead.
    """
    signal = daily_signal.shift(1)
    mask = daily_first_bar(df, at)
    if skip_weekend:
        mask = mask & (df.index.day_of_week < 5)
    dates = df.index[mask].normalize()
    vals = signal.reindex(dates).to_numpy(dtype=float)
    out = pd.Series(np.nan, index=df.index, dtype=float)
    out[mask] = vals
    return out.ffill().fillna(0).astype(int)


# ── T01 / T02: time-series momentum ──────────────────────────────────────────

def ts_momentum(
    df: pd.DataFrame, lookback: int = 252, skip: int = 21,
    at: str = DECIDE_TIME, allow_short: bool = True,
) -> pd.Series:
    """Лонг, если доходность close[t-skip]/close[t-lookback] > 0; шорт иначе.

    12-1: lookback=252, skip=21. 6-1: lookback=126, skip=21.
    """
    d = daily_bars(df)
    ret = d["close"].shift(skip) / d["close"].shift(lookback) - 1.0
    sig = pd.Series(0, index=d.index, dtype=int)
    sig[ret > 0] = 1
    if allow_short:
        sig[ret < 0] = -1
    return to_intraday(sig, df, at)


# ── T04: Donchian breakout ────────────────────────────────────────────────────

def donchian_signal(
    d: pd.DataFrame, entry: int = 20, exit_: int = 10,
    allow_short: bool = True,
) -> pd.Series:
    """Дневной сигнал Donchian по уже агрегированным дневным барам.

    Используется и бэктестом (`donchian`), и живым контуром (`algo.live`) —
    только так гарантируется совпадение логики.
    """
    c = d["close"].to_numpy(dtype=float)
    hh = d["high"].rolling(entry).max().shift(1).to_numpy(dtype=float)
    ll = d["low"].rolling(entry).min().shift(1).to_numpy(dtype=float)
    xh = d["high"].rolling(exit_).max().shift(1).to_numpy(dtype=float)
    xl = d["low"].rolling(exit_).min().shift(1).to_numpy(dtype=float)
    pos, out = 0, np.zeros(len(d), dtype=int)
    for i in range(len(d)):
        if not np.isfinite(c[i]):
            continue
        if pos == 0:
            if c[i] > hh[i]:
                pos = 1
            elif allow_short and c[i] < ll[i]:
                pos = -1
        elif pos == 1 and c[i] < xl[i]:
            pos = 0
        elif pos == -1 and c[i] > xh[i]:
            pos = 0
        out[i] = pos
    return pd.Series(out, index=d.index, name="donchian_signal")


def donchian(
    df: pd.DataFrame, entry: int = 20, exit_: int = 10,
    at: str = DECIDE_TIME, allow_short: bool = True,
) -> pd.Series:
    """Пробой HH(20)/LL(20) → вход; возврат к LL(10)/HH(10) → выход."""
    d = daily_bars(df)
    return to_intraday(donchian_signal(d, entry, exit_, allow_short), df, at)


# ── T06: EWMAC ───────────────────────────────────────────────────────────────

def ewmac(
    df: pd.DataFrame, fast: int = 8, slow: int = 32,
    vol_window: int = 25, threshold: float = 1.0, at: str = DECIDE_TIME,
) -> pd.Series:
    """forecast = (EMA_fast − EMA_slow) / (0.01·close·годовой vol); позиция по знаку."""
    d = daily_bars(df)
    c = d["close"]
    ef = c.ewm(span=fast, adjust=False).mean()
    es = c.ewm(span=slow, adjust=False).mean()
    vol = c.pct_change().rolling(vol_window).std() * np.sqrt(252)
    fc = (ef - es) / (0.01 * c * vol)
    sig = pd.Series(0, index=d.index, dtype=int)
    sig[fc > threshold] = 1
    sig[fc < -threshold] = -1
    return to_intraday(sig, df, at)


# ── T08: SMA cross ───────────────────────────────────────────────────────────

def sma_cross(
    df: pd.DataFrame, fast: int = 50, slow: int = 200, at: str = DECIDE_TIME,
    allow_short: bool = True,
) -> pd.Series:
    d = daily_bars(df)
    c = d["close"]
    f, s = c.rolling(fast).mean(), c.rolling(slow).mean()
    sig = pd.Series(0, index=d.index, dtype=int)
    sig[f > s] = 1
    if allow_short:
        sig[f < s] = -1
    return to_intraday(sig, df, at)


# ── M04: Bollinger reversion ─────────────────────────────────────────────────

def bollinger_reversion(
    df: pd.DataFrame, period: int = 20, k: float = 2.0, at: str = DECIDE_TIME,
) -> pd.Series:
    """Вход при z <= −k / >= +k, выход при возврате к средней (z=0)."""
    d = daily_bars(df)
    c = d["close"]
    ma = c.rolling(period).mean()
    sd = c.rolling(period).std()
    z = ((c - ma) / sd).to_numpy(dtype=float)
    pos, out = 0, np.zeros(len(d), dtype=int)
    for i in range(len(d)):
        if not np.isfinite(z[i]):
            continue
        if pos == 0:
            if z[i] <= -k:
                pos = 1
            elif z[i] >= k:
                pos = -1
        elif (pos == 1 and z[i] >= 0) or (pos == -1 and z[i] <= 0):
            pos = 0
        out[i] = pos
    return to_intraday(pd.Series(out, index=d.index), df, at)


# ── M05: RSI(2) ──────────────────────────────────────────────────────────────

def _rsi(close: pd.Series, period: int = 2) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def rsi_reversion(
    df: pd.DataFrame, period: int = 2, low: float = 5.0, high: float = 95.0,
    max_hold: int = 5, at: str = DECIDE_TIME,
) -> pd.Series:
    """Лонг RSI(2)<5 / шорт >95; выход при пересечении 50 или по времени."""
    d = daily_bars(df)
    r = _rsi(d["close"], period).to_numpy(dtype=float)
    pos, out, held, entry_dir = 0, np.zeros(len(d), dtype=int), 0, 0
    for i in range(len(d)):
        if not np.isfinite(r[i]):
            continue
        if pos == 0:
            if r[i] < low:
                pos, entry_dir, held = 1, 1, 0
            elif r[i] > high:
                pos, entry_dir, held = -1, -1, 0
        else:
            held += 1
            if (pos == 1 and r[i] >= 50) or (pos == -1 and r[i] <= 50) or held >= max_hold:
                pos = 0
        out[i] = pos
    return to_intraday(pd.Series(out, index=d.index), df, at)


# ── I01: Opening Range Breakout ──────────────────────────────────────────────

def opening_range_breakout(
    df: pd.DataFrame, start: str = "10:00", minutes: int = 30,
    flat_time: str = "23:40", skip_weekend: bool = True,
) -> pd.Series:
    """Диапазон первых `minutes` минут сессии; первый пробой → позиция до flat_time."""
    out = np.zeros(len(df), dtype=int)
    pos_all = df.index.get_indexer(df.index)
    sh, sm = (int(x) for x in start.split(":"))
    fh, fm = (int(x) for x in flat_time.split(":"))
    s_min, f_min = sh * 60 + sm, fh * 60 + fm
    n = max(1, minutes // 5)
    for _date, day in df.groupby(df.index.normalize()):
        if skip_weekend and _date.day_of_week >= 5:
            continue
        tm = day.index.hour.to_numpy() * 60 + day.index.minute.to_numpy()
        cand = np.flatnonzero(tm >= s_min)
        if len(cand) == 0:
            continue
        i0 = int(cand[0])
        i1 = min(i0 + n, len(day) - 1)
        if i1 <= i0:
            continue
        orh = float(day["high"].iloc[i0:i1 + 1].max())
        orl = float(day["low"].iloc[i0:i1 + 1].min())
        if not (orh > orl > 0):
            continue
        gidx = pos_all[df.index.get_indexer(day.index)]
        pos = 0
        for j in range(i1 + 1, len(day)):
            if tm[j] >= f_min:
                pos = 0
            elif pos == 0:
                c = float(day["close"].iloc[j])
                if c > orh:
                    pos = 1
                elif c < orl:
                    pos = -1
            out[gidx[j]] = pos
    return pd.Series(out, index=df.index, name="orb_target")


# ── C05: turn-of-month ───────────────────────────────────────────────────────

def turn_of_month(
    df: pd.DataFrame, after: int = 3, at: str = DECIDE_TIME,
) -> pd.Series:
    """Лонг в последний торговый день месяца и ещё `after` дней нового."""
    d = daily_bars(df)
    if len(d) < 2:
        return to_intraday(pd.Series(0, index=d.index, dtype=int), df, at)
    month = d.index.month.to_numpy()
    eom = np.flatnonzero(month[:-1] != month[1:])
    sig = pd.Series(0, index=d.index, dtype=int)
    for p in eom:
        for k in range(after + 1):
            if p + k < len(d):
                sig.iloc[p + k] = 1
    return to_intraday(sig, df, at)


# ── вторая партия: простые правила из каталога ─────────────────────────────────

def roc(df: pd.DataFrame, n: int = 5, at: str = DECIDE_TIME) -> pd.Series:
    """T27: лонг при ROC(n)>0, шорт при ROC(n)<0."""
    d = daily_bars(df)
    r = d["close"] / d["close"].shift(n) - 1.0
    sig = pd.Series(0, index=d.index, dtype=int)
    sig[r > 0] = 1
    sig[r < 0] = -1
    return to_intraday(sig, df, at)


def _zero_cross(series: pd.Series) -> pd.Series:
    """_stateful: держим знак до противоположного перехода через нуль."""
    v = series.to_numpy(dtype=float)
    pos, out = 0, np.zeros(len(v), dtype=int)
    for i in range(len(v)):
        if np.isfinite(v[i]):
            if pos == 0 and v[i] != 0:
                pos = 1 if v[i] > 0 else -1
            elif pos == 1 and v[i] < 0:
                pos = -1
            elif pos == -1 and v[i] > 0:
                pos = 1
        out[i] = pos
    return pd.Series(out, index=series.index)


def vma(df: pd.DataFrame, short: int = 5, long: int = 10, at: str = DECIDE_TIME) -> pd.Series:
    """T28: знак SMA(short)−SMA(long), реверс на переходе через 0."""
    d = daily_bars(df)
    c = d["close"]
    return to_intraday(_zero_cross(c.rolling(short).mean() - c.rolling(long).mean()), df, at)


def macd(df: pd.DataFrame, fast: int = 5, slow: int = 10, at: str = DECIDE_TIME) -> pd.Series:
    """T29: знак EMA(fast)−EMA(slow), реверс на переходе через 0."""
    d = daily_bars(df)
    c = d["close"]
    m = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    return to_intraday(_zero_cross(m), df, at)


def halloween(df: pd.DataFrame, at: str = DECIDE_TIME) -> pd.Series:
    """M22: лонг 31.10–30.04, кэш май–октябрь."""
    d = daily_bars(df)
    md = d.index.strftime("%m-%d")
    sig = pd.Series(0, index=d.index, dtype=int)
    sig[(md >= "10-31") | (md <= "04-30")] = 1
    return to_intraday(sig, df, at)


def rsi_reversal(
    df: pd.DataFrame, period: int = 14, upper: float = 70.0,
    lower: float = 30.0, at: str = DECIDE_TIME,
) -> pd.Series:
    """R10: RSI>70 → лонг, RSI<30 → шорт, всё время в рынке."""
    d = daily_bars(df)
    r = _rsi(d["close"], period).to_numpy(dtype=float)
    pos, out = 0, np.zeros(len(d), dtype=int)
    for i in range(len(d)):
        if np.isfinite(r[i]):
            if r[i] >= upper:
                pos = 1
            elif r[i] <= lower:
                pos = -1
        out[i] = pos
    return to_intraday(pd.Series(out, index=d.index), df, at)
