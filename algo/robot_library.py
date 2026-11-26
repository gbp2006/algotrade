"""Библиотека типов роботов (spec-ов). Неизменяемые описания из кода.

Инстанс со своим набором параметров создаётся из spec через `robot_store`;
здесь же параметры проверяются до записи.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .configs import CONFIGS
from .robot_configs import ROBOT_CONFIGS


@dataclass(frozen=True)
class RobotSpec:
    id: str
    strategy: str
    defaults: dict = field(default_factory=dict)
    schema: dict[str, str] = field(default_factory=dict)
    instruments: tuple[str, ...] = ()
    description: str = ""
    source: str = ""           # base / robot
    examples: tuple[str, ...] = ()


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _build() -> dict[str, RobotSpec]:
    grouped: dict[str, list] = {}
    for cfg in CONFIGS:
        grouped.setdefault(cfg.strategy, []).append((cfg, "base"))
    for cfg in ROBOT_CONFIGS:
        grouped.setdefault(cfg.strategy, []).append((cfg, "robot"))

    specs: dict[str, RobotSpec] = {}
    for strategy, items in grouped.items():
        first, source = items[0]
        defaults = dict(first.params)
        schema = {k: _type_name(v) for k, v in defaults.items()}
        # spec описывает ВСЕ параметры стратегии, а не только первого конфига:
        # иначе p-h1 с timeframe=60 не пройдёт валидацию при переносе в store
        for cfg, _ in items[1:]:
            for key, value in cfg.params.items():
                defaults.setdefault(key, value)
                schema[key] = _type_name(value)
        specs[strategy] = RobotSpec(
            id=strategy,
            strategy=strategy,
            defaults=defaults,
            schema=schema,
            instruments=tuple(sorted({cfg.instrument for cfg, _ in items})),
            description=first.comment or first.display,
            source=source,
            examples=tuple(cfg.id for cfg, _ in items[:5]),
        )
    # Денежный рынок — сервисный робот, не производная от CONFIGS.
    # Раннер появится отдельным ADR; spec нужен, чтобы создать инстанс из панели.
    mm_defaults = {
        "regime": "TwiceADay",          # Off / TwiceADay / OnceADay / OnlyClose
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
        # Лимиты фонда задаёт пользователь в карточке робота (не счёта):
        # паи считаются штуками, а не фьючерсными контрактами (ADR 26.11).
        "max_qty": 100000,
        "max_exposure": 1.0,
        # Паи фонда котируются реже фьючерсов: жёсткие 60 с блокируют ребаланс
        # вечером, когда сделок по фонду нет. Значение задаёт пользователь.
        "max_quote_age_sec": 3600,
        "pricing": "marketable",
    }
    specs["money_market"] = RobotSpec(
        id="money_market", strategy="money_market",
        defaults=mm_defaults,
        schema={k: _type_name(v) for k, v in mm_defaults.items()},
        instruments=("CASH",),
        description="Парковка свободных средств в фонд денежного рынка (FMMM); "
                    "пополнение кэша перед торгами, обратная покупка после",
        source="service",
    )
    return specs


SPECS = _build()


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
