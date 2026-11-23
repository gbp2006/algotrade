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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .execution import ExecutionError, Limits, positions_from_response, reconcile

ROOT = Path(__file__).resolve().parent.parent.parent
STOP_REAL = ROOT / "results" / "STOP_REAL"


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
                    stop: Path = STOP_REAL, enforce: bool = True) -> list[str]:
    """Сверка позиций модели и брокера. При расхождении выставляет STOP.

    `enforce=False` оставляет сверку информационной — режим репетиции, где
    бумажные позиции заведомо не уходят брокеру (`shadow.json`).
    """
    account = broker.account()
    actual = positions_from_response(account.get("positions", account))
    issues = reconcile(expected, actual)
    if issues and enforce:
        stop.parent.mkdir(parents=True, exist_ok=True)
        stop.write_text("\n".join(issues) + "\n", encoding="utf-8")
        raise ExecutionError("расхождение позиций с брокером: " + "; ".join(issues))
    return issues
