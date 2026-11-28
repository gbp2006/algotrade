"""Мост между store и раннерами: активные инстансы → объекты Config.

Источник правды — `RobotStore`: инстансы, версии параметров и runtime. При
отсутствии БД или пустом контуре `active_configs()` возвращает пустой список:
торговать по встроенным конфигам нельзя (ADR 28.11). Статические реестры
удалены; `configs_at()` берёт параметры только из `param_versions`.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .configs import Config
from .broker.live_guard import parse_pricing
from .instruments import DEFAULT, INSTRUMENTS
from .live_config import AccountSettings, LiveSettings, RobotSettings
from .portfolio import CAPITAL, ledger
from .robot_library import get_spec
from .robot_store import RobotStore

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "results" / "paper.csv"
MSK = timezone(timedelta(hours=3))


def _msk_naive(value: str) -> str:
    """Привести метку времени к naive МСК для сравнения с paper.csv.

    Старые записи — naive локальное время хоста (в песочнице это МСК), новые
    могут прийти с явным UTC/Z. Без нормализации версия из UTC применялась
    бы к решению на 3 часа раньше реального времени.
    """
    s = str(value or "")
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone(MSK).replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        pass
    return s


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
    """Активные инстансы контура из store; пустая/недоступная БД — пустой список.

    Раньше при отсутствии инстансов early runtime молча брал встроенные
    конфиги 2025 года. Теперь нет роботов — нет и решений (ADR 28.11).
    """
    st = store or RobotStore()
    try:
        rows = st.list_instances(mode=mode)
    except Exception:  # noqa: BLE001 — нет БД → контур без роботов
        return []
    return [_to_config(r) for r in rows if r["status"] == "active"]


def all_configs(store: RobotStore | None = None) -> list[Config]:
    """Все инстансы store в виде Config — для legacy API и отчётов."""
    st = store or RobotStore()
    try:
        return [_to_config(r) for r in st.list_instances()]
    except Exception:  # noqa: BLE001 — нет БД → нет конфигураций
        return []


def configs_at(day, mode: str = "paper", store: RobotStore | None = None,
               at: str = "") -> list[Config]:
    """Конфиги, действовавшие на дату `day` (опционально — до времени `at`).

    Параметры берутся из последней версии `param_versions`, созданной не позже
    этой даты; до первой версии — из текущих параметров инстанса. Без версий
    отчёт пересчитывал бы весь период по сегодняшним параметрам и показывал
    ложные расхождения после правки робота из панели.
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
        cutoff = _msk_naive(f"{day}T{at}" if at else f"{day}T23:59:59")
        applicable = [v for v in versions
                      if _msk_naive(str(v.get("created_at") or "")) <= cutoff]
        if applicable:
            params = json.loads(applicable[-1]["params_json"])
        else:
            params = dict(inst["params"])
        out.append(_to_config({**inst, "params": params}))
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

    Если живых инстансов нет — возвращаются пустые настройки: раннер не
    отправляет заявки. Файлового fallback больше нет (ADR 28.11).
    """
    st = store or RobotStore()
    st.init_db()
    accounts: dict[str, AccountSettings] = {}
    for row in st.list_accounts():
        if not row.get("enabled", True):
            continue
        # Виртуальный счёт TEST не должен попасть в боевой whitelist даже если
        # робот когда-то был переведён в live с paper-<id> (ADR 27.11).
        if str(row.get("mode") or "LIVE").upper() != "LIVE":
            continue
        accounts[row["id"]] = AccountSettings(
            id=row["id"],
            comment=row.get("label") or row.get("comment") or "",
            max_exposure=float(row["max_exposure"]),
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
            max_qty=acc.max_qty,
            key_ref=row.get("key_ref") or "",
            source_config=row.get("source_config") or "",
            exposure=float(row.get("exposure") or 0),
        )
    return LiveSettings(accounts=accounts, robots=robots)
