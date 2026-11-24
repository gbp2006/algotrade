"""Адаптер Т‑Инвестиций к нейтральному `BrokerAdapter`.

Контур намеренно **неактивен** без токена: `check_connection()` честно
возвращает причину, а операции бросают `NotConfiguredError`. Секрет берётся
только по имени из `auth.json`, в панель/БД уходит только имя ссылки.
"""

from __future__ import annotations

from .base import BrokerAdapter, ConnectionStatus, OrderRequest, OrderResult


class NotConfiguredError(RuntimeError):
    """Операция недоступна: нет токена или gRPC-клиента Т‑Инвестиций."""


class TInvestAdapter(BrokerAdapter):
    name = "tinvest"

    def __init__(self, token_ref: str = "", sandbox: bool = False,
                 account: str = ""):
        self.token_ref = str(token_ref or "")
        self.sandbox = bool(sandbox)
        self.account_id = str(account or "")
        self._token = ""
        if self.token_ref:
            try:
                from .secrets import resolve_secret
                self._token = resolve_secret(self.token_ref)
            except Exception:  # noqa: BLE001 — секрет может отсутствовать
                self._token = ""

    @property
    def mode(self) -> str:
        return "TEST" if self.sandbox else "LIVE"

    def _require(self) -> None:
        if not self._token:
            raise NotConfiguredError(
                "токен Т‑Инвестиций не настроен: укажите key_ref из auth.json")
        raise NotConfiguredError(
            "gRPC-клиент Т‑Инвестиций не подключён: операции заблокированы")

    def quote(self, symbol: str):
        self._require()

    def account(self, account: str | None = None) -> dict:
        self._require()
        return {}

    def place_order(self, request: OrderRequest) -> OrderResult:
        self._require()
        return OrderResult()

    def cancel_order(self, order_id: str, account: str | None = None):
        self._require()

    def find_order(self, client_order_id: str, account: str | None = None):
        self._require()

    def check_connection(self) -> ConnectionStatus:
        if not self._token:
            return ConnectionStatus(False, "токен Т‑Инвестиций не настроен")
        return ConnectionStatus(False, f"{self.mode}: gRPC-клиент не подключён")
