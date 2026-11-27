"""Разрешение реальной торговли из панели без systemd-таймера.

Единственный пуск — пользовательское расписание активного живого робота
(`inst:<id>:schedule`), которое исполняет внутренний планировщик. Включение
разрешает эти задания, выключение снимает. `.env` не меняется: флаг из команды
задания остаётся локальным для этого робота.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .robot_store import RobotStore

ROOT = Path(__file__).resolve().parent.parent
AUDIT_LOG = ROOT / "results" / "trading_toggle.jsonl"
STOP_REAL = ROOT / "results" / "STOP_REAL"
MSK = timezone(timedelta(hours=3))


class LiveControlError(RuntimeError):
    """Нет условий для включения реальной торговли."""


def _audit(action: str, detail: str) -> None:
    """Append-only журнал вкл/выкл: кто/когда/результат."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(MSK).isoformat(timespec="seconds"),
           "action": action, "detail": detail}
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def audit(limit: int = 50) -> list[dict]:
    if not AUDIT_LOG.exists():
        return []
    rows: list[dict] = []
    for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[-max(1, min(limit, 200)):][::-1]


def _live_ids(store: RobotStore) -> list[str]:
    return [str(i["id"]) for i in store.list_instances(mode="live", status="active")]


def live_account_ids(store: RobotStore) -> set[str]:
    """Включённые реальные счета, которые одни могут дать заявку."""
    return {str(a["id"]) for a in store.list_accounts()
            if str(a.get("mode") or "LIVE").upper() == "LIVE"
            and a.get("enabled", 1)}


def check_live_accounts(store: RobotStore) -> None:
    """Все активные боевые роботы обязаны быть на включённом счёте LIVE."""
    ids = live_account_ids(store)
    for inst in store.list_instances(mode="live", status="active"):
        if str(inst.get("account") or "") not in ids:
            raise LiveControlError(
                f"робот {inst['id']}: нужен включённый реальный счёт LIVE, "
                f"сейчас {inst.get('account')!r}")


def _jobs(store: RobotStore) -> list[dict]:
    ids = set(_live_ids(store))
    return [j for j in store.list_jobs()
            if j.get("owner") in ids and str(j.get("id", "")).startswith("inst:")]


def status(store: RobotStore | None = None) -> dict:
    st = store or RobotStore()
    jobs = _jobs(st)
    enabled = [j for j in jobs if j.get("enabled")]
    times = sorted({str(t) for j in enabled for t in (j.get("times") or [])})
    return {
        # старые поля сохранены: панель и API читают их без миграции
        "timer_installed": bool(jobs),
        "enabled": bool(enabled),
        "next_run": times[0] if times else None,
        "stop_real": STOP_REAL.exists(),
        "mode": "robots",
        "scheduled": len(jobs),
        "live_robots": len(_live_ids(st)),
    }


def enable(store: RobotStore) -> dict:
    live = _live_ids(store)
    if not live:
        raise LiveControlError("нет активных живых роботов — включать нечего")
    check_live_accounts(store)
    if not store.list_accounts():
        raise LiveControlError("нет счетов — включать нечего")
    if STOP_REAL.exists():
        raise LiveControlError("установлен STOP_REAL — снимите перед включением")
    jobs = _jobs(store)
    if not jobs:
        raise LiveControlError("у активных живых роботов нет заданий inst:schedule")
    for job in jobs:
        if not job.get("enabled"):
            store.upsert_job({**job, "enabled": True})
    result = status(store)
    _audit("enable", f"живых роботов: {len(live)}; заданий: {len(jobs)}; "
                     f"next_run={result.get('next_run')}")
    return result


def disable(store: RobotStore | None = None) -> dict:
    st = store or RobotStore()
    jobs = [j for j in _jobs(st) if j.get("enabled")]
    for job in jobs:
        st.upsert_job({**job, "enabled": False})
    result = status(st)
    _audit("disable", f"снято заданий: {len(jobs)}")
    return result
