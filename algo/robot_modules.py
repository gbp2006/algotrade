"""Переиспользуемые модули робота: сайзинг и правила выхода.

Чистые функции без состояния и без сети. Модули **не подключены** к текущему
контуру: модель сигналов, ATR-сайзинг (ADR 19.11) и дневной лимит (ADR 23.11)
остаются выключенными до отдельного решения. Сайзинг использует единственный
`size_contracts()` — второй формулы здесь нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .portfolio import MULT, size_contracts


class SizingMode(str, Enum):
    FIXED = "FIXED"        # фиксированный лот
    PERCENT = "PERCENT"    # процент от баланса через общий расчёт лотности
    STEPPED = "STEPPED"    # ступени: (баланс от, лотов)


class ExitReason(str, Enum):
    HOLD = "HOLD"
    STOP = "STOP"
    TAKE = "TAKE"
    TRAIL = "TRAIL"
    BREAKEVEN = "BREAKEVEN"
    TIME = "TIME"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True)
class SizingConfig:
    mode: SizingMode = SizingMode.PERCENT
    value: float = 100.0            # лоты для FIXED, % для PERCENT
    steps: tuple[tuple[float, int], ...] = ()
    min_lots: int = 1
    max_lots: int | None = None
    use_atr: bool = False           # выключено по ADR 19.11


@dataclass(frozen=True)
class ExitConfig:
    stop_loss_pct: float = 0.0      # 0 = модуль выключен
    take_profit_pct: float = 0.0
    trailing_pct: float = 0.0
    breakeven_after_pct: float = 0.0
    close_time: str = ""            # HH:MM МСК, пусто = выключено
    partial_close_pct: float = 0.0


def sizing_lots(balance: float, price: float, config: SizingConfig,
                mult: float = MULT) -> int:
    """Лот по выбранному режиму. Битые данные дают 0, не минимальный лот."""
    if balance <= 0 or price <= 0:
        return 0
    if config.mode is SizingMode.FIXED:
        raw = int(config.value)
    elif config.mode is SizingMode.PERCENT:
        # Экспозиция в долях: 100% → 1.0, 200% → 2.0.
        raw = size_contracts(balance, price, mult, config.value / 100.0)
    else:
        applicable = [lots for threshold, lots in config.steps
                      if balance >= threshold]
        raw = max(applicable) if applicable else 0
    if raw <= 0:
        return 0
    lots = max(raw, max(0, config.min_lots))
    if config.max_lots is not None:
        lots = min(lots, config.max_lots)
    return lots


def _move(side: int, entry: float, current: float) -> float:
    """Движение в пользу позиции, % (side: +1 лонг, -1 шорт)."""
    if entry <= 0:
        return 0.0
    return side * (current - entry) / entry * 100.0


def exit_reason(config: ExitConfig, entry: float, current: float,
                side: int, extreme: float | None = None,
                now: str = "") -> ExitReason:
    """Первое сработавшее правило выхода; приоритет — стоп, затем остальные.

    `extreme` — лучшая цена за время жизни позиции (для трейлинга).
    Правила с нулевым значением не участвуют; сигналы стратегии не меняются.
    """
    if entry <= 0 or current <= 0 or side == 0:
        return ExitReason.HOLD
    adverse = -_move(side, entry, current)
    if config.stop_loss_pct > 0 and adverse >= config.stop_loss_pct:
        return ExitReason.STOP
    favorable = _move(side, entry, current)
    if config.take_profit_pct > 0 and favorable >= config.take_profit_pct:
        return ExitReason.TAKE
    if config.trailing_pct > 0 and extreme and extreme > 0:
        peak_favorable = _move(side, entry, extreme)
        if peak_favorable - favorable >= config.trailing_pct:
            return ExitReason.TRAIL
    if (config.breakeven_after_pct > 0
            and _move(side, entry, extreme or current) >= config.breakeven_after_pct
            and side * (current - entry) >= 0):
        return ExitReason.BREAKEVEN
    if config.close_time and now and now[-5:] >= config.close_time:
        return ExitReason.TIME
    if (config.partial_close_pct > 0
            and favorable >= max(config.take_profit_pct, config.partial_close_pct) / 2):
        return ExitReason.PARTIAL
    return ExitReason.HOLD


def reduce_only_allowed(signal: str, position: int) -> bool:
    """Reduce-Only: новые входы запрещены, только выходы разрешены.

    Режим выключен в контуре (отдельный ADR), функция предназначена для
    будущей валидации заявок.
    """
    entering = signal in ("ENTER_LONG", "ENTER_SHORT")
    increasing = entering and ((signal == "ENTER_LONG" and position > 0)
                               or (signal == "ENTER_SHORT" and position < 0))
    return not increasing
