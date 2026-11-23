"""Квартальные фьючерсы: выбор ноги по ликвидности и перекладка позиции.

Модуль чистый: не ходит в сеть и не знает про брокера. На вход — контракты с
датами экспирации и дневные объёмы; на выход — решение о перекладке и две ноги.
Правила и порядок интеграции — docs/rollover-design.md.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Mapping

import pandas as pd

# Вечные контракты перекладки не требуют.
PERPETUAL = frozenset({"CNYRUBF@RTSX"})


@dataclass(frozen=True)
class RollDecision:
    day: dt.date
    held_symbol: str
    next_symbol: str
    qty: int
    reason: str
    roll_id: str = ""


@dataclass(frozen=True)
class RollLeg:
    symbol: str
    side: str            # buy / sell
    qty: int
    price: float
    role: str            # close / open
    roll_id: str


def days_to_expiry(day: dt.date, last_trade_date) -> int:
    """Календарные дни до последнего торгового дня контракта."""
    exp = dt.date.fromisoformat(str(last_trade_date)[:10])
    return (exp - day).days


def is_perpetual(symbol: str) -> bool:
    return symbol in PERPETUAL


def _volume_means(volumes: pd.DataFrame | None, day: dt.date,
                  window: int) -> pd.Series | None:
    if volumes is None or volumes.empty:
        return None
    v = volumes.copy()
    v.index = pd.to_datetime(v.index).normalize()
    hist = v[v.index < pd.Timestamp(day)].tail(window)
    if hist.empty:
        return None
    return hist.mean()


def front_on(day: dt.date, contracts: Mapping[str, str],
             volumes: pd.DataFrame | None = None, window: int = 5,
             exclude: str | None = None) -> str:
    """Front-contract по средней VOL за окно до дня решения.

    Если объёмов нет — откат к ближайшему неистёкшему контракту. `exclude`
    используется для принудительной перекладки перед экспирацией.
    """
    active = [s for s, exp in contracts.items()
              if days_to_expiry(day, exp) >= 0 and s != exclude]
    if not active:
        raise ValueError(f"{day}: нет активных контрактов")
    means = _volume_means(volumes, day, window)
    if means is None:
        return min(active, key=lambda s: days_to_expiry(day, contracts[s]))
    return max(active, key=lambda s: float(means.get(s, 0)))


def roll_decision(day: dt.date, held_symbol: str, qty: int,
                  contracts: Mapping[str, str],
                  volumes: pd.DataFrame | None = None,
                  policy: str = "volume",
                  force_before_expiry: int = 0) -> RollDecision | None:
    """Нужна ли перекладка. `qty` — знак и размер текущей позиции.

    policy:
      volume  — когда front по VOL отличается от удерживаемой ноги;
      never   — никогда (вечные контракты).
    force_before_expiry — за N календарных дней до экспирации переложиться
    принудительно, даже если VOL ещё не перешла.
    """
    if policy == "never" or is_perpetual(held_symbol):
        return None
    if qty == 0 or held_symbol not in contracts:
        return None

    left = days_to_expiry(day, contracts[held_symbol])
    if left < 0:
        return None  # контракт уже истёк — позиция должна быть закрыта заранее

    front = front_on(day, contracts, volumes)
    if front != held_symbol:
        reason = "переход ликвидности"
    elif force_before_expiry and left <= force_before_expiry:
        others = [s for s in contracts
                  if s != held_symbol and days_to_expiry(day, contracts[s]) >= 0]
        if not others:
            return None
        front = front_on(day, contracts, volumes, exclude=held_symbol)
        reason = f"до экспирации {left} дн."
    else:
        return None

    roll_id = hashlib.sha1(
        f"{day}:{held_symbol}:{front}:{qty}".encode("utf-8")).hexdigest()[:12]
    return RollDecision(day, held_symbol, front, qty, reason, roll_id)


def plan_roll(decision: RollDecision, old_price: float, new_price: float,
              ratio: float = 1.0) -> list[RollLeg]:
    """Две ноги с общим roll_id: закрыть старую, открыть новую."""
    if decision.next_symbol == decision.held_symbol:
        return []
    closing_side = "sell" if decision.qty > 0 else "buy"
    new_qty = round(abs(decision.qty) * ratio)
    if new_qty <= 0:
        raise ValueError("ratio слишком мал: новая нога нулевого размера")
    return [
        RollLeg(decision.held_symbol, closing_side, abs(decision.qty),
                old_price, "close", decision.roll_id),
        RollLeg(decision.next_symbol,
                "buy" if decision.qty > 0 else "sell", new_qty,
                new_price, "open", decision.roll_id),
    ]
