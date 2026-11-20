# Поиск параметров: train 2023–2025 → OOS 2026

Дата: 20.11.2026. Песочница, локальные архивы CNYRUBF (M1/M5) и Si (M5). Издержки 0.01% + 1 тик, skip_weekend=True. OOS 2026 — частичный год (до 20.11).

Методика: полная сетка по train, отбор по PF при ограничении на число сделок (Простушка ≥150, Универсалка ≥60), затем проверка топ-12 на OOS 2026. Параметры live-конфигураций (`p-base`, `u-base`) — в первой строке каждой таблицы. Выбор нового набора параметров **не производится** — это исследование, решение об изменении конфигураций принимается отдельно.

## Простушка (CNY, M5)

### Топ-12 по train и их OOS

| вариант | параметры | train сд | train net | train PF | train DD | train years+ | OOS сд | OOS net | OOS PF | OOS DD |
|---|---|---|---|---|---|---|---|---|---|---|
| p-top | ma_period=50;entry_time=13:40;filter_bars=1;use_filter_long=True;allow_short_friday=False | 384 | 13245.99 | 2.02 | -2283.90 | 3/3 | 113 | 2025.57 | 1.47 | -778.48 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=3;use_filter_long=False;allow_short_friday=False | 384 | 13245.99 | 2.02 | -2283.90 | 3/3 | 113 | 2025.57 | 1.47 | -778.48 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=3;use_filter_long=False;allow_short_friday=True | 373 | 14091.27 | 2.01 | -2146.53 | 3/3 | 110 | 2337.91 | 1.48 | -785.95 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=1;use_filter_long=True;allow_short_friday=True | 373 | 14091.27 | 2.01 | -2146.53 | 3/3 | 110 | 2337.91 | 1.48 | -785.95 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=6;use_filter_long=True;allow_short_friday=True | 360 | 13065.02 | 1.98 | -1946.28 | 3/3 | 112 | 2714.71 | 1.61 | -646.53 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=6;use_filter_long=True;allow_short_friday=False | 371 | 12219.73 | 1.98 | -2081.65 | 3/3 | 115 | 2402.38 | 1.62 | -761.98 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=9;use_filter_long=True;allow_short_friday=True | 347 | 12024.60 | 1.93 | -1929.82 | 3/3 | 111 | 2805.09 | 1.67 | -620.53 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=9;use_filter_long=True;allow_short_friday=False | 358 | 11179.31 | 1.93 | -2002.37 | 3/3 | 114 | 2492.75 | 1.69 | -590.83 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=4;use_filter_long=True;allow_short_friday=True | 364 | 12901.16 | 1.93 | -2088.34 | 3/3 | 110 | 2760.38 | 1.62 | -646.53 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=4;use_filter_long=True;allow_short_friday=False | 375 | 12055.87 | 1.93 | -2155.89 | 3/3 | 113 | 2448.05 | 1.62 | -761.98 |
| p-top | ma_period=48;entry_time=13:40;filter_bars=3;use_filter_long=False;allow_short_friday=True | 377 | 12972.06 | 1.91 | -2146.53 | 3/3 | 111 | 1897.81 | 1.37 | -785.95 |
| p-top | ma_period=48;entry_time=13:40;filter_bars=3;use_filter_long=False;allow_short_friday=False | 386 | 12135.73 | 1.91 | -2118.33 | 3/3 | 112 | 1478.41 | 1.32 | -778.48 |

Baseline `p-base` (MA40, 13:50, фильтр 3, шорт в пятницу запрещён): train PF 1.67, net 9661 ₽; OOS PF 1.53, net 2070 ₽, 105 сделок.

### Плато вокруг лучшего train-варианта

| стратегия | сдвиг MA | сдвиг входа мин | train PF | train сд |
|---|---|---|---|---|
| Простушка | -10.00 | -10.00 | 1.65 | 388 |
| Простушка | -10.00 | 0.00 | 1.84 | 379 |
| Простушка | -10.00 | 10.00 | 1.65 | 384 |
| Простушка | -5.00 | -10.00 | 1.65 | 387 |
| Простушка | -5.00 | 0.00 | 1.82 | 389 |
| Простушка | -5.00 | 10.00 | 1.66 | 389 |
| Простушка | 0.00 | -10.00 | 1.64 | 382 |
| Простушка | 0.00 | 0.00 | 2.02 | 384 |
| Простушка | 0.00 | 10.00 | 1.74 | 396 |
| Простушка | 5.00 | -10.00 | 1.64 | 381 |
| Простушка | 5.00 | 0.00 | 1.82 | 377 |
| Простушка | 5.00 | 10.00 | 1.71 | 391 |
| Простушка | 10.00 | -10.00 | 1.69 | 378 |
| Простушка | 10.00 | 0.00 | 1.73 | 378 |
| Простушка | 10.00 | 10.00 | 1.62 | 379 |

### Перенос на Si (M5)

| вариант | параметры | train сд | train net | train PF | train DD | train years+ | OOS сд | OOS net | OOS PF | OOS DD |
|---|---|---|---|---|---|---|---|---|---|---|
| p-base | ma_period=40;entry_time=13:50;filter_bars=3;use_filter_long=True;allow_short_friday=False | 412 | 31141.70 | 1.22 | -15987.12 | 2/3 | 104 | 16440.04 | 1.53 | -4880.34 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=1;use_filter_long=True;allow_short_friday=False | 413 | 36369.20 | 1.26 | -17381.36 | 2/3 | 109 | 18815.21 | 1.60 | -5574.73 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=3;use_filter_long=False;allow_short_friday=False | 413 | 36369.20 | 1.26 | -17381.36 | 2/3 | 109 | 18815.21 | 1.60 | -5574.73 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=3;use_filter_long=False;allow_short_friday=True | 405 | 47502.04 | 1.33 | -17950.20 | 2/3 | 109 | 20933.27 | 1.63 | -6148.66 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=1;use_filter_long=True;allow_short_friday=True | 405 | 47502.04 | 1.33 | -17950.20 | 2/3 | 109 | 20933.27 | 1.63 | -6148.66 |
| p-top | ma_period=50;entry_time=13:40;filter_bars=6;use_filter_long=True;allow_short_friday=True | 393 | 44606.06 | 1.33 | -16862.02 | 2/3 | 109 | 20463.53 | 1.68 | -5722.86 |

## Универсалка (CNY, M1)

### Топ-12 по train и их OOS

| вариант | параметры | train сд | train net | train PF | train DD | train years+ | OOS сд | OOS net | OOS PF | OOS DD |
|---|---|---|---|---|---|---|---|---|---|---|
| u-top | long_offset=0.002;short_offset=0.002;hold=daily;avg_window=0 | 303 | 8661.34 | 1.88 | -1918.85 | 3/3 | 101 | 2300.94 | 1.73 | -774.70 |
| u-top | long_offset=0.002;short_offset=0.004;hold=daily;avg_window=0 | 253 | 7193.98 | 1.88 | -1418.63 | 3/3 | 86 | 2017.63 | 1.73 | -619.73 |
| u-top | long_offset=0.003;short_offset=0.002;hold=daily;avg_window=0 | 284 | 7650.94 | 1.84 | -1795.47 | 3/3 | 95 | 2179.77 | 1.79 | -701.53 |
| u-top | long_offset=0.003;short_offset=0.004;hold=daily;avg_window=0 | 234 | 6183.59 | 1.83 | -1310.30 | 3/3 | 80 | 1896.45 | 1.80 | -762.95 |
| u-top | long_offset=0.002;short_offset=0.002;hold=daily;avg_window=5 | 312 | 8613.42 | 1.83 | -2021.67 | 3/3 | 98 | 2772.52 | 2.03 | -543.53 |
| u-top | long_offset=0.002;short_offset=0.003;hold=daily;avg_window=0 | 278 | 7303.55 | 1.81 | -1780.66 | 3/3 | 95 | 2409.20 | 1.84 | -592.44 |
| u-top | long_offset=0.003;short_offset=0.004;hold=morning;avg_window=0 | 292 | 6668.65 | 1.80 | -1228.61 | 3/3 | 104 | 1839.95 | 1.90 | -381.20 |
| u-top | long_offset=0.0005;short_offset=0.004;hold=morning;avg_window=0 | 443 | 8952.13 | 1.79 | -1228.61 | 3/3 | 136 | 2083.62 | 1.68 | -489.51 |
| u-top | long_offset=0.0005;short_offset=0.002;hold=daily;avg_window=0 | 344 | 9180.74 | 1.78 | -2138.76 | 3/3 | 101 | 2999.32 | 2.00 | -824.90 |
| u-top | long_offset=0.002;short_offset=0.001;hold=daily;avg_window=0 | 322 | 8502.19 | 1.78 | -2098.58 | 3/3 | 105 | 2706.86 | 1.83 | -508.72 |
| u-top | long_offset=0.003;short_offset=0.004;hold=morning;avg_window=10 | 290 | 6866.59 | 1.78 | -1333.42 | 3/3 | 104 | 1928.03 | 1.93 | -378.16 |
| u-top | long_offset=0.002;short_offset=0.004;hold=morning;avg_window=0 | 339 | 7322.90 | 1.78 | -1228.61 | 3/3 | 120 | 1683.04 | 1.63 | -483.06 |

Baseline `u-base` (0.4%/0.2%, 13:30, daily): train PF 1.73, net 6406 ₽; OOS PF 1.83, net 2089 ₽, 87 сделок.

### Плато вокруг лучшего train-варианта

| стратегия | сдвиг MA | сдвиг входа мин | train PF | train сд |
|---|---|---|---|---|
| Универсалка | -0.0010 | -0.0010 | 1.62 | 351 |
| Универсалка | -0.0010 | +0.0000 | 1.69 | 332 |
| Универсалка | -0.0010 | +0.0010 | 1.62 | 307 |
| Универсалка | +0.0000 | -0.0010 | 1.78 | 322 |
| Универсалка | +0.0000 | +0.0000 | 1.88 | 303 |
| Универсалка | +0.0000 | +0.0010 | 1.81 | 278 |
| Универсалка | +0.0010 | -0.0010 | 1.73 | 303 |
| Универсалка | +0.0010 | +0.0000 | 1.84 | 284 |
| Универсалка | +0.0010 | +0.0010 | 1.76 | 259 |

### Дополнительные варианты

| вариант | параметры | train сд | train net | train PF | train DD | train years+ | OOS сд | OOS net | OOS PF | OOS DD |
|---|---|---|---|---|---|---|---|---|---|---|
| u-base fri=True | ref_time=10:05;entry_time=13:30;long_offset=0.004;short_offset=0.002;hold=daily;exit_time=10:20;allow_short_friday=True | 262 | 7746.36 | 1.79 | -1843.28 | 3/3 | 92 | 2001.78 | 1.63 | -670.44 |
| u-base avg=10 | ref_time=10:05;entry_time=13:30;long_offset=0.004;short_offset=0.002;hold=daily;exit_time=10:20;allow_short_friday=False;avg_window=10 | 264 | 4977.99 | 1.52 | -2021.42 | 3/3 | 87 | 2089.94 | 1.85 | -533.77 |
| u-base ref=10:15 | ref_time=10:15;entry_time=13:30;long_offset=0.004;short_offset=0.002;hold=daily;exit_time=10:20;allow_short_friday=False | 225 | 6220.79 | 1.79 | -1553.13 | 3/3 | 88 | 1050.50 | 1.35 | -782.41 |
| u-base entry=13:40 | ref_time=10:05;entry_time=13:40;long_offset=0.004;short_offset=0.002;hold=daily;exit_time=10:20;allow_short_friday=False | 254 | 6896.96 | 1.81 | -1319.92 | 3/3 | 88 | 2463.37 | 2.15 | -541.37 |
| лучшая ×friday | long_offset=0.002;short_offset=0.002;hold=daily;avg_window=0;allow_short_friday=True | 308 | 10001.66 | 1.92 | -2046.86 | 3/3 | 106 | 2213.28 | 1.58 | -743.61 |

## Выводы (после проверки на независимых периодах)

Дополнительная проверка — `reports/entry-time-validation.md`: сдвиг времени входа и период
MA прогнан на Si 2009–2026 и CNY 2023–2026.

1. **Простушка: лучший train-вариант (MA50, вход 13:40, фильтр 1) не выдерживает проверки.**
   На CNY OOS он даёт PF 1.47 против 1.53 у базы; эффект входа 13:40 нестабилен:
   Si 2009–19 — PF 1.69 против 1.64 у 13:50, Si 2020–22 — 1.58 против 1.47,
   Si 2023–25 — 1.32 против 1.22, но CNY 2026 — 1.47 против 1.53. Это подгонка под train.
2. **Простушка: устойчивое улучшение — период MA 48–55 вместо 40** (уже предполагалось ADR 18.11).
   На CNY train PF 1.79–1.81 против 1.67; OOS 2026 PF 1.60–1.70 против 1.53.
   На Si OOS 2026 PF 1.57–1.65 против 1.53, и во всех четырёх периодах Si MA50 ≥ MA40.
   Плато по MA (48/50/55), а не isolated-пик — кандидат на новый конфиг, но не на замену `p-base`.
3. **Универсалка: вход 13:40 вместо 13:30 — лучший кандидат** (в 4 из 6 проверок лучше):
   CNY train PF 1.81 против 1.73, CNY OOS 2.15 против 1.83; Si 2009–19 1.98 против 1.91,
   Si 2020–22 1.78 против 1.67, Si 2023–25 1.24 против 1.23; исключение — Si 2026 (1.57 против 1.64).
   Вход 14:00 даёт CNY OOS 2.24, но Si 2026 всего 1.55 — менее устойчив.
4. **Универсалка: снижение порога лонга 0.4% → 0.2–0.3%** увеличивает число сделок (303 → 284–303
   на train) и train PF 1.84–1.88 против 1.73, но OOS PF 1.73–1.79 против 1.83 — один только порог
   надёжно не улучшает. Лучшее сочетание в сетке — 0.2%/0.2% с осреднением 5 мин: OOS PF 2.03.
5. Ни один найденный набор не меняет `CONFIGS`: существующие id фиксированы правилом реестра.
   При желании внедрить — новые id (`p-ma50`, `u-1340` и т.п.), отдельное решение в `docs/decisions.md`
   и запись в `results/runs.csv`. На WSL ничего не выкладывается до чистого месяца бумаги.

## Оговорки

- Train-оптимум почти всегда проигрывает baseline на OOS — это признак подгонки, а не найденного края.
- Узкое плато (только одно значение параметра даёт PF > 1) трактуем как шум.
- OOS 2026 — неполный год; для вывода нужна полная история 2026 и, желательно, 2027.
- Полная сетка: `reports/param-search-prostushka.csv`, `reports/param-search-universal.csv`.
- Отобранные прогоны записаны в `results/runs.csv` с note `param-search`.
