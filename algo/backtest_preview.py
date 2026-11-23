"""Быстрый предпросмотр стратегии с новыми параметрами (для панели).

Не для отчётов и не для ворот — только чтобы оператор увидел, не сломал ли он
параметры перед сохранением. Полная проверка — через обычные скрипты бэктеста.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from . import engine, store
from .data import DATA_ROOT, load_txt, to_timeframe
from .instruments import DEFAULT, INSTRUMENTS
from .strategies import channel_break, prostushka, universal
from .strategies.candidates import donchian

ROOT = Path(__file__).resolve().parent.parent

# параметр spec → аргумент функции стратегии
MAPPING: dict[str, dict[str, str]] = {
    "prostushka": {
        "ma_window": "ma_period", "entry": "entry_time",
        "filter_bars": "filter_bars", "short_friday": "allow_short_friday",
    },
    "universal": {
        "ref": "ref_time", "entry": "entry_time",
        "long_off": "long_offset", "short_off": "short_offset",
        "hold": "hold", "exit": "exit_time",
        "short_friday": "allow_short_friday",
    },
    "donchian": {
        "entry": "entry", "exit": "exit_",
        "entry_time": "at", "allow_short": "allow_short",
    },
    "channel_break": {
        "start": "start_time", "switch": "switch_time",
        "mode": "channel_mode", "direction": "direction", "sl": "sl",
        "boundary": "boundary_mode", "tick": "tick",
    },
}
FUNCS = {
    "prostushka": prostushka.targets,
    "universal": universal.targets,
    "donchian": donchian,
    "channel_break": channel_break.targets,
}
FILES = {
    "CNY": DATA_ROOT / "2026-11" / "CNYRUBF.txt",
    "Si": DATA_ROOT / "2026-11" / "Si.txt",
    "RTS": ROOT / "cache" / "iss" / "RTS_2026_M5_cont.txt",
    "GOLD": ROOT / "cache" / "iss" / "GOLD_2026_M5_cont.txt",
    "BR": ROOT / "cache" / "iss" / "BR_2026_M5_cont.txt",
}


def load_m5(instrument: str, days: int = 60) -> pd.DataFrame | None:
    path = FILES.get(instrument)
    if path is None or not path.exists():
        return None
    df = load_txt(path)
    if len(df) > days * 288:  # M5: ~288 баров в сутки
        df = df.iloc[-days * 288:]
    return to_timeframe(df, 5) if str(path).endswith(".txt") and instrument in ("CNY", "Si") else df


def preview(spec_id: str, instrument: str, params: dict[str, Any],
            days: int = 60) -> dict:
    if spec_id not in FUNCS:
        return {"ok": False, "reason": f"нет быстрого предпросмотра для {spec_id}"}
    inst = INSTRUMENTS.get(instrument, DEFAULT)
    df = load_m5(instrument, days)
    if df is None or df.empty:
        return {"ok": False, "reason": f"нет данных M5 для {instrument}"}
    kwargs = {}
    for key, value in (params or {}).items():
        target = MAPPING.get(spec_id, {}).get(key)
        if target:
            kwargs[target] = value
    if spec_id in ("prostushka", "universal"):
        kwargs.setdefault("skip_weekend", True)
    try:
        targets = FUNCS[spec_id](df, **kwargs)
        costs = engine.Costs(tick=inst.tick, slippage_ticks=1.0,
                             multiplier=inst.mult, commission_pct=0.0001)
        stats = engine.run(df, targets, costs).stats
    except Exception as exc:  # noqa: BLE001 — предпросмотр не должен ронять API
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    return {
        "ok": True, "bars": len(df),
        "from": str(df.index[0]), "to": str(df.index[-1]),
        "trades": int(stats.get("trades", 0)),
        "net_profit": round(float(stats.get("net_profit", 0)), 2),
        "profit_factor": round(float(stats.get("profit_factor", 0)), 3),
        "max_drawdown": round(float(stats.get("max_drawdown", 0)), 2),
        "win_rate": round(float(stats.get("win_rate", 0)), 3),
    }
