"""Дополнительные API денежных потоков и портфеля.

Подключается поверх существующего `web.instances_api`: старые маршруты,
виртуальные депозиты и боевые счета не переписываются. Для LIVE ручное
«применение» денег запрещено — потоки приходят только из опроса брокера.
"""

from __future__ import annotations

import json
from typing import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from algo import account_poller as poller
from algo.cash_flow_store import CashFlowStore
from algo.cash_flows import (CashFlow, CashFlowType, InsufficientPolicy,
                             Reaction, RobotSizing, preview_cash_flow)
from algo.pg_store import PgStore
from algo.portfolio import GO, MULT
from algo.portfolio_metrics import EquityPoint, summarize
from algo.robot_store import RobotStore
from web.instances_api import cached_analytics, get_store, invalidate_analytics

router = APIRouter(prefix="/api", tags=["cash-flows"])
Reporter = Callable[[str, str, object], list[dict]]
_flows_cache: CashFlowStore | None = None
LIVE_RUN = Path(__file__).resolve().parent.parent / "results" / "live_run.json"


def get_flows(store: RobotStore = Depends(get_store)) -> CashFlowStore:
    """Ленивая инициализация: новые таблицы не мешают старой панели."""
    global _flows_cache
    if _flows_cache is None or _flows_cache.store is not store:
        _flows_cache = CashFlowStore(store)
        _flows_cache.init_db()
    return _flows_cache


def _fail(exc: Exception) -> None:
    raise HTTPException(400, str(exc))


def _sizing(item: dict) -> RobotSizing:
    try:
        raw_max = item.get("max_lots")
        return RobotSizing(
            robot_id=str(item.get("robot_id") or item.get("id") or ""),
            name=str(item.get("name") or ""),
            price=float(item.get("price") or 0),
            mult=float(item.get("mult") or MULT),
            exposure=item.get("exposure"),
            margin_per_lot=float(item.get("margin_per_lot") or GO),
            position_lots=int(item.get("position_lots") or 0),
            reaction=Reaction(str(item.get("reaction") or Reaction.IMMEDIATE.value)),
            smoothing_pct=float(item.get("smoothing_pct") or 0),
            sizing_base=item.get("sizing_base"),
            min_lots=int(item.get("min_lots", 1)),
            max_lots=None if raw_max is None else int(raw_max),
            on_insufficient=InsufficientPolicy(
                str(item.get("on_insufficient") or InsufficientPolicy.PAUSE.value)),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"неверные настройки лотности: {exc}")


def _robots_from_store(store: RobotStore, account_id: str) -> list[RobotSizing]:
    """Роботы счёта: лот берём из runtime, цену — из последней котировки."""
    out: list[RobotSizing] = []
    for inst in store.list_instances():
        if inst.get("status") not in ("active", "running"):
            continue
        if account_id and str(inst.get("account") or "") != account_id:
            continue
        runtime = store.get_runtime(inst["id"]) or {}
        out.append(_sizing({
            "robot_id": inst["id"],
            "name": inst.get("note") or inst["id"],
            "price": runtime.get("last_price") or 0,
            "exposure": inst.get("exposure"),
            "position_lots": runtime.get("position") or 0,
        }))
    return out


def _robots_of(payload: dict, store: RobotStore) -> list[RobotSizing]:
    supplied = payload.get("robots")
    if supplied is not None:
        if not isinstance(supplied, list):
            raise HTTPException(400, "robots должен быть списком")
        return [_sizing(item) for item in supplied]
    return _robots_from_store(store, str(payload.get("account_id") or ""))


def _instance_balance(store: RobotStore, instance_id: str) -> float:
    inst = store.get_instance(instance_id)
    if inst is None:
        raise HTTPException(404, "нет робота с таким id")
    return float(inst.get("capital") or 0)


def _balance_for(payload: dict, store: RobotStore) -> float:
    if payload.get("balance_before") is not None:
        return float(payload["balance_before"])
    instance_id = str(payload.get("instance_id") or "")
    if instance_id:
        return _instance_balance(store, instance_id)
    return 0.0


def _flow_of(payload: dict, balance_before: float) -> CashFlow:
    try:
        kind = CashFlowType(str(payload.get("type") or "DEPOSIT").upper())
        return CashFlow.detect(
            kind, float(payload.get("amount") or 0), balance_before,
            created_at=str(payload.get("created_at") or ""),
            client_key=str(payload.get("client_key") or ""),
            note=str(payload.get("note") or ""))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"неверная операция: {exc}")


def _preview_payload(flow: CashFlow, preview, account_id: str) -> dict:
    return {
        "account_id": account_id,
        "flow": {"type": flow.type.value, "amount": flow.amount,
                 "balance_before": flow.balance_before,
                 "balance_after": flow.balance_after, "key": flow.key},
        "free_before": preview.free_before,
        "free_after": preview.free_after,
        "impact": preview.as_rows(),
        "validation": {"errors": list(preview.validation.errors),
                       "warnings": list(preview.validation.warnings)},
        "valid": preview.valid,
        "requires_confirmation": preview.requires_confirmation,
    }


def _pg_snapshots(account_id: str | None, limit: int, since: str = "") -> list[dict]:
    """Снимки из PostgreSQL, если DSN настроен; иначе пусто (есть SQLite)."""
    pg = PgStore()
    rows = pg.list_snapshots(account_id or "", limit)
    if since:
        rows = [row for row in rows if str(row.get("time") or "") >= since]
    return [{
        "account_id": row.get("account_id", ""),
        "timestamp": str(row.get("time") or ""),
        "equity": float(row.get("equity") or 0),
        "balance": float(row.get("balance") or 0),
        "cash_flow": 0.0,
        "drawdown_pct": float(row.get("drawdown_pct") or 0),
    } for row in rows][::-1]


def _pg_flows(account_id: str | None, limit: int) -> list[dict]:
    pg = PgStore()
    return pg.list_flows(account_id or "", limit)


# ---------- чистые view-функции (тестируются без HTTP) ----------
def preview_view(payload: dict, store: RobotStore) -> dict:
    balance = _balance_for(payload, store)
    flow = _flow_of(payload, balance)
    preview = preview_cash_flow(
        flow, _robots_of(payload, store),
        free_before=payload.get("free_before"),
        live=bool(payload.get("live")),
        large_flow_pct=float(payload.get("large_flow_pct", 20.0)))
    return _preview_payload(flow, preview, str(payload.get("account_id") or ""))


def apply_view(payload: dict, store: RobotStore, flows: CashFlowStore) -> dict:
    """Только виртуальные депозиты; LIVE меняет брокер, а не панель."""
    instance_id = str(payload.get("instance_id") or "")
    if not instance_id:
        raise HTTPException(400, "нужен instance_id виртуального робота")
    inst = store.get_instance(instance_id)
    if inst is None or inst.get("mode") != "paper":
        raise HTTPException(403, "ручное применение доступно только для виртуальных счетов")

    balance = _instance_balance(store, instance_id)
    flow = _flow_of(payload, balance)
    if not flow.client_key and not flow.broker_tx_id:
        raise HTTPException(400, "нужен client_key для защиты от повторной отправки")
    if flows.has_key(flow.key):
        return {"applied": False, "reason": "duplicate", "key": flow.key}

    robots = _robots_of(payload, store)
    preview = preview_cash_flow(flow, robots, free_before=balance)
    if not preview.valid:
        raise HTTPException(400, "; ".join(preview.validation.errors))
    result = flows.apply_virtual(instance_id, flow.delta, note=flow.note)
    recorded = flows.record_flow(flow, preview,
                                 account_id=str(inst.get("account") or instance_id),
                                 source="VIRTUAL")
    invalidate_analytics()
    return {"applied": True, **result, "key": recorded["key"],
            "impact": preview.as_rows()}


def sync_view(payload: dict, store: RobotStore, flows: CashFlowStore,
              reporter: Reporter | None = None,
              broker_factory: Callable[[dict], object] | None = None) -> dict:
    """Опрос всех счетов с ключами; отчёт брокера подтверждает поток."""
    wanted = str(payload.get("account_id") or "")
    accounts = [a for a in store.list_accounts()
                if not wanted or a["id"] == wanted]
    results = poller.sync_accounts(
        accounts, flows,
        broker_factory=broker_factory or payload.get("broker_factory"),
        reporter=reporter or poller.finam_report(),
        delta_abs=float(payload.get("delta_abs", 1_000.0)),
        delta_pct=float(payload.get("delta_pct", 1.0)),
        timestamp=str(payload.get("timestamp") or ""),
        force_report=bool(payload.get("force_report")))
    invalidate_analytics()
    return {"items": [r.__dict__ for r in results],
            "needs_report": [r.account_id for r in results if r.triggered and not r.flows]}


def history_view(account_id: str | None, limit: int,
                 flows: CashFlowStore) -> dict:
    pg_rows = _pg_flows(account_id, limit)
    if pg_rows:
        return {"items": pg_rows, "source": "postgres"}
    rows = flows.list_flows(account_id, limit)
    return {"items": [{**r, "impacts": flows.list_impacts(r["id"])} for r in rows],
            "source": "sqlite"}


def equity_view(account_id: str | None, limit: int, since: str,
                flows: CashFlowStore) -> dict:
    pg_rows = _pg_snapshots(account_id, limit, since)
    snapshots = pg_rows or flows.list_snapshots(account_id, limit, since)
    flow_rows = _pg_flows(account_id, min(limit, 200)) or flows.list_flows(
        account_id, min(limit, 200))
    markers = [{"timestamp": r["created_at"], "type": r["type"],
                "amount": r["amount"], "balance_before": r["balance_before"],
                "balance_after": r["balance_after"]} for r in reversed(flow_rows)]
    points = [EquityPoint(s["timestamp"], s["equity"],
                          cash_flow=s["cash_flow"]) for s in snapshots]
    metrics = summarize(points)
    return {"snapshots": snapshots, "markers": markers,
            "metrics": metrics.to_dict()}


def portfolio_analytics_view(account_id: str | None, store: RobotStore,
                             flows: CashFlowStore) -> dict:
    """Старые поля `/api/accounts/analytics` сохраняются, добавляется portfolio."""
    base = cached_analytics(store)
    snapshots = _pg_snapshots(account_id, 2000) or flows.list_snapshots(account_id, limit=2000)
    points = [EquityPoint(s["timestamp"], s["equity"],
                          cash_flow=s["cash_flow"]) for s in snapshots]
    return {**base, "portfolio": {
        "account_id": account_id or "", "points": len(points),
        "source": "postgres" if _pg_snapshots(account_id, 1) else "sqlite",
        "flows": len(_pg_flows(account_id, 500) or flows.list_flows(account_id, 500)),
        "metrics": summarize(points).to_dict(),
    }}


def reconciliation_view() -> dict:
    """Сверка расчётной лотности/цены с факт execution из live_run.json."""
    try:
        data = json.loads(LIVE_RUN.read_text(encoding="utf-8")) if LIVE_RUN.exists() else {}
    except (OSError, ValueError):
        data = {}
    rows: list[dict] = []
    for fill in data.get("fills", []) or []:
        rows.append({
            "robot": fill.get("robot") or fill.get("config") or "",
            "symbol": fill.get("symbol") or "",
            "planned_lots": fill.get("planned_lots") or fill.get("planned_qty") or 0,
            "actual_lots": fill.get("executed_qty") or fill.get("actual_lots") or 0,
            "planned_price": fill.get("signal_price") or fill.get("planned_price") or 0,
            "actual_price": fill.get("price") or fill.get("actual_price") or 0,
            "slippage_ticks": fill.get("slippage_ticks") or 0,
            "slippage_rub": fill.get("slippage_rub") or 0,
            "commission": fill.get("commission") or 0,
        })
    return {"date": data.get("date") or "", "items": rows,
            "note": "пусто — реальных исполнений пока нет" if not rows else ""}


# ---------- маршруты ----------
@router.post("/cash-flows/preview")
def preview_endpoint(payload: dict, store: RobotStore = Depends(get_store)):
    return preview_view(payload, store)


@router.post("/cash-flows", status_code=201)
def apply_endpoint(payload: dict, store: RobotStore = Depends(get_store),
                   flows: CashFlowStore = Depends(get_flows)):
    try:
        return apply_view(payload, store, flows)
    except ValueError as exc:
        _fail(exc)


@router.post("/cash-flows/sync")
def sync_endpoint(payload: dict | None = None,
                  store: RobotStore = Depends(get_store),
                  flows: CashFlowStore = Depends(get_flows)):
    return sync_view(payload or {}, store, flows)


@router.get("/cash-flows")
def history_endpoint(account_id: str | None = None, limit: int = 100,
                     flows: CashFlowStore = Depends(get_flows)):
    return history_view(account_id, limit, flows)


@router.get("/portfolio/equity")
def equity_endpoint(account_id: str | None = None, limit: int = 500,
                    since: str = "", flows: CashFlowStore = Depends(get_flows)):
    return equity_view(account_id, limit, since, flows)


@router.get("/portfolio/reconciliation")
def reconciliation_endpoint():
    return reconciliation_view()


@router.get("/portfolio/analytics")
def portfolio_analytics_endpoint(account_id: str | None = None,
                                 store: RobotStore = Depends(get_store),
                                 flows: CashFlowStore = Depends(get_flows)):
    return portfolio_analytics_view(account_id, store, flows)
