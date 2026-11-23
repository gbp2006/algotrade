"""Остальные реализуемые правила каталога (`reports/strategy-catalog.md`).

Все функции возвращают целевую позицию по индексу M5-баров, совместимую с
`algo.engine.run`. Естественное время работы задаётся вызывающим скриптом
через `at` (для дневных правил — первый бар следующего дня).
Логика, требующая стакана/опционов/истории акций/интрабарных стопов,
 сюда не включена — она перечислена в разделе исключений отчёта.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .candidates import daily_bars, donchian_signal, to_intraday, _rsi


def ts_momentum_signal(d, lookback, skip, allow_short=True):
    """Локальная копия: дневной сигнал TSMOM (candidates.py на WSL без _signal)."""
    ret = d["close"].shift(skip) / d["close"].shift(lookback) - 1.0
    sig = pd.Series(0, index=d.index, dtype=int)
    sig[ret > 0] = 1
    if allow_short:
        sig[ret < 0] = -1
    return sig


def sma_cross_signal(d, fast, slow, allow_short=True):
    """Локальная копия: знак разности SMA."""
    c = d["close"]
    f, s = c.rolling(fast).mean(), c.rolling(slow).mean()
    sig = pd.Series(0, index=d.index, dtype=int)
    sig[f > s] = 1
    if allow_short:
        sig[f < s] = -1
    return sig


def ts_mom_1m(df, at="00:00"):
    """T15: доходность за 21 день → направление."""
    return to_intraday(ts_momentum_signal(daily_bars(df), 21, 0), df, at)


def ts_mom_3m(df, at="00:00"):
    """T16: доходность за 63 дня → направление."""
    return to_intraday(ts_momentum_signal(daily_bars(df), 63, 0), df, at)


def ts_mom_12m(df, at="00:00"):
    """T17: доходность за 252 дня → направление."""
    return to_intraday(ts_momentum_signal(daily_bars(df), 252, 0), df, at)


def turtle2(df, at="00:00"):
    """T24: пробой HH55/LL55, выход LL20/HH20."""
    return to_intraday(donchian_signal(daily_bars(df), 55, 20), df, at)


def sma20_60(df, at="00:00"):
    return to_intraday(sma_cross_signal(daily_bars(df), 20, 60), df, at)


def sma30_90(df, at="00:00"):
    return to_intraday(sma_cross_signal(daily_bars(df), 30, 90), df, at)


def sma40_120(df, at="00:00"):
    return to_intraday(sma_cross_signal(daily_bars(df), 40, 120), df, at)


def ma1_200(df, at="00:00"):
    """M20: close > SMA200 → лонг, иначе шорт."""
    return to_intraday(sma_cross_signal(daily_bars(df), 1, 200), df, at)


def boll_breakout(df, at="00:00", period=20, k=2.0, squeeze_lb=126):
    """M18: вход после сжатия полосы и пробоя upper/lower, выход у полосы."""
    d = daily_bars(df)
    c = d["close"]
    ma = c.rolling(period).mean()
    sd = c.rolling(period).std()
    up, lo = ma + k * sd, ma - k * sd
    width = (up - lo) / ma
    squeeze = width < width.rolling(squeeze_lb).quantile(0.2)
    pos, out = 0, np.zeros(len(d), dtype=int)
    for i in range(len(d)):
        if np.isfinite(up.iloc[i]) and np.isfinite(squeeze.iloc[i]):
            if pos == 0 and squeeze.iloc[i]:
                if c.iloc[i] > up.iloc[i]:
                    pos = 1
                elif c.iloc[i] < lo.iloc[i]:
                    pos = -1
            elif pos == 1 and c.iloc[i] <= lo.iloc[i]:
                pos = 0
            elif pos == -1 and c.iloc[i] >= up.iloc[i]:
                pos = 0
        out[i] = pos
    return to_intraday(pd.Series(out, index=d.index), df, at)


def chandelier(df, at="00:00", entry_n=20, k=0.5, trail=3.0):
    """T05/T14: вход при пробое HH(N)+k·ATR, выход по HH_since_entry − trail·ATR."""
    d = daily_bars(df)
    c, h, l = d["close"], d["high"], d["low"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(entry_n).mean()
    hh = h.rolling(entry_n).max().shift(1)
    ll = l.rolling(entry_n).min().shift(1)
    pos, out, best = 0, np.zeros(len(d), dtype=float), 0.0
    for i in range(len(d)):
        if not np.isfinite(c.iloc[i]) or not np.isfinite(atr.iloc[i]):
            continue
        if pos == 0:
            if c.iloc[i] > hh.iloc[i] + k * atr.iloc[i]:
                pos, best = 1, h.iloc[i]
            elif c.iloc[i] < ll.iloc[i] - k * atr.iloc[i]:
                pos, best = -1, l.iloc[i]
        else:
            if pos == 1:
                best = max(best, h.iloc[i])
                if c.iloc[i] < best - trail * atr.iloc[i]:
                    pos = 0
            else:
                best = min(best, l.iloc[i])
                if c.iloc[i] > best + trail * atr.iloc[i]:
                    pos = 0
        out[i] = pos
    return to_intraday(pd.Series(out, index=d.index).astype(int), df, at)


def boll_mfi(df, at="00:00", period=20, mfi_n=10):
    """M19: %b>0.8 + MFI>80 → лонг; %b<0.2 + MFI<20 → шорт; выход %b=0.5."""
    d = daily_bars(df)
    c, h, l, v = d["close"], d["high"], d["low"], d["vol"]
    ma = c.rolling(period).mean()
    sd = c.rolling(period).std()
    pb = (c - (ma - 2 * sd)) / (4 * sd)
    tp = (h + l + c) / 3
    mf = tp * v
    up = (tp > tp.shift()).astype(float) * mf
    dn = (tp < tp.shift()).astype(float) * mf
    mfi = 100 - 100 / (1 + up.rolling(mfi_n).sum() / dn.rolling(mfi_n).sum().replace(0, np.nan))
    pos, out = 0, np.zeros(len(d), dtype=int)
    for i in range(len(d)):
        if not (np.isfinite(pb.iloc[i]) and np.isfinite(mfi.iloc[i])):
            continue
        if pos == 0:
            if pb.iloc[i] > 0.8 and mfi.iloc[i] > 80:
                pos = 1
            elif pb.iloc[i] < 0.2 and mfi.iloc[i] < 20:
                pos = -1
        elif (pos == 1 and pb.iloc[i] < 0.5) or (pos == -1 and pb.iloc[i] > 0.5):
            pos = 0
        out[i] = pos
    return to_intraday(pd.Series(out, index=d.index), df, at)


def rsi14_trend(df, at="00:00"):
    """R10: RSI14 пересекает 70 вверх → лонг, 30 вниз → шорт."""
    d = daily_bars(df)
    r = _rsi(d["close"], 14)
    sig = pd.Series(0, index=d.index, dtype=int)
    sig[r >= 70] = 1
    sig[r <= 30] = -1
    return to_intraday(sig, df, at)


def rsi14_counter(df, at="00:00"):
    """R10 контртренд: RSI14>70 → шорт, <30 → лонг."""
    d = daily_bars(df)
    r = _rsi(d["close"], 14)
    sig = pd.Series(0, index=d.index, dtype=int)
    sig[r >= 70] = -1
    sig[r <= 30] = 1
    return to_intraday(sig, df, at)


def gap_fade(df, threshold=0.002, flat_time="23:40"):
    """I11/I12: fade opening gap ≥0.2%, выход на последнем баре дня."""
    out = np.zeros(len(df), dtype=int)
    fh, fm = (int(x) for x in flat_time.split(":"))
    for _day, day in df.groupby(df.index.normalize()):
        if _day.day_of_week >= 5:
            continue
        idx = df.index.get_indexer(day.index)
        tm = day.index.hour.to_numpy() * 60 + day.index.minute.to_numpy()
        prev = float(df["close"].iloc[idx[0] - 1]) if idx[0] > 0 else 0.0
        if not prev:
            continue
        rel = (float(day["open"].iloc[0]) - prev) / prev
        if abs(rel) < threshold:
            continue
        side = -1 if rel > 0 else 1
        for j in range(1, len(day)):
            out[idx[j]] = 0 if tm[j] >= fh * 60 + fm else side
    return pd.Series(out, index=df.index)
