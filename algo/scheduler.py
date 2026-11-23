"""Внутренний планировщик задач (замена systemd-таймеров).

Первый режим — shadow: задачи НЕ выполняются, только пишутся в
`results/scheduler.log`. Systemd-таймеры продолжают вести счёт дней G2.
Переключение на реальный режим — `ALGO_SCHEDULER_SHADOW=0` отдельным решением
после проверки лога; до этого таймеры не отключаются.

Расписание повторяет `docs/live-gates.md` и текущие systemd-юниты 1:1.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "results" / "scheduler_state.json"
LOG = ROOT / "results" / "scheduler.log"
LOCK = ROOT / "results" / "scheduler.lock"
MSK = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class Task:
    name: str
    command: str
    weekdays_only: bool = True
    minute_multiple: int | None = None
    at: tuple[int, int] | None = None
    hours: tuple[int, int] | None = None
    timeout: int = 1800


TASKS = (
    Task("morning", "./run.sh paper-live", at=(10, 25)),
    Task("daily", "./run.sh paper-live; ./run.sh update; ./run.sh report", at=(13, 55)),
    Task("shadow", ".venv/bin/python scripts/33_shadow_live.py", at=(13, 57)),
    Task("friday", "./run.sh paper-live; ./run.sh update; ./run.sh report",
         at=(18, 45)),
    Task("update_live", ".venv/bin/python scripts/10b_append_finam.py",
         minute_multiple=10, weekdays_only=False),
    Task("channel", ".venv/bin/python scripts/31_paper_live.py --channel",
         minute_multiple=10, hours=(9, 23)),
)


def shadow() -> bool:
    return os.environ.get("ALGO_SCHEDULER_SHADOW", "1") != "0"


def due(task: Task, now: datetime, last: dict[str, str]) -> bool:
    """Идемпотентно: одна задача не запускается дважды в одну минуту."""
    stamp = now.strftime("%Y-%m-%d %H:%M")
    if last.get(task.name) == stamp:
        return False
    if task.weekdays_only and now.weekday() >= 5:
        return False
    if task.hours and not (task.hours[0] <= now.hour <= task.hours[1]):
        return False
    if task.at:
        return (now.hour, now.minute) == task.at
    if task.minute_multiple:
        return now.minute % task.minute_multiple == 0
    return False


def _log(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(MSK):%Y-%m-%d %H:%M:%S} {line}\n")


def _run(command: str, timeout: int) -> None:
    _log(f"RUN {command}")
    try:
        result = subprocess.run(command, shell=True, cwd=ROOT, timeout=timeout,
                                capture_output=True, text=True)
        tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
        _log(f"EXIT {result.returncode} {' | '.join(tail)[:300]}")
    except subprocess.TimeoutExpired:
        _log(f"TIMEOUT {command}")


def run_once(now: datetime | None = None, execute: bool | None = None) -> list[str]:
    """Проверить расписание и (в реальном режиме) выполнить нашедшиеся задачи."""
    now = now or datetime.now(MSK)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    fired: list[str] = []
    real = (not shadow()) if execute is None else execute
    for task in TASKS:
        if not due(task, now, state):
            continue
        fired.append(task.name)
        state[task.name] = now.strftime("%Y-%m-%d %H:%M")
        if real:
            _run(task.command, task.timeout)
        else:
            _log(f"SHADOW {task.name}: {task.command}")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return fired


def loop(interval: int = 10) -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        _log("уже запущен (scheduler.lock)")
        return
    os.write(fd, str(os.getpid()).encode())
    _log(f"старт, shadow={shadow()}")
    try:
        while True:
            try:
                run_once()
            except Exception as exc:  # noqa: BLE001 — планировщик не должен падать
                _log(f"ERROR {type(exc).__name__}: {exc}")
            time.sleep(interval)
    finally:
        os.close(fd)
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    loop()
