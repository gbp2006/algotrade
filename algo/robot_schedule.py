"""Гибкое расписание конкретного робота: дни недели, времена, интервал, окно.

Одна запись в `scheduler_jobs` на робота (`inst:<id>:schedule`). Пользователь
включает расписание галкой в карточке робота и редактирует дефолтные значения
в отдельной вкладке. Выключение сохраняет настройки, но убирает задание из
активных (`enabled=0`). Модуль не запускает команды — только готовит задание
для `algo.scheduler`.
"""

from __future__ import annotations

import re
from typing import Any

from .robot_store import RobotStore

WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def job_id(instance_id: str) -> str:
    return f"inst:{instance_id}:schedule"


def _weekdays(params: dict[str, Any]) -> list[int]:
    flags = (("trade_mon", 0), ("trade_tue", 1), ("trade_wed", 2),
             ("trade_thu", 3), ("trade_fri", 4), ("trade_sat", 5),
             ("trade_sun", 6))
    if any(name in params for name, _ in flags):
        return [number for name, number in flags if params.get(name)]
    return [0, 1, 2, 3, 4]


def _times(instance: dict[str, Any], params: dict[str, Any]) -> list[str]:
    spec = str(instance.get("spec_id") or "")
    times: list[str] = []
    if spec == "money_market":
        for key in ("time_buy", "time_sell"):
            value = params.get(key)
            if isinstance(value, str) and TIME_RE.match(value):
                times.append(value)
    else:
        for key in ("entry", "entry_time"):
            value = params.get(key)
            if isinstance(value, str) and TIME_RE.match(value):
                times.append(value)
                break
        if params.get("hold") == "morning":
            value = params.get("exit")
            if isinstance(value, str) and TIME_RE.match(value):
                times.append(value)
    return list(dict.fromkeys(times))


def default_schedule(instance: dict[str, Any]) -> dict[str, Any]:
    """Дефолтное расписание, которое пользователь может отредактировать."""
    params = dict(instance.get("params") or {})
    iid = str(instance.get("id") or "")
    spec = str(instance.get("spec_id") or "")
    mode = str(instance.get("mode") or "paper")
    if spec == "channel_break":
        command = f"./run.sh paper-live --channel --config {iid}"
        interval, hours_from, hours_to = 10, 9, 23
    elif spec == "money_market":
        # Специальный робот: ребаланс фонда через API панели (там же ARM/лимиты).
        command = ".venv/bin/python scripts/36_mm_rebalance.py --instance " + iid
        interval, hours_from, hours_to = None, None, None
    elif mode == "live":
        command = "./run.sh live-run"
        interval, hours_from, hours_to = None, None, None
    else:
        command = f"./run.sh paper-live --config {iid}"
        interval, hours_from, hours_to = None, None, None
    return {
        "id": job_id(iid),
        "owner": iid,
        "enabled": False,
        "times": _times(instance, params),
        "weekdays": _weekdays(params),
        "interval_min": interval,
        "hours_from": hours_from,
        "hours_to": hours_to,
        "timeout": 1800,
        "stop_aware": True,
        "catchup_template": "",
        "command": command,
        "note": f"расписание робота {iid}",
    }


def normalize(payload: dict[str, Any]) -> dict[str, Any]:
    """Проверить и привести пользовательские значения к полям scheduler_jobs."""
    out: dict[str, Any] = {}
    times = payload.get("times", [])
    if isinstance(times, str):
        times = [part.strip() for part in times.split(",") if part.strip()]
    if not isinstance(times, list):
        raise ValueError("времена должны быть списком HH:MM")
    clean_times: list[str] = []
    for value in times:
        text = str(value).strip()
        if not TIME_RE.match(text):
            raise ValueError(f"неверное время {text!r} — нужно HH:MM")
        clean_times.append(text)
    out["times"] = list(dict.fromkeys(clean_times))

    weekdays = payload.get("weekdays", [0, 1, 2, 3, 4])
    if isinstance(weekdays, str):
        weekdays = [int(x) for x in weekdays.split(",") if x.strip()]
    clean_days: list[int] = []
    for value in weekdays:
        day = int(value)
        if day < 0 or day > 6:
            raise ValueError("день недели должен быть от 0 (Пн) до 6 (Вс)")
        if day not in clean_days:
            clean_days.append(day)
    out["weekdays"] = sorted(clean_days)
    if not out["times"] and not out["weekdays"]:
        raise ValueError("нужно хотя бы одно время или день недели")

    for key in ("interval_min", "hours_from", "hours_to", "timeout"):
        raw = payload.get(key)
        out[key] = None if raw in (None, "") else int(raw)
    out["enabled"] = bool(payload.get("enabled"))
    out["stop_aware"] = bool(payload.get("stop_aware", True))
    out["command"] = str(payload.get("command") or "").strip()
    if not out["command"]:
        raise ValueError("укажите команду задания")
    out["catchup_template"] = str(payload.get("catchup_template") or "")
    out["note"] = str(payload.get("note") or "")
    return out


def read_schedule(store: RobotStore, instance: dict[str, Any]) -> dict[str, Any]:
    """Сохранённое задание или дефолт, если галка ещё не включалась."""
    base = default_schedule(instance)
    rows = store.list_jobs(owner=str(instance.get("id") or ""))
    saved = next((r for r in rows if r["id"] == base["id"]), None)
    if saved is None:
        return base
    return {**base, **{k: v for k, v in saved.items() if k in base},
            "enabled": bool(saved.get("enabled"))}


def save_schedule(store: RobotStore, instance: dict[str, Any],
                  payload: dict[str, Any]) -> dict[str, Any]:
    values = normalize(payload)
    base = default_schedule(instance)
    row = {**base, **values}
    row["id"] = base["id"]
    row["owner"] = base["owner"]
    store.upsert_job(row)
    return read_schedule(store, instance)


def all_schedules(store: RobotStore) -> dict[str, dict[str, Any]]:
    """Состояние галок для таблицы роботов: один запрос на всех."""
    out: dict[str, dict[str, Any]] = {}
    for instance in store.list_instances():
        schedule = read_schedule(store, instance)
        out[str(instance["id"])] = {
            "enabled": schedule["enabled"],
            "times": schedule["times"], "weekdays": schedule["weekdays"],
        }
    return out
