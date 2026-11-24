"""Денежные потоки и предпросмотр влияния на лотность.

Чистый расчётный слой: не зависит от FastAPI, Jinja и БД. Источник правды
по деньгам — брокер; здесь фиксируется уже обнаруженная операция для журнала,
метрик и сайзинга, а не изменение брокерского equity. Лотность считается
только через :func:`algo.portfolio.size_contracts` — второго расчёта нет.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from .portfolio import GO, MULT, size_contracts


class CashFlowType(str, Enum):
    """Тип внешней операции. Знак задаётся типом, `amount` — положительная величина."""

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    DIVIDEND = "DIVIDEND"
    VIRTUAL_RESET = "VIRTUAL_RESET"  # для тестовых счетов: amount = целевой баланс


class Reaction(str, Enum):
    """Когда робот применяет новый баланс к расчётной лотности."""

    IMMEDIATE = "IMMEDIATE"      # сразу
    AFTER_CLOSE = "AFTER_CLOSE"  # после закрытия открытой позиции
    SMOOTHED = "SMOOTHED"        # при превышении порога изменения баланса, %


class InsufficientPolicy(str, Enum):
    """Поведение при нехватке средств под расчётный лот."""

    PAUSE = "PAUSE"      # уйти в паузу, новых входов нет
    MIN_LOT = "MIN_LOT"  # попытаться минимальным лотом
    SKIP = "SKIP"        # пропустить вход, не меняя статус робота


class LotStatus(str, Enum):
    UNCHANGED = "UNCHANGED"
    INCREASED = "INCREASED"
    REDUCED = "REDUCED"
    DEFERRED = "DEFERRED"  # изменение отложено (позиция открыта / порог не пройден)
    PAUSED = "PAUSED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class CashFlow:
    """Одна операция по счёту. Поля совпадают с будущей таблицей `cash_flows`."""

    type: CashFlowType
    amount: float
    balance_before: float
    balance_after: float
    created_at: str = ""
    broker_tx_id: str = ""  # id транзакции брокера — первичный ключ идемпотентности
    client_key: str = ""    # ключ идемпотентности для виртуальных счетов
    note: str = ""

    @classmethod
    def detect(cls, flow_type: CashFlowType | str, amount: float,
               balance_before: float, **kwargs) -> "CashFlow":
        """Создать запись с вычисленным балансом после операции."""
        kind = CashFlowType(flow_type)
        if kind is CashFlowType.VIRTUAL_RESET:
            after = float(amount)
        elif kind in (CashFlowType.DEPOSIT, CashFlowType.DIVIDEND):
            after = float(balance_before) + float(amount)
        elif kind is CashFlowType.WITHDRAWAL:
            after = float(balance_before) - float(amount)
        else:  # защита от нового типа без правила
            raise ValueError(f"неизвестный тип операции: {kind}")
        return cls(type=kind, amount=float(amount), balance_before=float(balance_before),
                   balance_after=after, **kwargs)

    @property
    def delta(self) -> float:
        """Изменение баланса счёта, знаковое."""
        return self.balance_after - self.balance_before

    @property
    def key(self) -> str:
        """Стабильный ключ идемпотентности: брокер → клиент → хэш полей."""
        if self.broker_tx_id:
            return f"broker:{self.broker_tx_id}"
        if self.client_key:
            return f"client:{self.client_key}"
        raw = f"{self.type.value}|{self.amount}|{self.balance_before}|{self.created_at}"
        return "auto:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class RobotSizing:
    """Настройки сайзинга одного робота счёта для предпросмотра."""

    robot_id: str
    name: str = ""
    price: float = 0.0
    mult: float = MULT
    exposure: float | None = None  # None — общий EXPOSURE из algo.portfolio
    margin_per_lot: float = GO     # ГО на контракт для проверки достаточности средств
    position_lots: int = 0
    reaction: Reaction = Reaction.IMMEDIATE
    smoothing_pct: float = 0.0
    sizing_base: float | None = None  # баланс, на который уже применён текущий лот
    min_lots: int = 1
    max_lots: int | None = None
    on_insufficient: InsufficientPolicy = InsufficientPolicy.PAUSE


@dataclass(frozen=True)
class LotImpact:
    """Строка таблицы «лот до → лот после» для одного робота."""

    robot_id: str
    name: str
    lots_before: int
    lots_after: int
    effective_lots: int  # лоты, доступные для следующей сделки (0 = входов нет)
    status: LotStatus
    reaction: Reaction
    note: str = ""


@dataclass(frozen=True)
class Validation:
    """Результат двухуровневой проверки."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.warnings)


@dataclass(frozen=True)
class CashFlowPreview:
    """Расчёт без записи: пригоден и для LIVE, и для симулятора потоков."""

    flow: CashFlow
    free_before: float
    free_after: float
    impacts: tuple[LotImpact, ...]
    validation: Validation

    @property
    def valid(self) -> bool:
        return self.validation.ok

    @property
    def requires_confirmation(self) -> bool:
        return self.validation.needs_confirmation

    def as_rows(self) -> list[dict]:
        """Готовые строки для таблицы UI/API."""
        return [{
            "robot_id": i.robot_id,
            "name": i.name,
            "lots_before": i.lots_before,
            "lots_after": i.lots_after,
            "effective_lots": i.effective_lots,
            "status": i.status.value,
            "reaction": i.reaction.value,
            "note": i.note,
        } for i in self.impacts]


def _lots(robot: RobotSizing, equity: float) -> int:
    """Лот через единственный расчёт, с ограничениями min/max.

    При невалидном equity/цене `size_contracts()` даёт 0 — `min_lots` не должен
    воскрешать позицию на битых данных (ADR 24.11).
    """
    raw = size_contracts(equity, robot.price, robot.mult, robot.exposure)
    if raw <= 0:
        return 0
    lots = max(raw, max(0, robot.min_lots))
    if robot.max_lots is not None:
        lots = min(lots, robot.max_lots)
    return lots


def _base_before(robot: RobotSizing, flow: CashFlow) -> float:
    if robot.reaction is Reaction.SMOOTHED and robot.sizing_base is not None:
        return robot.sizing_base
    return flow.balance_before


def _base_after(robot: RobotSizing, flow: CashFlow) -> tuple[float, bool]:
    """Новая база сайзинга и флаг «применять сейчас»."""
    before = _base_before(robot, flow)
    if robot.reaction is Reaction.AFTER_CLOSE and robot.position_lots != 0:
        return before, False
    if robot.reaction is Reaction.SMOOTHED:
        if before <= 0:
            return before, False
        change = abs(flow.balance_after - before) / before * 100.0
        if change < robot.smoothing_pct:
            return before, False
    return flow.balance_after, True


def _field_validation(flow: CashFlow, known_keys: Iterable[str]) -> tuple[list[str], list[str]]:
    """Уровень 1: формальные ошибки и уровень 2: предупреждения о риске."""
    errors: list[str] = []
    try:
        kind = CashFlowType(flow.type)
    except ValueError:
        return [f"неизвестный тип операции: {flow.type}"], []

    if kind is CashFlowType.VIRTUAL_RESET:
        if flow.amount < 0:
            errors.append("целевой баланс не может быть отрицательным")
    elif flow.amount <= 0:
        errors.append("сумма операции должна быть положительной")

    expected = CashFlow.detect(kind, flow.amount, flow.balance_before)
    if abs(expected.balance_after - flow.balance_after) > 1e-6:
        errors.append("баланс после операции не соответствует типу и сумме")
    if kind is CashFlowType.WITHDRAWAL and flow.amount > flow.balance_before + 1e-6:
        errors.append("недостаточно средств на счёте для снятия")
    if flow.balance_after < -1e-6:
        errors.append("баланс после операции отрицательный")

    if flow.key in set(known_keys):
        errors.append("повтор операции: такой ключ уже записан (идемпотентность)")
    return errors, []


def preview_cash_flow(flow: CashFlow,
                      robots: Sequence[RobotSizing] = (),
                      free_before: float | None = None,
                      known_keys: Iterable[str] = (),
                      live: bool = False,
                      large_flow_pct: float = 20.0) -> CashFlowPreview:
    """Предпросмотр операции: баланс, свободные средства и лотность роботов счёта.

    `free_before` — остаток средств для новых входов; по умолчанию равен балансу.
    Затем из него последовательно вычитается ГО по роботам, у которых сайзинг
    применяется сейчас. Отложенные изменения (AFTER_CLOSE / SMOOTHED) ГО не
    резервируют, поэтому не мешают соседним роботам.
    """
    errors, warnings = _field_validation(flow, known_keys)
    start_free = flow.balance_before if free_before is None else float(free_before)
    available = start_free + flow.delta

    impacts: list[LotImpact] = []
    for robot in robots:
        before = _lots(robot, _base_before(robot, flow))
        base_after, apply_now = _base_after(robot, flow)
        after = _lots(robot, base_after) if apply_now else before

        if not apply_now:
            status = LotStatus.DEFERRED
            note = ("до закрытия позиции" if robot.reaction is Reaction.AFTER_CLOSE
                    else f"изменение ниже порога {robot.smoothing_pct:g}%")
            effective = before
        else:
            required = after * robot.margin_per_lot
            if after <= 0 or required <= available + 1e-6:
                effective = after
                status = (LotStatus.INCREASED if after > before else
                          LotStatus.REDUCED if after < before else LotStatus.UNCHANGED)
                note = ""
                available -= required
            elif (robot.on_insufficient is InsufficientPolicy.MIN_LOT
                  and robot.min_lots > 0
                  and robot.min_lots * robot.margin_per_lot <= available + 1e-6):
                effective = robot.min_lots
                status = LotStatus.REDUCED
                note = f"ограничено остатком средств: {effective} лот(ов)"
                available -= effective * robot.margin_per_lot
            else:
                effective = 0
                status = (LotStatus.PAUSED if robot.on_insufficient is InsufficientPolicy.PAUSE
                          else LotStatus.SKIPPED)
                note = (f"недостаточно средств: нужно {required:,.0f} ₽ ГО, "
                        f"доступно {max(available, 0):,.0f} ₽")

        impacts.append(LotImpact(robot_id=robot.robot_id, name=robot.name or robot.robot_id,
                                 lots_before=before, lots_after=after,
                                 effective_lots=effective, status=status,
                                 reaction=robot.reaction, note=note))

    if live:
        warnings.append("LIVE: операция обнаружена у брокера; ручное изменение баланса запрещено")
    if flow.balance_before > 0 and large_flow_pct > 0:
        if abs(flow.delta) / flow.balance_before * 100.0 >= large_flow_pct:
            warnings.append("крупная операция: проверьте сумму и список роботов счёта")
    if (flow.type is CashFlowType.WITHDRAWAL
            and free_before is not None and flow.amount > float(free_before)):
        warnings.append("снятие превышает свободные средства: возможны принудительные закрытия")
    if available < -1e-6:
        warnings.append("отрицательный остаток средств после операции")
    for impact in impacts:
        if impact.effective_lots == 0 and impact.lots_before > 0:
            warnings.append(f"робот {impact.name}: входы запрещены после операции")
        elif impact.status is LotStatus.DEFERRED:
            warnings.append(f"робот {impact.name}: пересчёт лотности отложен")

    return CashFlowPreview(flow=flow, free_before=start_free, free_after=available,
                           impacts=tuple(impacts),
                           validation=Validation(tuple(errors), tuple(warnings)))


def validate_cash_flow(flow: CashFlow,
                       robots: Sequence[RobotSizing] = (),
                       free_before: float | None = None,
                       known_keys: Iterable[str] = (),
                       live: bool = False,
                       large_flow_pct: float = 20.0) -> Validation:
    """Уровни 1 и 2 одной функцией: ошибки блокируют, предупреждения — подтверждение."""
    return preview_cash_flow(flow, robots, free_before, known_keys, live,
                             large_flow_pct).validation


def stress_preview(balance: float, drop_pct: float,
                   robots: Sequence[RobotSizing] = (), **kwargs) -> CashFlowPreview:
    """Гипотетический сценарий «баланс упадёт на X%» без реального изменения баланса."""
    amount = round(float(balance) * float(drop_pct) / 100.0, 2)
    flow = CashFlow.detect(CashFlowType.WITHDRAWAL, amount, balance,
                           note=f"стресс-сценарий: −{drop_pct:g}%")
    return preview_cash_flow(flow, robots, free_before=balance, **kwargs)
