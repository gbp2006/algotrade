"""RU-02 «Сырьевой импульс» — исследовательский порт.

Источник идей: https://t-j.ru/kak-ia-delaiu-torgovye-algoritmy-na-mosbirzhe/
(импульс на пяти фьючерсах: золото, серебро, Brent, газ, юань; лонг и шорт;
+219% за 2024–2026 при DD −6%). Точные правила автором не опубликованы, поэтому
проверяются две честные формализации:

* `xs_impulse_targets` — кросс-секционный ранг доходности за N дней: лонг
  лидерам, шорт отстающим, по одному контракту на ногу;
* `ts_impulse_targets` — тайм-серийный импульс: вход при доходности за N дней
  выше +k σ (лонг) или ниже −k σ (шорт), выход через `hold` дней или по знаку.

Сигнал по дневному close, исполнение первым баром следующего дня (`to_intraday`
делает shift(1)), издержки и проскальзывание считает движок. research-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .candidates import daily_bars, to_intraday


def xs_impulse_targets(
    data: dict[str, pd.DataFrame], lookback: int = 10, top: int = 2,
    bottom: int = 2, at: str = "00:00",
) -> dict[str, pd.Series]:
    """Лонг `top` лидерам, шорт `bottom` отстающим по доходности за `lookback`."""
    daily = {n: daily_bars(df) for n, df in data.items()}
    dates = sorted(set.intersection(*[set(d.index) for d in daily.values()]))
    if len(dates) < lookback + 2:
        return {n: pd.Series(0, index=df.index, dtype=int) for n, df in data.items()}
    rets = pd.DataFrame(
        {n: daily[n]["close"].pct_change(lookback) for n in data}, index=dates,
    )
    sig = pd.DataFrame(0, index=dates, columns=data.keys(), dtype=int)
    for date in dates:
        row = rets.loc[date].dropna()
        if len(row) < len(data):
            continue
        order = row.sort_values(ascending=False)
        for n in order.index[:top]:
            sig.loc[date, n] = 1
        losers = list(order.index[-bottom:]) if bottom else []
        for n in losers:
            sig.loc[date, n] = -1
    return {n: to_intraday(sig[n], data[n], at) for n in data}


def ts_impulse_targets(
    df: pd.DataFrame, lookback: int = 10, k: float = 1.0, hold: int = 10,
    vol_filter: bool = False, at: str = "00:00",
) -> pd.Series:
    """Импульс по знаку нормированной доходности с фиксированным удержанием."""
    d = daily_bars(df)
    ret = d["close"].pct_change(lookback)
    vol = d["close"].pct_change().rolling(lookback).std()
    z = ret / (vol * np.sqrt(lookback))
    if vol_filter:
        vm = vol / vol.rolling(252).median()
        z = z.where(vm > 1.0)

    pos, held, out = 0, 0, np.zeros(len(d), dtype=int)
    zv = z.to_numpy(dtype=float)
    for i in range(len(d)):
        if np.isfinite(zv[i]):
            if pos == 0:
                if zv[i] > k:
                    pos, held = 1, 0
                elif zv[i] < -k:
                    pos, held = -1, 0
            else:
                held += 1
                if held >= hold or (pos == 1 and zv[i] < -k) or (pos == -1 and zv[i] > k):
                    pos, held = 0, 0
        out[i] = pos
    return to_intraday(pd.Series(out, index=d.index), df, at)
