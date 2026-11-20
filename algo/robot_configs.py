"""Дополнительные роботы для бумажной торговли (новые id, работают параллельно).

Конфигурации зафиксированы ДО начала бумажного теста: реестр `CONFIGS` не меняется.
Три кандидата прошли check OOS 2026, четвёртый (`p-train`) — **контроль подгонки**:
лучший по train 2023–25 набор, который на OOS проиграл базе. Все получают ATR-резку
сайза по `algo/risk.py`. Исследование — `reports/param-search-2025-2026.md`,
`reports/entry-time-validation.md`, `reports/regime-vs-overfit.md`.
"""

from __future__ import annotations

from .configs import Config

ROBOT_CONFIGS: list[Config] = [
    Config(
        "p-ma50", "prostushka",
        dict(ma_window=250, entry="13:50", filter_bars=3,
             short_friday=False, risk_vol=True),
        "MA50 M5, вход 13:50: плато на CNY и Si (OOS PF 1.60–1.70 / 1.57–1.65) "
        "+ резка экспозиции по ATR",
        "Простушка · MA50 риск",
    ),
    Config(
        "p-fast2", "prostushka",
        dict(ma_window=250, entry="13:40", filter_bars=3,
             short_friday=True, risk_vol=True),
        "MA50 M5, вход 13:40: бэктест-контроль (CNY OOS PF 1.62, Si 1.68) "
        "+ резка экспозиции по ATR",
        "Простушка · быстрая риск",
    ),
    Config(
        "u-1340", "universal",
        dict(ref="10:05", entry="13:40", long_off=0.004, short_off=0.002,
             hold="daily", short_friday=False, risk_vol=True),
        "вход 13:40: CNY train PF 1.81 / OOS 2.15 против 1.73/1.83 у u-base; "
        "Si 2009–25 лучше, 2026 хуже — риск-резка обязательна",
        "Универсалка · 13:40 риск",
    ),
    Config(
        "p-train", "prostushka",
        dict(ma_window=250, entry="13:40", filter_bars=1,
             short_friday=False, risk_vol=True),
        "КОНТРОЛЬ ПОДГОНКИ: лучший по train 2023–25 PF 2.02 (MA50, 13:40, фильтр 1, "
        "без шорта в пятницу), но на OOS 2026 PF 1.47 против 1.53 у p-base — "
        "проверяем, подтвердится ли шум в бумажном контуре",
        "Простушка · train-пик риск",
    ),
    Config(
        "cb-day", "channel_break",
        dict(start="01:00", switch="13:00", mode="day", direction="long",
             sl=0.12, boundary="first_bar", tick=0.001, risk_vol=True),
        "пробой дневного канала 09:00→13:00, вход после пробоя HH, выход в 09:00; "
        "CNY train PF 2.07 / OOS 2.17, Si 1.44 / 2.06, BR 1.32 OOS, GOLD 1.13, "
        "RTS 1.04; контроль «просто лонг» убыточен — край есть",
        "Пробой канала · day риск",
    ),
]

ROBOT_BY_ID = {c.id: c for c in ROBOT_CONFIGS}
