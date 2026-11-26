"""Разрешения на реальную отправку заявок (фонд и закрытие позиций).

Хранятся в `results/arm_state.json`, переменные окружения `ALGO_*_ARMED`
остаются fallback. По умолчанию всё в dry-run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARM_STATE = ROOT / "results" / "arm_state.json"
ARM_ENV = {"mm": "ALGO_MM_ARMED", "close": "ALGO_CLOSE_ARMED"}


def state() -> dict:
    try:
        saved = json.loads(ARM_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    return {
        **{kind: bool(saved.get(kind)) for kind in ARM_ENV},
        **{f"{kind}_env": os.environ.get(name) == "1"
           for kind, name in ARM_ENV.items()},
    }


def enabled(kind: str) -> bool:
    current = state()
    return bool(current.get(kind)) or bool(current.get(f"{kind}_env"))


def set_enabled(kind: str, value: bool) -> dict:
    if kind not in ARM_ENV:
        raise ValueError("kind: mm | close")
    current = state()
    current[kind] = bool(value)
    ARM_STATE.parent.mkdir(parents=True, exist_ok=True)
    ARM_STATE.write_text(json.dumps({k: current[k] for k in ARM_ENV},
                                    ensure_ascii=False), encoding="utf-8")
    return state()
