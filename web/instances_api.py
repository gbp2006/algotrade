"""API управления роботами, счетами и брокерами (сервис, этап 2).

Подключается к панели через `app.include_router(router)`. Бизнес-логика вынесена
в функции с явным store — их можно тестировать без HTTP-клиента.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from algo import robot_library as lib
from algo.broker import registry
from algo.robot_store import ConflictError, RobotStore, StoreError

router = APIRouter(prefix="/api", tags=["instances"])
_default_store = RobotStore()
_default_store.init_db()   # идемпотентно; без этого /api/instances падал на пустой БД


def get_store() -> RobotStore:
    return _default_store


def _fail(exc: Exception) -> None:
    if isinstance(exc, ConflictError):
        raise HTTPException(409, str(exc))
    if isinstance(exc, StoreError):
        raise HTTPException(400, str(exc))
    raise HTTPException(400, str(exc))


# ---------- библиотека ----------
def specs_view() -> list[dict]:
    return [
        {
            "id": s.id, "strategy": s.strategy, "defaults": s.defaults,
            "schema": s.schema, "instruments": list(s.instruments),
            "description": s.description, "examples": list(s.examples),
        }
        for s in lib.list_specs()
    ]


@router.get("/specs")
def specs():
    return specs_view()


@router.get("/specs/{spec_id}")
def spec_detail(spec_id: str):
    try:
        s = lib.get_spec(spec_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"id": s.id, "defaults": s.defaults, "schema": s.schema,
            "instruments": list(s.instruments), "description": s.description}


# ---------- инстансы ----------
def instances_view(store: RobotStore, mode: str | None = None,
                   status: str | None = None) -> list[dict]:
    return store.list_instances(mode=mode, status=status)


@router.get("/instances")
def instances(mode: str | None = None, status: str | None = None,
              store: RobotStore = Depends(get_store)):
    return instances_view(store, mode, status)


def create_view(store: RobotStore, payload: dict) -> dict:
    try:
        return store.create_instance(payload)
    except (StoreError, ValueError) as exc:
        _fail(exc)


@router.post("/instances", status_code=201)
def create(payload: dict, store: RobotStore = Depends(get_store)):
    return create_view(store, payload)


@router.get("/instances/{iid}")
def detail(iid: str, store: RobotStore = Depends(get_store)):
    inst = store.get_instance(iid)
    if inst is None:
        raise HTTPException(404, f"нет инстанса {iid}")
    return inst


def update_view(store: RobotStore, iid: str, payload: dict) -> dict:
    data = dict(payload)
    try:
        version = int(data.pop("version"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, "нужна версия инстанса (version)") from exc
    reason = str(data.pop("reason", ""))
    try:
        return store.update_instance(iid, data, version, reason=reason)
    except (StoreError, ValueError) as exc:
        _fail(exc)


@router.patch("/instances/{iid}")
def update(iid: str, payload: dict, store: RobotStore = Depends(get_store)):
    return update_view(store, iid, payload)


_ACTIONS = {"start": "active", "pause": "paused", "stop": "stopped",
            "archive": "archived"}


def action_view(store: RobotStore, iid: str, action: str,
                payload: dict | None = None) -> dict:
    if action == "promote":
        data = dict(payload or {})
        data["mode"] = "live"
        old = store.get_instance(iid)
        if old is None:
            raise HTTPException(404, f"нет инстанса {iid}")
        try:
            store.update_instance(iid, data, old["version"],
                                  reason="перевод в бой")
            return store.set_status(iid, "active", "перевод в бой")
        except (StoreError, ValueError) as exc:
            _fail(exc)
    status = _ACTIONS.get(action)
    if status is None:
        raise HTTPException(404, f"неизвестное действие {action}")
    try:
        return store.set_status(iid, status, (payload or {}).get("reason", ""))
    except StoreError as exc:
        _fail(exc)


@router.post("/instances/{iid}/{action}")
def action(iid: str, action: str, payload: dict | None = None,
           store: RobotStore = Depends(get_store)):
    return action_view(store, iid, action, payload)


def history_view(store: RobotStore, iid: str) -> list[dict]:
    return store.history(iid)


@router.get("/instances/{iid}/history")
def history(iid: str, store: RobotStore = Depends(get_store)):
    return history_view(store, iid)


# ---------- счета и брокеры ----------
@router.get("/accounts")
def accounts(store: RobotStore = Depends(get_store)):
    return store.list_accounts()


@router.post("/accounts", status_code=201)
def create_account(payload: dict, store: RobotStore = Depends(get_store)):
    try:
        return store.create_account(payload)
    except (StoreError, ValueError) as exc:
        _fail(exc)


@router.get("/brokers")
def brokers():
    return [{"name": name, "description": "адаптер брокера"}
            for name in registry.available()]


def broker_check_view(name: str) -> dict:
    try:
        adapter = registry.get_adapter(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    status = adapter.check_connection()
    return {"name": name, "ok": status.ok, "detail": status.detail}


@router.post("/brokers/{name}/check")
def broker_check(name: str):
    return broker_check_view(name)
