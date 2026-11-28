"""Безопасный слой исполнения заявок (G3), подключённый к живым роботам.

Заявка уходит только от активного робота на включённом счёте LIVE по включённому
заданию `inst:*` (ADR 27.11). Каждая заявка проходит STOP, лок, проверки лимитов
и цены, пишется в `results/live.csv` и не отправляется повторно при сбое.
`dry_run=True` — явная репетиция без отправки, а не дополнительный замок.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import trade_journal as tj

ROOT = Path(__file__).resolve().parent.parent.parent
JOURNAL = ROOT / "results" / "live.csv"

FIELDS = ["ts", "client_id", "client_order_id", "order_id", "config", "symbol",
          "side", "qty", "price", "multiplier", "status", "reason", "response",
          "account", "pricing", "order_type"]

class ExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Order:
    client_id: str          # детерминированный ключ: config + дата + символ + сторона
    config: str
    symbol: str
    side: str               # buy / sell
    qty: int
    price: float
    multiplier: float = 1.0
    min_step: float = 0.0   # шаг цены инструмента; 0 = проверка кратности выключена
    order_type: str = "limit"  # limit / market
    account: str = ""       # реальный счёт из настроек активного робота в store
    pricing: str = ""       # signal / marketable / market
    # Подписанная позиция по символу после исполнения заявки. Лимит номинала
    # проверяется по ней, а не по qty: разворот −2 → +2 требует 4 контракта,
    # но итог +2 укладывается в потолок счёта. None — старая проверка по qty.
    result_qty: int | None = None


@dataclass(frozen=True)
class Limits:
    max_qty: int = 100
    max_notional: float = 5_000_000.0
    allowed_symbols: frozenset[str] | None = None


@dataclass(frozen=True)
class Result:
    status: str             # blocked / rejected / duplicate / planned / sent / error / uncertain
    reason: str = ""
    response: Any = None
    client_order_id: str = ""
    order_id: str = ""

    @property
    def sent(self) -> bool:
        return self.status == "sent"


class OrderGateway:
    """Шлюз с предохранителями. Транспорт внедряется — тесты не ходят в сеть."""

    def __init__(self, broker: Any, limits: Limits | None = None,
                 journal: Path | None = None, lock: Path | None = None,
                 journal_db: Path | None = None):
        # `lock` принимается для совместимости старых вызовов и игнорируется:
        # локи убраны (ADR 27.11); повторную отправку ловит статус заявки
        # в журнале, а UNIQUE client_order_id хранит одну строку на решение.
        self.broker = broker
        self.limits = limits or Limits()
        self.journal = journal or JOURNAL
        # БД — источник правды; CSV — зеркало. В тестах БД рядом с временным журналом.
        self.journal_db = Path(journal_db) if journal_db else (
            tj.TRADES_DB if self.journal == JOURNAL else self.journal.with_suffix(".db"))
        if self.journal == JOURNAL and not tj.records(limit=1):
            tj.migrate_csv(self.journal)

    def _rows(self) -> list[dict]:
        if not self.journal.exists():
            return []
        with self.journal.open(encoding="utf-8") as f:
            return [r for r in csv.DictReader(f) if "client_id" in r]

    def _write(self, order: Order, result: Result) -> Result:
        row = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "client_id": order.client_id,
            "client_order_id": result.client_order_id, "order_id": result.order_id,
            "config": order.config,
            "symbol": order.symbol, "side": order.side, "qty": order.qty,
            "price": f"{order.price:.6f}", "multiplier": order.multiplier,
            "status": result.status, "reason": result.reason[:200],
            "response": str(result.response)[:300],
            "account": order.account, "pricing": order.pricing,
            "order_type": order.order_type,
        }
        # Полный ответ брокера — в отдельную таблицу: поле response в orders/CSV
        # оставлено коротким для человека, но диагностика терять его не должна.
        tj.store_response(result.client_order_id, result.response, self.journal_db)
        tj.append(row, self.journal_db)  # источник правды, идемпотентно
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        new = not self.journal.exists()
        with self.journal.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
        return result

    def log_decision(self, order: Order, status: str, reason: str = "") -> Result:
        """Записать решение, по которому заявка НЕ отправлялась (skip/reject)."""
        return self._write(order, Result(status, reason,
                                         client_order_id=client_order_id(order.client_id)))

    def _validate(self, order: Order) -> str:
        if order.qty <= 0:
            return "количество должно быть положительным"
        if order.price <= 0:
            return "цена должна быть положительной"
        if order.min_step > 0 and order.order_type == "limit":
            steps = order.price / order.min_step
            if abs(steps - round(steps)) > 1e-6:
                return f"цена {order.price} не кратна шагу {order.min_step}"
        if order.side.lower() not in ("buy", "sell"):
            return f"неизвестная сторона: {order.side}"
        lim = self.limits
        if lim.allowed_symbols is not None and order.symbol not in lim.allowed_symbols:
            return f"символ не разрешён: {order.symbol}"
        if order.qty > lim.max_qty:
            return f"количество {order.qty} выше лимита {lim.max_qty}"
        # ADR 25.11: потолок — на итоговую позицию, а не на оборот заявки.
        check_qty = abs(order.result_qty) if order.result_qty is not None else order.qty
        notional = check_qty * order.price * order.multiplier
        if notional > lim.max_notional:
            return f"номинал {notional:.0f} выше лимита {lim.max_notional:.0f}"
        return ""

    def submit(self, order: Order, account: str | None = None,
               dry_run: bool = False, stop: Path | None = None) -> Result:
        """`dry_run=True` проверяет всё, кроме отправки, и пишет статус `planned`.

        Разрешение на заявку определяется маршрутизацией счёта (только LIVE),
        активным роботом и включённым заданием; отдельного env-флага больше нет
        (ADR 27.11). `dry_run` остаётся явным режимом репетиции, а не воротом.

        `stop` — путь к боевому STOP-флагу; проверяется перед КАЖДОЙ заявкой,
        а не только в начале прогона (флаг может появиться mid-session).
        """
        cid = client_order_id(order.client_id)
        if stop is not None and stop.exists():
            return self._write(order, Result("blocked", f"STOP: {stop.name}",
                                             client_order_id=cid))

        try:
            duplicate = tj.exists_active(cid, self.journal_db)
        except Exception:  # noqa: BLE001 — при недоступной БД не теряем страховку CSV
            duplicate = any(r["client_id"] == order.client_id
                            and r.get("status") in tj.ACTIVE_STATUSES
                            for r in self._rows())
        if duplicate:
            return self._write(order, Result("duplicate", "client_id уже в журнале",
                                             client_order_id=cid))
        reason = self._validate(order)
        if reason:
            return self._write(order, Result("rejected", reason,
                                             client_order_id=cid))
        if dry_run:
            return self._write(order, Result(
                "planned", "dry-run: проверено, заявка не отправлена",
                client_order_id=cid))
        try:
            acc = account or order.account
            if order.order_type == "market":
                # client_order_id — общее поле PlaceOrder, применимо и к market
                response = self.broker.place_market(
                    order.symbol, order.side, order.qty, acc, cid)
            else:
                response = self.broker.place_limit(
                    order.symbol, order.side, order.qty, order.price, acc, cid)
        except Exception as exc:  # noqa: BLE001 — ответ мог потеряться после отправки
            found = None
            finder = getattr(self.broker, "find_order", None)
            if finder is not None:
                try:
                    found = finder(cid, account)
                except Exception:  # noqa: BLE001 — сверка не должна маскировать ошибку
                    found = None
            if found is not None:
                return self._write(order, Result(
                    "uncertain", "ответ потерян, заявка найдена на сервере",
                    found, cid, order_id_from(found)))
            return self._write(order, Result(
                "error", f"{type(exc).__name__}: {exc}"[:200], client_order_id=cid))
        return self._write(order, Result(
            "sent", "", response, cid, order_id_from(response)))


def _scalar(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("value", 0)
    return float(value)


def client_order_id(client_id: str) -> str:
    """Детерминированный ID ≤20 символов (требование Finam)."""
    return hashlib.sha1(client_id.encode("utf-8")).hexdigest()[:20]


def order_id_from(response: Any) -> str:
    if not isinstance(response, dict):
        return ""
    for key in ("order_id", "orderId", "id"):
        if response.get(key):
            return str(response[key])
    order = response.get("order")
    if isinstance(order, dict):
        return str(order.get("order_id", order.get("orderId", "")))
    return ""


def order_state(item: dict) -> dict:
    """Статус и доли исполнения из ответа брокера (не только один enum)."""
    order = item.get("order", item) if isinstance(item, dict) else {}
    return {
        "status": str(item.get("status") or order.get("status", "")),
        "executed": int(_scalar(item.get("executed_quantity",
                                       order.get("executed_quantity", 0)))),
        "remaining": int(_scalar(item.get("remaining_quantity",
                                        order.get("remaining_quantity", 0)))),
    }


def positions_from_response(response: Any) -> dict[str, int]:
    """Нормализовать ответ брокера к {symbol: позиция}. Неизвестный формат — ошибка."""
    if isinstance(response, dict):
        for key in ("positions", "items"):
            if key in response:
                response = response[key]
                break
        else:
            if "symbol" in response:
                response = [response]
            else:
                raise ExecutionError("неизвестный формат ответа позиций")
    if not isinstance(response, list):
        raise ExecutionError("неизвестный формат ответа позиций")
    out: dict[str, int] = {}
    for p in response:
        sym = p.get("symbol") or p.get("ticker") or p.get("instrument")
        if not sym:
            raise ExecutionError("в позиции нет символа")
        out[str(sym)] = int(_scalar(p.get("quantity", p.get("qty", 0))))
    return out


def reconcile(expected: dict[str, int], actual: dict[str, int]) -> list[str]:
    """Расхождения модели и брокера; пустой список = всё сходится."""
    return [f"{sym}: модель {expected.get(sym, 0):+d}, брокер {actual.get(sym, 0):+d}"
            for sym in sorted(set(expected) | set(actual))
            if expected.get(sym, 0) != actual.get(sym, 0)]
