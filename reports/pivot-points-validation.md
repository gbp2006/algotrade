# Pivot Points: строгая проверка

Прототип по идее OsEngine `PivotPointsRobot`. Gating как в `scripts/79_rigorous_validation.py`, N trials = 167, порог 30 сделок.

| Инструмент | Стратегия | Сделок | Net | PF | DSR | p-sign | Вердикт |
|---|---|---:|---:|---:|---:|---:|---|
| Si | Pivot R1/S1 long | 349 | 52936 | 1.41 | 0.038 | 0.082 | неотличим от случая; DSR<0.95 |
| Si | Pivot R1/S1 long+short | 538 | 90270 | 1.48 | 0.117 | 0.034 | DSR<0.95 |
| Si | Pivot R3 long | 199 | 36085 | 1.44 | 0.013 | 0.191 | неотличим от случая; DSR<0.95 |
| CNY | Pivot R1/S1 long | 123 | 3465 | 1.52 | 0.056 | 0.085 | неотличим от случая; DSR<0.95 |
| CNY | Pivot R1/S1 long+short | 180 | 5526 | 1.57 | 0.158 | 0.026 | DSR<0.95 |
| CNY | Pivot R3 long | 70 | 3039 | 1.72 | 0.058 | 0.092 | неотличим от случая; DSR<0.95 |

## Walk-forward по годам

| Инструмент | Стратегия | Год | Сделок | Net | PF |
|---|---|---:|---:|---:|---:|
| Si | Pivot R1/S1 long | 2016 | 31 | -9865 | 0.55 |
| Si | Pivot R1/S1 long | 2017 | 38 | -5438 | 0.55 |
| Si | Pivot R1/S1 long | 2018 | 38 | 4712 | 1.65 |
| Si | Pivot R1/S1 long | 2019 | 33 | -8701 | 0.13 |
| Si | Pivot R1/S1 long | 2020 | 35 | 6255 | 1.47 |
| Si | Pivot R1/S1 long | 2021 | 35 | -328 | 0.96 |
| Si | Pivot R1/S1 long | 2022 | 30 | 41087 | 3.72 |
| Si | Pivot R1/S1 long | 2023 | 43 | 17409 | 2.30 |
| Si | Pivot R1/S1 long | 2024 | 35 | 11875 | 1.98 |
| Si | Pivot R1/S1 long | 2025 | 31 | -4070 | 0.72 |
| Si | Pivot R1/S1 long+short | 2016 | 54 | -13461 | 0.57 |
| Si | Pivot R1/S1 long+short | 2017 | 58 | -6040 | 0.60 |
| Si | Pivot R1/S1 long+short | 2018 | 55 | 4374 | 1.37 |
| Si | Pivot R1/S1 long+short | 2019 | 54 | -7016 | 0.48 |
| Si | Pivot R1/S1 long+short | 2020 | 51 | 9519 | 1.47 |
| Si | Pivot R1/S1 long+short | 2021 | 58 | -3806 | 0.76 |
| Si | Pivot R1/S1 long+short | 2022 | 47 | 69120 | 4.14 |
| Si | Pivot R1/S1 long+short | 2023 | 51 | 19092 | 2.12 |
| Si | Pivot R1/S1 long+short | 2024 | 54 | 11726 | 1.62 |
| Si | Pivot R1/S1 long+short | 2025 | 56 | 6761 | 1.28 |
| Si | Pivot R3 long | 2016 | 17 | -5199 | 0.51 |
| Si | Pivot R3 long | 2017 | 21 | 250 | 1.06 |
| Si | Pivot R3 long | 2018 | 22 | 5676 | 2.50 |
| Si | Pivot R3 long | 2019 | 16 | -2807 | 0.18 |
| Si | Pivot R3 long | 2020 | 23 | 2873 | 1.28 |
| Si | Pivot R3 long | 2021 | 20 | 300 | 1.07 |
| Si | Pivot R3 long | 2022 | 21 | 29876 | 3.08 |
| Si | Pivot R3 long | 2023 | 22 | 8656 | 1.81 |
| Si | Pivot R3 long | 2024 | 20 | 4075 | 1.45 |
| Si | Pivot R3 long | 2025 | 17 | -7615 | 0.35 |
| CNY | Pivot R1/S1 long | 2023 | 39 | 2055 | 2.63 |
| CNY | Pivot R1/S1 long | 2024 | 34 | 1869 | 2.21 |
| CNY | Pivot R1/S1 long | 2025 | 32 | -1000 | 0.55 |
| CNY | Pivot R1/S1 long+short | 2023 | 49 | 2327 | 2.33 |
| CNY | Pivot R1/S1 long+short | 2024 | 48 | 2284 | 2.04 |
| CNY | Pivot R1/S1 long+short | 2025 | 53 | -30 | 0.99 |
| CNY | Pivot R3 long | 2023 | 26 | 1675 | 2.59 |
| CNY | Pivot R3 long | 2024 | 18 | 1328 | 2.48 |
| CNY | Pivot R3 long | 2025 | 16 | -536 | 0.51 |

Прошли все гейты: 0 из 6.
В контур не добавляется до отдельного решения пользователя.
