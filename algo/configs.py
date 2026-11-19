"""Реестр конфигураций для бумажной торговли.

Правило: конфигурации фиксируются ДО начала теста и не меняются, иначе сравнение
превращается в подгонку. Менять — только создав новый id.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    id: str
    strategy: str          # "prostushka" | "universal"
    params: dict = field(default_factory=dict)
    comment: str = ""
    display: str = ""
    instrument: str = "CNY"    # ключ из algo.instruments.INSTRUMENTS
    capital: float | None = None   # свой счёт; None — ALGO_CAPITAL


CONFIGS: list[Config] = [
    Config("p-base", "prostushka",
           dict(ma_window=200, entry="13:50", filter_bars=3, short_friday=False),
           "как в ТЗ: MA40 M5, 13:50, фильтр 15 мин",
           "Простушка · база"),
    Config("p-fast", "prostushka",
           dict(ma_window=250, entry="13:40", filter_bars=6, short_friday=True),
           "лучшая по сетке: MA50, 13:40, фильтр 30 мин, шорт в пятницу разрешён",
           "Простушка · быстрая"),
    Config("p-h1", "prostushka",
           dict(ma_window=400, entry="13:50", filter_bars=1, short_friday=True, timeframe=60),
           "решение по H1, окно 400 мин",
           "Простушка · H1"),
    Config("p-friday", "prostushka",
           dict(ma_window=200, entry="13:50", filter_bars=3, short_friday=False,
                close_friday=True),
           "как база, но в пятницу позиция закрывается перед выходными (18:45)",
           "Простушка · без выходных"),
    Config("u-base", "universal",
           dict(ref="10:05", entry="13:30", long_off=0.004, short_off=0.002,
                hold="daily", short_friday=False),
           "как в ТЗ: пороги 0.4/0.2%, суточное удержание",
           "Универсалка · база"),
    Config("u-wide", "universal",
           dict(ref="10:05", entry="13:30", long_off=0.001, short_off=0.001,
                hold="daily", short_friday=False),
           "широкие входы: пороги 0.1/0.1%",
           "Универсалка · широкая"),
    Config("u-morning", "universal",
           dict(ref="10:05", entry="13:30", long_off=0.004, short_off=0.002,
                hold="morning", exit="10:20", short_friday=False),
           "выход в 10:20 следующего дня",
           "Универсалка · утро"),
    # --- пул инструментов (19.11.2026): те же правила, другой класс актива ---
    Config("p-rts", "prostushka",
           dict(ma_window=200, entry="13:50", filter_bars=3, short_friday=False),
           "как база, на индексе РТС (RI); диверсификация к CNY",
           "Простушка · РТС", instrument="RTS"),
    Config("p-gold", "prostushka",
           dict(ma_window=200, entry="13:50", filter_bars=3, short_friday=False),
           "как база, на золоте (GD); ноль корреляции к валюте и рынку РФ",
           "Простушка · золото", instrument="GOLD"),
]

BY_ID = {c.id: c for c in CONFIGS}
