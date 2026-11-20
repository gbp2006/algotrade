"""Дополнительные роботы для бумажной торговли (новые id, работают параллельно).

Конфигурации зафиксированы ДО начала бумажного теста: реестр `CONFIGS` не меняется.
Все три кандидата прошли check OOS 2026 (reports/param-search-2025-2026.md,
reports/entry-time-validation.md) и получают ATR-резку сайза по `algo/risk.py`.
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
]

ROBOT_BY_ID = {c.id: c for c in ROBOT_CONFIGS}
