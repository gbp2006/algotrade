# Parabolic SAR: строгая проверка

Прототип по идее OsEngine `ParabolicSarTrade`. Gating как в `scripts/79_rigorous_validation.py`, N trials = 171, порог 30 сделок.

| Инструмент | Стратегия | Сделок | Net | PF | DSR | p-sign | Вердикт |
|---|---|---:|---:|---:|---:|---:|---|
| Si | Parabolic SAR long | 16679 | -207936 | 0.83 | 0.0 | 1.000 | убыточен; неотличим от случая; DSR<0.95 |
| Si | Parabolic SAR long+short | 33358 | -421145 | 0.82 | 0.0 | 1.000 | убыточен; неотличим от случая; DSR<0.95 |
| CNY | Parabolic SAR long | 4913 | -27344 | 0.64 | 0.0 | 1.000 | убыточен; неотличим от случая; DSR<0.95 |
| CNY | Parabolic SAR long+short | 9825 | -54092 | 0.65 | 0.0 | 1.000 | убыточен; неотличим от случая; DSR<0.95 |

## Walk-forward по годам

| Инструмент | Стратегия | Год | Сделок | Net | PF |
|---|---|---:|---:|---:|---:|
| Si | Parabolic SAR long | 2016 | 1603 | -20868 | 0.84 |
| Si | Parabolic SAR long | 2017 | 1586 | -23356 | 0.68 |
| Si | Parabolic SAR long | 2018 | 1639 | -14283 | 0.83 |
| Si | Parabolic SAR long | 2019 | 1578 | -32021 | 0.53 |
| Si | Parabolic SAR long | 2020 | 1630 | -14226 | 0.88 |
| Si | Parabolic SAR long | 2021 | 2030 | -37707 | 0.64 |
| Si | Parabolic SAR long | 2022 | 1466 | 2026 | 1.01 |
| Si | Parabolic SAR long | 2023 | 1695 | -10293 | 0.93 |
| Si | Parabolic SAR long | 2024 | 1690 | -18288 | 0.86 |
| Si | Parabolic SAR long | 2025 | 1762 | -38921 | 0.75 |
| Si | Parabolic SAR long+short | 2016 | 3207 | -28947 | 0.89 |
| Si | Parabolic SAR long+short | 2017 | 3172 | -42737 | 0.71 |
| Si | Parabolic SAR long+short | 2018 | 3278 | -40863 | 0.76 |
| Si | Parabolic SAR long+short | 2019 | 3155 | -56117 | 0.57 |
| Si | Parabolic SAR long+short | 2020 | 3261 | -40848 | 0.83 |
| Si | Parabolic SAR long+short | 2021 | 4060 | -76273 | 0.63 |
| Si | Parabolic SAR long+short | 2022 | 2931 | 9819 | 1.03 |
| Si | Parabolic SAR long+short | 2023 | 3391 | -42465 | 0.85 |
| Si | Parabolic SAR long+short | 2024 | 3380 | -50080 | 0.81 |
| Si | Parabolic SAR long+short | 2025 | 3523 | -52634 | 0.83 |
| CNY | Parabolic SAR long | 2023 | 1219 | -3274 | 0.81 |
| CNY | Parabolic SAR long | 2024 | 1474 | -4398 | 0.75 |
| CNY | Parabolic SAR long | 2025 | 1642 | -8701 | 0.58 |
| CNY | Parabolic SAR long+short | 2023 | 2439 | -9302 | 0.74 |
| CNY | Parabolic SAR long+short | 2024 | 2947 | -9897 | 0.72 |
| CNY | Parabolic SAR long+short | 2025 | 3284 | -14877 | 0.64 |

Прошли все гейты: 0 из 4.
В контур не добавляется до отдельного решения пользователя.
