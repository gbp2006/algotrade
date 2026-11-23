"""API управления роботами, счетами и брокерами (сервис, этап 2).

Подключается к панели через `app.include_router(router)`. Бизнес-логика вынесена
в функции с явным store — их можно тестировать без HTTP-клиента.
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from algo import backtest_preview, robot_library as lib, scheduler
from algo.broker import registry
from algo.instance_configs import migrate_runtime_from_paper, seed_static_configs
from algo.robot_store import ConflictError, RobotStore, StoreError

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "results" / "live.csv"
PAPER = ROOT / "results" / "paper.csv"
HEALTH = ROOT / "results" / "health.json"
SHADOW = ROOT / "results" / "shadow.json"
ROLLOVER = ROOT / "results" / "rollover_run.json"
STOP = ROOT / "results" / "STOP"
STOP_REAL = ROOT / "results" / "STOP_REAL"

router = APIRouter(prefix="/api", tags=["instances"])
_default_store = RobotStore()
_default_store.init_db()   # идемпотентно; без этого /api/instances падал на пустой БД
seed_static_configs(_default_store)  # статические конфиги становятся управляемыми инстансами
try:
    migrate_runtime_from_paper(_default_store)  # позиции запущенных роботов из paper.csv
except Exception:  # noqa: BLE001 — журнал остаётся главным источником, панель должна подняться
    pass
try:
    scheduler.seed_default_jobs(_default_store)  # расписание видно в панели
except Exception:  # noqa: BLE001
    pass


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


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _slug(value: str) -> str:
    """Имя → латинский идентификатор, пригодный для журналов."""
    text = "".join(_TRANSLIT.get(ch, ch) for ch in value.strip().lower())
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40]


def generated_instance_id(name: str, spec_id: str, instrument: str,
                          store: RobotStore) -> str:
    """Внутренний генератор id: по имени, с уникальным суффиксом."""
    base = _slug(name) or _slug(f"{spec_id}-{instrument}")
    candidate, suffix = base, 2
    while store.get_instance(candidate) is not None:
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    return candidate


def create_view(store: RobotStore, payload: dict) -> dict:
    data = dict(payload)
    name = str(data.pop("name", "") or "").strip()
    if not data.get("id"):
        data["id"] = generated_instance_id(
            name, str(data.get("spec_id", "")),
            str(data.get("instrument", "CNY")), store)
    if name:
        data["note"] = name
    try:
        return store.create_instance(data)
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


def backtest_preview_view(payload: dict) -> dict:
    try:
        return backtest_preview.preview(
            str(payload.get("spec_id", "")),
            str(payload.get("instrument", "CNY")),
            payload.get("params") or {},
            int(payload.get("days", 60)),
        )
    except Exception as exc:  # noqa: BLE001 — предпросмотр не должен ронять API
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


@router.post("/backtest-preview")
def backtest_preview_endpoint(payload: dict):
    return backtest_preview_view(payload)


@router.get("/instances/{iid}/history")
def history(iid: str, store: RobotStore = Depends(get_store)):
    return history_view(store, iid)


# ---------- счета и брокеры ----------
@router.get("/runtime")
def runtime(store: RobotStore = Depends(get_store)):
    return store.list_runtime()


@router.post("/runtime/migrate")
def runtime_migrate(store: RobotStore = Depends(get_store)):
    return {"migrated": migrate_runtime_from_paper(store)}


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


# ---------- вкладка «Торговля» ----------
def _json_file(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


def live_orders_view(limit: int = 60) -> list[dict]:
    if not LIVE.exists():
        return []
    with LIVE.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if "client_id" in r]
    return list(reversed(rows[-limit:]))


def live_state_view() -> dict:
    days: set[str] = set()
    if PAPER.exists():
        with PAPER.open(encoding="utf-8") as f:
            days = {r.get("date", "") for r in csv.DictReader(f) if "config" in r}
    days.discard("")
    shadow_days: set[str] = set()
    if LIVE.exists():
        with LIVE.open(encoding="utf-8") as f:
            shadow_days = {str(r.get("ts", ""))[:10]
                           for r in csv.DictReader(f)
                           if r.get("status") == "planned" and r.get("ts")}
    return {
        "allow_trading": os.environ.get("FINAM_ALLOW_TRADING") == "1",
        "stop_paper": STOP.exists(),
        "stop_real": STOP_REAL.exists(),
        "paper_days": len(days),
        "shadow_days": len(shadow_days),
        "health": _json_file(HEALTH),
        "shadow": _json_file(SHADOW),
        "rollover": _json_file(ROLLOVER),
    }


@router.get("/live-orders")
def live_orders(limit: int = 60):
    return live_orders_view(limit)


@router.get("/live-state")
def live_state():
    return live_state_view()


def stop_real_view(action: str) -> dict:
    if action == "set":
        STOP_REAL.parent.mkdir(parents=True, exist_ok=True)
        STOP_REAL.write_text("установлен из панели\n", encoding="utf-8")
    elif action == "clear":
        STOP_REAL.unlink(missing_ok=True)
    else:
        raise HTTPException(400, "action: set | clear")
    return {"stop_real": STOP_REAL.exists()}


@router.post("/stop-real")
def stop_real(payload: dict):
    return stop_real_view(str(payload.get("action", "")).lower())


# ---------- планировщик ----------
@router.get("/scheduler/jobs")
def scheduler_jobs(store: RobotStore = Depends(get_store)):
    return store.list_jobs()


@router.post("/scheduler/jobs", status_code=201)
def scheduler_upsert_job(payload: dict, store: RobotStore = Depends(get_store)):
    try:
        return store.upsert_job(payload)
    except StoreError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/scheduler/jobs/{job_id}")
def scheduler_delete_job(job_id: str, store: RobotStore = Depends(get_store)):
    return {"deleted": store.delete_job(job_id)}


@router.get("/scheduler/runs")
def scheduler_runs(limit: int = 50, job_id: str | None = None,
                   store: RobotStore = Depends(get_store)):
    return store.list_runs(limit=limit, job_id=job_id)


@router.get("/scheduler/state")
def scheduler_state(store: RobotStore = Depends(get_store)):
    return {
        "shadow": scheduler.shadow(),
        "jobs": len(store.list_jobs()),
        "runs": len(store.list_runs(limit=200)),
        "log": scheduler.LOG.name,
    }
