"""KZ-01/02/03 «Пробой дня» Коваль-Зайцева — исследовательский порт.

Источник: t.me/truetrading_ru/488, /531, /11; YouTube 3sY1BeV3XQU, xIRnW-eOCyI.
Правила автора (EasyLanguage, data2 = дневной график):

    buy_level  = high of data2;
    sell_level = low  of data2;
    if close < buy_level and close > Average(close,30) data2
       and (bbup - bbdown)/bbdown < 0.15
    then buy size contract next bar buy_level stop;
    if close > sell_level then sell next bar sell_level stop;

Две честные интерпретации `next bar` ( их нельзя смешивать в одном прогоне ):

* `kz_daily`   — решение по дневному close, исполнение на первом баре следующего
  дня (как остальные дневные стратегии проекта через `candidates.to_intraday`);
* `kz_intraday` — ежедневный HH/LL предыдущего дня и фильтры берутся по
  последнему завершённому дневному бару, а пробой отслеживается на M5; сделка
  исполняется по open следующего M5-бара. Ближе к автору, но оборот выше.

Это research-only: роботов и конфигураций по модулю нет.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .candidates import daily_bars, to_intraday

DECIDE_TIME = "00:00"


def _daily_levels(
    d: pd.DataFrame, ma_len: int, bb_len: int, dev: float, koef: float,
    use_filters: bool,
) -> dict[str, pd.Series]:
    """Уровни и фильтры по ЗАВЕРШЁННЫМ дневным барам (сдвиг на 1 без look-ahead)."""
    o, h, l, c = (d[x] for x in ("open", "high", "low", "close"))
    ma = c.rolling(ma_len).mean()
    bb_ma = c.rolling(bb_len).mean()
    sd = c.rolling(bb_len).std()
    up, down = bb_ma + dev * sd, bb_ma - dev * sd
    bandwidth = (up - down) / down
    ok = pd.Series(True, index=d.index)
    if use_filters:
        ok = (c > ma) & (bandwidth < koef)
    return {
        "high": h.shift(1),
        "low": l.shift(1),
        "pivot": ((o + h + l + c) / 4.0).shift(1),
        "ok": ok.shift(1).fillna(False),  # фильтр последнего завершённого дня
        "armed": ((c < h.shift(1)) & ok).shift(1).fillna(False),
    }


def kz_daily(
    df: pd.DataFrame, ma_len: int = 30, bb_len: int = 14, dev: float = 2.0,
    koef: float = 0.15, use_filters: bool = True, allow_short: bool = False,
    exit_mode: str = "low", at: str = DECIDE_TIME,
) -> pd.Series:
    """Дневная интерпретация: сигнал по close, позиция — на следующий день.

    `exit_mode='low'`  — выход при close < вчерашнего LL (код автора);
    `exit_mode='pivot'` — выход при close < (O+H+L+C)/4 вчерашнего дня (пост 11).
    """
    d = daily_bars(df)
    L = _daily_levels(d, ma_len, bb_len, dev, koef, use_filters)
    hh, ll = L["high"], L["low"]
    exit_level = L["pivot"] if exit_mode == "pivot" else ll

    pos, out = 0, np.zeros(len(d), dtype=int)
    hi, lo, ok, ex = (x.to_numpy(dtype=float) for x in (hh, ll, L["ok"], exit_level))
    c = d["close"].to_numpy(dtype=float)
    for i in range(len(d)):
        if np.isfinite(c[i]):
            can_long = bool(c[i] < hi[i]) and (not use_filters or bool(ok[i]))
            can_short = bool(c[i] > lo[i]) and (not use_filters or bool(ok[i]))
            if pos == 0:
                if can_long:
                    pos = 1
                elif allow_short and can_short:
                    pos = -1
            elif pos == 1 and c[i] < ex[i]:
                pos = 0
            elif pos == -1 and c[i] > hi[i]:
                pos = 0
        out[i] = pos
    return to_intraday(pd.Series(out, index=d.index), df, at)


def kz_intraday(
    df: pd.DataFrame, ma_len: int = 30, bb_len: int = 14, dev: float = 2.0,
    koef: float = 0.15, use_filters: bool = True, allow_short: bool = False,
    exit_mode: str = "low", skip_weekend: bool = True,
) -> pd.Series:
    """Интрадей-интерпретация: пробой вчерашнего HH/LL на M5, стоп next bar open.

    Уровни и фильтры считаются по последнему завершённому дневному бару, поэтому
    текущий формирующийся день в них не участвует. Позиция переносится через
    выходные, если `skip_weekend` (решений в выходные нет, как в проекте).
    """
    d = daily_bars(df)
    L = _daily_levels(d, ma_len, bb_len, dev, koef, use_filters)
    by_date = pd.DataFrame({
        "high": L["high"], "low": L["low"],
        "pivot": L["pivot"], "ok": L["ok"],
    })

    out = np.zeros(len(df), dtype=int)
    pos = 0
    for date, day in df.groupby(df.index.normalize()):
        if skip_weekend and date.day_of_week >= 5:
            out[df.index.get_indexer(day.index)] = pos
            continue
        row = by_date.loc[date] if date in by_date.index else None
        if row is None or not np.isfinite(row["high"]):
            out[df.index.get_indexer(day.index)] = pos
            continue
        hh, ll = float(row["high"]), float(row["low"])
        ex = float(row["pivot"]) if exit_mode == "pivot" else ll
        ok = bool(row["ok"]) if use_filters else True
        c = day["close"].to_numpy(dtype=float)
        gidx = df.index.get_indexer(day.index)
        for j in range(len(c)):
            if pos == 0:
                if ok and j > 0 and c[j] > hh and c[j - 1] <= hh:
                    pos = 1
                elif allow_short and ok and j > 0 and c[j] < ll and c[j - 1] >= ll:
                    pos = -1
            elif pos == 1 and c[j] < ex:
                pos = 0
            elif pos == -1 and c[j] > hh:
                pos = 0
            out[gidx[j]] = pos
    return pd.Series(out, index=df.index, name="kz_intraday")
