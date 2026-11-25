# Сессия — предпроверка боя 26.11 (read-only)

## 00:34 — состояние WSL перед прогоном 14:00

Подключился сам через `ssh wsl-algo` (VPN `Sysinv SSTP` уже был поднят). Ничего не переключал:

- таймеры активны: `algotrading-daily` 13:55, `algotrading-shadow` 13:57,
  `algotrading-live` 14:00; `algotrading-channel` 09:00, `morning` 10:25,
  `update-live` каждые 30 мин, backup 03:00, friday;
- `algotrading-scheduler.service` active;
- `results/STOP`, `STOP_REAL`, `live_run.lock`, `live.lock`, `shadow.lock` — отсутствуют;
- `live_run.json` за 25.11: `armed=true`, `rejected=1` (старый лимит до ADR);
- настройки из store: `prostushka-test-1`, счёт `2102993`, `source_config=p-base`,
  `pricing=marketable`, `exposure=0.5`, `max_exposure=0.5`, `max_qty=100`;
- `/api/health`: OK, warning об устаревших данных — ожидаем ночью;
- через `.venv/bin/python` (секрет не печатал): позиция брокера
  `CNYRUBF@RTSX = −2`, заявок 0; `runtime_state` для робота ещё пустой —
  новая запись появится после прогона 14:00.

## 00:35 — симуляция решения 25.11 с реальными данными

Прогон `34_live_execute.py --day 2026-11-25` на WSL с `dry_run=True` (без
`--arm`), но с реальными `paper.csv`, настройками store и брокером для чтения.
Журнал, сводка, лок и `RobotStore` подменены на временные каталоги; в журнал
предзагружена filled-строка 24.11, чтобы модель позиции совпадала с брокером.

Первый прогон в 00:35 дал `rejected: котировка устарела` — это корректная
защита `max_quote_age_sec` в неторговые часы, а не регрессия лимита. Повторный
прогон с подменённым `quote_age_sec=5` (только внутри симуляции):

```
decision buy 4 → planned, STOP_REAL не создан
runtime: position −2, equity 50022, last_price 12.319,
         last_decision "2026-11-25 12:00 planned: dry-run..."
```

То есть ADR-лимит по итоговой позиции проходит и новая запись `runtime_state`
пишется именно от факта счёта. Реальная заявка не отправлялась; брокер по-прежнему
держит −2 CNY, STOP и настройки не тронуты.

### 00:37 — Конец: предпроверка боя 26.11

Статус: **решено**. Всё готово к 14:00: таймеры active, STOP/локов нет,
настройки и позиция совпадают с ожидаемыми. Симуляция с реальными данными
подтвердила `planned` и запись `runtime_state`. Контроль факта — автоматика
`aut_2147b1b0e0018j8l9TkuwoYlun` в 14:10 МСК; заявки в ходе проверки не
отправлялись.
