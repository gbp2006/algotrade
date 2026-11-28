# MODULES — инвентарь частей проекта

Обязательный справочник по `AGENTS.md`. Для каждой части указаны роль, входы,
выходы/сайд-эффекты, зависимости и тесты. При добавлении нового модуля/endpoint/
секции UI/скрипта/юнета — **добавить строку сюда же**. Подробности сценариев —
`docs/ARCHITECTURE.md`, решения — `docs/decisions.md`.

## 1. Ядро и стратегии (`algo/`)

| Часть | Роль | Входы → выходы, сайд-эффекты | Зависимости | Тесты |
|---|---|---|---|---|
| `engine.py` | Бэктест-движок | OHLCV + конфиг → сделки/équity; модель close→open | `data.py`, config | `test_engine.py` |
| `data.py` | Чтение баров | txt/cache → DataFrame; копирование данных запрещено | pandas | `test_store.py` |
| `configs.py` | DTO `Config` (без реестра) | раннеры/тесты → тип конфигурации; источник параметров — `RobotStore`, фикстуры тестов — `tests/fixtures_configs.py` | — | `test_engine.py`, `test_robot_store_storage.py` |
| `strategies/*.py` | Сигналы | бар → `ENTER_LONG/SHORT/EXIT/HOLD`; **только сигналы**, не знают про деньги | — | `test_engine.py`, `test_donchian_live.py` |
| `author.py`, `mvp.py`, `live.py`, `channel_live.py` | Дневная логика решений | цены/канал → написание `paper.csv` | `configs`, `portfolio` | `test_paper_live.py`, `test_live_execution.py` |
| `portfolio.py` | **Единственный расчёт лотности** | `equity, price, mult, exposure` → `int`; 0 при битых данных; `ledger()`, `account_card()`, `drawdown_stats()` | stdlib | `test_portfolio_metrics.py`, ADR 24.11 |

| `instance_configs.py` | Активные конфиги и версии параметров по времени решения | store → `active_configs`, `configs_at`, `live_settings_from_store`; пустая/недоступная БД → пустой список, а не статические конфиги (ADR 28.11); TZ МСК | `robot_store` | `test_instance_configs.py`, `test_time_normalization.py` |
| `robot_store.py` | SQLite `robots.db`: счета, инстансы, версии, события, рантайм, `robot_decisions` (персональный журнал сигналов), планировщик; WAL + индексы | CRUD → строки БД; владелец схемы | sqlite3 | `test_robot_store_storage.py`, `test_store.py` |

| `algo/live_signal.py` | Сигнал боя по свежим барам без `paper.csv`: параметры робота → решение; бары пишутся в `market.db`, решения — в `robot_decisions` | `RobotStore` + `LiveSettings` + брокер → планы `(счёт, символ)`; `M5`/`D1` для графика | `algo.live`, `algo.channel_live`, `algo.store`, `robot_library` | `test_live_signal.py` |
| `trade_journal.py` | SQLite `trades.db`, journal заявок и исполнений | заявки → статусы/журнал/CSV; `executed_qty()` = MAX; `exists_active()` = дубль только для `sent/filled/partial/uncertain`; повтор по неактивному статусу обновляет строку и пишет событие | sqlite3 | `test_trade_journal.py`, `test_execution.py` |
| `metrics_store.py`, `results.py` | История метрик и журнал прогонов | метрики → `paper_metrics.db`, `results/runs.csv` | sqlite3 | `test_metrics_store.py` |
| `scheduler.py` | Планировщик заданий роботов; режимы `off`/`robots`/`all` через `ALGO_SCHEDULER_MODE`; системные задания не создаются, старые удаляются при старте | `jobs` → запуски в `robots.db`; исполняются только `inst:*`, чужие системные задания — `SKIP-SYSTEM`/`log_only` | `robot_store` | `test_scheduler.py` |
| `scripts/33_shadow_live.py` | Теневой прогон: только `planned`-журнал | `paper.csv` → `shadow.json` (counts/issues); ошибка API сверки пишется в `reconcile_error`, не в `issues` | `broker`, `portfolio` | `test_shadow.py` |
| `scripts/32_paper_report.py` | Отчёт по бумажному журналу | `paper.csv` → строки метрик по активным инстансам store + снимок в `paper_metrics.db`; сравнения с ожиданием и robot_compare нет | `instance_configs`, `metrics_store` | `test_report.py` |
| `scripts/40_watchdog.py` | Сторож живости контура | `paper.csv`, systemd (включая backup.timer), STOP, `market.db`, STOP/STOP_REAL, возраст `results/backup.json` → `results/health.json`; проверки tracking error удалены (ADR 28.11), старый бэкап — warning | systemd, `algo.store` | `test_watchdog.py` |
| `scripts/95_backup_db.py`, `infra/systemd/algotrading-backup.{timer,service}` | Ежедневный бэкап трёх БД в 03:00 | `trades.db`, `robots.db`, `paper_metrics.db` через sqlite backup API + `integrity_check` → `backups/db` (30 daily + 12 monthly, 0700/0600) и состояние `results/backup.json` | sqlite3, systemd | `test_backup.py`, `test_watchdog.py` |
| `strategy_descriptions.py`, `robot_library.py` | Единые описания/схемы стратегий | id → name/description/defaults/schema; SPEC зафиксированы в коде (не выводятся из реестра) | `strategies` | `test_instance_configs.py` |
| `instruments.py`, `instruments_catalog.py`, `iss.py` | Справочник инструментов и MOEX ISS | symbol → mult/tick digits; каталог (~595k) | requests | `test_instruments_catalog.py` |
| `rollover.py`, `rollover_integration.py`, `scripts/35_rollover_live.py` | Перекладка контрактов | roll → planned-заявки; не включены по умолчанию; раннер сверяет позиции по журналу, неопределённость пропускает счёт, расхождения пишет в `rollover_run.json` без STOP | `broker`, `portfolio`, `journal_positions` | `test_rollover*.py` |
| `algo/journal_positions.py` | Единая модель позиций контура для сверки с брокером | `live.csv` + исполнения из `trades.db` → `{symbol: qty}` и число `uncertain`; используется боевым раннером и перекладкой | `trade_journal` | `test_journal_positions.py`, `test_live_execution.py`, `test_rollover_live.py` |

## 2. Денежные потоки, метрики, БД (новый контур)

| Часть | Роль | Входы → выходы, сайд-эффекты | Зависимости | Тесты |
|---|---|---|---|---|
| `cash_flows.py` | Чистые DTO и расчёты | `CashFlow`, `RobotSizing` → `preview_cash_flow()`, `validate_cash_flow()`, `stress_preview()`; записи нет | `portfolio.size_contracts` | `test_cash_flows.py` |
| `portfolio_metrics.py` | Метрики без искажений потоками | кривая → TWR/MWR/DD/Sharpe/Sortino/PF/Winrate/Expectancy; короткая история → `None`→«н/д» | stdlib | `test_portfolio_metrics.py` |
| `cash_flow_store.py` | Новые таблицы в `robots.db` | поток → `cash_flows`+`cash_flow_lot_impacts`+`instance_events`; `equity_snapshots`; идемпотентность по `key` | `robot_store._conn()` | `test_cash_flow_store.py` |
| `account_poller.py` | Опрос счетов | брокер → снимки equity; подтверждение потока из `/v1/accounts/{id}/transactions`; `fresh_equity()`, `size_for_trade()` | `cash_flow_store`, `pg_store`,Finam | `test_account_poller.py` |
| `pg_store.py` | PostgreSQL/TimescaleDB | DSN из `auth.json` → схема/запись/чтение снимков и потоков; без DSN — no-op | psycopg2 | `test_pg_store.py` |
| `broker/base.py`, `registry.py` | `IBrokerAdapter` и реестр | только `finam`; секреты не попадают в типы | — | `test_service_foundation.py`, `test_broker_adapters.py` |
| `broker/finam.py`, `finam_adapter.py` | Рабочий адаптер REST | JWT, лимиты, котировки, счета, заявки | requests | `test_broker.py` |
| `broker/secrets.py` | Секреты по имени | `auth.json` или `{env:...}` → строка; значения не логируются | — | `test_secrets.py` |
| `broker/execution.py`, `live_guard.py`, `position_ops.py` | Шлюз заявок | `OrderRequest` → `OrderResult`, LOCAL lock, STOP, battle limits (номинал по итоговой позиции `Order.result_qty`, ADR 25.11), reconcile; `duplicate` только если заявка могла уйти брокеру (dry-run/rejected/blocked/error разрешают повтор); `close_all(store, account_id)` закрывает позиции одного счёта по данным брокера (не по активным роботам), минуя STOP и лимиты входа; паи фонда пропускаются | `trade_journal` | `test_execution.py`, `test_live_guard.py`, `test_position_ops.py`, `test_mm_limits.py` |

## 3. Web и интерфейс

| Часть | Роль | Входы → выходы, сайд-эффекты | Зависимости | Тесты |
|---|---|---|---|---|
| `web/app.py` | FastAPI: раздача React и API (`/api/state`, `/api/config`, `/api/metrics`, `/api/trades`, `/api/stop`, `/api/candles`, `/api/quote`); прямые ссылки всех семи разделов панели и `/ui/...` отдают `react_index()`; свечи читаются из `market.db`, брокер — fallback | HTTP → JSON/HTML; фоновые циклы кэша/здоровья/опроса счетов | `instances_api`, `cash_flows_api`, `algo.store` | `test_http_api.py`, `test_web_cache.py`, `check-all.mjs` |
| `web/instances_api.py` | CRUD роботов и счетов, `TEST/LIVE`, ключи/журнал/логи, `money_market`, ручной `/api/live-run` (неблокирующий `flock`: второй прогон → 409), `/api/live-state` (с причиной STOP_REAL), `/api/live-orders`, STOP, планировщик, `POST /api/positions/close-all` с обязательным `{account}` (только позиции этого счёта), `GET /api/instances/{id}/decisions`; PATCH привязывает готовую ссылку `key_ref`, `/accounts/{id}/refresh` подхватывает уже сохранённый `acc:<id>` | HTTP → `RobotStore`/broker; инвалидация `invalidate_analytics()` | `algo.*`, broker | `test_instances_api.py`, `test_http_api.py`, `test_gui_v2_api.py`, `test_live_run_guard.py` |
| `algo/robot_schedule.py` | Отдельный модуль расписания робота: дефолт из параметров робота (вход/выход, `time_buy`/`time_sell`, дни), валидация HH:MM/дней/окна, чтение и запись задания `inst:<id>:schedule` через `RobotStore.upsert_job()` | инстанс + payload → настройки задания в `scheduler_jobs`; галка не удаляет задание, а ставит `enabled=0` | `algo.scheduler`, `RobotStore` | `test_robot_schedule.py` |
| `algo/robot_trade.py` | Одна кнопка «Старт/Стоп»: статус робота + его задание + разрешение живых заданий; робот с виртуальным счётом не стартует | `start/stop(store, iid)` → состояние и список включённых заданий | `RobotStore`, `live_control` | `test_robot_trade.py` |
| `scripts/36_mm_rebalance.py` | Тонкая оболочка планировщика: вызывает существующий API `/api/money-market/{id}/rebalance` (лимиты не дублируются) | `--instance`, `--regime` → JSON результата | HTTP API панели | `test_robot_schedule.py`, `test_mm_limits.py` |
| `algo/live_control.py` | Вкл/выкл реальной торговли через задания `inst:*` активных живых роботов: проверяет роботов, счета, STOP_REAL; состояние берётся из store, а не из `.env`; вкл/выкл пишутся в `results/trading_toggle.jsonl` | HTTP/API → `enable/disable(store)` заданий роботов | `robot_store` | `test_live_control.py`, `test_http_api.py`, проверка на WSL |
| `web/trading_api.py` | `/api/trading/status`, `/api/trading/toggle`, `/api/trading/audit` — единственный путь включения/выключения реальной торговли через `live_control` (дубль `/api/live-control/*` удалён 28.11) и чтение журнала переключений | HTTP → задания `inst:*` активных живых роботов; реальные заявки только по включённому заданию | `algo.live_control` | `test_http_api.py` |
| `web/cash_flows_api.py` | `/api/cash-flows/*`, `/api/portfolio/analytics`, `/api/portfolio/equity` | preview/apply/sync/equity/analytics; ручное применение — только paper | `cash_flows`, `account_poller`, `pg_store` | `test_web_cash_flows.py`, `test_http_api.py` |
| `webui/src/App.tsx`, `store/ui.ts` | Каркас: 7 разделов, топбар, темы/плотность, STOP; deep-link `/robots` (и `/ui/robots`) открывает нужный раздел, `pushState`/`popstate` синхронизируют URL | AJAX → Zustand/localStorage; смена раздела пишет URL | React, TanStack Query | `check-all.mjs`, `test_http_api.py` |
| `webui/src/lib/api.ts`, `types.ts` | Единый клиент и DTO | fetch `/api/...` → типизированные данные; ошибка = `ApiError` | — | `npm test` |
| `webui/src/lib/offline.ts` | Dexie/IndexedDB | ошибка сети → кэш счетов/роботов/сделок/потоков/логов | dexie | `offline.test.ts` |
| `webui/src/lib/format.ts`, `csv.ts` | Форматирование и экспорт | числа→«н/д»/рубли/%, строки→CSV (BOM) | — | `format.test.ts` |
| `webui/src/lib/resultText.ts` | Человекочитаемые уведомления панели: сводка справочника инструментов, результаты действий с инструментами и фондом вместо сырого JSON | ответ API + действие → русская фраза с числами, причиной и ошибкой | `format.ts`, `Robots.tsx` | `resultText.test.ts`, `check-all.mjs` |
| `webui/src/lib/robotEquity.ts` | Equity робота для таблицы: своя строка `runtime_state`, иначе equity реального счёта из аналитики (фонд не пишет runtime) | robot + runtime + analytics → число/null | `api.ts`, `types.ts` | `robotEquity.test.ts` |
| `webui/src/lib/tableFilter.ts` | Поиск по строке таблицы: рекурсивный текст простых полей, вложенных объектов и массивов (глубина 3, защита от ссылок), регистронезависимо | строка + запрос → `rowMatches`/`rowText` | — | `tableFilter.test.ts` |
| `webui/src/components/ui.tsx` | Общие элементы панели: `Card`, `Kpi`, `Tabs`, `DataTable`, диалоги. `DataTable` хранит сортировку/видимость колонок в localStorage, ищет по строкам через `rowMatches`; отфильтрованный массив мемоизируется и `autoResetPageIndex` выключен — иначе react-table на новую ссылку `data` зацикливает `setState` и вешает вкладку | props → таблица/диалог; сайд-эффект — записи `dt:<key>:sort/cols` | Radix, TanStack Table | `npm test`, `check-all.mjs` |
| `webui/src/sections/Portfolio.tsx` | KPI, кривая, позиции, аллокация, метрики | `/api/portfolio/*` → графики/таблицы | lightweight-charts | `check-all.mjs` |
| `webui/src/sections/Charts.tsx` | Свечи; выбор робота/инструмента (вместо всегда первого), маркеры сделок, заявок и потоков по включённым слоям, вкладка «Заявки брокера», предупреждение о корреляции | `/api/candles`, `/api/trades`, `/api/live-orders`, `/api/cash-flows`, `/api/runtime` + фильтр ALL/TEST/LIVE | lightweight-charts | `check-all.mjs` |
| `webui/src/sections/Robots.tsx` | Полный цикл робота: фильтр ALL/TEST/LIVE, живые роботы сверху, действия `start/pause/stop/archive/promote/delete/close`, смена счёта, money-market rebalance/close; вкладки «Боевой контур» (ручной прогон dry-run/arm, таймер, STOP с причиной STOP_REAL, «Закрыть всё на счёте» по выбранному в шапке счёту, заявки), «Инструменты» (поиск, избранное, обновление каталога, создание робота по тикеру), блок «Расписание робота» внутри формы «Настроить» (галка, дни/времена/интервал/окно/команда), русские подписи параметров алгоритмов, шаблоны, мастер (поля калькулятора потоков не сохраняются в роботе; «Максимальный лот» пишется в `max_qty`), дневник | RHF+Zod и TanStack Query → `/api/instances`, `/api/live-*`, `/api/instruments*`, `/api/scheduler/*`, `/api/accounts` | RHF, Zod, Radix | `check-all.mjs`, `npm test` |
| `webui/src/sections/Simulation.tsx` | Песочница и симулятор потоков | `/api/cash-flows/preview` → таблица «лот до→после» | — | `check-all.mjs` |
| `webui/src/sections/Accounts.tsx` | Счета с редактированием ID (старый ID в URL PATCH, новый в `new_id`), ключ и кнопка «Баланс» с состоянием запроса, кнопка «Закрыть всё» на строке каждого LIVE-счёта (только его позиции), результат рядом с таблицей, реальные брокеры с кнопкой «Проверить», сервисный ключ, потоки, sync, поиск и сохранение сортировки/колонок | `/api/accounts`, `/api/accounts/{id}/refresh`, `/api/keys`, `/api/brokers`, `/api/brokers/{name}/check`, `/api/service-key`, `/api/cash-flows` → таблицы/диалоги | `DataTable` | `check-all.mjs`, `test_instances_api.py` |
| `webui/src/sections/History.tsx` | Журнал сделок с фильтрами по роботу/счёту/дате, операции, пересчёт лотов, CSV | `/api/journal`, `/api/cash-flows` → таблицы | — | `check-all.mjs` |
| `webui/src/sections/Logs.tsx` | Фильтры по реальным источникам (`orders`, `instances`, `scheduler`, `health`), поиск, JSON-инспектор | `/api/logs` → таблица + JsonDialog | Radix | `check-all.mjs` |
| `webui/check.mjs`, `check-all.mjs` | Обязательная headless-проверка GUI | Chrome → обход 7 разделов/вкладок реальными кликами, all deep-link (8 адресов), диалоги (подтверждение удаления счёта, JSON-инспектор логов, карточки «Настроить»/расписание и мастер робота — только открытие и отмена), перехваченная правка счёта (старый ID в URL, новый в теле), сохранение ключа (секрет в `/api/keys`, `acc:<id>` в PATCH) и ввод в поиск по строкам таблицы счетов (страница не должна подвисать); 0 ошибок JS | puppeteer-core | `./run.sh check-ui` перед показом |
| `webui/vite.config.ts` | Сборка SPA: `base=/ui/`, proxy `/api`, четыре чанка (index/query/charts/vendor) вместо одного 721 КБ | `npm run build` → `webui/dist` | Vite, Rollup | `npm test`, `check-all.mjs` |

## 4. Инфраструктура, скрипты, данные

| Часть | Роль | Входы → выходы, сайд-эффекты | Зависимости | Тесты |
|---|---|---|---|---|
| `infra/db/schema_timescale.sql` | Целевая DDL PG: NUMERIC-поля, append-only, уникальные ключи, гипертаблицы при наличии расширения | SQL → таблицы; к рабочей SQLite не применяется | PostgreSQL | `test_timescale_schema.py` |
| `infra/systemd/algotrading-web.service` | Юнит панели | `Requires/After=postgresql`; Restart=always | systemd | проверка на WSL |
| `scripts/start_project.sh` | Старт вместе с WSL | PG → схема/миграция → удаление старого UI → юнит → HTTP-проверка | sudo, curl | запуск на WSL |
| `scripts/98_assign_paper_accounts.py` | Разводит бумажных роботов по отдельным TEST-счетам `paper-<id>`; идемпотентно, боевых не трогает | `./run.sh assign-paper-accounts` | `robot_store` | `test_assign_paper_accounts.py` |
| `scripts/97_migrate_to_postgres.py` | Идемпотентная миграция SQLite→PG | `robots.db` → счета/роботы/потоки/снимки; одна строка сводки | `pg_store` | ручной прогон |
| `scripts/deploy_wsl.sh` | Деплой только по whitelist | rsync → WSL, md5, опц. restart | ssh | `deploy --list` |
| `scripts/34_live_execute.py` | Боевой контур | сигнал считается в `live_signal` по свежим барам; заявки через шлюз без ARM/env-флага; STOP/лимиты/идемпотентность сохраняются; режим цены из плана приводится к `PricingMode`; счёт без ключа/equity пропускается, остальные продолжают; `--dry-run` — явная репетиция; факт позиции пишется в `runtime_state`; STOP между заявками (неопределённость, расхождение, `assert_stop_clear`) прерывает прогон с кодом 2, но сводка `live_run.json` всё равно записывается с причиной | `live_signal`, `broker`, `trade_journal`, `journal_positions`, `robot_store` | `test_live_execution.py`, `test_live_runner_accounts.py`, `test_execution.py` |
| `scripts/*.py` (01–96) | Скачивание данных, прогоны, отчёты, уборка, бекап, MCP-профили | см. `scripts/README.md` | — | соответствующие `test_*.py` |
| `tests/test_*.py` | 289 Python-тестов; один файл = одна тема | `./run.sh test` | unittest | — |
| `infra/db/*.db`, `results/*` | Рабочие данные и журналы; не редактировать вручную | данные для движка/панели | — | — |
| `docs/decisions.md`, `PROGRESS.md`, `docs/ONBOARDING.md`, этот файл | Память проекта и обязательная документация | ADR/статус/онбординг/инвентарь | — | проверка при ревью |

Любая новая строка здесь должна отвечать на вопросы: **зачем, что приходит,
что уходит/меняется, от чего зависит, как проверяется**.
| `scripts/99_robot_names_descriptions.py` | Однократно проставляет простые имена и описания идеи 19 существующим роботам; только `note`/`description` + событие в журнале | запуск скрипта → UPDATE instances + instance_events | `robot_store` | ручной прогон на WSL |
