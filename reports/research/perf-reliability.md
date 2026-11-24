# Скорость и надёжность панели/контура — read-only замеры (24.11.2026)

Режим: только чтение. Код не менялся, сервисы не перезапускались, `data/`, `materials/`,
`cache/` не читались, строки данных БД не выводились, секреты не печатались.
Источник фактов: `web/app.py`, `web/instances_api.py`, `algo/*`, `scripts/*`,
curl к `localhost:8080` на WSL, `systemctl`, `du`/`ls`, `PRAGMA`/`SELECT COUNT(*)`
через `python3 -c` в `mode=ro` (CLI `sqlite3` на WSL отсутствует).

## 1. Методика

- Тёплый запас: 5 подряд `/api/state`; Cold: после паузы >60 с (TTL `price` = 60 с,
 остальные TTL 5–15 с истекли); сервис поднят в 15:54:03, `_warm_cache()` работает только на startup.
- Время — `curl -w %{time_total}` (полный round-trip до uvicorn), HTTP-код 200 везде.
- `/api/accounts/analytics`: 1-й вызов = cold (заполняет кэш), 2-й сразу же = кэш.

## 2. Измерения

| Эндпоинт | Холодный | Тёплый | Бюджет брифа | Вердикт |
|---|---|---|---|---|
| `/api/state` | 800 мс, 526 мс (2 замера) | 4.4–5.1 мс; **288 мс** первый после простоя 15–60 с | <700 / <50 мс | тёплый ✅, холодный ✗/на грани, «первый клик» ❌ |
| `/api/health` | 0.9 мс | 0.6 мс | <20 мс | ✅ (запас ~20×) |
| `/api/accounts/analytics` | 190 мс и **1252 мс** (разброс) | 1.0 мс (кэш 30 с) | <200 / <20 мс | кэш ✅, холодный ~/❌ |
| `/api/logs` | 2.8 мс | 3.1 мс | — | ✅ |
| `/`, `/trade`, `/robots`, `/accounts`, `/health` | 1.4–5.7 мс | — | — | ✅ |

 cold `/api/state` = `quote()` + `price_series()` + до 4 `quote_for()` (17 конфигов,
4 инструмента: CNY, GOLD, RTS, Si) + `metrics_store.latest()` + чтение paper.csv (12 КБ)
и daily.log (16 КБ); сеть Finam доминирует. cold analytics = `broker.account()` на 1 реальный
счёт + 17×`get_runtime()` — отсюда 6× разброс. `health.json` — чтение одного маленького файла.

## 3. Таймеры и БД (факты)

- Активны: `daily` 13:55, `shadow` 13:57, `live` 14:00, `morning` 10:25, `friday` 18:45,
  `channel` и `update-live` каждые 10 мин (следующий запуск 16:10), `algotrading-scheduler.service`
  в shadow (`ALGO_SCHEDULER_SHADOW=1`, Restart=always). Web: 139.8 МБ RSS (peak 199.7 МБ), 11 задач.
- `infra/db/`, всего 176 МБ: `market.db` 156 МБ, WAL 0.88 МБ + `-shm` (активный писатель в 16:00);
  `instruments.db` 24.5 МБ (delete); `trades.db` 45 КБ (WAL, 18 заявок / 19 событий / 1 сделка,
  индексы `ts`, `account,ts`, `client_order_id`); `robots.db` 139 КБ (**journal=delete**, 18 инстансов,
  17 runtime, 23 события, 363 запуска, индекса по `instance_id` в `instance_events`/`param_versions` нет);
  `paper_metrics.db` 24 КБ (delete, 32 строки, индекс `config,day` есть); `memory.db` 1.6 МБ.
- Lock-файлы на момент замера: `scheduler.lock` есть с 23.11 20:59 (5 байт = PID),
  `live.lock`, `live_run.lock`, `rollover.lock` отсутствуют.

## 4. Кэши и точки отказа

- `web/app.py:_cache` — общий dict TTL: remote paper 5 с, quote 15 с, price 60 с, candles 20 с,
  timer 10 с, expected 3600 с, quote_fast 2 с. Нет вытеснения (ключи ограничены 17 конфигами),
  нет stale-возврата: при ошибке брокера исключение ловится и подменяется `{"error": ...}`,
  кэш не обновляется (хорошо, но пользователь видит ошибку вместо последнего значения).
- `_warm_cache()` (app.py:105) греет quote/price/3 timer **только при старте**: после простоя >
  60 с первый клиент платит 288 мс — измерено.
- `instances_api.cached_analytics()` TTL 30 с, одна глобальная ячейка, `time.monotonic`.
  `invalidate_analytics()` вызывается только из `/accounts` POST/PATCH и `/keys` POST
  (строки 289/355/368); изменения инстансов и runtime его **не** инвалидируют → виртуальный
  equity/position может быть устаревшим до 30 с.
- `metrics_store.latest()` и др. вызывают `init_db()` (executescript DDL) на каждом запросе панели.
- `trade_journal.connect()` на **каждом** соединении (включая чтения `/api/logs`) исполняет
  `PRAGMA journal_mode=WAL` + `executescript(SCHEMA)` — лишняя работа и захват схемы.
- `read_health()` возвращает `None` при отсутствии/битом `health.json` → `/api/health` = 503
  (в PROGRESS уже описан ложный 503). Файл обновляется фоновым поток раз в 5 мин; свежесть
  поля `checked` эндпоинтом не проверяется. Один WSL-хост, один uvicorn, без авторизации.

## 5. Гонки 13:55 / 13:57 / 14:00

1. **Общий lock и журнал.** `daily`(13:55) пишет `paper.csv`/`market.db`; `shadow`(13:57) через
   `OrderGateway(..., journal=results/live.csv, lock=results/live.lock)` пишет `planned`-строки
   в `live.csv`/`live.db`; `live`(14:00) использует `live_run.lock` и **тот же** `live.lock` +
   `live.csv`/`live.db` (34_live_execute.py:227). Если shadow затянется за 14:00, реальная заявка
   получит `rejected: уже выполняется другая заявка` (execution.py:166–169) — тихая потеря исполнения.
2. **Stale lock.** В `OrderGateway` и `acquire_run_lock()` — `O_EXCL` без проверки PID/возраста;
   падение process между созданием файла и `finally` (execution.py:164–215) блокирует заявки
   до ручного удаления. В `scheduler.py:310` есть проверка `_stale_lock()` — образец для остальных.
3. **Двойные задания.** `scheduler.DEFAULT_JOBS` (scheduler.py:77–88) содержит те же daily/shadow/
   update_live/channel, что и systemd-таймеры. Сейчас `shadow=1` (только логи), но при снятии флага
   возникнет двойной запуск daily и каждые 10 мин.
4. **Конкурентная запись БД.** `robots.db` в режиме `delete`: планировщик пишет `scheduler_runs`
   каждые 10 мин и в 13:55–14:00, панель одновременно читает его в `/api/logs`, `/accounts/analytics`;
   `sqlite3.connect` без `busy_timeout` → риск «database is locked» / ожидания до 5 с.
5. **Общий `market.db`.** `daily update` и 10-минутные `update-live`/`channel` пишут один WAL-файл
   (0.88 МБ в момент замера); при долгом читателе возможен рост WAL и паузы на checkpoint.
6. **Сеть в request path.** `/api/state` и analytics синхронно ждут Finam; нет circuit breaker и
   таймаута на уровне запроса → внешний сбой = медленная/пустая панель.
7. **Один health-файл.** Устаревший или отсутствующий `results/health.json` даёт 503/старый статус
   без явного признака «данные устарели» — источник прошлого ложного сигнала.

## 6. Проблема — измерение — решение — проверка

| Проблема | Измерение | Решение | Проверка |
|---|---|---|---|
| Cold `/api/state` вне бюджета | 800/526 мс; 6 сетевых вызовов | Фоновый refresh quote/bars раз в 10–15 с + stale-while-revalidate | После 65 с простоя 1-й вызов <50 мс, p95 cold <700 мс |
| «Первый клик» после простоя | 288 мс (истёк TTL 15/60 с) | Расширить `_warm_cache()` до periodic loop, развести TTL | 5 замеров после 20/60 с: все <50 мс |
| Cold analytics нестабилен | 190 и 1252 мс (брокер) | Фоновая закачка счёта, возврат последнего удачного значения + `stale` флаг | p95 cold <200 мс; при недоступном брокере ответ <20 мс |
| Кэш analytics не инвалидируется при смене инстансов | ≤30 с устаревший equity | Вызывать `invalidate_analytics()` во всех мутациях инстансов/runtime | Тест: PATCH instance → следующий `/analytics` свежий |
| `robots.db` без WAL | journal=delete, 363 запуска, параллельные чтения | Включить WAL + `busy_timeout` в `RobotStore._conn` | Параллельный writer + 100 чтений: без `locked`, <20 мс |
| DDL в read-path | `init_db()`/`executescript` на каждый вызов | Вынести схему из чтений, инициализировать один раз | Микробенч `/api/logs`, `/api/metrics` до/после |
| `trade_journal.connect()` делает PRAGMA+DDL на чтении | 3 соединения на `/api/logs` | Разделить `connect_ro()` и `init_db()` | p95 `/api/logs` не растёт с числом заявок |
| shadow и live делят `live.lock`/журнал | 13:57 → 14:00, 3 мин запас | Раздельные `shadow.lock`/`shadow.db` (dry-run) или guard по времени | Тест: shadow держит lock → live исполняется, не `rejected` |
| Stale `live.lock`/`live_run.lock` | Нет PID/возраста, как в scheduler | Перенести `_stale_lock()` из `scheduler.py` в `OrderGateway` | Убить holder → следующая заявка проходит |
| Дубли systemd + internal scheduler | Одинаковые имена/времена | Один владелец расписания (или явный флаг отключения дублей) | `systemctl list-timers` + `/api/scheduler/jobs` не пересекаются |
| Рост WAL `market.db` | 0.88 МБ за 10 мин | Контроль `wal_autocheckpoint`, метрика размера WAL | Через 24 ч WAL < нескольких МБ, без длинных read-транзакций |
| Ложный 503 health | PROGRESS: инцидент 24.11 | Проверка возраста `checked` + явный `stale: true` | Удалить/испортить health.json → `/api/health` честно сообщает о неизвестности |
| Нет индекса `instance_events(instance_id)` | 23 строки сейчас, full scan при росте | `CREATE INDEX` на `instance_id`, `param_versions(instance_id,version)` | `EXPLAIN QUERY PLAN` без `SCAN TABLE` |

## 7. План проверки (до изменений — только read-only)

1. Повторить замеры 3× в разные минуты, записать p50/p95 в отчёт; не трогать `FINAM_ALLOW_TRADING`.
2. Перед ADR: воспроизвести гонку на **копии** БД/локов (не на рабочих файлах): держатель `live.lock`
   + попытка submit → зафиксировать `rejected`.
3. После ADR и выкладки тем же скриптом curl: `/api/state` (cold/warm), `/api/health`,
   `/api/accounts/analytics`, `/api/logs`, 5 страниц; сравнить с таблицей раздела 2.
4. Конкурентный тест WAL на отдельной копии `robots.db`: writer + 100 reader, без `database is locked`.
5. Smoke по брифу: `/`, `/trade`, `/robots`, `/accounts`, `/health`, `/api/health`.

## 8. Риски

- Правки lock/журнала задевают реальные заявки: только после ADR, на бумаге, с откатом git;
  STOP и `FINAM_ALLOW_TRADING` не трогать.
- Фоновый refresh добавит вызовы к Finam: ограничить параллелизм и возвращать stale при ошибке.
- WAL меняет семантику бэкапа `robots.db` — нужна процедура checkpoint/backup.
- Перезапуск сервисов и выкладку делает основной сеанс (на десктопе панель не запускать).

**Приоритет 1–3:** (1) раздельный shadow lock/журнал + stale-lock check; (2) фоновый
refresh для `/api/state` и analytics с stale-возвратом; (3) WAL и индексы в `robots.db`.
