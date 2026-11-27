"""Сигнал боевого контура считается по свежим барам, а не читается из paper.csv.

Данные: Finam M5 (+ дневные бары) → `market.db`, оттуда же их читает панель.
Решение: те же функции `algo.live.decision` / `algo.channel_live.channel_decision`,
что и в бумажном контуре, но параметры берутся из карточки самого робота.
Каждое решение пишется в персональный журнал `RobotStore.robot_decisions`.
Размер позиции по-прежнему считает боевой раннер от equity реального счёта.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import store as market
from .channel_live import channel_decision
from .configs import Config
from .instruments import DEFAULT, INSTRUMENTS
from .live import decision
from .live_config import LiveSettings
from .robot_library import get_spec
from .robot_store import RobotStore
from .rollover_integration import front_symbol

MSK = dt.timezone(dt.timedelta(hours=3))


def _config(iid: str, inst: dict[str, Any]) -> Config:
    spec_id = str(inst.get("spec_id") or "")
    strategy = get_spec(spec_id).strategy if spec_id else ""
    return Config(
        id=iid,
        strategy=strategy,
        params=dict(inst.get("params") or {}),
        instrument=str(inst.get("instrument") or "CNY"),
        exposure=inst.get("exposure"),
        capital=inst.get("capital"),
    )


def _bars(broker: Any, symbol: str, day: dt.date) -> Any:
    """Свежие M5 и дневные бары; всё укладывается в market.db для графика."""
    start = (dt.datetime.combine(day, dt.time.min, MSK) - dt.timedelta(days=10)
             ).strftime("%Y-%m-%dT00:00:00Z")
    end = (dt.datetime.combine(day, dt.time.min, MSK) + dt.timedelta(days=1)
           ).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    m5 = broker.bars(symbol, "TIME_FRAME_M5", start, end)
    if m5 is None or m5.empty:
        return None
    market.init_db()
    market.upsert(m5, symbol, "M5", "finam_live")
    try:
        daily = broker.bars(symbol, "TIME_FRAME_D", start, end)
        if daily is not None and not daily.empty:
            market.upsert(daily, symbol, "D1", "finam_live")
    except Exception:  # noqa: BLE001 — дневные бары нужны только для графика
        pass
    return m5


def collect(store: RobotStore, settings: LiveSettings, day: dt.date,
            broker: Any) -> tuple[dict, list[str], list[dict]]:
    """Планы по (счёт, ключ) + заметки + записанные решения роботов."""
    plans: dict[tuple[str, str], dict[str, dict]] = {}
    notes: list[str] = []
    recorded: list[dict] = []
    for iid, rs in settings.robots.items():
        inst = store.get_instance(iid) or {}
        cfg = _config(iid, inst)
        instrument = INSTRUMENTS.get(cfg.instrument, DEFAULT)
        try:
            symbol = front_symbol(instrument, day)
        except Exception as exc:  # noqa: BLE001 — без символа робот пропускается
            notes.append(f"{iid}: нет символа ({type(exc).__name__})")
            continue
        m5 = _bars(broker, symbol, day)
        if m5 is None:
            notes.append(f"{iid}: нет баров по {symbol}")
            continue

        dec = None
        if cfg.strategy == "channel_break":
            runtime = store.get_runtime(iid) or {}
            dec = channel_decision(cfg.params, m5,
                                   int(runtime.get("position") or 0),
                                   float(runtime.get("last_price") or 0.0))
        elif cfg.strategy in ("prostushka", "universal", "donchian"):
            dec = decision(cfg, m5, day)
        if dec is None:
            notes.append(f"{iid}: решения на {day} ещё нет")
            continue

        when = dec.ts.strftime("%H:%M")
        row = {"instance_id": iid, "day": str(day), "ts": when,
               "symbol": symbol, "signal": int(dec.target),
               "price": float(dec.price), "detail": dec.detail}
        if store.add_decision(iid, day, when, symbol, dec.target,
                              dec.price, dec.detail):
            recorded.append(row)

        plan = plans.setdefault((rs.account, rs.key_ref), {}).setdefault(symbol, {
            "target": 0, "price": float(dec.price), "robots": [],
            "pricings": set(), "expiry": True, "exposures": [], "when": when,
        })
        plan["target"] += int(dec.target)
        plan["robots"].append(iid)
        plan["pricings"].add(rs.pricing.value if hasattr(rs.pricing, "value") else str(rs.pricing))
        plan["exposures"].append(float(cfg.exposure or rs.exposure or 1.0))
    return plans, notes, recorded
