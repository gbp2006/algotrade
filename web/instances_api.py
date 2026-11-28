"""API управления роботами, счетами и брокерами (сервис, этап 2).

Подключается к панели через `app.include_router(router)`. Бизнес-логика вынесена
в функции с явным store — их можно тестировать без HTTP-клиента.
"""

from __future__ import annotations

import csv
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from algo import (account_poller, backtest_preview,
                  cash_flow_store, instruments_catalog as catalog,
                  live_control, robot_library as lib, robot_schedule,
                  robot_trade, scheduler, strategy_descriptions as sd,
                  trade_journal as tj)
from algo.broker import position_ops as pos, registry
from algo.broker.finam import FinamBroker
from algo.broker.secrets import resolve_secret
from algo.instance_configs import migrate_runtime_from_paper, seed_static_configs
from algo.robot_store import ConflictError, RobotStore, StoreError

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "results" / "live.csv"
SHADOW_JOURNAL = ROOT / "results" / "shadow.csv"
PAPER = ROOT / "results" / "paper.csv"
HEALTH = ROOT / "results" / "health.json"
SHADOW = ROOT / "results" / "shadow.json"
ROLLOVER = ROOT / "results" / "rollover_run.json"
STOP = ROOT / "results" / "STOP"
STOP_REAL = ROOT / "results" / "STOP_REAL"
LIVE_RUN_LOCK = ROOT / "results" / "live_run.lock"
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
            "id": s.id, "strategy": s.strategy, "title": sd.name(s.strategy),
            "defaults": s.defaults,
            "schema": s.schema, "instruments": list(s.instruments),
            "description": s.description, "examples": list(s.examples),
            "about": sd.describe(s.strategy),
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
            "instruments": list(s.instruments), "description": s.description,
            "about": sd.describe(s.strategy)}


# ---------- инстансы ----------
def instances_view(store: RobotStore, mode: str | None = None,
                   status: str | None = None) -> list[dict]:
    rows = store.list_instances(mode=mode, status=status)
    for r in rows:
        # `note` — короткое имя, `description` — описание идеи робота,
        # `about` — описание самой стратегии (fallback для старых строк).
        r["description"] = r.get("description") or r.get("note") or ""
        r["strategy_name"] = sd.name(r.get("spec_id") or "")
        r["about"] = sd.describe(r.get("spec_id") or "")
    return rows


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
    if "key_ref" in data:
        data["key_ref"] = _robot_key(data, data["id"])
    try:
        return store.create_instance(data)
    except (StoreError, ValueError) as exc:
        _fail(exc)


@router.post("/instances", status_code=201)
def create(payload: dict, store: RobotStore = Depends(get_store)):
    result = create_view(store, payload)
    invalidate_analytics()  # виртуальный equity/position в аналитике
    return result


@router.get("/instances/{iid}")
def detail(iid: str, store: RobotStore = Depends(get_store)):
    inst = store.get_instance(iid)
    if inst is None:
        raise HTTPException(404, f"нет инстанса {iid}")
    return {**inst,
            "description": inst.get("description") or inst.get("note") or "",
            "strategy_name": sd.name(inst.get("spec_id") or ""),
            "about": sd.describe(inst.get("spec_id") or "")}


def update_view(store: RobotStore, iid: str, payload: dict) -> dict:
    data = dict(payload)
    try:
        version = int(data.pop("version"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, "нужна версия инстанса (version)") from exc
    reason = str(data.pop("reason", ""))
    if "key_ref" in data:
        data["key_ref"] = _robot_key(data, iid)
    try:
        return store.update_instance(iid, data, version, reason=reason)
    except (StoreError, ValueError) as exc:
        _fail(exc)


@router.patch("/instances/{iid}")
def update(iid: str, payload: dict, store: RobotStore = Depends(get_store)):
    result = update_view(store, iid, payload)
    invalidate_analytics()
    return result


_ACTIONS = {"start": "active", "pause": "paused", "stop": "stopped",
            "archive": "archived"}


def action_view(store: RobotStore, iid: str, action: str,
                payload: dict | None = None) -> dict:
    if action == "close":
        try:
            return pos.close_instance(store, iid, dry_run=False)
        except pos.OpError as exc:
            raise HTTPException(400, str(exc))
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


# ---------- простой старт/стоп торговли робота ----------
@router.post("/instances/{iid}/trade")
def robot_trade_control(iid: str, payload: dict,
                        store: RobotStore = Depends(get_store)):
    """Старт включает робота и его расписание; стоп выключает оба."""
    try:
        return (robot_trade.start(store, iid) if payload.get("start")
                else robot_trade.stop(store, iid))
    except (ValueError, StoreError) as exc:
        raise HTTPException(400, str(exc))


# ---------- расписание робота (галка в карточке + отдельная вкладка) ----------
# Роуты объявлены ДО общего /instances/{iid}/{action}, иначе он перехватит
# action="schedule" и вернёт 404.
@router.get("/schedules")
def schedules_all(store: RobotStore = Depends(get_store)):
    return robot_schedule.all_schedules(store)


@router.get("/instances/{iid}/schedule")
def schedule_get(iid: str, store: RobotStore = Depends(get_store)):
    inst = store.get_instance(iid)
    if inst is None:
        raise HTTPException(404, f"нет робота {iid}")
    return robot_schedule.read_schedule(store, inst)


@router.post("/instances/{iid}/schedule")
def schedule_save(iid: str, payload: dict, store: RobotStore = Depends(get_store)):
    inst = store.get_instance(iid)
    if inst is None:
        raise HTTPException(404, f"нет робота {iid}")
    try:
        return robot_schedule.save_schedule(store, inst, payload)
    except (ValueError, StoreError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/instances/{iid}/{action}")
def action(iid: str, action: str, payload: dict | None = None,
           store: RobotStore = Depends(get_store)):
    result = action_view(store, iid, action, payload)
    invalidate_analytics()
    return result


@router.delete("/instances/{iid}")
def delete_instance(iid: str, store: RobotStore = Depends(get_store)):
    """Полное удаление архивного/чернового робота (не боевого и не активного)."""
    try:
        result = store.delete_instance(iid)
        invalidate_analytics()
        return result
    except StoreError as exc:
        raise HTTPException(400, str(exc))


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


@router.get("/instances/{iid}/decisions")
def instance_decisions(iid: str, store: RobotStore = Depends(get_store)):
    """Персональный журнал сигналов робота (не paper.csv)."""
    return {"items": store.list_decisions(iid)}


@router.get("/instances/{iid}/history")
def history(iid: str, store: RobotStore = Depends(get_store)):
    return history_view(store, iid)


# ---------- счета и брокеры ----------
@router.get("/runtime")
def runtime(store: RobotStore = Depends(get_store)):
    return store.list_runtime()


@router.post("/runtime/migrate")
def runtime_migrate(store: RobotStore = Depends(get_store)):
    result = {"migrated": migrate_runtime_from_paper(store)}
    invalidate_analytics()
    return result


@router.get("/accounts")
def accounts(store: RobotStore = Depends(get_store)):
    return store.list_accounts()


def _account_id(value: object) -> str:
    """Finam ждёт числовой ID; из «КлФ-2115210» берём «2115210»."""
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    return digits or raw


@router.post("/accounts", status_code=201)
def create_account(payload: dict, store: RobotStore = Depends(get_store)):
    data = dict(payload)
    try:
        # TEST-счета имеют имена вида paper-<id> — их не трогаем.
        if str(data.get("mode") or "LIVE").upper() == "LIVE":
            data["id"] = _account_id(data.get("id", ""))
        key = str(data.get("key_ref") or "").strip()
        if key.startswith("tapi_sk_"):
            ref = f"acc:{data['id']}"
            _write_key(ref, key)  # секрет → auth.json, в счёте только имя
            data["key_ref"] = ref
        invalidate_analytics()
        return store.create_account(data)
    except (StoreError, ValueError) as exc:
        _fail(exc)


def _auth_path() -> Path:
    return Path(os.environ.get("ALGO_AUTH", str(ROOT / "auth.json")))


def _read_auth() -> dict:
    path = _auth_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


@router.get("/keys")
def list_keys():
    """Только имена ключей — значения никогда не отдаются наружу."""
    return {"names": sorted((_read_auth().get("finam") or {}).keys())}


def _write_key(ref: str, secret: str) -> str:
    ref = str(ref or "").strip()
    # Имя счёта может содержать скобки и кириллицу (например, «acc:Дневной канал (cb-day)»).
    if not ref or not re.fullmatch(r"[\w\-:. ()]{1,64}", ref, re.UNICODE):
        raise ValueError("неверное имя ключа")
    if not secret:
        raise ValueError("ключ не задан")
    data = _read_auth()
    data.setdefault("finam", {})[ref] = secret
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return ref


def _robot_key(payload: dict, iid: str) -> str:
    """Поле ключа робота: секрет сохраняется в auth.json, наружу — только имя."""
    value = str(payload.get("key_ref") or "").strip()
    if value.startswith("tapi_sk_"):
        ref = f"robot:{iid}"
        _write_key(ref, value)
        return ref
    return value


def _rename_key(old_ref: str, new_ref: str) -> None:
    """Переименовать запись ключа, не раскрывая секрет."""
    data = _read_auth()
    finam = data.get("finam") or {}
    if old_ref not in finam:
        return
    finam[new_ref] = finam.pop(old_ref)
    path = _auth_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


@router.patch("/accounts/{acc_id}")
def update_account(acc_id: str, payload: dict,
                   store: RobotStore = Depends(get_store)):
    data = dict(payload)
    if "enabled" in data:
        data["enabled"] = bool(data["enabled"])
    new_raw = str(data.pop("new_id", "") or data.pop("id", "") or "").strip()
    key = str(data.pop("key_ref", "") or "").strip()
    if store.get_account(acc_id) is None:
        raise HTTPException(404, f"нет счёта {acc_id}")
    old_id = acc_id
    target = new_raw or acc_id
    if str(data.get("mode") or "LIVE").upper() == "LIVE" and new_raw:
        target = _account_id(new_raw)
    if target != acc_id:
        try:
            _rename_key(f"acc:{acc_id}", f"acc:{target}")
            store.rename_account(acc_id, target)
        except (StoreError, ValueError) as exc:
            _fail(exc)
        acc_id = target
        # Фронтенд пишет секрет под старым ID до PATCH; после переименования
        # ссылка должна указывать на новое имя ключа.
        if key == f"acc:{old_id}":
            key = f"acc:{acc_id}"
    if key.startswith("tapi_sk_"):
        try:
            data["key_ref"] = _write_key(f"acc:{acc_id}", key)
        except ValueError as exc:
            _fail(exc)
    elif key:
        # Готовая ссылка (acc:<id> после /api/keys или legacy-имя): привязываем
        # к счёту. Раньше значение молча отбрасывалось, и новый ключ не работал.
        data["key_ref"] = key
    try:
        result = store.update_account(acc_id, data)
        invalidate_analytics()
        return result
    except (StoreError, ValueError) as exc:
        _fail(exc)


@router.post("/accounts/{acc_id}/refresh")
def refresh_account(acc_id: str, store: RobotStore = Depends(get_store)):
    """Запросить свежий баланс одного счёта у брокера."""
    acc = store.get_account(acc_id)
    if acc is None:
        raise HTTPException(404, f"нет счёта {acc_id}")
    if not acc.get("key_ref"):
        # Самовосстановление: ключ уже мог быть записан панелью под acc:<id>,
        # но не привязан к счёту из-за старой ошибки PATCH.
        ref = f"acc:{acc_id}"
        if ref in (_read_auth().get("finam") or {}):
            store.update_account(acc_id, {"key_ref": ref})
            acc = store.get_account(acc_id) or acc
    if not acc.get("key_ref"):
        raise HTTPException(400, "у счёта нет API-ключа")
    if not acc.get("enabled", True):
        raise HTTPException(400, "счёт выключен — включите его для запроса баланса")
    flows = cash_flow_store.CashFlowStore(store)
    try:
        results = account_poller.sync_accounts(
            [acc], flows, reporter=account_poller.finam_report())
    except Exception as exc:  # noqa: BLE001 — ошибка брокера не роняет панель
        raise HTTPException(400, f"{type(exc).__name__}: {exc}"[:200])
    result = results[0] if results else account_poller.PollOutcome(acc_id, False)
    invalidate_analytics()
    return {"ok": result.ok, "equity": result.equity, "delta": result.delta,
            "error": result.error, "flows": list(result.flows)}


@router.delete("/accounts/{acc_id}")
def delete_account(acc_id: str, store: RobotStore = Depends(get_store)):
    """Удалить счёт можно только если к нему не привязаны роботы."""
    try:
        result = store.delete_account(acc_id)
        invalidate_analytics()
        return {"deleted": result, "id": acc_id}
    except StoreError as exc:
        raise HTTPException(400, str(exc))


@router.post("/keys", status_code=201)
def save_key(payload: dict):
    """Записать именованный ключ в auth.json (600). В ответе — только имя."""
    try:
        result = {"key_ref": _write_key(payload.get("key_ref"),
                                        str(payload.get("secret") or "")),
                  "saved": True}
        invalidate_analytics()
        return result
    except ValueError as exc:
        _fail(exc)


@router.get("/service-key")
def service_key_status():
    from algo.broker.secrets import SERVICE_KEY_REF
    names = list((_read_auth().get("finam") or {}).keys())
    return {"ref": SERVICE_KEY_REF, "set": SERVICE_KEY_REF in names,
            "env_fallback": bool(os.environ.get("FINAM_SECRET"))}


@router.post("/service-key")
def service_key_save(payload: dict):
    from algo.broker.secrets import SERVICE_KEY_REF
    try:
        return {"ref": _write_key(SERVICE_KEY_REF,
                                  str(payload.get("secret") or "")), "saved": True}
    except ValueError as exc:
        _fail(exc)


def _catalog_broker(store: RobotStore) -> FinamBroker:
    """Сервисные операции идут под сервисным ключом, не под ключом счёта."""
    from algo.broker.secrets import resolve_service_secret
    rows = store.list_accounts()
    account = rows[0]["id"] if rows else os.environ.get("FINAM_ACCOUNT", "")
    if not account:
        raise HTTPException(400, "нет счетов: нечем обновлять справочник")
    return FinamBroker(secret=resolve_service_secret(), account=account)


@router.get("/instruments")
def instruments_search(search: str = "", limit: int = 30,
                       scope: str = "liquid"):
    return catalog.search(search, limit=min(max(limit, 1), 100), scope=scope)


@router.get("/instruments/favorites")
def instruments_favorites():
    return catalog.favorites()


@router.post("/instruments/{symbol}/favorite")
def instrument_favorite(symbol: str, payload: dict | None = None):
    return catalog.toggle_favorite(symbol, (payload or {}).get("note", ""))


@router.post("/instruments/refresh-liquid")
def instruments_refresh_liquid():
    return catalog.refresh_liquid()


@router.get("/instruments/stats")
def instruments_stats():
    return catalog.stats()


@router.post("/instruments/refresh")
def instruments_refresh(store: RobotStore = Depends(get_store)):
    return catalog.refresh(_catalog_broker(store))


@router.post("/instruments/{symbol}/params")
def instruments_params(symbol: str, store: RobotStore = Depends(get_store)):
    rows = store.list_accounts()
    if not rows:
        raise HTTPException(400, "нет счетов")
    try:
        return catalog.enrich(symbol, _catalog_broker(store), rows[0]["id"])
    except Exception as exc:  # noqa: BLE001 — API может не знать символ
        raise HTTPException(400, f"{type(exc).__name__}: {exc}"[:200])


@router.post("/money-market/{iid}/rebalance")
def mm_rebalance(iid: str, payload: dict | None = None,
                 store: RobotStore = Depends(get_store)):
    """Ребалансировка фонда денежного рынка (по образцу TmonRebalancer)."""
    try:
        result = pos.mm_rebalance(
            store, iid, dry_run=False,
            regime=(payload or {}).get("regime"))
        invalidate_analytics()
        return result
    except pos.OpError as exc:
        raise HTTPException(400, str(exc))


@router.post("/money-market/{iid}/close")
def mm_close(iid: str, store: RobotStore = Depends(get_store)):
    try:
        fund = pos._context(store, iid)["params"].get("symbol")
        result = pos.close_instance(
            store, iid, dry_run=False,
            symbol=str(fund) if fund else None)
        invalidate_analytics()
        return result
    except pos.OpError as exc:
        raise HTTPException(400, str(exc))


@router.post("/positions/close-all")
def close_all_positions(payload: dict, store: RobotStore = Depends(get_store)):
    """Закрыть позиции только того счёта, на котором нажата кнопка."""
    account_id = str(payload.get("account") or "").strip()
    if not account_id:
        raise HTTPException(400, "укажите счёт для закрытия позиций")
    try:
        result = pos.close_all(store, account_id)
    except pos.OpError as exc:
        raise HTTPException(400, str(exc))
    invalidate_analytics()
    return result


@contextmanager
def _live_run_guard():
    """Один ручной прогон одновременно: второй получает 409, а не дубль заявок.

    Журнал и UNIQUE ловят повтор только после отправки брокеру, поэтому гонку
    двух процессов останавливаем до старта раннера (ADR 27.11).
    """
    LIVE_RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LIVE_RUN_LOCK.open("a+") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise HTTPException(409, "боевой прогон уже идёт") from exc
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _live_run_view(payload: dict) -> dict:
    """Ручной прогон боевого контура; `dry_run` — явная репетиция."""
    if STOP_REAL.exists():
        raise HTTPException(400, "установлен STOP_REAL — снимите перед запуском")
    dry_run = bool(payload.get("dry_run"))
    day = str(payload.get("day") or date.today().isoformat())
    cmd = [sys.executable, str(ROOT / "scripts" / "34_live_execute.py")]
    if dry_run:
        cmd.append("--dry-run")
    cmd += ["--day", day]
    with _live_run_guard():
        try:
            proc = subprocess.run(cmd, cwd=ROOT, env=dict(os.environ), capture_output=True,
                                  text=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "боевой раннер не ответил за 180 с")
        summary: dict = {}
        path = ROOT / "results" / "live_run.json"
        if path.exists():
            try:
                summary = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        log = ROOT / "results" / "live_manual.log"
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} "
                    f"{'dry-run' if dry_run else 'live'} "
                    f"day={day} rc={proc.returncode} {proc.stdout.strip()[:160]}\n")
        invalidate_analytics()  # прогон мог изменить позиции/equity
        return {"ok": proc.returncode == 0, "dry_run": dry_run, "summary": summary,
                "stdout": proc.stdout.strip()[-800:], "stderr": proc.stderr.strip()[-400:]}


@router.post("/live-run")
def live_run(payload: dict | None = None):
    return _live_run_view(payload or {})


@router.get("/journal")
def journal(limit: int = 100, account: str | None = None):
    """Последние записи журнала из SQLite (источник правды)."""
    return tj.records(limit=min(max(limit, 1), 1000), account=account)


@router.post("/journal/backup")
def journal_backup():
    path = tj.backup()
    return {"backup": str(path.relative_to(ROOT)), "ok": True}


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
    # Тень с 24.11 пишет в shadow.csv; старые planned-строки жили в live.csv —
    # читаем оба журнала, чтобы счётчик G3 не терял историю при разделении.
    for journal in (LIVE, SHADOW_JOURNAL):
        if not journal.exists():
            continue
        with journal.open(encoding="utf-8") as f:
            shadow_days |= {str(r.get("ts", ""))[:10]
                            for r in csv.DictReader(f)
                            if r.get("status") == "planned" and r.get("ts")}
    return {
        "routing": "только счета LIVE; виртуальные не торгуют",
        "live_trading_enabled": bool((live_control.status() or {}).get("enabled")),
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


# ---------- архив, аналитика счетов и единый лог (GUI v2) ----------
def archive_list(store: RobotStore) -> list[dict]:
    """Роботы, выведенные из эксплуатации: реал и бумага в одном списке."""
    out = []
    for r in store.list_instances():
        if r["status"] not in ("archived", "stopped"):
            continue
        try:
            rt = store.get_runtime(r["id"]) or {}
        except Exception:  # noqa: BLE001 — рантайм не обязателен для архива
            rt = {}
        out.append({
            "id": r["id"], "mode": r["mode"], "status": r["status"],
            "strategy": r["spec_id"], "note": r.get("note") or "",
            "updated_at": r.get("updated_at") or "",
            "last_decision": rt.get("last_decision") or "",
            "position": rt.get("position"),
        })
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


@router.get("/archive")
def api_archive(store: RobotStore = Depends(get_store)):
    return {"items": archive_list(store)}


def _scalar(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("value", 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def account_analytics(store: RobotStore) -> dict:
    """Аналитика реальных и виртуальных счетов (без вывода секретов)."""
    real = []
    for acc in store.list_accounts():
        if not acc.get("enabled", True):
            continue
        if str(acc.get("mode") or "LIVE").upper() == "TEST":
            continue  # локальные TEST-счета показываются в virtual по инстансам
        row = {"id": acc["id"], "label": acc.get("label") or acc["id"],
               "mode": str(acc.get("mode") or "LIVE").lower(),
               "equity": None, "positions": [],
               "status": "нет ключа"}
        try:
            broker = FinamBroker(secret=resolve_secret(acc["key_ref"]),
                                 account=acc["id"])
            data = broker.account(acc["id"])
            row["equity"] = _scalar(data.get("equity"))
            row["positions"] = [
                {"symbol": p.get("symbol"),
                 "qty": _scalar(p.get("quantity")),
                 "pnl": _scalar(p.get("unrealized_pnl"))}
                for p in data.get("positions", [])]
            row["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 — счёт без доступа не роняет панель
            row["status"] = type(exc).__name__
        real.append(row)
    virtual = []
    for inst in store.list_instances(mode="paper"):
        try:
            rt = store.get_runtime(inst["id"]) or {}
        except Exception:  # noqa: BLE001
            rt = {}
        virtual.append({
            "id": inst["id"], "mode": "paper",
            "label": inst.get("note") or inst["id"],
            "equity": rt.get("equity"), "position": rt.get("position"),
            "last_price": rt.get("last_price"),
            "last_decision": rt.get("last_decision") or "",
        })
    return {"real": real, "virtual": virtual}


_ANALYTICS_TTL = 30.0
_analytics_cache: tuple[float, dict] | None = None


def invalidate_analytics() -> None:
    global _analytics_cache
    _analytics_cache = None


def cached_analytics(store: RobotStore) -> dict:
    """Кэш на 30 с: страницы «Счета» и «Торговля» не дёргают брокера на каждый клик."""
    global _analytics_cache
    now = time.monotonic()
    if _analytics_cache and now - _analytics_cache[0] < _ANALYTICS_TTL:
        return _analytics_cache[1]
    data = account_analytics(store)
    _analytics_cache = (now, data)
    return data


@router.get("/accounts/analytics")
def api_accounts_analytics(store: RobotStore = Depends(get_store)):
    return cached_analytics(store)


def logs_aggregate(store: RobotStore, limit: int = 80) -> list[dict]:
    """Единый лог: заявки, события инстансов, запуски таймеров, здоровье."""
    out: list[dict] = []
    for r in tj.records(limit=limit):
        out.append({"ts": r["ts"], "source": "orders", "details": dict(r),
                    "text": f"{r['config']} {r['side']} {r['qty']} "
                            f"@{r['price']} — {r['status']}"})
    for e in store.events_feed(limit=limit):
        out.append({"ts": e.get("created_at") or "", "source": "instances",
                    "details": dict(e),
                    "text": f"{e.get('instance_id')}: {e.get('action')} "
                            f"{e.get('reason') or ''}".strip()})
    for r in store.list_runs(limit=limit):
        out.append({"ts": r.get("started") or "", "source": "scheduler",
                    "details": dict(r),
                    "text": f"{r.get('job_id')}: {r.get('status')} "
                            f"{r.get('detail') or ''}".strip()})
    try:
        wd = json.loads(HEALTH.read_text(encoding="utf-8"))
        for p in wd.get("problems", []):
            out.append({"ts": wd.get("checked") or "", "source": "health",
                        "details": {"problem": p}, "text": p})
    except Exception:  # noqa: BLE001 — битый health не должен ронять лог
        pass
    return sorted(out, key=lambda x: x["ts"], reverse=True)[:limit * 2]


@router.get("/logs")
def api_logs(limit: int = 80, store: RobotStore = Depends(get_store)):
    return {"items": logs_aggregate(store, min(max(limit, 1), 500))}
