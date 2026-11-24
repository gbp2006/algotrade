"""Денежный рынок: доход на свободный капитал, не занятый в позициях.

Прототип идеи автора (фонды ликвидности, «единая денежная позиция») и робота
OsEngine ``TmonRebalancer``: свободные средства вечером уходят в фонд денежного
рынка, утром фонд продаётся. Наш ориентир — **FMMM** (БПИФ «Финам — Денежный
рынок»), у Финам комиссия за паи нулевая. У нас модель дневная — паи начисляют
доход каждый календарный день, а при росте ГО часть паёв продаётся обратно в кэш.

Что делает модуль:
- считает свободный капитал как ``equity − ГО×буфер − резерв``;
- начисляет доход по паям фонда (NAV растёт на дневную ставку);
- держит целевую долю в фонде и сообщает план ребалансировки (аналог OsEngine).

Тайминг Т+1 учтён в доходе: паи, купленные в конце дня t, начинают приносить
доход только с t+1; паи, проданные в конце t, дохода с t+1 не дают. Деньги от
продажи приходят на следующий день, поэтому в конфиге есть ``min_balance`` и
``margin_buffer`` — они покрывают однодневный рост ГО. FMMM торговался в Т+1
и в 2025 (борд TQTF), и сейчас (с 22.06.2026, борд TQBR).

Чего НЕ делает: не меняет модель исполнения движка, не отправляет заявки,
не моделирует задержку поступления денег от продажи и налоги. Это отдельный
поток дохода для отчётов и будущего интеграционного решения. Research-only,
в контур не включать без ADR.

Источник ставки по умолчанию: 8.7% годовых — консервативная средняя фонда
денежного рынка за 2010–2026 (``reports/russian-market-ideas-2026.md``). Для
реальной оценки загрузите ``reports/fmmm-rate.csv`` (история iNAV FMMMA с MOEX
ISS, `scripts/93_fmmm_rate.py`) через ``load_rate_csv`` или свою callable.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

RATE_10Y_AVG = 0.087  # 8.7% годовых, фонд денежного рынка 2010–2026
DAYS_PER_YEAR = 365

RateSource = float | Callable[[dt.date], float]


def _as_date(value: dt.date | dt.datetime) -> dt.date:
    """Приводит date/datetime/pandas.Timestamp к календарному дню."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if hasattr(value, "date"):
        return value.date()  # type: ignore[union-attr]
    raise TypeError(f"ожидалась дата, получено {type(value).__name__}")


def free_capital(equity: float, margin: float, reserve: float = 0.0,
                 margin_buffer: float = 1.0) -> float:
    """Свободные деньги: капитал минус зарезервированное ГО и подушка.

    ``margin_buffer > 1`` оставляет запас на рост ГО/просадку, чтобы не
    приходилось срочно продавать паи. Отрицательный результат обрезается в 0.
    """
    free = equity - margin * margin_buffer - reserve
    return max(0.0, free)


def daily_rate(annual_rate: float, days_per_year: int = DAYS_PER_YEAR) -> float:
    """Простая дневная ставка из годовой (без налогообложения)."""
    return annual_rate / days_per_year


@dataclass(frozen=True)
class FundConfig:
    """Параметры фонда и политики парковки свободных средств."""

    name: str = "FMMM"
    annual_rate: RateSource = RATE_10Y_AVG
    min_balance: float = 5000.0   # резерв в кэше, как порог 5000 ₽ у OsEngine
    margin_buffer: float = 1.0    # запас на ГО: 2.0 = считаем, что нужно вдвое больше
    tolerance: float = 100.0      # не ребалансировать мелочь (₽)
    fee_pct: float = 0.0          # комиссия брокера на покупку/продажу паёв
    days_per_year: int = DAYS_PER_YEAR

    def rate_on(self, day: dt.date) -> float:
        rate = self.annual_rate(day) if callable(self.annual_rate) else self.annual_rate
        return float(rate)


@dataclass(frozen=True)
class RebalancePlan:
    """Что сделать с паями на текущий день (для отчёта и будущего раннера)."""

    action: str        # buy / sell / hold
    traded: float      # ₽, знак показывает направление
    free: float        # целевой свободный капитал, ₽
    target_value: float  # целевая стоимость паёв, ₽
    target_units: float


@dataclass
class FundState:
    """Состояние счёта фонда после шага."""

    date: dt.date | None = None
    nav: float = 1.0
    units: float = 0.0
    income_total: float = 0.0
    income_today: float = 0.0
    action: str = "hold"
    traded: float = 0.0
    free: float = 0.0

    @property
    def value(self) -> float:
        return self.units * self.nav


class MoneyMarket:
    """Парковка свободного капитала в фонде с ежедневным начислением дохода."""

    def __init__(self, cfg: FundConfig | None = None, initial_units: float = 0.0):
        self.cfg = cfg or FundConfig()
        self.state = FundState(units=initial_units)

    def plan(self, equity: float, margin: float) -> RebalancePlan:
        """Целевой объём паёв по текущему/free капиталу (без начисления дохода)."""
        total = equity + self.state.income_total
        free = free_capital(total, margin, self.cfg.min_balance,
                            self.cfg.margin_buffer)
        target_units = free / self.state.nav
        traded = (target_units - self.state.units) * self.state.nav
        if abs(traded) < self.cfg.tolerance:
            action = "hold"
            traded = 0.0
        else:
            action = "buy" if traded > 0 else "sell"
        return RebalancePlan(action, traded, free, free, target_units)

    def step(self, date: dt.date | dt.datetime, equity: float,
             margin: float) -> FundState:
        """Один календарный день: сначала доход по паям, потом ребалансировка.

        ``equity`` — капитал торговой части без дохода фонда (P&L + депозит),
        ``margin`` — ГО, занятое открытыми позициями. Доход текущего дня не
        участвует в расчёте целевого объёма, чтобы не было подглядывания.
        """
        day = _as_date(date)
        if self.state.date is not None and day <= self.state.date:
            raise ValueError(f"дата должна расти: {self.state.date} -> {day}")

        rate = daily_rate(self.cfg.rate_on(day), self.cfg.days_per_year)
        old_nav = self.state.nav
        self.state.nav = old_nav * (1.0 + rate)
        gross = self.state.units * (self.state.nav - old_nav)

        plan = self.plan(equity, margin)
        fee = abs(plan.traded) * self.cfg.fee_pct
        if plan.action != "hold":
            self.state.units = plan.target_units
        self.state.income_total += gross - fee
        self.state.income_today = gross - fee
        self.state.action = plan.action
        self.state.traded = plan.traded
        self.state.free = plan.free
        self.state.date = day
        return self.state

    def summary(self) -> dict:
        """Короткая сводка по накопленному доходу фонда."""
        return {
            "fund": self.cfg.name,
            "income": round(self.state.income_total, 2),
            "fund_value": round(self.state.value, 2),
            "units": round(self.state.units, 4),
            "nav": round(self.state.nav, 6),
            "last_action": self.state.action,
        }


def load_rate_csv(path: str | Path) -> Callable[[dt.date], float]:
    """Читает серию ставок из CSV ``date,rate`` (rate в % годовых).

    Для дат раньше первой/последней записи берётся ближайшая ставка — так
    серию можно подавать в ``FundConfig(annual_rate=...)`` без пропусков.
    """
    rows: list[tuple[dt.date, float]] = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append((dt.date.fromisoformat(row["date"]),
                         float(row["rate"]) / 100.0))
    if not rows:
        raise ValueError(f"пустой файл ставок: {path}")
    rows.sort()

    def rate_on(day: dt.date) -> float:
        rate = rows[0][1]
        for d, r in rows:
            if d <= day:
                rate = r
            else:
                break
        return rate

    return rate_on


def apply_to_daily(dates: Sequence, equity: Sequence[float],
                   margin: Sequence[float], cfg: FundConfig | None = None,
                   initial_units: float = 0.0) -> dict:
    """Прогоняет модель по дневным точкам и возвращает ряды и сводку.

    Полезно поверх готового бэктеста: ``equity`` — депозит + P&L движка,
    ``margin`` — ГО по открытым позициям на конец дня. Ничего не пишет в
    ``results/`` и не меняет исходные ряды.
    """
    if not (len(dates) == len(equity) == len(margin)):
        raise ValueError("dates, equity и margin должны быть одинаковой длины")
    mm = MoneyMarket(cfg, initial_units)
    income: list[float] = []
    total: list[float] = []
    fund_value: list[float] = []
    free: list[float] = []
    actions: list[str] = []

    for day, e, m in zip(dates, equity, margin):
        st = mm.step(day, e, m)
        income.append(st.income_today)
        total.append(float(e) + mm.state.income_total)
        fund_value.append(st.value)
        free.append(st.free)
        actions.append(st.action)

    value = sum(fund_value) / len(fund_value) if fund_value else 0.0
    return {
        "dates": list(dates),
        "base_equity": list(equity),
        "margin": list(margin),
        "income": income,
        "equity_with_fund": total,
        "fund_value": fund_value,
        "free": free,
        "actions": actions,
        "summary": {
            **mm.summary(),
            "days": len(income),
            "invested_days": sum(v > 0 for v in fund_value),
            "avg_fund_value": round(value, 2),
            "max_fund_value": round(max(fund_value, default=0.0), 2),
            "income_pct_of_start": round(
                100 * mm.state.income_total / equity[0], 2) if equity and equity[0] else 0.0,
        },
    }
