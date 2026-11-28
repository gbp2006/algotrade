"""Фикстуры конфигураций для тестов (бывшие static CONFIGS/ROBOT_CONFIGS).

Рабочий контур берёт конфиги только из RobotStore; эти объекты нужны лишь
тестам движка и раннеров. ./run.sh test
"""

from __future__ import annotations

from algo.configs import Config  # noqa: E402

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
    # DD номинала: RTS 50.6%, золото 43.5% (reports/prostushka-multi-instrument.md).
    # Потолок экспозиции = 30% бюджета просадки / DD инструмента, счёт подобран так,
    # чтобы минимальный лот не выходил за потолок: RTS 1 контракт = 59%, золото 69%.
    Config("p-rts", "prostushka",
           dict(ma_window=200, entry="13:50", filter_bars=3, short_friday=False),
           "как база, на индексе РТС (RI); диверсификация к CNY",
           "Простушка · РТС", instrument="RTS", capital=260_000, exposure=0.60),
    Config("p-gold", "prostushka",
           dict(ma_window=200, entry="13:50", filter_bars=3, short_friday=False),
           "как база, на золоте (GD); ноль корреляции к валюте и рынку РФ",
           "Простушка · золото", instrument="GOLD", capital=450_000, exposure=0.70),
]

ROBOT_FIXTURES: list[Config] = [
    Config(
        "p-ma50", "prostushka",
        dict(ma_window=250, entry="13:50", filter_bars=3,
             short_friday=False),
        "MA50 M5, вход 13:50: плато на CNY и Si (OOS PF 1.60–1.70 / 1.57–1.65) "
        "",
        "Простушка · MA50 риск",
    ),
    Config(
        "p-fast2", "prostushka",
        dict(ma_window=250, entry="13:40", filter_bars=3,
             short_friday=True),
        "MA50 M5, вход 13:40: бэктест-контроль (CNY OOS PF 1.62, Si 1.68) "
        "",
        "Простушка · быстрая риск",
    ),
    Config(
        "u-1340", "universal",
        dict(ref="10:05", entry="13:40", long_off=0.004, short_off=0.002,
             hold="daily", short_friday=False),
        "вход 13:40: CNY train PF 1.81 / OOS 2.15 против 1.73/1.83 у u-base; "
        "Si 2009–25 лучше, 2026 хуже",
        "Универсалка · 13:40 риск",
    ),
    Config(
        "p-train", "prostushka",
        dict(ma_window=250, entry="13:40", filter_bars=1,
             short_friday=False),
        "КОНТРОЛЬ ПОДГОНКИ: лучший по train 2023–25 PF 2.02 (MA50, 13:40, фильтр 1, "
        "без шорта в пятницу), но на OOS 2026 PF 1.47 против 1.53 у p-base — "
        "проверяем, подтвердится ли шум в бумажном контуре",
        "Простушка · train-пик риск",
    ),
    Config(
        "cb-day", "channel_break",
        dict(start="01:00", switch="13:00", mode="day", direction="long",
             sl=0.12, boundary="first_bar", tick=0.001),
        "пробой дневного канала 09:00→13:00, вход после пробоя HH, выход в 09:00; "
        "CNY train PF 2.07 / OOS 2.17, Si 1.44 / 2.06, BR 1.32 OOS, GOLD 1.13, "
        "RTS 1.04; контроль «просто лонг» убыточен — край есть",
        "Пробой канала · day риск",
    ),
    Config(
        "cb-day-si", "channel_break",
        dict(start="01:00", switch="13:00", mode="day", direction="long",
             sl=1000.0, boundary="first_bar", tick=1.0),
        "пробой дневного канала на Si: train PF 1.44 / OOS 2.06 (+4 869 ₽), "
        "DD −1 157 ₽; тот же режим day/long, стоп 1000 п.",
        "Пробой канала · Si риск", instrument="Si",
    ),
    # --- 23.11.2026: диверсификаторы (не замена базы) ---
    # Решение по дневному бару предыдущей даты, публикация в 13:55.
    # Отбор: reports/strategy-diversifiers.md — корреляция с базой 0.16,
    # +6.65% в её худшей квартили; одиночный SS не заменяет базу.
    Config(
        "d20-cn", "donchian",
        dict(entry=20, exit=10, entry_time="13:55", allow_short=True),
        "диверсификатор: Donchian HH20/LL20 → выход LL10/HH10; "
        "корр 0.16 с базой, +6.65% в её худшие годы (36% плюса); "
        "OOS 2026 CNY PF 1.91 против 1.53 у базы; 200% номинала, DD ~17% счёта",
        "Donchian 20/10 · CNY риск", capital=200_000, exposure=2.0,
    ),
    Config(
        "d20-si", "donchian",
        dict(entry=20, exit=10, entry_time="13:55", allow_short=True),
        "диверсификатор на Si: OOS 2026 PF 2.04 против 1.48 у базы; "
        "10-летняя DD 30.9% номинала → потолок 100%, DD ~25% счёта",
        "Donchian 20/10 · Si риск", instrument="Si",
        capital=200_000, exposure=1.0,
    ),
]


BASE_CONFIGS = list(CONFIGS)
CONFIGS = BASE_CONFIGS + list(ROBOT_FIXTURES)
BY_ID = {c.id: c for c in CONFIGS}
