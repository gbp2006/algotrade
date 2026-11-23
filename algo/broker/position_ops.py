"""Ручные операции по роботу: закрытие позиций и ребалансировка денежного рынка.

Обе операции идут через ``OrderGateway``: STOP_REAL перед заявкой, лимиты из
капитала счёта, уникальный ``client_id``,journal в SQLite и зеркало в CSV.
По умолчанию ``dry_run=True`` — пишется только ``planned``; реальная отправка
требует отдельного «замка» в окружении панели (``ALGO_CLOSE_ARMED`` /
``ALGO_MM_ARMED``), analogues ``--arm`` у раннера.

Логика денежного рынка повторяет OsEngine ``TmonRebalancer``: режимы
Off / TwiceADay / OnceADay / OnlyClose, минимальный баланс, фильтр спреда,
покупка на свободные средства по ask и закрытие позиции целиком.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .. import trade_journal as tj
from ..instruments import DEFAULT, INSTRUMENTS
from .execution import Order, OrderGateway, positions_from_response
from .finam import FinamBroker
from .live_guard import (STOP_REAL, battle_limits, decision_client_id,
                         parse_pricing, price_for, quote_age_sec)
from .secrets import resolve_secret

ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = ROOT / "results" / "live.csv"
MAX_QUOTE_AGE = 60


class OpError(RuntimeError):
    """Операция не выполнена: не хватает данных или сработал предохранитель."""


def _context(store: Any, iid: str) -> dict[str, Any]:
    inst = store.get_instance(iid)
    if inst is None:
        raise OpError(f"нет инстанса {iid}")
    if inst.get("mode") != "live":
        raise OpError("инстанс не в режиме «бой»")
    acc_id = inst.get("account")
    if not acc_id:
        raise OpError("у инстанса нет счёта")
    row = next((a for a in store.list_accounts() if a["id"] == acc_id), None)
    if row is None:
        raise OpError(f"счёт {acc_id} не описан в store")
    broker = FinamBroker(
        secret=resolve_secret(row.get("key_ref") or "{env:FINAM_SECRET}"),
        account=acc_id)
    runtime = store.get_runtime(iid) or {}
    spec = INSTRUMENTS.get(inst.get("instrument"), DEFAULT)
    symbol = runtime.get("symbol") or spec.symbol or ""
    try:
        params = json.loads(inst.get("params_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        params = {}
    return {"inst": inst, "acc": row, "acc_id": acc_id, "broker": broker,
            "runtime": runtime, "symbol": symbol, "params": params,
            "capital": float(row.get("capital") or 50000)}


def _gateway(ctx: dict[str, Any]) -> OrderGateway:
    acc = ctx["acc"]
    return OrderGateway(
        ctx["broker"],
        limits=battle_limits(ctx["capital"],
                             max_exposure=float(acc.get("max_exposure") or 1.0),
                             max_qty=int(acc.get("max_qty") or 100)).as_limits(),
        journal=LIVE, lock=ROOT / "results" / "live.lock",
    )


def _quote(broker: Any, symbol: str, tick: float):
    quote = broker.quote(symbol)
    age = quote_age_sec(quote)
    if age is None or age > MAX_QUOTE_AGE:
        raise OpError("котировка устарела")
    return quote


def available_cash(broker: Any, account: str) -> float:
    """Свободные деньги счёта: portfolio_mc / portfolio_forts / cash (RUB)."""
    resp = broker.account(account)
    for key in ("portfolio_mc", "portfolio_forts"):
        section = resp.get(key) or {}
        value = section.get("available_cash")
        if value:
            return float(value.get("value", value)) if isinstance(value, dict) else float(value)
    total = 0.0
    for item in resp.get("cash") or []:
        if str(item.get("currency_code", "RUB")).upper() not in ("RUB", "643"):
            continue
        total += float(item.get("units", 0)) + float(item.get("nanos", 0)) / 1e9
    return total


def _send_close(ctx: dict[str, Any], symbol: str, qty: int,
                *, dry_run: bool, note: str) -> dict[str, Any]:
    if STOP_REAL.exists():
        raise OpError("STOP_REAL установлен")
    broker, acc_id = ctx["broker"], ctx["acc_id"]
    inst = INSTRUMENTS.get(ctx["inst"].get("instrument"), DEFAULT)
    tick = inst.tick if symbol == (inst.symbol or symbol) else 0.001
    quote = _quote(broker, symbol, tick)
    side = "sell" if qty > 0 else "buy"
    price, order_type, price_note = price_for(
        parse_pricing("marketable"), quote.last, side, quote, tick)
    now = dt.datetime.now().strftime("%H%M%S")
    order = Order(
        client_id=decision_client_id("close:" + ctx["inst"]["id"],
                                     dt.date.today().isoformat(), side, now, abs(qty)),
        config="close:" + ctx["inst"]["id"], symbol=symbol, side=side,
        qty=abs(qty), price=price, multiplier=inst.mult, min_step=tick,
        order_type=order_type, account=acc_id, pricing="marketable",
    )
    result = _gateway(ctx).submit(order, account=acc_id, stop=STOP_REAL,
                                 dry_run=dry_run)
    if result.sent:
        ctx["store"].set_runtime(ctx["inst"]["id"],
                                 {"symbol": symbol, "position": 0,
                                  "note": f"закрытие {note}",
                                  "updated_at": dt.datetime.now().isoformat(timespec="seconds")})
    return {"ok": result.status in ("sent", "planned"), "status": result.status,
            "reason": result.reason, "symbol": symbol, "qty": abs(qty),
            "side": side, "price": price, "price_note": price_note,
            "client_id": order.client_id, "dry_run": dry_run}


def close_instance(store: Any, iid: str, *, dry_run: bool = True,
                   symbol: str | None = None) -> dict[str, Any]:
    """Закрыть позицию инструмента, открытую этим инстансом."""
    ctx = _context(store, iid)
    ctx["store"] = store
    target = symbol or ctx["symbol"] or str(ctx["params"].get("symbol") or "")
    if not target:
        raise OpError("неизвестен символ позиции инстанса")
    actual = positions_from_response(
        ctx["broker"].account(ctx["acc_id"]).get("positions", []))
    qty = int(actual.get(target, 0))
    if qty == 0:
        return {"ok": True, "closed": 0, "reason": "открытой позиции нет",
                "symbol": target}
    return _send_close(ctx, target, qty, dry_run=dry_run, note="все позиции")


def mm_rebalance(store: Any, iid: str, *, dry_run: bool = True,
                 regime: str | None = None) -> dict[str, Any]:
    """Ребалансировка фонда денежного рынка (по мотивам TmonRebalancer)."""
    ctx = _context(store, iid)
    ctx["store"] = store
    p = ctx["params"]
    mode = str(regime or p.get("regime") or "TwiceADay")
    if mode == "Off":
        return {"ok": True, "skipped": True, "reason": "режим Off"}
    symbol = str(p.get("symbol") or "FMMM@MISX")
    min_balance = max(float(p.get("min_balance") or 5000), 500)
    balance = available_cash(ctx["broker"], ctx["acc_id"])
    fund = positions_from_response(
        ctx["broker"].account(ctx["acc_id"]).get("positions", [])).get(symbol, 0)

    if mode == "OnlyClose" or balance <= min_balance:
        if fund == 0:
            return {"ok": True, "closed": 0, "reason": "нечего закрывать",
                    "symbol": symbol}
        return _send_close(ctx, symbol, int(fund), dry_run=dry_run, note="фонд")

    quote = _quote(ctx["broker"], symbol, 0.0001)
    mid = (quote.ask + quote.bid) / 2
    if mid <= 0:
        raise OpError("нет котировки фонда")
    spread_pct = (quote.ask - quote.bid) / mid * 100
    allowed = float(p.get("allowed_spread_pct") or 0.01)
    if allowed and spread_pct > allowed:
        return {"ok": False, "reason": f"спред {spread_pct:.4f}% > {allowed}%",
                "symbol": symbol}

    free = balance - min_balance
    volume = int(free // quote.ask)  # лот фонда = 1
    if volume <= 0:
        return {"ok": True, "skipped": True, "reason": "не хватает до цены пая",
                "symbol": symbol}
    if STOP_REAL.exists():
        raise OpError("STOP_REAL установлен")
    now = dt.datetime.now().strftime("%H%M%S")
    order = Order(
        client_id=decision_client_id("mm:" + ctx["inst"]["id"],
                                     dt.date.today().isoformat(), "buy", now, volume),
        config="money_market:" + ctx["inst"]["id"], symbol=symbol, side="buy",
        qty=volume, price=quote.ask, multiplier=1.0, min_step=0.0001,
        order_type="limit", account=ctx["acc_id"], pricing="marketable",
    )
    result = _gateway(ctx).submit(order, account=ctx["acc_id"], stop=STOP_REAL,
                                 dry_run=dry_run)
    return {"ok": result.status in ("sent", "planned"), "status": result.status,
            "reason": result.reason, "symbol": symbol, "qty": volume,
            "side": "buy", "price": quote.ask, "free_cash": free,
            "spread_pct": spread_pct, "dry_run": dry_run}
