"""Метрики портфеля и роботов, очищенные от внешних денежных потоков.

Чистый расчётный слой: только stdlib, не зависит от FastAPI, Jinja и БД.
Пополнения и снятия не считаются доходностью — сначала из equity вычитается
накопленный внешний поток, и уже по очищенной кривой считаются TWR/MWR, DD,
Sharpe/Sortino. При короткой истории метрики возвращают ``None`` (в UI — «н/д»).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

METRICS_NA = "н/д"     # подпись для недостающих метрик в UI
MIN_SAMPLES = 30       # минимум наблюдений для Sharpe/Sortino


@dataclass(frozen=True)
class EquityPoint:
    """Точка кривой капитала.

    `cash_flow` — внешний поток в эту точку, уже включённый в `equity`
    (положительный — пополнение/дивиденд, отрицательный — снятие).
    `net_trading_pnl` — накопительный чистый торговый результат, если его
    хранит источник; используется только для отчёта, не для очистки кривой.
    """

    timestamp: str
    equity: float
    cash_flow: float = 0.0
    net_trading_pnl: float | None = None


@dataclass(frozen=True)
class Trade:
    """Исполненная сделка. `pnl` — результат уже с комиссией (net)."""

    pnl: float
    commission: float = 0.0
    timestamp: str = ""
    symbol: str = ""


def clean_equity(points: Sequence[EquityPoint]) -> list[float]:
    """Капитал без внешних потоков — основа всех метрик доходности."""
    flow_sum = 0.0
    out: list[float] = []
    for point in points:
        flow_sum += float(point.cash_flow)
        out.append(float(point.equity) - flow_sum)
    return out


def net_trading_result(points: Sequence[EquityPoint],
                       trades: Sequence[Trade] = ()) -> float:
    """Чистый торговый результат: из источника или из сделок, не из потока."""
    if points and points[-1].net_trading_pnl is not None:
        return float(points[-1].net_trading_pnl)
    if trades:
        return round(sum(t.pnl for t in trades), 2)
    if len(points) >= 2:
        equity = clean_equity(points)
        return round(equity[-1] - equity[0], 2)
    return 0.0


def twr(points: Sequence[EquityPoint]) -> float | None:
    """Взвешенная по времени доходность: цепочка доходностей между потоками."""
    equity = clean_equity(points)
    if len(equity) < 2 or any(value <= 0 for value in equity[:-1]):
        return None
    growth = 1.0
    for previous, current in zip(equity, equity[1:]):
        growth *= current / previous
    return growth - 1.0


def _days_between(start: str, end: str, fallback: int) -> int:
    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
    except (ValueError, TypeError):
        return fallback


def mwr(points: Sequence[EquityPoint], days_per_year: float = 365.0) -> float | None:
    """Денежно-взвешенная доходность (XIRR) по внешним потокам.

    Со стороны инвестора: начальные вложения и пополнения — отрицательный
    поток, снятия и остаточная стоимость — положительный. Решается бисекцией
    годовой ставки; при отсутствии значной смены знака — ``None``.
    """
    if len(points) < 2:
        return None
    start = float(points[0].equity)
    final = float(points[-1].equity)
    if start <= 0 or final < 0:
        return None

    flows: list[tuple[int, float]] = [(0, -start)]
    for index, point in enumerate(points[1:], start=1):
        if point.cash_flow:
            days = _days_between(points[0].timestamp, point.timestamp, index)
            flows.append((days, -float(point.cash_flow)))
    last_days = _days_between(points[0].timestamp, points[-1].timestamp, len(points) - 1)
    if last_days == 0:
        last_days = 1
    flows.append((last_days, final))

    def npv(rate: float) -> float:
        if rate <= -0.999999:
            return float("inf")
        return sum(cash / (1.0 + rate) ** (days / days_per_year)
                   for days, cash in flows)

    low, high = -0.9999, 10.0
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        return None
    for _ in range(200):
        middle = (low + high) / 2.0
        f_middle = npv(middle)
        if f_low * f_middle <= 0:
            high, f_high = middle, f_middle
        else:
            low, f_low = middle, f_middle
    return (low + high) / 2.0


def drawdown(points: Sequence[EquityPoint]) -> dict:
    """Текущая и максимальная просадка по очищенной кривой (знак минус)."""
    equity = clean_equity(points)
    if not equity:
        return {"current_dd": 0.0, "max_dd": 0.0, "current_dd_pct": 0.0,
                "max_dd_pct": 0.0, "max_dd_days": 0}

    peak = equity[0]
    peak_index = 0
    max_dd = 0.0
    max_days = 0
    peak_for_max = peak_index
    for index, value in enumerate(equity):
        if value >= peak:
            peak, peak_index = value, index
            continue
        depth = value - peak
        if depth < max_dd:
            max_dd = depth
            peak_for_max = peak_index
            max_days = _days_between(points[peak_for_max].timestamp,
                                     points[index].timestamp, index - peak_for_max)
    current = equity[-1] - peak
    return {
        "current_dd": round(current, 2),
        "max_dd": round(max_dd, 2),
        "current_dd_pct": round(100.0 * current / peak, 2) if peak > 0 else 0.0,
        "max_dd_pct": round(100.0 * max_dd / peak, 2) if peak > 0 else 0.0,
        "max_dd_days": max_days,
    }


def _returns(points: Sequence[EquityPoint]) -> list[float]:
    equity = clean_equity(points)
    return [current / previous - 1.0
            for previous, current in zip(equity, equity[1:]) if previous > 0]


def sharpe(points: Sequence[EquityPoint], risk_free: float = 0.0,
           periods_per_year: int = 252) -> float | None:
    """Годовой Sharpe по дневным доходностям. Короткая история — ``None``."""
    returns = _returns(points)
    if len(returns) < MIN_SAMPLES:
        return None
    target = risk_free / periods_per_year
    excess = [value - target for value in returns]
    mean = sum(excess) / len(excess)
    variance = sum((value - mean) ** 2 for value in excess) / (len(excess) - 1)
    if variance <= 0:
        return None
    return mean / variance ** 0.5 * periods_per_year ** 0.5


def sortino(points: Sequence[EquityPoint], risk_free: float = 0.0,
            periods_per_year: int = 252) -> float | None:
    """Годовой Sortino: риск считается только по отрицательным отклонениям."""
    returns = _returns(points)
    if len(returns) < MIN_SAMPLES:
        return None
    target = risk_free / periods_per_year
    excess = [value - target for value in returns]
    mean = sum(excess) / len(excess)
    downside = sum(min(0.0, value - target) ** 2 for value in excess) / len(excess)
    if downside <= 0:
        return None
    return mean / downside ** 0.5 * periods_per_year ** 0.5


def realized_pnl(trades: Sequence[Trade]) -> float:
    return round(sum(trade.pnl for trade in trades), 2)


def winrate(trades: Sequence[Trade]) -> float | None:
    """Доля прибыльных сделок, %. Нет сделок — ``None``."""
    if not trades:
        return None
    return round(100.0 * sum(1 for t in trades if t.pnl > 0) / len(trades), 2)


def profit_factor(trades: Sequence[Trade]) -> float | None:
    """Прибыль / убыток. Без убыточных сделок значение не определено."""
    gains = sum(t.pnl for t in trades if t.pnl > 0)
    losses = -sum(t.pnl for t in trades if t.pnl < 0)
    if losses <= 0:
        return None
    return round(gains / losses, 2)


def expectancy(trades: Sequence[Trade]) -> float | None:
    """Средний результат на сделку, ₽."""
    if not trades:
        return None
    return round(sum(t.pnl for t in trades) / len(trades), 2)


def streaks(trades: Sequence[Trade]) -> dict:
    """Самые длинные серии прибыльных и убыточных сделок."""
    best_win = best_loss = win = loss = 0
    for trade in trades:
        if trade.pnl > 0:
            win, loss = win + 1, 0
            best_win = max(best_win, win)
        elif trade.pnl < 0:
            loss, win = loss + 1, 0
            best_loss = max(best_loss, loss)
        else:
            win = loss = 0
    return {"max_win_streak": best_win, "max_loss_streak": best_loss}


@dataclass(frozen=True)
class PortfolioMetrics:
    """Сводка для API/UI. ``None`` означает «н/д» при короткой истории."""

    equity: float
    net_pnl: float
    twr: float | None
    mwr: float | None
    current_dd: float
    max_dd: float
    max_dd_days: int
    sharpe: float | None
    sortino: float | None
    trades: int
    winrate: float | None
    profit_factor: float | None
    expectancy: float | None

    def to_dict(self) -> dict:
        return {
            "equity": self.equity,
            "net_pnl": self.net_pnl,
            "twr": self.twr,
            "mwr": self.mwr,
            "current_dd": self.current_dd,
            "max_dd": self.max_dd,
            "max_dd_days": self.max_dd_days,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "trades": self.trades,
            "winrate": self.winrate,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
        }


def summarize(points: Sequence[EquityPoint],
              trades: Sequence[Trade] = ()) -> PortfolioMetrics:
    """Все метрики одним вызовом; потоки уже исключены из кривой."""
    dd = drawdown(points)
    return PortfolioMetrics(
        equity=round(float(points[-1].equity), 2) if points else 0.0,
        net_pnl=net_trading_result(points, trades),
        twr=twr(points),
        mwr=mwr(points),
        current_dd=dd["current_dd"],
        max_dd=dd["max_dd"],
        max_dd_days=dd["max_dd_days"],
        sharpe=sharpe(points),
        sortino=sortino(points),
        trades=len(trades),
        winrate=winrate(trades),
        profit_factor=profit_factor(trades),
        expectancy=expectancy(trades),
    )


def display(value: float | None, digits: int = 2, percent: bool = False) -> str:
    """Подпись метрики для UI: ``None`` → «н/д»."""
    if value is None:
        return METRICS_NA
    text = f"{value:,.{digits}f}".replace(",", " ")
    return text + (" %" if percent else "")
