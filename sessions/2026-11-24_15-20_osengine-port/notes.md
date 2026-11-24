# Сессия: порт стратегий в OsEngine и сравнение бэктестов

## 15:20 — Старт темы
Пользователь попросил «эти же стратегии» (таблица 17 роботов из
`reports/year-returns-by-deposit.md`) написать для OsEngine, прогнать там же
тесты и сравнить результаты. Требуется выяснить: формат роботов/данных OsEngine,
доступный рантайм (Wine/GUI/MCP :6500), объём порта и корректность сравнения
(издержки, сайзинг, окна). Пока ничего не менял, кроме отчёта по предыдущему
вопросу. Жду разведку по OsEngine (subagent).

## 15:25 — Карта порта (из `algo/configs.py`, `algo/robot_configs.py`)
17 счётов сводятся к 4 семействам правил:
1. `prostushka`: p-base (MA40/13:50/ф3/пт0), p-fast (MA50/13:40/ф6/пт1),
   p-h1 (H1, ma_window=400 → 7 баров H1, 13:50/ф1/пт1),
   p-friday (дубль p-base — `close_friday` не передаётся в `targets_for`),
   p-rts и p-gold (как p-base на RTS/GOLD), p-ma50 (MA50/13:50/ф3/пт0),
   p-fast2 (MA50/13:40/ф3/пт1), p-train (MA50/13:40/ф1/пт0).
2. `universal`: u-base (0.4/0.2%, 13:30, daily), u-wide (0.1/0.1%, 13:30, daily),
   u-morning (0.4/0.2%, 13:30, morning exit 10:20), u-1340 (0.4/0.2%, 13:40, daily).
3. `channel_break`: cb-day (start 01:00 → proxy 23:40, switch 13:00, mode day,
   long, sl=0.12, boundary=first_bar, tick=0.001), cb-day-si (то же, sl=1000, tick=1).
4. `donchian`: d20-cn / d20-si (HH20/LL20 → LL10/HH10, вход 13:55, LS).
Все — 100% номинала, депозиты из таблицы, издержки 0.01% + 1 тик, сигнал по close →
сделка по open следующего бара. OsEngine запущен под Wine (`-data`, port 6500).

## 15:33–16:00 — Порт и прогоны
- C#-порты: `assets/osengine/AlgoProstushka.cs`, `AlgoUniversal.cs`,
  `AlgoChannelBreak.cs`, `AlgoDonchian.cs` (один файл = один `[Bot]`; общий
  хелпер продублирован с уникальным именем — OsEngine компилирует каждый
  скрипт отдельно). Скопированы в `Custom/Robots`, принимаются через
  `wiki_robot_info` / `optimizer_bot_set`.
- Данные: `scripts/97_osengine_data_prepare.py` → `cache/osengine_compare/
  algo_2023_2026/{CNY,SI,RTS,GOLD}.txt` (M5) и `algo_h1_2023_2026` (H1).
- Batch: `scripts/98_osengine_port_batch.py` через MCP `optimizer_*`, по одному
  проходу на конфигурацию; переключение Set→Folder требует toggle (иначе
  storage не пересобирается). Записи в `results/runs.csv` с префиксом
  `osengine:`.
- Отчёт: `reports/osengine-port-comparison.md` — 32 строки (16 конфигураций ×
  2025/2026; `p-h1` исключён: folder-режим не отдаёт Hour1).

## 16:00 — Результат сравнения
Из 27 валидных пар число сделок совпало в 25 (±2 сделки). Средний PF наш 2.14
против 2.26 в OsEngine, средняя доходность 16.8% против 18.5%. OsEngine
систематически чуть выше PF — разница в исполнении (Intersection) и в том,
что в folder-режиме OsEngine не знает step cost: PnL нормирован умножением на
multiplier, DD из OsEngine поэтому не сопоставим и не показан.
`cb-day*`: у порта 0 сделок (реализация стопа/границы не совпала с питоновской),
`p-gold/2026`: 0 сделок в optimizer — помечены нулями, не интерпретировать как
результат стратегии.

### 16:05 — Конец: порт OsEngine и сравнение бэктестов
**решено** (исследовательский канал; ADR 18.11 не отменяется, эталон — наш
бэктест). Файлы: `assets/osengine/*.cs`, `scripts/97_*`, `scripts/98_*`,
`reports/osengine-port-comparison.md`, `results/runs.csv` (префикс `osengine:`).
OsEngine изолирован от бумажного/боевого контура; модели исполнения и издержки
нашей песочницы не менялись.
