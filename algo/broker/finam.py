"""Клиент Finam Trade API (REST).

Авторизация: POST /v1/sessions {secret} -> token, дальше Authorization: <token>.
Секрет и счёт берутся из окружения (FINAM_SECRET, FINAM_ACCOUNT) или передаются явно.
Торговые методы заблокированы, пока не выставлен FINAM_ALLOW_TRADING=1.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

BASE = "https://api.finam.ru"
MSK = 3 * 3600  # МСК = UTC+3


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    timestamp: str


class FinamError(RuntimeError):
    pass


class FinamBroker:
    def __init__(self, secret: str | None = None, account: str | None = None,
                 base: str = BASE, timeout: int = 20):
        self.secret = secret or os.environ.get("FINAM_SECRET", "")
        self.account_id = account or os.environ.get("FINAM_ACCOUNT", "")
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._token: str | None = None
        self._token_ts = 0.0
        if not self.secret:
            raise FinamError("не задан FINAM_SECRET")

    # ---------- транспорт ----------
    def _auth(self, force: bool = False) -> str:
        if not force and self._token and time.time() - self._token_ts < 600:
            return self._token
        r = requests.post(f"{self.base}/v1/sessions", json={"secret": self.secret},
                          timeout=self.timeout)
        if r.status_code != 200:
            raise FinamError(f"авторизация: {r.status_code} {r.text[:200]}")
        self._token = r.json()["token"]
        self._token_ts = time.time()
        return self._token

    def _call(self, method: str, path: str, params: dict | None = None,
              body: dict | None = None, retries: int = 3) -> Any:
        last = None
        for attempt in range(retries):
            token = self._auth(force=attempt > 0 and last is not None and last.status_code == 401)
            r = requests.request(method, f"{self.base}{path}", params=params, json=body,
                                 headers={"Authorization": token, "Accept": "application/json"},
                                 timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401:
                last = r
                continue
            if r.status_code == 429:
                time.sleep(1 + attempt)
                last = r
                continue
            raise FinamError(f"{method} {path}: {r.status_code} {r.text[:200]}")
        raise FinamError(f"{method} {path}: не удалось ({last.status_code if last else '?'})")

    # ---------- данные ----------
    def quote(self, symbol: str) -> Quote:
        j = self._call("GET", f"/v1/instruments/{symbol}/quotes/latest")
        q = j["quote"]

        def f(x: dict) -> float:
            return float(x["value"]) if isinstance(x, dict) else float(x)

        return Quote(symbol=symbol, bid=f(q["bid"]), ask=f(q["ask"]), last=f(q["last"]),
                     timestamp=q.get("timestamp", ""))

    def bars(self, symbol: str, timeframe: str = "TIME_FRAME_M5",
             start: str | None = None, end: str | None = None) -> pd.DataFrame:
        """Свечи в DataFrame с индексом в МСК. start/end — ISO UTC."""
        params = {"timeframe": timeframe}
        if start:
            params["interval.start_time"] = start
        if end:
            params["interval.end_time"] = end
        j = self._call("GET", f"/v1/instruments/{symbol}/bars", params=params)
        rows = []
        for b in j.get("bars", []):
            ts = pd.Timestamp(b["timestamp"])
            rows.append({
                "dt": ts.tz_localize(None) + pd.Timedelta(seconds=MSK),
                "open": float(b["open"]["value"]),
                "high": float(b["high"]["value"]),
                "low": float(b["low"]["value"]),
                "close": float(b["close"]["value"]),
                "vol": float(b.get("volume", {}).get("value", 0)),
            })
        df = pd.DataFrame(rows).set_index("dt") if rows else pd.DataFrame()
        return df

    # ---------- счёт ----------
    def account(self, account: str | None = None) -> dict:
        acc = account or self.account_id
        if not acc:
            raise FinamError("не задан FINAM_ACCOUNT")
        return self._call("GET", f"/v1/accounts/{acc}")

    def orders(self, account: str | None = None) -> list[dict]:
        acc = account or self.account_id
        return self._call("GET", f"/v1/accounts/{acc}/orders").get("orders", [])

    # ---------- торговля ----------
    def place_market(self, symbol: str, side: str, qty: int,
                     account: str | None = None,
                     client_order_id: str | None = None) -> dict:
        if os.environ.get("FINAM_ALLOW_TRADING") != "1":
            raise FinamError("торговля выключена: не выставлен FINAM_ALLOW_TRADING=1")
        if client_order_id and len(client_order_id) > 20:
            raise FinamError("client_order_id длиннее 20 символов")
        acc = account or self.account_id
        body = {
            "symbol": symbol,
            "quantity": {"value": str(qty)},
            "side": "SIDE_BUY" if side.lower() in ("buy", "long", "1") else "SIDE_SELL",
            "type": "ORDER_TYPE_MARKET",
            "time_in_force": "TIME_IN_FORCE_DAY",
        }
        # client_order_id — общее поле PlaceOrder, применимо и к рыночным заявкам
        # (проверено по OpenAPI /v1/accounts/{account_id}/orders 23.11.2026),
        # поэтому идемпотентность работает для всех трёх режимов цены.
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._call("POST", f"/v1/accounts/{acc}/orders", body=body)

    def place_limit(self, symbol: str, side: str, qty: int, price: float,
                    account: str | None = None,
                    client_order_id: str | None = None) -> dict:
        """Лимитная заявка по схеме Finam Trade API (поле `limit_price`).

        `client_order_id` — уникальная строка не длиннее 20 символов. Цена
        обязана быть кратна шагу инструмента — это проверяет шлюз, когда
        ему передан `min_step`.
        """
        if os.environ.get("FINAM_ALLOW_TRADING") != "1":
            raise FinamError("торговля выключена: не выставлен FINAM_ALLOW_TRADING=1")
        if client_order_id and len(client_order_id) > 20:
            raise FinamError("client_order_id длиннее 20 символов")
        acc = account or self.account_id
        body = {
            "symbol": symbol,
            "quantity": {"value": str(qty)},
            "side": "SIDE_BUY" if side.lower() in ("buy", "long", "1") else "SIDE_SELL",
            "type": "ORDER_TYPE_LIMIT",
            "time_in_force": "TIME_IN_FORCE_DAY",
            "limit_price": {"value": f"{price:.6f}".rstrip("0").rstrip(".")},
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._call("POST", f"/v1/accounts/{acc}/orders", body=body)

    def order(self, order_id: str, account: str | None = None) -> dict:
        return self._call("GET", f"/v1/accounts/{account or self.account_id}/orders/{order_id}")

    def cancel_order(self, order_id: str, account: str | None = None) -> dict:
        if os.environ.get("FINAM_ALLOW_TRADING") != "1":
            raise FinamError("торговля выключена: не выставлен FINAM_ALLOW_TRADING=1")
        return self._call("DELETE", f"/v1/accounts/{account or self.account_id}/orders/{order_id}")

    def find_order(self, client_order_id: str, account: str | None = None) -> dict | None:
        """Найти заявку на сервере по client_order_id (сверка после потери ответа)."""
        for item in self.orders(account):
            order = item.get("order", item)
            if order.get("client_order_id") == client_order_id:
                return item
        return None
