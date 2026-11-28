"""DTO конфигурации робота.

Реестр конфигов удалён 28.11: источник правды — `RobotStore` (инстансы и версии
параметров). Здесь остаётся только тип `Config`, которым пользуются раннеры и
тесты. Исторические списки для тестов — `tests/fixtures_configs.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    id: str
    strategy: str          # spec_id робота
    params: dict = field(default_factory=dict)
    comment: str = ""
    display: str = ""
    instrument: str = "CNY"    # ключ из algo.instruments.INSTRUMENTS
    capital: float | None = None   # свой счёт; None — ALGO_CAPITAL
    exposure: float | None = None  # свой потолок номинала; None — ALGO_EXPOSURE
