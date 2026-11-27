"""Заготовки конфигураций с риск-модулем (НЕ активны в бумажном контуре).

Создать новые id можно только так: existing `config id` не меняются. Этот
вариант использует те же параметры сигнала, что `p-base`, и отличается только
резкой экспозиции по ATR. Дневной лимит убытка удалён (ADR 27.11). Попадут в `CONFIGS` отдельным решением после чистого месяца
и 30 дней бумаги — см. ADR 19.11 и `docs/strategies/risk.md`.
"""

from __future__ import annotations

from .configs import Config

_BASE = dict(ma_window=200, entry="13:50", filter_bars=3, short_friday=False)

RISK_CONFIGS: list[Config] = [
    Config("p-base-vol", "prostushka", dict(_BASE, risk_vol=True),
           "база + резка экспозиции по ATR (200/100/50/30%)",
           "Простушка · ATR-сайз", instrument="CNY"),
]

RISK_BY_ID = {c.id: c for c in RISK_CONFIGS}
