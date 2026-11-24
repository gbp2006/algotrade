"""Мост между store и раннерами: активные инстансы → объекты Config.

Перенос делает старые статические конфиги инстансами с теми же id и параметрами —
бумажный тест не меняется, но роботами можно управлять из панели. Fallback на
статику оставлен только на случай отсутствия БД/ещё не сделанного seed.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .configs import CONFIGS, Config
from .broker.live_guard import parse_pricing
from .instruments import DEFAULT, INSTRUMENTS
from .live_config import AccountSettings, LiveSettings, RobotSettings
from .portfolio import CAPITAL, ledger
from .robot_configs import ROBOT_CONFIGS
from .robot_library import get_spec
from .robot_store import RobotStore

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "results" / "paper.csv"
STATIC = list(CONFIGS) + list(ROBOT_CONFIGS)


def seed_static_configs(store: RobotStore | None = None) -> int:
    """Создать в store недостающие инстансы из статического реестра.

    Идемпотентно: существующие инстансы (в том числе изменённые пользователем)
    не перезаписываются. Архивные остаются архивными.
    """
    st = store or RobotStore()
    st.init_db()
    added = 0
    for cfg in STATIC:
        if st.get_instance(cfg.id) is not None:
            continue
        st.create_instance({
            "id": cfg.id,
            "spec_id": cfg.strategy,
            "instrument": cfg.instrument,
            "params": dict(cfg.params),
            "mode": "paper",
            "status": "active",
            "capital": cfg.capital,
            "exposure": cfg.exposure,
            "note": "перенос из статического реестра",
        }, actor="seed")
        added += 1
    return added


def _display(inst: dict) -> str:
    try:
        return get_spec(inst["spec_id"]).description[:80] or inst["id"]
    except ValueError:
        return inst["id"]


def _to_config(inst: dict) -> Config:
    return Config(
        id=inst["id"],
        strategy=inst["spec_id"],
        params=dict(inst["params"]),
        comment=inst.get("note") or "",
        display=_display(inst),
        instrument=inst["instrument"],
        capital=inst.get("capital"),
        exposure=inst.get("exposure"),
    )


def active_configs(mode: str = "paper",
                   store: RobotStore | None = None) -> list[Config]:
    """Активные инстансы контура. Fallback — статический реестр."""
    st = store or RobotStore()
    try:
        rows = st.list_instances(mode=mode)
    except Exception:  # noqa: BLE001 — нет БД → работаем как раньше
        return list(STATIC) if mode == "paper" else []
    if not rows:
        return list(STATIC) if mode == "paper" else []
    return [_to_config(r) for r in rows if r["status"] == "active"]


def configs_at(day, mode: str = "paper",
               store: RobotStore | None = None) -> list[Config]:
    """Конфиги, действовавшие на дату `day`.

    Параметры берутся из последней версии `param_versions`, созданной не позже
    этой даты; до первой версии инстанса используется статический реестр —
    именно он и работал в бумаге до переноса в store. Без этого отчёт
    «факт/ожидание» пересчитывает весь период по сегодняшним параметрам и
    показывает ложные расхождения после правки робота из панели.
    """
    st = store or RobotStore()
    try:
        rows = st.list_instances(mode=mode)
    except Exception:  # noqa: BLE001 — нет БД → работаем как раньше
        rows = []
    out: list[Config] = []
    for inst in rows:
        if inst.get("status") != "active":
            continue
        versions = []
        try:
            versions = st.param_history(inst["id"])
        except Exception:  # noqa: BLE001 — старыми БД пренебрегаем
            pass
        cutoff = str(day)
        applicable = [v for v in versions
                      if str(v.get("created_at") or "")[:10] <= cutoff]
        if applicable:
            params = json.loads(applicable[-1]["params_json"])
        else:
            static = next((c for c in STATIC if c.id == inst["id"]), None)
            params = dict(static.params) if static else dict(inst["params"])
        out.append(_to_config({**inst, "params": params}))
    if not out and mode == "paper":
        return list(STATIC)
    return out


def migrate_runtime_from_paper(store: RobotStore | None = None,
                               paper: Path = PAPER) -> int:
    """Перенести текущие позиции/equity запущенных роботов из paper.csv в store.

    Возвращает число перенесённых инстансов. Идемпотентно: перезаписывает
    рантайм-состояние по тем же id из актуального журнала.
    """
    st = store or RobotStore()
    st.init_db()
    if not paper.exists():
        return 0
    with paper.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if "config" in r]
    count = 0
    for cfg in active_configs("paper", st):
        mine = [r for r in rows if r.get("config") == cfg.id]
        if not mine:
            continue
        last = mine[-1]
        mult = INSTRUMENTS.get(cfg.instrument, DEFAULT).mult
        capital = float(cfg.capital or CAPITAL)
        st.set_runtime(cfg.id, {
            "symbol": last.get("symbol", ""),
            "position": int(float(last.get("position_after") or 0)),
            "equity": ledger(mine, cfg.id, mult, capital)["equity"],
            "last_price": float(last.get("price") or 0),
            "last_decision": f"{last.get('date','')} {last.get('time','')} "
                             f"{last.get('action','')}",
            "note": "миграция из paper.csv",
        })
        count += 1
    return count


def live_settings_from_store(store: RobotStore | None = None) -> LiveSettings:
    """Настройки боя из активных live-инстансов store.

    Если живых инстансов нет — вызывающий может применить свой fallback
    (например, `live_settings.json`), эта функция его не подменяет.
    """
    st = store or RobotStore()
    st.init_db()
    accounts: dict[str, AccountSettings] = {}
    for row in st.list_accounts():
        accounts[row["id"]] = AccountSettings(
            id=row["id"],
            comment=row.get("label") or row.get("comment") or "",
            max_exposure=float(row["max_exposure"]),
            max_daily_loss_pct=float(row["max_daily_loss_pct"]),
            max_qty=int(row["max_qty"]),
            key_ref=row.get("key_ref") or "{env:FINAM_SECRET}",
            trading_code=row.get("trading_code") or "",
            label=row.get("label") or "",
        )
    robots: dict[str, RobotSettings] = {}
    for row in st.list_instances(mode="live", status="active"):
        acc_id = row.get("account")
        if not acc_id or acc_id not in accounts:
            continue  # без описанного счёта инстанс в бой не попадёт
        acc = accounts[acc_id]
        robots[row["id"]] = RobotSettings(
            config_id=row["id"], account=acc_id,
            pricing=parse_pricing(row.get("pricing") or "marketable"),
            trade_on_expiry=bool(row.get("trade_on_expiry")),
            max_exposure=acc.max_exposure,
            max_daily_loss_pct=acc.max_daily_loss_pct,
            max_qty=acc.max_qty,
            key_ref=row.get("key_ref") or "",
            source_config=row.get("source_config") or "",
            exposure=float(row.get("exposure") or 0),
        )
    return LiveSettings(accounts=accounts, robots=robots)
