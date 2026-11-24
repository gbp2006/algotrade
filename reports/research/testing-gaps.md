# Тестовые пропуски критических путей (по состоянию на 24.11.2026)

Инвентарь: `tests/*.py` — 27 файлов / 136 тестов; `algo/` — ~55, `scripts/` — ~80, `web/*.py` — 3. Покрытие хорошее на уровне «счастливого пути» (journal, store, scheduler, watchdog, execution, broker), но почти нет тестов на **переходные состояния** заявки и на **HTTP-слой**.

## Обозначения риска
**Деньги** — лишняя/пропущенная заявка или неверная позиция; **STOP** — ложный/непоставленный STOP_REAL; **UI** — регресс панели; **Косметика** — мелочи.

## Таблица пропусков

| Путь | Состояние | Риск | Минимальный тест |
|---|---|---|---|
| `execution.py::OrderGateway.submit(stop=STOP_REAL)` | `test_live_guard.py::test_gateway_blocks_per_order`: флаг уже стоит до submit. Нет сценария «флаг появился между двумя submit» | Деньги | submit#1 → создать STOP_REAL → submit#2 → `Result.blocked`, в журнале 1 запись |
| `34_live_execute.py:273` `assert_stop_clear` перед submit | Не тестируется на уровне раннера (только `order_state`/guard изолированно) | STOP | прогнать `plan` с STOP_REAL → ни одного `place_*`, STOP не снят |
| `trade_journal.refresh_executions` | Только `ORDER_STATUS_FILLED` (`test_refresh_executions`) | Деньги | PARTIALLY_FILLED(1) из 2 → status=partial + `executed_qty()==1`; затем FILLED(2) → executed_qty==2, одна строка в `trades` (без дубля) |
| `trade_journal.refresh_executions` CANCELLED/REJECTED | Нет ни одного теста | STOP | статус CANCELLED → `status=cancelled`, позиция не учитывается, `uncertain` не растёт |
| `trade_journal.mark_execution` несовпадение qty | Идемпотентность проверена только одинаковым `filled:1` | Деньги | partial:1 + filled:1 → в `trades` корректная сумма, маркер `status:qty` не дублируется |
| `trade_journal.executed_qty()` | Прямого теста нет | Деньги | вернуть 0/1/2 для нет заявки / partial / filled |
| `34_live_execute.py::journal_positions` | Только `filled` (`test_filled_orders_stay_in_position_model`) | STOP/Деньги | (а) partial计入 позицию; (б) `sent` с order_id计入; (в) `uncertain>0` → флаг STOP_REAL и пропуск прогона; (г) фильтр по `account` не смешивает счета |
| `34_live_execute.py::plan_targets` конфликт `pricings` (строка 245) | Есть тест `source_config`/exposure; нет теста двух разных pricing у одного робота | Деньги | два робота с `signal` и `marketable` → строка拒绝, `sent` не выставляется |
| `plan_targets` `trade_on_expiry` / размеры | Не покрыто | Деньги | день экспирации + `expiry=False` → пропуск; суммарный exposure → ожидаемые lot'ы |
| `expected.py::expected(..., cfg_for=...)` и `expected_pnl` | Прямых тестов нет (в `test_report.py` тестируется др. функция `32_paper_report.expected`) | STOP | этот же набор баров с cfg_for, меняющим параметр с даты X → tracking error == 0; без cfg_for → отличен |
| `40_watchdog.py::tracking_errors` при недоступном отчёте | Тесты всегда мокируют `tracking_errors=[]`; ветка исключения (строка 98–99) не покрыта | STOP | подменить `mod.build_rows` на raise → результат — warning, а не `ok=False`/503 (или явно зафиксировать текущее поведение как problem) |
| `40_watchdog.py::check()` STOP-флаг | Проверка `STOP.exists()` → warning, теста нет | STOP | создать STOP → `warnings` содержит «стоп-флаг», `ok` остаётся True |
| `robot_store.init_db` миграции ALTER TABLE (`key_ref`, `trading_code`, `source_config`) | Теста на старой схеме нет | STOP/Деньги | создать БД без этих колонок → `init_db()` → колонки добавлены, данные не потеряны |
| `robot_store.delete_instance` каскад | Тестируются только active/live/archive (`test_gui_v2_api.py`) | Косметика/Деньги | удалить архивного робота с runtime_state+param_versions+instance_events → все 3 таблицы пусты, journal нетронут |
| `robot_store.delete_instance` paper **draft** | Нет теста (код разрешает draft/archived) | UI | удалить paper draft → успех |
| `instances_api.archive_list` статус `stopped` | Тест только `archived`; код фильтрует `("archived","stopped")` | UI | робот со статусом stopped попадает в архив с `last_decision`/`position` из runtime |
| `account_analytics` real-счёт через FinamBroker | Тест только virtual | Деньги/секреты | подменить `FinamBroker` → equity/positions в ответе; `key_ref` и секрет не утекают в JSON |
| `cached_analytics` TTL `_ANALYTICS_TTL=30` | Тест только ручной `invalidate_analytics()` | UI | подменить `time.monotonic` → после 30 с данные пересчитаны |
| `stop_real_view` невалидный `action` | set/clear покрыты, ветка `HTTPException(400)` — нет | Косметика | `stop_real_view("boom")` → 400 |
| `/api/logs`, `/api/archive`, `/api/accounts/analytics` как HTTP | Только view-функции, ни одного `TestClient` | UI | 4 теста: 200/400/409, лимит `limit` (clamp 1..500/1000), сортировка логов по `ts desc`, битый JSON-файл → не 500 |
| `app.py::alerts_digest` / `alerts_seen` / `ack_alerts` | Нет ни одного теста (grep по `alerts_seen`/`ack` в tests — пусто) | UI | digest стабилен при смене времени, меняется при смене текста; битый `alerts_seen.json` → «не прочитано»; ack с пустым digest → `dismissed=False` |
| `web/static/ui-state.js` (память вкладок, `algo.ui.v1`) | JS не тестируется вообще | UI | минимально: в `test_instances_api.py` проверять наличие `data-ui-nav`/`data-ui-restore`/`ui-state.js` в шаблонах (smoke) |
| `/api/logs` чтение `_json_file` здоровья | Нет теста | Косметика | битый/отсутствующий health.json → запись с источником, без 500 |

## Тесты, ставшие неактуальными / вводящими в заблуждение

1. `test_service_foundation.py::test_place_order_dispatch` — тестирует `FinamAdapter.place_order` (уровень адаптера). Реальный живой путь идёт через `OrderGateway.submit` (`execution.py`) с идемпотентностью, STOP и uncertain. Зелёный тест создаёт **ложное ощущение** покрытия отправки заявки. Не удалять, но дополнить gateway-тестами из таблицы.
2. `test_live_execution.py::test_live_views_and_stop` (в `test_instances_api.py`) использует «плоский» `live.csv` с полем `client_id` — это легаси-формат; журнал теперь SQLite + CSV-зеркало. Тест проходит, но не проверяет реальный `TRADES_DB`.
3. `test_trade_journal.py::test_migrate_csv` — миграция покрыта, но нет теста «migrate_csv после append» и «дубли строк в CSV»; при текущей схеме поведение неочевидно.
4. `test_watchdog.py` все прогоны мокируют `tracking_errors`, поэтому регресс в расчёте ожидания/`cfg_for` не ловится ни одним тестом стража.

## Приоритет (минимум на первый коммит)

1. gateway STOP mid-session + `journal_positions` partial/uncertain — **деньги/STOP**.
2. `refresh_executions` partial→filled + `executed_qty` — **деньги**.
3. `expected(cfg_for)` + миграции БД — **ложный STOP**.
4. HTTP-тесты через `TestClient` для `/api/archive`, `/api/accounts/analytics`, `/api/logs`, ACK алертов — **регресс UI**.
