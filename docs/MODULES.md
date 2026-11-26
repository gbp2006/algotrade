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
| `configs.py`, `robot_configs.py`, `risk_configs.py` | Статические реестры конфигураций | код → параметры стратегий; новые risk-конфиги не активны | — | `test_risk.py` |
| `strategies/*.py` | Сигналы | бар → `ENTER_LONG/SHORT/EXIT/HOLD`; **только сигналы**, не знают про деньги | `risk.py` (опц.) | `test_engine.py`, `test_donchian_live.py` |
| `author.py`, `mvp.py`, `live.py`, `channel_live.py` | Дневная логика решений | цены/канал → написание `paper.csv`, ожидание | `configs`, `portfolio` | `test_paper_live.py`, `test_live_execution.py` |
| `portfolio.py` | **Единственный расчёт лотности** | `equity, price, mult, exposure` → `int`; 0 при битых данных; `ledger()`, `account_card()`, `drawdown_stats()` | stdlib | `test_risk.py`, ADR 24.11 |
| `risk.py` | ATR-лестница и дневной лимит | ATR(14)/медиана 252 → экспозиция; **в контур не подключено** | pandas, `portfolio` | `test_risk.py` |
| `expected.py`, `instance_configs.py` | Ожидание P&L с версиями параметров по времени решения | `paper.csv` + store → expected; TZ МСК | `robot_store` | `test_report.py`, `test_time_normalization.py` |
| `robot_store.py` | SQLite `robots.db`: счета, инстансы, версии, события, рантайм, планировщик; WAL + индексы | CRUD → строки БД; владелец схемы | sqlite3 | `test_robot_store_storage.py`, `test_store.py` |
| `trade_journal.py` | SQLite `trades.db`, journal заявок и исполнений | заявки → статусы/журнал/CSV; `executed_qty()` = MAX | sqlite3 | `test_trade_journal.py`, `test_execution.py` |
| `metrics_store.py`, `results.py` | История метрик и журнал прогонов | метрики → `paper_metrics.db`, `results/runs.csv` | sqlite3 | `test_metrics_store.py` |
| `scheduler.py` | Планировщик заданий (shadow) | jobs → запуски в `robots.db` | `robot_store` | `test_scheduler.py` |
| `scripts/33_shadow_live.py` | Теневой прогон G3: только `planned`-журнал | `paper.csv` → `shadow.json` (counts/issues); ошибка API сверки пишется в `reconcile_error`, не в `issues` | `broker`, `portfolio` | `test_shadow.py` |
| `strategy_descriptions.py`, `robot_library.py` | Единые описания/схемы стратегий | id → name/description/defaults/schema | `strategies` | `test_instance_configs.py` |
| `instruments.py`, `instruments_catalog.py`, `iss.py` | Справочник инструментов и MOEX ISS | symbol → mult/tick digits; каталог (~595k) | requests | `test_instruments_catalog.py` |
| `money_market.py`, `rollover.py`, `rollover_integration.py` | Фонд денежного рынка и перекладка контрактов | H1→FMMM, roll → planned-заявки; не включены по умолчанию | `broker`, `portfolio` | `test_money_market.py`, `test_rollover*.py` |

## 2. Денежные потоки, метрики, БД (новый контур)

| Часть | Роль | Входы → выходы, сайд-эффекты | Зависимости | Тесты |
|---|---|---|---|---|
| `cash_flows.py` | Чистые DTO и расчёты | `CashFlow`, `RobotSizing` → `preview_cash_flow()`, `validate_cash_flow()`, `stress_preview()`; записи нет | `portfolio.size_contracts` | `test_cash_flows.py` |
| `portfolio_metrics.py` | Метрики без искажений потоками | кривая → TWR/MWR/DD/Sharpe/Sortino/PF/Winrate/Expectancy; короткая история → `None`→«н/д» | stdlib | `test_portfolio_metrics.py` |
| `cash_flow_store.py` | Новые таблицы в `robots.db` | поток → `cash_flows`+`cash_flow_lot_impacts`+`instance_events`; `equity_snapshots`; идемпотентность по `key` | `robot_store._conn()` | `test_cash_flow_store.py` |
| `account_poller.py` | Опрос счетов | брокер → снимки equity; подтверждение потока из `/v1/accounts/{id}/transactions`; `fresh_equity()`, `size_for_trade()` | `cash_flow_store`, `pg_store`,Finam | `test_account_poller.py` |
| `pg_store.py` | PostgreSQL/TimescaleDB | DSN из `auth.json` → схема/запись/чтение снимков и потоков; без DSN — no-op | psycopg2 | `test_pg_store.py` |
| `robot_modules.py` | Модули сайзинга/выходов | `FIXED/PERCENT/STEPPED`, SL/TP/трейлинг/безубыток/время/Reduce-Only → чистые функции; в контур не подключено | `portfolio` | `test_robot_modules.py` |
| `broker/base.py`, `registry.py` | `IBrokerAdapter` и реестр | `finam`, `tinvest`; секреты не попадают в типы | — | `test_service_foundation.py`, `test_broker_adapters.py` |
| `broker/finam.py`, `finam_adapter.py` | Рабочий адаптер REST | JWT, лимиты, котировки, счета, заявки | requests | `test_broker.py` |
| `broker/tinvest_adapter.py` | Адаптер Т‑Инвестиций | без токена/gRPC инертен: `NotConfiguredError`; sandbox=LIVE метка TEST | `secrets` | `test_broker_adapters.py` |
| `broker/secrets.py` | Секреты по имени | `auth.json` или `{env:...}` → строка; значения не логируются | — | `test_secrets.py` |
| `broker/instrument_map.py` | Маппинг тикеров | ticker → FIGI/UID/Board/Finam symbol | — | `test_broker_adapters.py` |
| `broker/execution.py`, `live_guard.py`, `position_ops.py` | Шлюз заявок | `OrderRequest` → `OrderResult`, LOCAL lock, STOP, battle limits (номинал по итоговой позиции `Order.result_qty`, ADR 25.11), reconcile | `trade_journal` | `test_execution.py`, `test_live_guard.py` |

## 3. Web и интерфейс

| Часть | Роль | Входы → выходы, сайд-эффекты | Зависимости | Тесты |
|---|---|---|---|---|
| `web/app.py` | FastAPI: раздача React на всех адресах страниц и «старые» API (`/api/state`, `/api/config`, `/api/metrics`, `/api/trades`, `/api/stop`, `/api/candles`, `/api/quote`) | HTTP → JSON/HTML; фоновые циклы кэша/здоровья/опроса счетов | `instances_api`, `cash_flows_api` | `test_http_api.py`, `test_web_cache.py` |
| `web/instances_api.py` | CRUD роботов и счетов (DELETE с защитой от привязанных), `TEST/LIVE`, `enabled`, ключи/журнал/логи; справочник инструментов, money-market rebalance/close, ручной `/api/live-run`, `/api/live-state`, `/api/live-orders`, `/api/live-control`, STOP, планировщик, `/api/arm-state` | HTTP → `RobotStore`/broker/systemd; инвалидация `invalidate_analytics()`; флаги реальной отправки пишутся в `results/arm_state.json` (env — fallback) | `algo.*`, broker, systemd | `test_instances_api.py`, `test_http_api.py`, `test_gui_v2_api.py` |
| `results/arm_state.json` | Разрешения панели на реальную отправку: `mm`, `close` (по умолчанию `false` = dry-run) | POST `/api/arm-state` → JSON; читается `arm_enabled()` вместо env | `web/instances_api.py` | `test_http_api.py::test_arm_state_toggle` |
| `algo/robot_schedule.py` | Отдельный модуль расписания робота: дефолт из параметров робота (вход/выход, `time_buy`/`time_sell`, дни), валидация HH:MM/дней/окна, чтение и запись задания `inst:<id>:schedule` через `RobotStore.upsert_job()` | инстанс + payload → настройки задания в `scheduler_jobs`; галка не удаляет задание, а ставит `enabled=0` | `algo.scheduler`, `RobotStore` | `test_robot_schedule.py` |
| `algo/live_control.py` | Вкл/выкл реальной торговли через таймер systemd: проверяет активных live-роботов, счета, STOP_REAL; состояние берётся из `list-timers`, а не из `.env`; вкл/выкл пишутся в `results/trading_toggle.jsonl` | HTTP/API → `enable/disable` таймера `algotrading-live.timer` | systemd, `robot_store` | `test_http_api.py`, проверка на WSL |
| `web/trading_api.py` | `/api/trading/status`, `/api/trading/toggle`, `/api/trading/audit` — управление таймером раннера через `live_control` и чтение журнала переключений | HTTP → systemd-таймер; реальные заявки только по расписанию | `algo.live_control` | `test_http_api.py` |
| `web/cash_flows_api.py` | `/api/cash-flows/*`, `/api/portfolio/*`, `/api/portfolio/reconciliation` | preview/apply/sync/equity/analytics; ручное применение — только paper | `cash_flows`, `account_poller`, `pg_store` | `test_web_cash_flows.py`, `test_http_api.py` |
| `webui/src/App.tsx`, `store/ui.ts` | Каркас: 7 разделов, топбар, темы/плотность, STOP; deep-link `/robots` (и `/ui/robots`) открывает нужный раздел, `pushState`/`popstate` синхронизируют URL | AJAX → Zustand/localStorage; смена раздела пишет URL | React, TanStack Query | `check-all.mjs`, `test_http_api.py` |
| `webui/src/lib/api.ts`, `types.ts` | Единый клиент и DTO | fetch `/api/...` → типизированные данные; ошибка = `ApiError` | — | `npm test` |
| `webui/src/lib/offline.ts` | Dexie/IndexedDB | ошибка сети → кэш счетов/роботов/сделок/потоков/логов | dexie | `offline.test.ts` |
| `webui/src/lib/format.ts`, `csv.ts` | Форматирование и экспорт | числа→«н/д»/рубли/%, строки→CSV (BOM) | — | `format.test.ts` |
| `webui/src/sections/Portfolio.tsx` | KPI, кривая, позиции, аллокация, метрики, сверка факт | `/api/portfolio/*` → графики/таблицы | lightweight-charts | `check-all.mjs` |
| `webui/src/sections/Charts.tsx` | Свечи, маркеры сделок/потоков, предупреждение о корреляции | `/api/candles`, `/api/trades`, `/api/runtime` | lightweight-charts | `check-all.mjs` |
| `webui/src/sections/Robots.tsx` | Полный цикл робота: фильтр ALL/TEST/LIVE, живые роботы сверху, действия `start/pause/stop/archive/promote/delete/close`, смена счёта, money-market rebalance/close; вкладки «Боевой контур» (ручной прогон dry-run/arm, таймер, STOP, флаги ARM, заявки), «Инструменты» (поиск, избранное, обновление каталога, создание робота по тикеру), «Расписание» (jobs/runs), галка «Расписание» и появляющаяся подвкладка «Расписание робота» (дни/времена/интервал/окно/команда), русские подписи параметров алгоритмов, шаблоны, мастер, дневник | RHF+Zod и TanStack Query → `/api/instances`, `/api/live-*`, `/api/instruments*`, `/api/scheduler/*`, `/api/arm-state` | RHF, Zod, Radix | `check-all.mjs`, `npm test` |
| `webui/src/sections/Simulation.tsx` | Песочница и симулятор потоков | `/api/cash-flows/preview` → таблица «лот до→после» | — | `check-all.mjs` |
| `webui/src/sections/Accounts.tsx` | Счета, коннекторы, потоки, sync | `/api/accounts`, `/api/cash-flows` → таблицы/диалоги | — | `check-all.mjs` |
| `webui/src/sections/History.tsx` | Журнал сделок, операции, пересчёт лотов | `/api/journal`, `/api/cash-flows` → CSV | — | `check-all.mjs` |
| `webui/src/sections/Logs.tsx` | Фильтры, поиск, JSON-инспектор | `/api/logs` → таблица + JsonDialog | Radix | `check-all.mjs` |
| `webui/check.mjs`, `check-all.mjs` | Обязательная headless-проверка GUI | Chrome → обход 7 разделов/вкладок; 0 ошибок JS | puppeteer-core | запуск вручную перед показом |
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
| `scripts/34_live_execute.py` | Боевой контур | сигналы бумаги → заявки через шлюз; `--arm` + финам-флаг; свежий equity; в заявку передаётся целевая позиция для лимита; после прогона пишет факт позиции счёта в `runtime_state` (только наблюдение, ошибка записи не роняет бой) | `broker`, `trade_journal`, `robot_store` | `test_live_execution.py`, `test_execution.py` |
| `scripts/*.py` (01–96) | Скачивание данных, прогоны, отчёты, уборка, бекап, MCP-профили | см. `scripts/README.md` | — | соответствующие `test_*.py` |
| `tests/test_*.py` | 289 Python-тестов; один файл = одна тема | `./run.sh test` | unittest | — |
| `infra/db/*.db`, `results/*` | Рабочие данные и журналы; не редактировать вручную | данные для движка/панели | — | — |
| `docs/decisions.md`, `PROGRESS.md`, `docs/ONBOARDING.md`, этот файл | Память проекта и обязательная документация | ADR/статус/онбординг/инвентарь | — | проверка при ревью |

Любая новая строка здесь должна отвечать на вопросы: **зачем, что приходит,
что уходит/меняется, от чего зависит, как проверяется**.
