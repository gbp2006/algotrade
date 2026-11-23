"""Нейтральный интерфейс брокера. Роботы и шлюз не зависят от Finam.

Конкретный брокер реализует `BrokerAdapter`; заявки описываются через
`OrderRequest`/`OrderResult`. Секреты не попадают в эти типы.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str                      # buy / sell
    qty: int
    account: str = ""
    order_type: str = "limit"      # limit / market
    price: float = 0.0
    min_step: float = 0.0
    client_order_id: str = ""
    note: str = ""


@dataclass(frozen=True)
class OrderResult:
    order_id: str = ""
    status: str = ""
    executed: int = 0
    remaining: int = 0
    raw: Any = None


@dataclass(frozen=True)
class ConnectionStatus:
    ok: bool
    detail: str = ""


class BrokerAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def quote(self, symbol: str) -> Any:
        """Последняя котировка (bid/ask/last/timestamp)."""

    @abstractmethod
    def account(self, account: str | None = None) -> dict:
        """Счёт: деньги, позиции, маржа в формате брокера."""

    def positions(self, account: str | None = None) -> dict[str, int]:
        """Нормализованные позиции {symbol: qty}."""
        from .execution import positions_from_response
        data = self.account(account)
        return positions_from_response(data.get("positions", data))

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        """Отправить заявку. Проверка флага торговли — в адаптере."""

    @abstractmethod
    def cancel_order(self, order_id: str, account: str | None = None) -> Any:
        """Отменить заявку."""

    @abstractmethod
    def find_order(self, client_order_id: str,
                   account: str | None = None) -> Any:
        """Найти заявку по client_order_id после потери ответа."""

    @abstractmethod
    def check_connection(self) -> ConnectionStatus:
        """Проверка доступности и прав (без отправки заявок)."""
