"""Простое управление роботом: «Старт» = торгует по расписанию, «Стоп» = нет.

Модуль только оркестрирует уже существующие части и не дублирует их логику:
`RobotStore` (статус и задания), `algo.arm_state` (реальные заявки),
`algo.live_control` (таймер боя). Расписание остаётся пользовательским:
включение задания не меняет времена и дни, заданные в панели.
"""

from __future__ import annotations

from typing import Any

from . import arm_state, live_control
from .robot_store import RobotStore


def start(store: RobotStore, iid: str) -> dict[str, Any]:
    inst = store.get_instance(iid)
    if inst is None:
        raise ValueError(f"нет робота {iid}")
    if inst["status"] != "active":
        inst = store.set_status(iid, "active", "старт торговли из панели")

    jobs = []
    for job in store.list_jobs(owner=iid):
        jobs.append(store.upsert_job({**job, "enabled": True}))

    armed = False
    timer = None
    if inst["mode"] == "live":
        if inst["spec_id"] == "money_market":
            arm_state.set_enabled("mm", True)
            armed = True
        try:
            timer = live_control.enable(store)
        except live_control.LiveControlError as exc:
            timer = {"error": str(exc)}
    return {
        "id": iid, "status": inst["status"], "scheduled": len(jobs),
        "armed_mm": armed, "timer": timer,
    }


def stop(store: RobotStore, iid: str) -> dict[str, Any]:
    inst = store.get_instance(iid)
    if inst is None:
        raise ValueError(f"нет робота {iid}")
    if inst["status"] == "active":
        store.set_status(iid, "paused", "стоп торговли из панели")

    jobs = []
    for job in store.list_jobs(owner=iid):
        jobs.append(store.upsert_job({**job, "enabled": False}))

    if inst["spec_id"] == "money_market":
        arm_state.set_enabled("mm", False)

    # Если живых роботов не осталось — гасим общий таймер, чтобы не было
    # холостых прогонов по пустому белому списку.
    timer = None
    if not store.list_instances(mode="live", status="active"):
        try:
            timer = live_control.disable()
        except live_control.LiveControlError as exc:
            timer = {"error": str(exc)}
    return {
        "id": iid, "status": "paused", "scheduled": len(jobs),
        "armed_mm": False, "timer": timer,
    }
