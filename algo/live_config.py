"""Настройки боевого контура: счета, роботы, режимы цены, лимиты.

Файл `live_settings.json` живёт на WSL и в git не попадает. В репозитории —
только `live_settings.example.json`. Если файла нет, раннер не отправляет
ничего: белый список роботов пуст.

Структура описана в `docs/live-design.md`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .broker.execution import ExecutionError
from .broker.live_guard import PricingMode, parse_pricing


def _pricing(value, name):
    try:
        return parse_pricing(value, name)
    except ExecutionError as exc:
        raise SettingsError(str(exc)) from exc

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "live_settings.json"


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class AccountSettings:
    id: str
    comment: str = ""
    max_exposure: float = 1.0
    max_qty: int = 100
    key_ref: str = "{env:FINAM_SECRET}"  # ссылка на ключ, не сам секрет
    trading_code: str = ""              # торговый код Финама (не секрет)
    label: str = ""                     # номер счёта в интерфейсе Финама
    # Лот считается по правилу Силаева: equity × экспозиция / (цена × множитель).
    # Экспозиция берётся из конфигов (2.0 база, 0.6 RTS, 0.7 золото) и режется
    # по волатильности в risk.py; здесь только потолок номинала на счёт.


@dataclass(frozen=True)
class RobotSettings:
    config_id: str
    account: str
    pricing: PricingMode
    trade_on_expiry: bool
    max_exposure: float
    max_qty: int
    key_ref: str = ""          # свой ключ; пустой → ключ счёта
    source_config: str = ""    # id бумажного конфига, решения которого повторяем
    exposure: float = 0.0      # экспозиция инстанса (0 → из конфига/счёта)


@dataclass(frozen=True)
class LiveSettings:
    accounts: dict[str, AccountSettings] = field(default_factory=dict)
    robots: dict[str, RobotSettings] = field(default_factory=dict)
    max_quote_age_sec: int = 60

    @property
    def empty(self) -> bool:
        return not self.robots


def _number(value: Any, name: str, lo: float, hi: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{name}: ожидалось число, получено {value!r}") from exc
    if not lo <= out <= hi:
        raise SettingsError(f"{name}: {out} вне диапазона [{lo}, {hi}]")
    return out


def _flag(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if str(value).lower() in ("1", "true", "yes", "on"):
        return True
    if str(value).lower() in ("0", "false", "no", "off"):
        return False
    raise SettingsError(f"{name}: ожидался флаг, получено {value!r}")


def parse_settings(data: dict[str, Any]) -> LiveSettings:
    """Проверить конфиг и вернуть настройки. Любая ошибка = отказ без заявок."""
    if not isinstance(data, dict):
        raise SettingsError("ожидался JSON-объект")
    defaults = data.get("defaults") or {}
    d_pricing = _pricing(defaults.get("pricing", "marketable"), "defaults.pricing")
    d_expiry = _flag(defaults.get("trade_on_expiry", False), "defaults.trade_on_expiry")
    d_exposure = _number(defaults.get("max_exposure", 1.0), "defaults.max_exposure", 0.01, 2.0)
    d_qty = int(_number(defaults.get("max_qty", 100), "defaults.max_qty", 1, 10000))
    age = int(_number(data.get("max_quote_age_sec", 60), "max_quote_age_sec", 1, 3600))

    accounts: dict[str, AccountSettings] = {}
    for acc_id, raw in (data.get("accounts") or {}).items():
        if not isinstance(raw, dict):
            raise SettingsError(f"accounts.{acc_id}: ожидался объект")
        accounts[str(acc_id)] = AccountSettings(
            id=str(acc_id),
            comment=str(raw.get("comment", "")),
            max_exposure=_number(raw.get("max_exposure", d_exposure),
                                 f"accounts.{acc_id}.max_exposure", 0.01, 2.0),
            max_qty=int(_number(raw.get("max_qty", d_qty),
                                f"accounts.{acc_id}.max_qty", 1, 10000)),
            key_ref=str(raw.get("key_ref") or "{env:FINAM_SECRET}").strip(),
            trading_code=str(raw.get("trading_code", "")).strip(),
            label=str(raw.get("label", "")).strip(),
        )

    robots: dict[str, RobotSettings] = {}
    for cfg_id, raw in (data.get("robots") or {}).items():
        if not isinstance(raw, dict):
            raise SettingsError(f"robots.{cfg_id}: ожидался объект")
        acc_id = str(raw.get("account", ""))
        if acc_id not in accounts:
            raise SettingsError(f"robots.{cfg_id}: счёт {acc_id!r} не описан в accounts")
        acc = accounts[acc_id]
        robots[str(cfg_id)] = RobotSettings(
            config_id=str(cfg_id),
            account=acc_id,
            # d_pricing уже разобран в PricingMode — повторный _pricing() от
            # enum давал "pricingmode.marketable" и падал без явного pricing.
            pricing=_pricing(raw["pricing"], f"robots.{cfg_id}.pricing")
            if "pricing" in raw else d_pricing,
            trade_on_expiry=_flag(raw.get("trade_on_expiry", d_expiry),
                                  f"robots.{cfg_id}.trade_on_expiry"),
            max_exposure=acc.max_exposure,
            max_qty=acc.max_qty,
            key_ref=str(raw.get("key_ref", "")).strip(),
            source_config=str(raw.get("source_config", "")).strip(),
            exposure=float(raw.get("exposure", 0) or 0),
        )
    return LiveSettings(accounts=accounts, robots=robots, max_quote_age_sec=age)


def load_settings(path: Path = SETTINGS_PATH) -> LiveSettings:
    """Отсутствующий файл = пустой белый список = ноль заявок."""
    if not path.exists():
        return LiveSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsError(f"не удалось прочитать {path}: {exc}") from exc
    return parse_settings(data)
