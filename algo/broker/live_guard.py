"""Предохранители боевого контура (G3 → G4). Не включают торговлю сами по себе.

Модуль готовит то, чего не хватало в `live-execution.md`: боевые лимиты из
реального капитала, STOP перед каждой заявкой, уникальный `client_id` и
блокирующую сверку позиций с брокером. Ни один вызов не отправляет заявку —
отправка остаётся исключительно в `OrderGateway.submit()`.

Решения:
- 2026-11-23 — лимиты считаются от equity счёта, а не хардкодятся (5 млн
  номинала и 100 контрактов не являются боевыми значениями);
- 2026-11-23 — STOP проверяется перед каждой заявкой, а не только в начале
  прогона: флаг может быть выставлен и mid-session;
- 2026-11-23 — `client_id` включает время и порядковый номер решения, иначе
  два одноправленных решения по одному конфигу в день дают ложный `duplicate`;
- 2026-11-23 — расхождение позиций с брокером выставляет `STOP_REAL` и
  прерывaет прогон: торговать с расхождением запрещено воротами G3.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from typing import Any

from .execution import ExecutionError, Limits, positions_from_response, reconcile

ROOT = Path(__file__).resolve().parent.parent.parent
STOP_REAL = ROOT / "results" / "STOP_REAL"

# Вечный том-контракт юаня: экспирации не имеет (ADR 18.11).
PERPETUAL_SYMBOLS = frozenset({"CNYRUBF@RTSX"})
EXPIRY_MONTHS = (3, 6, 9, 12)  # квартальные контракты MOEX, третий четверг


class PricingMode(str, Enum):
    SIGNAL = "signal"        # лимитка по цене сигнала из paper.csv
    MARKETABLE = "marketable"  # лимитка за спред: ask+тик / bid-тик
    MARKET = "market"        # ORDER_TYPE_MARKET


def parse_pricing(value: Any, name: str = "pricing") -> PricingMode:
    try:
        return PricingMode(str(value).lower())
    except ValueError as exc:
        raise ExecutionError(
            f"{name}: неизвестный режим {value!r}; допустимо "
            f"{', '.join(m.value for m in PricingMode)}") from exc


def round_to_tick(value: float, tick: float) -> float:
    """Округление цены до шага инструмента (Decimal, без бинарного мусора)."""
    if tick <= 0:
        return float(value)
    step = Decimal(str(tick))
    q = (Decimal(str(value)) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(q * step)


def third_thursday(year: int, month: int) -> dt.date:
    """Третий четверг месяца — дата экспирации квартального фьючерса MOEX."""
    first = dt.date(year, month, 1)
    offset = (3 - first.weekday()) % 7  # Thursday == 3
    return first + dt.timedelta(days=offset + 14)


def is_expiry_day(day: dt.date, symbol: str | None = None) -> bool:
    """day — день экспирации квартального контракта (вечные — никогда)."""
    if symbol and symbol in PERPETUAL_SYMBOLS:
        return False
    return day.month in EXPIRY_MONTHS and day == third_thursday(day.year, day.month)


def expiry_allows(day: dt.date, symbol: str, delta: int,
                  trade_on_expiry: bool) -> bool:
    """False → в день экспирации не открываем/увеличиваем позицию.

    Закрытие и уменьшение (delta < 0) разрешены всегда — иначе позиция уйдёт
    в экспирацию незакрытой.
    """
    if trade_on_expiry or not is_expiry_day(day, symbol):
        return True
    return delta <= 0


def quote_age_sec(quote: Any, now: dt.datetime | None = None) -> float | None:
    """Возраст котировки в секундах; None, если метка времени непонятна."""
    raw = getattr(quote, "timestamp", "")
    if not raw:
        return None
    try:
        ts = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    return max(0.0, (now - ts).total_seconds())


def price_for(mode: PricingMode, signal_price: float, side: str,
              quote: Any, tick: float, market_offset_ticks: int = 1
              ) -> tuple[float, str, str]:
    """Цена, тип заявки и пояснение для журнала.

    При `market` возвращённая цена — справочная (для проверки номинала).
    Вызывающий обязан проверить свежесть quote для MARKETABLE/MARKET и
    при необходимости отказаться от заявки.
    """
    buy = side.lower() in ("buy", "long", "1")
    if mode is PricingMode.MARKET:
        ref = getattr(quote, "last", 0) or signal_price
        return round_to_tick(float(ref), tick), "market", "рыночная заявка"
    if quote is None:
        return round_to_tick(signal_price, tick), "limit", "цена сигнала (нет котировки)"
    if mode is PricingMode.MARKETABLE:
        raw = float(getattr(quote, "ask" if buy else "bid", 0) or 0)
        if raw <= 0:
            raise ExecutionError("в котировке нет цены ask/bid")
        shift = tick * abs(market_offset_ticks) * (1 if buy else -1)
        return round_to_tick(raw + shift, tick), "limit", "маркет-лимит за спред"
    return round_to_tick(signal_price, tick), "limit", "цена сигнала"


@dataclass(frozen=True)
class BattleLimits:
    """Лимиты под реальный капитал. Конвертируются в `Limits` шлюза."""

    capital: float
    max_exposure: float = 2.0
    max_daily_loss_pct: float = 0.03
    max_qty: int = 100
    allowed_symbols: frozenset[str] | None = None

    @property
    def max_notional(self) -> float:
        return self.capital * self.max_exposure

    @property
    def max_daily_loss(self) -> float:
        return self.capital * self.max_daily_loss_pct

    def as_limits(self) -> Limits:
        return Limits(
            max_qty=self.max_qty,
            max_notional=self.max_notional,
            max_daily_loss=self.max_daily_loss,
            allowed_symbols=self.allowed_symbols,
        )


def battle_limits(capital: float, max_exposure: float = 2.0,
                  max_qty: int = 100,
                  allowed_symbols: set[str] | None = None) -> BattleLimits:
    """Боевые лимиты из капитала счёта. TODO: max_qty считается из лотности."""
    if capital <= 0:
        raise ValueError("капитал должен быть положительным")
    return BattleLimits(
        capital=float(capital),
        max_exposure=float(max_exposure),
        max_qty=int(max_qty),
        allowed_symbols=frozenset(allowed_symbols) if allowed_symbols else None,
    )


def assert_stop_clear(stop: Path = STOP_REAL) -> None:
    """STOP перед заявкой. Флаг выставлен — торговля немедленно прекращается."""
    if stop.exists():
        raise ExecutionError(f"боевой STOP установлен: {stop}")


def decision_client_id(config: str, day: str, side: str,
                       when: str = "", seq: int = 0) -> str:
    """Уникальный ключ решения: конфиг + дата + время + сторона + номер.

    Время и номер нужны, чтобы два одноправленных решения в день не превращались
    в `duplicate` (старый формат `config:date:side` страдал этим).
    """
    parts = [config, str(day), when or "na", side, str(int(seq))]
    return ":".join(parts)


def reconcile_guard(broker: Any, expected: dict[str, int], *,
                    account: str | None = None, stop: Path = STOP_REAL,
                    enforce: bool = True) -> list[str]:
    """Сверка позиций модели и брокера. При расхождении выставляет STOP.

    `enforce=False` оставляет сверку информационной — режим репетиции, где
    бумажные позиции заведомо не уходят брокеру (`shadow.json`).
    """
    response = broker.account(account)
    actual = positions_from_response(response.get("positions", response))
    issues = reconcile(expected, actual)
    if issues and enforce:
        stop.parent.mkdir(parents=True, exist_ok=True)
        stop.write_text("\n".join(issues) + "\n", encoding="utf-8")
        raise ExecutionError("расхождение позиций с брокером: " + "; ".join(issues))
    return issues
