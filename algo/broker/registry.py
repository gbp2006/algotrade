"""Реестр адаптеров брокеров. Добавление брокера не меняет роботов.

Регистрация по имени; конкретные секреты берутся из окружения адаптером.
"""

from __future__ import annotations

from typing import Callable

from .base import BrokerAdapter
from .finam_adapter import FinamAdapter

_FACTORIES: dict[str, Callable[..., BrokerAdapter]] = {}


def register(name: str, factory: Callable[..., BrokerAdapter]) -> None:
    _FACTORIES[name] = factory


def available() -> list[str]:
    return sorted(_FACTORIES)


def get_adapter(name: str, **kwargs) -> BrokerAdapter:
    factory = _FACTORIES.get(name.lower())
    if factory is None:
        raise ValueError(f"неизвестный брокер {name!r}; доступны: {', '.join(available())}")
    return factory(**kwargs)


register("finam", FinamAdapter)
