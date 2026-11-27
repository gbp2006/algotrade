"""Ручные операции по роботу: закрытие позиций и ребалансировка денежного рынка.

Обе операции идут через ``OrderGateway``: лимиты из капитала счёта, уникальный
``client_id``, журнал в SQLite и зеркало в CSV. Закрытие и ребаланс фонда
отправляют заявки сразу (ADR 27.11): счёт LIVE + лимиты/идемпотентность.
``dry_run=True`` остался явным режимом репетиции.

STOP_REAL задерживает только заявки на ОТКРЫТИЕ: закрытие позиции уменьшает
риск, поэтому при выставленном STOP разрешено (иначе аварийный тормоз мешает
аварийному же закрытию). Лимиты входа тоже не применяются к закрытию.

``close_all(store, account_id)`` смотрит на позиции брокера одного счёта — того,
на котором нажата кнопка, — а не на список активных роботов: после «Стоп всех»
робот уже не активен, а позиция осталась и её всё равно надо закрыть. Чужие
счета не трогаются, паи фонда денежного рынка не трогаются.

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
from .execution import Limits, Order, OrderGateway, positions_from_response
from .finam import FinamBroker
from .live_guard import (STOP_REAL, account_equity, battle_limits,
                         decision_client_id, parse_pricing, price_for,
                         quote_age_sec)
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
    if str(row.get("mode") or "LIVE").upper() != "LIVE" or not row.get("enabled", 1):
        raise OpError(f"счёт {acc_id} виртуальный или выключен: реальные операции запрещены")
    key_ref = inst.get("key_ref") or row.get("key_ref") or "{env:FINAM_SECRET}"
    broker = FinamBroker(secret=resolve_secret(key_ref), account=acc_id)
    runtime = store.get_runtime(iid) or {}
    spec = INSTRUMENTS.get(inst.get("instrument"), DEFAULT)
    symbol = runtime.get("symbol") or spec.symbol or ""
    try:
        params = json.loads(inst.get("params_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        params = {}
    equity = account_equity(broker, acc_id)
    if not equity or equity <= 0:
        raise OpError("нет equity счёта — операция недоступна")
    return {"inst": inst, "acc": row, "acc_id": acc_id, "broker": broker,
            "runtime": runtime, "symbol": symbol, "params": params,
            "capital": equity}


def _gateway(ctx: dict[str, Any], limits=None) -> OrderGateway:
    return OrderGateway(ctx["broker"], limits=limits or _default_limits(ctx),
                        journal=LIVE)


def _instrument_for(symbol: str):
    """Найти спецификацию по символу Финама. Неизвестный символ — CNY-фолбэк.

    Для фьючерсов с плавающим контрактом (Si/RTS/GOLD) префикс SECID совпадает
    с кодом инструмента; обращение к ISS здесь не нужно.
    """
    for inst in INSTRUMENTS.values():
        if inst.symbol == symbol:
            return inst
        if inst.asset and symbol.split("@")[0].startswith(inst.asset):
            return inst
    return DEFAULT


def _default_limits(ctx: dict[str, Any]) -> Limits:
    acc = ctx["acc"]
    return battle_limits(ctx["capital"],
                         max_exposure=float(acc.get("max_exposure") or 1.0),
                         max_qty=int(acc.get("max_qty") or 100)).as_limits()


def _close_limits(base: Limits, qty: int, price: float, mult: float) -> Limits:
    """Расширить лимиты под закрывающий объём.

    Лимиты счёта калиброваны под вход. Закрытие не создаёт нового риска, поэтому
    `max_qty`/`max_notional` должны пропустить любой реальный объём позиции.
    """
    return Limits(
        max_qty=max(int(base.max_qty), abs(qty)),
        max_notional=max(float(base.max_notional), abs(qty) * price * mult),
        max_daily_loss=float(base.max_daily_loss),
        allowed_symbols=base.allowed_symbols,
    )


def mm_limits(ctx: dict[str, Any]):
    """Паи фонда считаются штуками, а не фьючерсными контрактами счёта.

    Лимиты счёта (`max_qty=100`, `max_exposure=0.5`) калиброваны под CNY
    (~12 000 ₽ за контракт). Пай стоит ~14 ₽, поэтому парковка свободного кэша
    упиралась в эти лимиты. Плеча нет: покупаем только на свободные деньги,
    потолок — `max_units` из параметров робота (ADR 26.11).
    """
    p = ctx["params"]
    # Значения задаются пользователем в карточке робота; по умолчанию берём
    # max_units и полный капитал (паи без плеча).
    max_qty = int(p.get("max_qty") or p.get("max_units") or 100000)
    max_exposure = float(p.get("max_exposure") or 1.0)
    return battle_limits(ctx["capital"], max_exposure=max_exposure,
                         max_qty=max_qty).as_limits()


def _quote(broker: Any, symbol: str, tick: float, max_age: float = MAX_QUOTE_AGE):
    quote = broker.quote(symbol)
    age = quote_age_sec(quote)
    if age is None or age > max_age:
        raise OpError(f"котировка устарела: возраст {age:.0f} с, лимит {max_age:.0f} с")
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
                *, dry_run: bool, note: str, limits=None,
                multiplier: float | None = None) -> dict[str, Any]:
    """Отправить закрывающую заявку. STOP и лимиты входа не мешают."""
    broker, acc_id = ctx["broker"], ctx["acc_id"]
    inst = _instrument_for(symbol)
    tick = inst.tick
    quote = _quote(broker, symbol, tick)
    side = "sell" if qty > 0 else "buy"
    price, order_type, price_note = price_for(
        parse_pricing("marketable"), quote.last, side, quote, tick)
    mult = inst.mult if multiplier is None else multiplier
    now = dt.datetime.now().strftime("%H%M%S")
    owner = str(ctx["inst"]["id"])
    config = f"close:{owner}:{symbol}"
    order = Order(
        client_id=decision_client_id(config,
                                     dt.date.today().isoformat(), side, now, abs(qty)),
        config=config, symbol=symbol, side=side,
        qty=abs(qty), price=price, multiplier=mult, min_step=tick,
        result_qty=0,  # итоговая позиция нулевая — лимит номинала проверяем по ней
        order_type=order_type, account=acc_id, pricing="marketable",
    )
    base = limits or _default_limits(ctx)
    result = _gateway(ctx, _close_limits(base, qty, price, mult)).submit(
        order, account=acc_id, stop=None, dry_run=dry_run)
    if result.sent and ctx.get("store") is not None:
        ctx["store"].set_runtime(owner,
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


def _fund_symbols(store: Any) -> set[str]:
    """Символы паёв фонда — «Закрыть всё» их не трогает."""
    out = {"FMMM@MISX"}
    for inst in store.list_instances(mode="live"):
        if inst.get("spec_id") != "money_market":
            continue
        try:
            params = json.loads(inst.get("params_json") or "{}")
        except (TypeError, ValueError):
            params = {}
        value = params.get("symbol")
        if value:
            out.add(str(value))
    return out


def _account_ctx(acc: dict, broker: Any, equity: float) -> dict[str, Any]:
    """Контекст для закрытия по позициям счёта, без привязки к роботу."""
    return {"inst": {"id": f"account:{acc['id']}", "instrument": ""},
            "acc": acc, "acc_id": str(acc["id"]), "broker": broker,
            "runtime": {}, "symbol": "", "params": {}, "capital": equity,
            "store": None}


def close_all(store: Any, account_id: str) -> dict[str, Any]:
    """Закрыть позиции ОДНОГО счёта по данным брокера.

    Граница — счёт, на котором нажата кнопка: чужие счета не трогаются.
    Не зависит от статусов роботов: после «Стоп всех» или архивации позиция
    остаётся на счёте и должна закрываться. Паи фонда денежного рынка не
    трогаются. STOP_REAL не мешает закрытию — это уменьшение риска.
    """
    result: dict[str, Any] = {"ok": True, "account": str(account_id),
                              "closed": 0, "items": [], "skipped": [], "errors": []}
    acc = store.get_account(str(account_id))
    if acc is None:
        raise OpError(f"нет счёта {account_id}")
    if str(acc.get("mode") or "LIVE").upper() != "LIVE":
        raise OpError("закрытие позиций доступно только на реальном счёте LIVE")
    acc_id = str(acc["id"])
    fund_symbols = _fund_symbols(store)
    try:
        key_ref = acc.get("key_ref") or "{env:FINAM_SECRET}"
        broker = FinamBroker(secret=resolve_secret(key_ref), account=acc_id)
        equity = account_equity(broker, acc_id)
        if not equity or equity <= 0:
            raise OpError("нет equity счёта — позиции не закрыты")
        positions = positions_from_response(
            broker.account(acc_id).get("positions", []))
    except Exception as exc:  # noqa: BLE001 — причина уйдёт в ответ и в UI
        reason = f"{type(exc).__name__}: {exc}"[:200]
        result["ok"] = False
        result["errors"].append({"id": acc_id, "reason": reason})
        return result
    for symbol, qty in sorted(positions.items()):
        if not qty:
            continue
        if symbol in fund_symbols:
            result["skipped"].append({"id": acc_id, "symbol": symbol,
                                      "reason": "паи фонда денежного рынка"})
            continue
        try:
            row = _send_close(_account_ctx(acc, broker, equity), symbol, qty,
                              dry_run=False, note="все позиции")
        except Exception as exc:  # noqa: BLE001 — закрываем остальные позиции счёта
            row = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
        item = {"id": acc_id, "symbol": symbol, **row}
        result["items"].append(item)
        if row.get("ok") and row.get("qty"):
            result["closed"] += 1
        if not row.get("ok"):
            result["errors"].append(item)
    result["ok"] = not result["errors"]
    return result


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
        return _send_close(ctx, symbol, int(fund), dry_run=dry_run, note="фонд",
                           limits=mm_limits(ctx), multiplier=1.0)

    quote = _quote(ctx["broker"], symbol, 0.0001,
                   max_age=float(p.get("max_quote_age_sec") or MAX_QUOTE_AGE))
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
    result = _gateway(ctx, mm_limits(ctx)).submit(order, account=ctx["acc_id"],
                                                  stop=STOP_REAL, dry_run=dry_run)
    return {"ok": result.status in ("sent", "planned"), "status": result.status,
            "reason": result.reason, "symbol": symbol, "qty": volume,
            "side": "buy", "price": quote.ask, "free_cash": free,
            "spread_pct": spread_pct, "dry_run": dry_run}
