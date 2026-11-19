"""Бэктест-движок: целевая позиция -> сделки -> эквити.

Модель исполнения:
  сигнал считается по close бара t,
  сделка исполняется по open бара t+1 со сдвигом на проскальзывание.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class Costs:
    """Издержки и параметры контракта."""

    commission_pct: float = 0.0001  # 0.01% от номинала за сторону
    slippage_ticks: float = 1.0     # проскальзывание в тиках
    tick: float = 0.001             # шаг цены CNY
    multiplier: float = 1000.0      # руб. на 1.0 изменения цены (1 контракт = 1000 CNY)
    go: float = 0.0                 # ГО на контракт, руб. (0 = не считать)

    def slip(self) -> float:
        return self.slippage_ticks * self.tick


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int
    entry_price: float
    exit_price: float
    pnl: float
    commission: float

    @property
    def net(self) -> float:
        return self.pnl - self.commission


@dataclass
class Result:
    trades: list[Trade]
    equity: pd.Series
    position: pd.Series
    stats: dict[str, Any] = field(default_factory=dict)


def run(df: pd.DataFrame, targets: pd.Series, costs: Costs | None = None) -> Result:
    """Прогоняет целевую позицию по барам.

    targets — желаемая позиция ПОСЛЕ закрытия бара (в контрактах, со знаком).
    Позиция на баре t = targets[t-1].
    """
    costs = costs or Costs()
    df = df.copy()
    pos_target = targets.reindex(df.index).shift(1).fillna(0).astype(int)

    o = df["open"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    tg = pos_target.to_numpy(dtype=int)
    idx = df.index

    pos = 0
    entry_price = 0.0
    entry_time = None
    realized = 0.0
    commissions = 0.0
    entry_commission = 0.0
    slip = costs.slip()

    equity = np.empty(len(df))
    trades: list[Trade] = []

    for i in range(len(df)):
        target = tg[i]
        price_open = o[i]

        if target != pos:
            # закрываем старую позицию
            if pos != 0:
                exit_price = price_open - pos * slip
                pnl = (exit_price - entry_price) * costs.multiplier * pos
                com = abs(exit_price) * costs.multiplier * abs(pos) * costs.commission_pct
                realized += pnl
                commissions += com
                trades.append(
                    Trade(entry_time, idx[i], pos, entry_price, exit_price, pnl,
                          com + entry_commission)
                )
            # открываем новую
            if target != 0:
                entry_price = price_open + target * slip
                entry_time = idx[i]
                entry_commission = (
                    abs(entry_price) * costs.multiplier * abs(target) * costs.commission_pct
                )
                commissions += entry_commission
            else:
                entry_price = 0.0
            pos = target

        unrealized = (c[i] - entry_price) * costs.multiplier * pos if pos != 0 else 0.0
        equity[i] = realized + unrealized - commissions

    eq = pd.Series(equity, index=idx, name="equity")
    st = _stats(trades, eq, costs, pos_target)
    return Result(trades=trades, equity=eq, position=pos_target, stats=st)


def _stats(
    trades: list[Trade], eq: pd.Series, costs: Costs, pos: pd.Series | None = None
) -> dict[str, Any]:
    if not trades:
        return {"trades": 0}

    pnl = np.array([t.net for t in trades])
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0

    dd = eq - eq.cummax()
    max_dd = float(dd.min())
    peak = float(eq.cummax().iloc[-1]) or 0.0

    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = float(pnl.sum())
    return {
        "trades": len(trades),
        "net_profit": round(total, 2),
        "in_market_pct": round(100 * float((pos != 0).mean()), 1) if pos is not None else None,
        "win_rate": round(100 * len(wins) / len(trades), 1),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else float("inf"),
        "avg_trade": round(total / len(trades), 2),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_dd_pct_of_peak": round(100 * max_dd / peak, 1) if peak else 0.0,
        "years": round(years, 2),
        "return_per_year": round(total / years, 2) if years else 0.0,
        "go": costs.go,
        "return_on_go_per_year": round(total / years / costs.go * 100, 1) if costs.go and years else None,
    }


def yearly(trades: list[Trade]) -> pd.DataFrame:
    """Разбивка результата по годам закрытия сделок."""
    if not trades:
        return pd.DataFrame()
    rows = []
    for t in trades:
        rows.append({"year": t.exit_time.year, "net": t.net})
    df = pd.DataFrame(rows)
    g = df.groupby("year")["net"].agg(["count", "sum", "mean"])
    g.columns = ["trades", "net", "avg"]
    g["net"] = g["net"].round(0)
    g["avg"] = g["avg"].round(1)
    return g
