"""Опрос счетов: снимки equity и подтверждение денежных потоков.

Правило (ADR 24.11): дельта equity — только триггер, а не денежный поток там
сидят нереализованный P&L и комиссии. Поток записывается только из отчёта
брокера с id транзакции. При недоступном API старый снимок остаётся, а сайзинг
перед сделкой требует свежего подтверждения (решение раннера, не этого модуля).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .cash_flow_store import CashFlowStore
from .cash_flows import (CashFlow, CashFlowType, preview_cash_flow)
from .pg_store import PgStore
from .portfolio import size_contracts

Reporter = Callable[[str, str, object], list[dict]]
BrokerFactory = Callable[[dict], object]


@dataclass(frozen=True)
class PollOutcome:
    account_id: str
    ok: bool
    equity: float | None = None
    delta: float = 0.0
    triggered: bool = False
    flows: tuple[dict, ...] = ()
    error: str = ""


def scalar(value: object) -> float:
    """Брокер иногда отдаёт число как строку или объект {"value": ...}."""
    if isinstance(value, dict):
        value = value.get("value", 0)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def trigger_reason(delta: float, previous_equity: float,
                   delta_abs: float, delta_pct: float) -> bool:
    """Порог срабатывания: абсолютная дельта или процент от прежнего equity."""
    if previous_equity <= 0:
        return abs(delta) >= delta_abs
    return (abs(delta) >= delta_abs
            or abs(delta) / previous_equity * 100.0 >= delta_pct)


def poll_account(account_id: str, broker: object, flows: CashFlowStore,
                 reporter: Reporter | None = None,
                 delta_abs: float = 1_000.0, delta_pct: float = 1.0,
                 timestamp: str = "", force_report: bool = False) -> PollOutcome:
    """Опросить один счёт, записать снимок и, только по отчёту, потоки."""
    pg = PgStore()
    try:
        data = broker.account(account_id)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — сеть не должна ронять панель
        return PollOutcome(account_id, False, error=f"{type(exc).__name__}: {exc}")

    equity = scalar((data or {}).get("equity"))
    balance = scalar((data or {}).get("balance")
                     or (data or {}).get("cash") or equity)
    previous = flows.latest_snapshot(account_id)
    prev_equity = scalar(previous.get("equity")) if previous else equity
    delta = equity - prev_equity
    triggered = previous is not None and trigger_reason(
        delta, prev_equity, delta_abs, delta_pct)

    recorded: list[dict] = []
    flow_sum = 0.0
    running_before = scalar(previous.get("balance")) if previous else balance
    if (triggered or force_report) and reporter is not None:
        since = str(previous.get("timestamp") or "") if previous else ""
        try:
            rows: Sequence[dict] = reporter(account_id, since, broker) or []
        except Exception as exc:  # noqa: BLE001 — отчёт не обязан быть доступен
            rows = []
        for row in rows:
            try:
                kind = CashFlowType(str(row.get("type", "DEPOSIT")).upper())
                amount = abs(scalar(row.get("amount")))
                if amount <= 0:
                    continue
                flow = CashFlow.detect(
                    kind, amount, running_before,
                    created_at=str(row.get("timestamp") or timestamp),
                    broker_tx_id=str(row.get("tx_id") or ""))
                preview = preview_cash_flow(flow)
                result = flows.record_flow(flow, preview, account_id, source="BROKER")
                recorded.append({**result, "type": flow.type.value,
                                 "amount": flow.amount, "delta": flow.delta})
                running_before = flow.balance_after
                flow_sum += flow.delta
                try:
                    pg.save_flow(account_id, flow.type.value, flow.amount,
                                 flow.balance_before, flow.balance_after,
                                 flow.created_at or timestamp,
                                 flow.broker_tx_id, flow.client_key, "BROKER")
                except Exception:  # noqa: BLE001 — PG не должна ломать SQLite-контур
                    pass
            except (ValueError, TypeError):
                continue

    history = flows.list_snapshots(account_id, limit=1000)
    peak = max([scalar(s.get("equity")) for s in history] + [equity]) or equity
    drawdown_pct = 100.0 * (equity - peak) / peak if peak > 0 else 0.0
    flows.add_snapshot(account_id, equity, balance, timestamp=timestamp or None,
                       cash_flow=flow_sum, drawdown_pct=drawdown_pct)
    try:
        latest = flows.latest_snapshot(account_id)
        if latest:
            pg.save_snapshot(account_id, str(latest["timestamp"]), equity, balance,
                             flow_sum, drawdown_pct)
    except Exception:  # noqa: BLE001 — SQLite остаётся рабочим источником
        pass
    return PollOutcome(account_id, True, equity=equity, delta=delta,
                       triggered=triggered, flows=tuple(recorded))


_CASH_CATEGORIES = {"DEPOSIT", "WITHDRAW", "INCOME"}
_CATEGORY_NUMBERS = {1: "DEPOSIT", 2: "WITHDRAW", 3: "INCOME"}


def _money(value: object) -> float:
    """Money из Finam REST: {"units": "100", "nanos": 500000000}."""
    if isinstance(value, dict):
        return scalar(value.get("units")) + scalar(value.get("nanos")) / 1e9
    return scalar(value)


def _stamp(value: object) -> str:
    if isinstance(value, dict) and value.get("seconds") is not None:
        from datetime import datetime, timezone
        seconds = int(scalar(value["seconds"]))
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    return str(value or "")


def finam_report(limit: int = 50) -> Reporter:
    """Подтверждение потока из `/v1/accounts/{id}/transactions` Финам.

    Берём только денежные категории (DEPOSIT/WITHDRAW/INCOME); сделки,
    комиссии, налоги и переводы бумаг в поток не попадают. Идемпотентность —
    по `id` транзакции брокера, повторный опрос не создаёт дубли.
    """
    def reporter(account_id: str, since: str, broker: object) -> list[dict]:
        params: dict[str, object] = {"limit": limit}
        if since:
            params["interval.start_time"] = since
        data = broker._call(  # type: ignore[attr-defined]
            "GET", f"/v1/accounts/{account_id}/transactions", params=params)
        out: list[dict] = []
        for row in (data or {}).get("transactions", []) or []:
            category = row.get("transaction_category")
            if isinstance(category, int):
                category = _CATEGORY_NUMBERS.get(category, str(category))
            category = str(category or row.get("category") or "").upper()
            if category not in _CASH_CATEGORIES:
                continue
            change = _money(row.get("change"))
            if not change:
                continue
            out.append({
                "tx_id": str(row.get("id") or ""),
                "type": "DEPOSIT" if change > 0 else "WITHDRAWAL",
                "amount": abs(change),
                "timestamp": _stamp(row.get("timestamp")),
            })
        return out
    return reporter


def fresh_equity(account_id: str, broker: object) -> float | None:
    """Принудительный опрос перед сделкой: только свежий equity, без кэша.

    ``None`` при недоступном API или неположительном equity — вызывающий
    обязан отказаться от входа по существующим правилам STOP. Нарушать
    модель исполнения и маршрутизацию счетов здесь нельзя.
    """
    try:
        data = broker.account(account_id)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — консервативный отказ
        return None
    equity = scalar((data or {}).get("equity"))
    return equity if equity > 0 else None


def size_for_trade(account_id: str, broker: object, price: float,
                   mult: float, exposure: float | None = None) -> int:
    """Лот следующей сделки по свежему equity; при ошибке — 0 контрактов."""
    equity = fresh_equity(account_id, broker)
    if equity is None:
        return 0
    return size_contracts(equity, price, mult, exposure)


def _default_factory(account: dict) -> object:
    from .broker.finam import FinamBroker
    from .broker.secrets import resolve_secret

    return FinamBroker(secret=resolve_secret(account.get("key_ref") or ""),
                       account=account["id"])


def sync_accounts(accounts: Iterable[dict], flows: CashFlowStore,
                  broker_factory: BrokerFactory | None = None,
                  reporter: Reporter | None = None,
                  **kwargs) -> list[PollOutcome]:
    """Опросить все счета с ключами; без ключа счёт пропускается."""
    factory = broker_factory or _default_factory
    results: list[PollOutcome] = []
    for account in accounts:
        if not account.get("key_ref") or not account.get("enabled", True):
            continue
        try:
            broker = factory(account)
        except Exception as exc:  # noqa: BLE001
            results.append(PollOutcome(str(account.get("id", "")), False,
                                       error=f"{type(exc).__name__}: {exc}"))
            continue
        results.append(poll_account(str(account["id"]), broker, flows,
                                    reporter, **kwargs))
    return results
