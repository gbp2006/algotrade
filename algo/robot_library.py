"""Библиотека типов роботов: SPEC с дефолтами, схемой и инструментами.

Значения зафиксированы 28.11 в этом файле: раньше они выводились из статических
`CONFIGS`/`ROBOT_CONFIGS`, теперь источник параметров — `RobotStore`, а SPEC —
явный контракт типа робота для мастера и валидации.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RobotSpec:
    id: str
    strategy: str
    defaults: dict = field(default_factory=dict)
    schema: dict[str, str] = field(default_factory=dict)
    instruments: tuple[str, ...] = ()
    description: str = ""
    source: str = ""           # base / robot / service
    examples: tuple[str, ...] = ()


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _spec(spec_id: str, defaults: dict, instruments: tuple[str, ...],
          description: str, source: str, examples: tuple[str, ...]) -> RobotSpec:
    return RobotSpec(
        id=spec_id, strategy=spec_id, defaults=defaults,
        schema={k: _type_name(v) for k, v in defaults.items()},
        instruments=instruments, description=description,
        source=source, examples=examples)


SPECS: dict[str, RobotSpec] = {
    "prostushka": _spec(
        "prostushka",
        {"ma_window": 200, "entry": "13:50", "filter_bars": 3,
         "short_friday": False, "timeframe": 60, "close_friday": True},
        ("CNY", "GOLD", "RTS"),
        "как в ТЗ: MA40 M5, 13:50, фильтр 15 мин", "base",
        ("p-base", "p-fast", "p-h1", "p-friday", "p-rts")),
    "universal": _spec(
        "universal",
        {"ref": "10:05", "entry": "13:30", "long_off": 0.004,
         "short_off": 0.002, "hold": "daily", "short_friday": False,
         "exit": "10:20"},
        ("CNY",),
        "как в ТЗ: пороги 0.4/0.2%, суточное удержание", "base",
        ("u-base", "u-wide", "u-morning", "u-1340")),
    "channel_break": _spec(
        "channel_break",
        {"start": "01:00", "switch": "13:00", "mode": "day",
         "direction": "long", "sl": 0.12, "boundary": "first_bar",
         "tick": 0.001},
        ("CNY", "Si"),
        "пробой дневного канала 09:00→13:00, вход после пробоя HH, выход в 09:00; "
        "CNY train PF 2.07 / OOS 2.17, Si 1.44 / 2.06, BR 1.32 OOS, GOLD 1.13, "
        "RTS 1.04; контроль «просто лонг» убыточен — край есть",
        "robot", ("cb-day", "cb-day-si")),
    "donchian": _spec(
        "donchian",
        {"entry": 20, "exit": 10, "entry_time": "13:55", "allow_short": True},
        ("CNY", "Si"),
        "диверсификатор: Donchian HH20/LL20 → выход LL10/HH10; корр 0.16 с базой, "
        "+6.65% в её худшие годы (36% плюса); OOS 2026 CNY PF 1.91 против 1.53 у базы; "
        "200% номинала, DD ~17% счёта",
        "robot", ("d20-cn", "d20-si")),
    "money_market": _spec(
        "money_market",
        {"regime": "TwiceADay",          # Off / TwiceADay / OnceADay / OnlyClose
         "symbol": "FMMM@MISX",
         "min_balance": 5000.0,          # как у OsEngine TmonRebalancer
         "allowed_spread_pct": 0.01,     # фильтр спреда, %
         "time_buy": "23:00",
         "time_sell": "10:05",
         "trade_mon": True, "trade_tue": True, "trade_wed": True,
         "trade_thu": True, "trade_fri": True,
         "trade_sat": False, "trade_sun": False,
         "reserve_pct": 0.2,
         "reserve_abs": 20000.0,
         "min_trade": 5000.0,
         "max_units": 100000,
         # Лимиты фонда задаёт пользователь в карточке робота, не счёта (ADR 26.11).
         "max_qty": 100000,
         "max_exposure": 1.0,
         # Паи котируются реже фьючерсов (ADR 26.11).
         "max_quote_age_sec": 3600,
         "pricing": "marketable"},
        ("CASH",),
        "Парковка свободных средств в фонд денежного рынка (FMMM); "
        "пополнение кэша перед торгами, обратная покупка после",
        "service", ()),
}


def list_specs() -> list[RobotSpec]:
    return list(SPECS.values())


def get_spec(spec_id: str) -> RobotSpec:
    spec = SPECS.get(spec_id)
    if spec is None:
        raise ValueError(f"нет типа робота {spec_id!r}; доступны: {', '.join(SPECS)}")
    return spec


def validate_params(spec_id: str, overrides: dict[str, Any] | None) -> dict:
    """Объединить дефолты spec с переопределениями и проверить типы."""
    spec = get_spec(spec_id)
    out = dict(spec.defaults)
    for key, value in (overrides or {}).items():
        if key not in spec.schema:
            raise ValueError(f"{spec_id}: неизвестный параметр {key!r}")
        expected = spec.schema[key]
        ok = {
            "bool": lambda v: isinstance(v, bool),
            "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "str": lambda v: isinstance(v, str),
        }[expected](value)
        if not ok:
            raise ValueError(f"{spec_id}.{key}: ожидался {expected}, получено {value!r}")
        out[key] = value
    return out
