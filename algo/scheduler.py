"""Гибкий планировщик заданий для бумаги, боя и обслуживания данных.

Каждое задание — это отдельная запись в `scheduler_jobs`: своё время, свои дни,
свой интервал, свой таймаут, своя команда и своя политика STOP. Задания
загружаются из store на каждом цикле, поэтому новые роботы и их расписания
появляются без перезапуска сервиса.

Важно: пока включён shadow-режим (`ALGO_SCHEDULER_SHADOW=1`), задания только
пишутся в лог и не выполняются. Systemd-таймеры остаются главными — счёт
дней G2/G3 не прерывается.

Устойчивость:
- каждый запуск занимает свой слот в БД (UNIQUE job_id+slot) — нет дублей;
- задания выполняются в пуле потоков — один зависший робот не блокирует остальных;
- при сбое — повторы с задержкой, результат пишется в `scheduler_runs`;
- если сервис был выключен, пропущенные слоты догоняются в окне catch-up
  (только если у задания есть `catchup_template` с правильной датой реплея);
- перед каждым заданием проверяются STOP-флаги.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .robot_store import RobotStore

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "results" / "scheduler_state.json"
LOG = ROOT / "results" / "scheduler.log"
LOCK = ROOT / "results" / "scheduler.lock"
STOP = ROOT / "results" / "STOP"
STOP_REAL = ROOT / "results" / "STOP_REAL"
MSK = timezone(timedelta(hours=3))

MAX_WORKERS = 4
CATCHUP_MINUTES = 360
MAX_SLOTS_PER_JOB = 12
RETRIES = (0, 60, 300)


@dataclass(frozen=True)
class Job:
    id: str
    command: str
    owner: str = "system"
    times: tuple[str, ...] = ()
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    interval_min: int | None = None
    hours: tuple[int, int] | None = None
    enabled: bool = True
    timeout: int = 1800
    stop_aware: bool = True
    catchup_template: str = ""
    note: str = ""

    @property
    def name(self) -> str:
        """Прежнее имя поля — оставлено для совместимости тестов и API."""
        return self.id


Task = Job  # обратная совместимость с прежними тестами


def _job(id: str, command: str, **kwargs) -> Job:
    return Job(id=id, command=command, **kwargs)


DEFAULT_JOBS = (
    _job("morning", "./run.sh paper-live", times=("10:25",)),
    _job("daily", "./run.sh paper-live; ./run.sh update; ./run.sh report",
         times=("13:55",)),
    _job("shadow", ".venv/bin/python scripts/33_shadow_live.py", times=("13:57",)),
    _job("friday", "./run.sh paper-live; ./run.sh update; ./run.sh report",
         times=("18:45",), weekdays=(4,)),
    _job("update_live", ".venv/bin/python scripts/10b_append_finam.py",
         interval_min=10, weekdays=(0, 1, 2, 3, 4, 5, 6)),
    _job("channel", ".venv/bin/python scripts/31_paper_live.py --channel",
         interval_min=10, hours=(9, 23)),
)
TASKS = DEFAULT_JOBS


def shadow() -> bool:
    return os.environ.get("ALGO_SCHEDULER_SHADOW", "1") != "0"


def robots_only() -> bool:
    """Включить только задания роботов (owner `inst:`), системные оставить в shadow."""
    return os.environ.get("ALGO_SCHEDULER_ONLY_ROBOTS", "0") == "1"


def is_real(job: Job) -> bool:
    return not shadow() and (not robots_only() or str(job.id).startswith("inst:"))


def _slots_for(job: Job, now: datetime,
               lookback=CATCHUP_MINUTES) -> list[datetime]:
    """Все слоты задания в окне [now-lookback, now], включая текущий."""
    out: list[datetime] = []
    first = now - timedelta(minutes=lookback)
    if job.interval_min:
        cursor = first.replace(second=0, microsecond=0)
        cursor -= timedelta(minutes=cursor.minute % job.interval_min)
        while cursor <= now:
            if (cursor.weekday() in job.weekdays
                    and (not job.hours or job.hours[0] <= cursor.hour <= job.hours[1])):
                out.append(cursor)
            cursor += timedelta(minutes=job.interval_min)
    else:
        for day_offset in (0, 1):
            day = (now - timedelta(days=day_offset)).date()
            if day.weekday() not in job.weekdays:
                continue
            for value in job.times:
                hour, minute = (int(x) for x in value.split(":"))
                slot = datetime(day.year, day.month, day.day, hour, minute,
                                tzinfo=now.tzinfo)
                if first <= slot <= now:
                    out.append(slot)
    return sorted(set(out))[-MAX_SLOTS_PER_JOB:]


def due(job: Job, now: datetime, last: dict[str, str]) -> bool:
    """Есть ли у задания слот сейчас и не выполнялся ли он уже в нём."""
    slots = _slots_for(job, now, lookback=0)
    if not slots:
        return False
    minute = now.replace(second=0, microsecond=0)
    if job.interval_min and minute.minute % job.interval_min != 0:
        return False
    if not any(s == minute for s in slots):
        return False
    slot = minute.strftime("%Y-%m-%d %H:%M")
    return last.get(job.id) != slot and job.enabled


def _store() -> RobotStore:
    return RobotStore()


def load_jobs(store: RobotStore | None = None) -> list[Job]:
    """Задания из store; если БД пуста — встроенные (для первых запусков)."""
    st = store or _store()
    try:
        rows = st.list_jobs(enabled_only=True)
    except Exception:  # noqa: BLE001 — нет таблиц → работаем по встроенным
        rows = []
    if rows:
        return [Job(
            id=r["id"], command=r["command"], owner=r["owner"],
            times=tuple(r["times"]), weekdays=tuple(r["weekdays"]),
            interval_min=r["interval_min"],
            hours=(r["hours_from"], r["hours_to"])
            if r["hours_from"] is not None and r["hours_to"] is not None else None,
            enabled=r["enabled"], timeout=r["timeout"],
            stop_aware=r["stop_aware"], catchup_template=r["catchup_template"],
            note=r.get("note", ""),
        ) for r in rows]
    return list(DEFAULT_JOBS)


def seed_default_jobs(store: RobotStore | None = None) -> int:
    st = store or _store()
    st.init_db()
    have = {j["id"] for j in st.list_jobs()}
    added = 0
    for job in DEFAULT_JOBS:
        if job.id in have:
            continue
        st.upsert_job({
            "id": job.id, "owner": job.owner, "command": job.command,
            "times": list(job.times), "weekdays": list(job.weekdays),
            "interval_min": job.interval_min,
            "hours_from": job.hours[0] if job.hours else None,
            "hours_to": job.hours[1] if job.hours else None,
            "timeout": job.timeout, "stop_aware": int(job.stop_aware),
            "note": "встроенное расписание",
        })
        added += 1
    return added


def instance_jobs(store: RobotStore | None = None) -> list[Job]:
    """Расписания активных инстансов. У робота может быть свой вход/выход.

    Системные задания остаются общими: они гарантируют, что ни один день не
    будет пропущен даже если персональное задание не сработало. Per-instance
    задания добавляют к ним точные времена этого робота.
    """
    from .instance_configs import active_configs

    st = store or _store()
    out: list[Job] = []
    for cfg in active_configs("paper", st):
        params = cfg.params
        if cfg.strategy == "channel_break":
            out.append(Job(
                id=f"inst:{cfg.id}:channel", owner=cfg.id,
                command=f"./run.sh paper-live --channel --config {cfg.id}",
                interval_min=10, hours=(9, 23),
                note="внутридневной пробой канала"))
        entry = params.get("entry") or params.get("entry_time")
        if isinstance(entry, str) and ":" in entry:
            out.append(Job(
                id=f"inst:{cfg.id}:entry", owner=cfg.id,
                command=f"./run.sh paper-live --config {cfg.id}",
                times=(entry,), catchup_template=(
                    f"./run.sh paper-live --config {cfg.id} "
                    "--date {date} --time {time}"),
                note="своё время входа"))
        if params.get("hold") == "morning" and isinstance(params.get("exit"), str):
            out.append(Job(
                id=f"inst:{cfg.id}:exit", owner=cfg.id,
                command=f"./run.sh paper-live --config {cfg.id}",
                times=(params["exit"],),
                note="утренний выход"))
    return out


def sync_instance_jobs(store: RobotStore | None = None) -> int:
    """Добавить недостающие per-instance задания, не перетирая правки юзера."""
    st = store or _store()
    st.init_db()
    have = {j["id"] for j in st.list_jobs()}
    added = 0
    for job in instance_jobs(st):
        if job.id in have:
            continue
        st.upsert_job({
            "id": job.id, "owner": job.owner, "command": job.command,
            "times": list(job.times), "weekdays": list(job.weekdays),
            "interval_min": job.interval_min,
            "hours_from": job.hours[0] if job.hours else None,
            "hours_to": job.hours[1] if job.hours else None,
            "catchup_template": job.catchup_template, "note": job.note,
        })
        added += 1
    return added


def _log(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(MSK):%Y-%m-%d %H:%M:%S} {line}\n")


def _execute(job: Job, slot: datetime, run_id: int, st: RobotStore) -> None:
    if job.stop_aware and (STOP.exists() or STOP_REAL.exists()):
        _log(f"SKIP {job.id}: STOP")
        st.finish_run(run_id, "skipped", "STOP-флаг")
        return
    command = job.command
    if slot.date() != datetime.now(MSK).date() and job.catchup_template:
        command = job.catchup_template.format(
            date=slot.date().isoformat(), time=slot.strftime("%H:%M"))
    last = ""
    for attempt, delay in enumerate(RETRIES, start=1):
        if delay:
            time.sleep(delay)
        try:
            res = subprocess.run(command, shell=True, cwd=ROOT,
                                 timeout=job.timeout, capture_output=True, text=True)
            last = (res.stdout + res.stderr).strip().splitlines()[-3:]
            if res.returncode == 0:
                st.finish_run(run_id, "ok", " | ".join(last), attempt)
                _log(f"OK {job.id} attempts={attempt}")
                return
            detail = f"exit {res.returncode}: {' | '.join(last)[:250]}"
        except subprocess.TimeoutExpired:
            detail = "timeout"
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}"[:250]
        _log(f"RETRY {job.id} attempt={attempt}: {detail}")
    st.finish_run(run_id, "failed", detail, len(RETRIES))


def run_once(now: datetime | None = None, execute: bool | None = None,
             store: RobotStore | None = None) -> list[str]:
    """Разобрать слоты, занять их в БД и выполнить/залогировать."""
    now = now or datetime.now(MSK)
    st = store or _store()
    real = (not shadow()) if execute is None else execute
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    real_job = lambda job: real and (not robots_only() or str(job.id).startswith("inst:"))
    jobs = load_jobs(st)
    fired: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for job in jobs:
            for slot in _slots_for(job, now):
                stamp = slot.strftime("%Y-%m-%d %H:%M")
                run_id = st.claim_run(job.id, stamp)
                if run_id is None:
                    continue  # уже взято или выполнено
                fired.append(job.id)
                state[job.id] = stamp
                if not real_job(job):
                    _log(f"SHADOW {job.id}: {job.command} (slot {stamp})")
                    st.finish_run(run_id, "shadow", "shadow-режим")
                    continue
                _log(f"RUN {job.id}: {job.command} (slot {stamp})")
                catchup = slot.date() != now.date() or stamp != now.strftime("%Y-%m-%d %H:%M")
                if catchup and not job.catchup_template:
                    _log(f"SKIP {job.id}: пропущенный слот {stamp} без реплея")
                    st.finish_run(run_id, "skipped", "нет catchup_template")
                    continue
                pool.submit(_execute, job, slot, run_id, st)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return fired


def _stale_lock() -> bool:
    """Lock от упавшего процесса не должен блокировать сервис после рестарта."""
    if not LOCK.exists():
        return False
    try:
        pid = int(LOCK.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)  # живой ли процесс
    except (ValueError, ProcessLookupError, OSError):
        return True
    return False


def loop(interval: int = 10) -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if _stale_lock():
        LOCK.unlink(missing_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        _log("уже запущен (scheduler.lock)")
        return
    os.write(fd, str(os.getpid()).encode())
    st = _store()
    seed_default_jobs(st)
    sync_instance_jobs(st)
    _log(f"старт, shadow={shadow()}, jobs={len(load_jobs(st))}")
    try:
        while True:
            try:
                run_once(store=st)
            except Exception as exc:  # noqa: BLE001 — цикл не должен падать
                _log(f"ERROR {type(exc).__name__}: {exc}")
            time.sleep(interval)
    finally:
        os.close(fd)
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    loop()
