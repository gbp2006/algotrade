# Three Soldiers: строгая проверка

Прототип по идее OsEngine `ThreeSoldierVolatilityAdaptive`. Gating как в `scripts/79_rigorous_validation.py`, N trials = 169, порог 30 сделок.

| Инструмент | Стратегия | Сделок | Net | PF | DSR | p-sign | Вердикт |
|---|---|---:|---:|---:|---:|---:|---|
| Si | 3 soldiers k=0.5 long | 12 | 5920 | 1.25 | 0.008 | 0.437 | сделок <30; неотличим от случая; DSR<0.95 |
| Si | 3 soldiers k=1.0 long+short | 2 | -11301 | 0.53 | 0.0 | 1.000 | сделок <30; убыточен; неотличим от случая; DSR<0.95 |
| CNY | 3 soldiers k=0.5 long | 6 | -1393 | 0.69 | 0.002 | 0.623 | сделок <30; убыточен; неотличим от случая; DSR<0.95 |
| CNY | 3 soldiers k=1.0 long+short | 0 | 0 | 0.00 | 0.0 | 1.000 | сделок <30; убыточен; неотличим от случая; DSR<0.95 |

## Walk-forward по годам

| Инструмент | Стратегия | Год | Сделок | Net | PF |
|---|---|---:|---:|---:|---:|
| Si | 3 soldiers k=0.5 long | 2016 | 1 | -15737 | 0.00 |
| Si | 3 soldiers k=0.5 long | 2017 | 1 | -940 | 0.00 |
| Si | 3 soldiers k=0.5 long | 2018 | 1 | 3163 | inf |
| Si | 3 soldiers k=0.5 long | 2019 | 3 | -2302 | 0.13 |
| Si | 3 soldiers k=0.5 long | 2020 | 1 | 10110 | inf |
| Si | 3 soldiers k=0.5 long | 2021 | 0 | 0 | 0.00 |
| Si | 3 soldiers k=0.5 long | 2022 | 1 | 1226 | inf |
| Si | 3 soldiers k=0.5 long | 2023 | 2 | 10567 | 10.15 |
| Si | 3 soldiers k=0.5 long | 2024 | 1 | 2601 | inf |
| Si | 3 soldiers k=0.5 long | 2025 | 1 | -2767 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2016 | 0 | 0 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2017 | 0 | 0 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2018 | 0 | 0 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2019 | 0 | 0 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2020 | 0 | 0 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2021 | 0 | 0 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2022 | 0 | 0 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2023 | 0 | 0 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2024 | 1 | -24239 | 0.00 |
| Si | 3 soldiers k=1.0 long+short | 2025 | 0 | 0 | 0.00 |
| CNY | 3 soldiers k=0.5 long | 2023 | 2 | 3062 | inf |
| CNY | 3 soldiers k=0.5 long | 2024 | 1 | -691 | 0.00 |
| CNY | 3 soldiers k=0.5 long | 2025 | 2 | -2240 | 0.00 |
| CNY | 3 soldiers k=1.0 long+short | 2023 | 0 | 0 | 0.00 |
| CNY | 3 soldiers k=1.0 long+short | 2024 | 0 | 0 | 0.00 |
| CNY | 3 soldiers k=1.0 long+short | 2025 | 0 | 0 | 0.00 |

Прошли все гейты: 0 из 4.
В контур не добавляется до отдельного решения пользователя.
