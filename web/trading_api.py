"""Управление реальной торговлей из панели.

Включает/выключает таймер боевого раннера (`live_control`), а не меняет `.env`.
При включении проверяются активные live-роботы, счета и STOP_REAL.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from algo import live_control

router = APIRouter(prefix="/api/trading", tags=["trading"])


@router.get("/status")
def status():
    return live_control.status()


@router.get("/audit")
def audit(limit: int = 50):
    return {"items": live_control.audit(limit)}


@router.post("/toggle")
def toggle(payload: dict):
    wanted = bool(payload.get("enabled"))
    try:
        if wanted:
            return live_control.enable(_store())
        return live_control.disable()
    except live_control.LiveControlError as exc:
        raise HTTPException(400, str(exc))


def _store():
    from web.instances_api import get_store
    return get_store()
