"""Адаптер Finam к нейтральному интерфейсу `BrokerAdapter`.

Оборачивает существующий `FinamBroker` и сохраняет его legacy-методы
(`place_limit`, `place_market`, `find_order`, `account`, `quote`), чтобы шлюз
`OrderGateway` продолжал работать без изменений.
"""

from __future__ import annotations

from .base import BrokerAdapter, ConnectionStatus, OrderRequest, OrderResult
from .execution import order_id_from, order_state
from .finam import FinamBroker


class FinamAdapter(BrokerAdapter):
    name = "finam"

    def __init__(self, secret: str | None = None, account: str | None = None):
        self.broker = FinamBroker(secret=secret, account=account)

    # --- данные ---
    def quote(self, symbol: str):
        return self.broker.quote(symbol)

    def account(self, account: str | None = None) -> dict:
        return self.broker.account(account)

    # --- заявки ---
    def place_order(self, request: OrderRequest) -> OrderResult:
        if request.order_type == "market":
            raw = self.place_market(
                request.symbol, request.side, request.qty,
                request.account, request.client_order_id)
        else:
            raw = self.place_limit(
                request.symbol, request.side, request.qty, request.price,
                request.account, request.client_order_id)
        state = order_state(raw)
        return OrderResult(
            order_id=order_id_from(raw) or str(raw.get("order_id", "")),
            status=state["status"], executed=state["executed"],
            remaining=state["remaining"], raw=raw,
        )

    def place_limit(self, symbol, side, qty, price, account=None, client_order_id=None):
        return self.broker.place_limit(symbol, side, qty, price, account, client_order_id)

    def place_market(self, symbol, side, qty, account=None, client_order_id=None):
        return self.broker.place_market(symbol, side, qty, account, client_order_id)

    def cancel_order(self, order_id: str, account: str | None = None):
        return self.broker.cancel_order(order_id, account)

    def find_order(self, client_order_id: str, account: str | None = None):
        return self.broker.find_order(client_order_id, account)

    def order_state(self, item: dict) -> dict:
        return order_state(item)

    def check_connection(self) -> ConnectionStatus:
        try:
            self.broker.account()
            return ConnectionStatus(True, "account: OK")
        except Exception as exc:  # noqa: BLE001 — статус, а не исключение
            return ConnectionStatus(False, f"{type(exc).__name__}: {exc}"[:200])
