# Аудит хранения: БД, CSV-зеркала, логи, бэкапы

Дата: 24.11.2026. Режим: только исследование — код, БД и конфиги не менялись,
коммитов и выкладок нет; `data/`, `materials/`, `cache/` не читались, секреты не
выводились (только имена файлов и режимы доступа).

## Метод

- Локально: `ls/du`, `sqlite3` через Python `file:...?mode=ro` (sqlite_master,
  PRAGMA, COUNT, MIN/MAX, EXPLAIN QUERY PLAN), чтение кода и документации.
- WSL `ssh wsl-algo` (BatchMode, только чтение): те же запросы к рабочим БД,
  `systemctl list-timers`, `journalctl`, `tar -tzf` (только имена), `ls -l`.
- Числа ниже — снимок на 24.11 ~16:00 MSK; WSL — рабочий контур, десктоп —
  локальная копия.

## 1. Инвентарь (факты)

| Хранилище | Десктоп | WSL (рабочий) | Роль по факту |
|---|---|---|---|
| `infra/db/trades.db` | 36 864 B; orders/trades/events = **0/0/0**, journal=WAL | 45 056 B; **18/1/19**, journal=WAL | заявки, статусы, исполнения |
| `results/live.csv` | 6 строк, 20.11 18:27, gitignore | 18 строк (17 planned + 1 filled), gitignore | «зеркало» + читается панелью/скриптами |
| `robots.db` | 86 016 B; 19 инстансов | 139 264 B; 18 инстансов, 363 `scheduler_runs` | инстансы, версии, раунтайм, планировщик |
| `paper.csv` | 32 строки (19–23.11), **в git** | 52 строки (19–24.11), 17 конфигов | решения бумажного контура |
| `paper_metrics.db` | 13 строк equity/snapshot | 32 строки, день 23–24.11 | производные дневные метрики |
| `market.db` | 158,5 MB, 808 552 бара | 156,6 MB, 797 152 бара | бары, `bars(symbol,tf,dt,source)` PK WITHOUT ROWID + `bars_range` |
| `instruments.db` | 26,1 MB, 127 143 строки | 24,5 MB, 127 143 | справочник |
| `results/*.log`, `journald` | `scheduler.log` 205 KB | `web.log` 1,1 MB; journald 24 MB (default) | технические логи |
| `backups/` | нет | 1 tarball 23.11 (15 MB) + 6 каталогов снимков 23–24.11 | ручные снимки перед деплоями |

Источники: `docs/trade-journal.md`, `algo/trade_journal.py`,
`algo/broker/execution.py`, `web/instances_api.py`, `scripts/deploy_wsl.sh`.

## 2. Дублирование и рассинхрон

**WSL сейчас согласован:** 18/18 `client_order_id` совпадают между `orders` и
`live.csv`, расхождений по `ts/status/reason/symbol/side/qty/price` — 0; у одной
заявки 2 события (`planned` → `filled`), у остальных по 1. Единственная сделка:
`2 CNY sell @12.288`, `ts=2026-11-24T11:00:24.177Z` (UTC), счёт из PROGRESS.

**Десктоп — устаревшая и частично чужая копия:**

- `live.csv` 6 строк от 20.11 18:27 с другими `client_order_id` и временем, чем
  на WSL (там те же прогоны записаны в 18:28); `trades.db` пуст, хотя в журнале
  WSL есть исполнение 24.11. Локальный журнал нельзя использовать для сверки.
- `paper.csv` 32 против 52 строк; `robots.db` содержит `promo-test`, `smoke-test`
  (их нет на WSL), на WSL есть `prostushka-test-1` (нет локально).
- `market.db` локально больше на ~11 400 баров — данные расходятся в обе стороны.

**Дублирование ролей:**

1. Заявка живёт одновременно в `orders` и `live.csv`; исполнение — в `trades` +
   `order_events` + перезаписанном `status/reason` в `orders` + изменённой CSV.
2. Бумажные решения — `paper.csv`; метрики — `paper_metrics.db` и `snapshot`;
   позиции — `robots.db.runtime_state` (миграция из `paper.csv` в
   `algo/instance_configs.py:136`). Три хранилища одного смысла.
3. Справочник инструментов дублируется в `instruments.db` и `moex_catalog.db`
   (последний — каталог файлов; на WSL файл нулевого размера).
4. Описания роботов/стратегий — уже отмеченный в брифе дубль между
   `Config.comment`, `RobotSpec.description`, `strategy_descriptions.py`, docs.

**Механические риски дублирования:**

- `OrderGateway._write()` (`execution.py:108-115`) пишет в БД, затем **всегда**
  дописывает CSV. При `tj.append() == False` (дубль) CSV получает вторую строку;
  при падении между записями БД и CSV — расхождение без реконсиляции.
- `mark_execution()` (`trade_journal.py:194-207`) при обновлении CSV читает весь
  файл и перезаписывает его `DictWriter` — при обрыве можно потерять хвост
  зеркала (источник правды при этом не страдает).
- `live.csv` в `.gitignore`: история зеркала не восстанавливается git';
  `paper.csv` и `runs.csv` — в git, т.е. политика версионирования разная.

## 3. Индексы и целостность (проверено EXPLAIN QUERY PLAN)

`trades.db` имеет только `idx_orders_ts`, `idx_orders_account`, `idx_events_cid`.
Запросы, реально используемые journal/сверкой, идут полным сканом:

| Запрос | План сейчас |
|---|---|
| `trades WHERE client_order_id=?` (`executed_qty`) | `SCAN trades` |
| `order_events WHERE ts>?` | `SCAN order_events` |
| `orders WHERE config=? ORDER BY ts DESC` | `SCAN orders USING INDEX idx_orders_ts` (фильтр по config) |
| `param_versions WHERE instance_id=? ORDER BY version DESC` | `SCAN` + `USE TEMP B-TREE` |
| `instance_events WHERE instance_id=? ORDER BY created_at DESC` | `SCAN` + `USE TEMP B-TREE` |
| `scheduler_runs WHERE status=? ORDER BY slot DESC` | `SCAN` + `USE TEMP B-TREE` |
| `runtime_state WHERE updated_at<?` | `SCAN` |

В `robots.db` **нет ни одного индекса**; в `trades.db` **нет ни одного
FOREIGN KEY** (`PRAGMA foreign_key_list` пуст для orders/trades/order_events).
Сейчас это терпимо (18 заявок, 363 запуска), но при росте журнала и истории
версий — линейный рост времени. `market.db`/`instruments.db`/`paper_metrics.db`
индексированы адекватно; `memory.db` — полный набор индексов, `sqlite_stat1`
есть.

Другие находки:

- Идемпотентность `mark_execution()` держится на `LIKE 'status:qty%'` по
  `order_events.detail` без UNIQUE — при двух конкурентых сверках возможны
  дубли событий и строк в `trades` (сейчас дублей нет).
- `response` обрезается до 300 символов (`execution.py:104`), `reason` — до 200
  (`trade_journal.py:101`): у одного filled-заказа `response` ровно 300 символов,
  т.е. ответ брокера уже потерян. Полного сырого ответа нигде нет.
- `param_versions(instance_id, version)` не уникален (дублей в данных пока нет),
  `trades.client_order_id` не имеет ни индекса, ни FK к `orders`.

## 4. Риск потери истории и ретенция

1. **Нет автоматического бэкапа БД.** `docs/trade-journal.md:32` обещает ежедневный
   `POST /api/journal/backup`, но в systemd-таймерах бэкапа нет, файлов
   `trades_*.db` не найдено, cron пуст. Есть только ручные снимки перед
   деплоями (23–24.11) и один tarball от 23.11 с `.env` внутри. Policies
   «30 daily + 1 monthly» из того же документа не реализована.
2. **Снимки содержат секреты.** Tarball `backups/state-before-deploy-*.tar.gz`
   имеет режим 0644 и включает `.env`; каталоги снимков — 0700, но файлы `env`
   внутри. Упомянуто только как факт режима/состава, содержимое не читалось.
3. **Логи неhave ретенции.** Сервисы пишут stdout/stderr в
   `results/*.log` через `append:` (проверено `systemctl cat algotrading-web`);
   `logrotate.d` настроек для algotrading нет, journald — дефолт 24 MB,
   `SystemMaxUse/MaxRetentionSec` закомментированы. `web.log` уже 1,1 MB.
4. **Ретенция CSV не определена:** в `docs/trade-journal.md:14` сказано
   «можно чистить/архивировать», без criteria; `paper-legacy.csv` — мёртвый
   формат 18.11, хранится рядом с актуальным.
5. **Копия на десктопе не является бэкапом** (раздел 2), а деплой whitelist
   (`scripts/deploy_wsl.sh`) БД и CSV не трогает — правильно, но делает
   расхождение постоянным.
6. **Смешение форматов/единиц:** `orders.ts` — локальный ISO без таймзоны,
   `trades.ts` — UTC с `Z` и мс, `live.csv.ts` — локальный; `multiplier`
   1000.0 для CNY и 1.644562 для RIZ6 смешивает шаг цены и стоимость пункта;
   human-отчёт показывает `ORDER_STATUS_*`/`planned`, raw `6b3b…`, JSON в
   `response`, `None` как строку.

## 5. Предлагаемая иерархия: источник правды → зеркало → отчёт

| Уровень | Что | Правило |
|---|---|---|
| I. Источник правды | `trades.db` (orders/order_events/trades), `robots.db`, `market.db`, `instruments.db`, `paper.csv` (пока — журнал бумажных решений) | только append/версионированные изменения; никаких чисток; WAL + `PRAGMA foreign_keys=ON`; uniqueness на уровне схемы |
| II. Зеркало | `results/live.csv`, `paper_metrics.db`, дневные CSV-выгрузки | **пересоздаётся** из уровня I по требованию; никогда не является арбитром; контрольная сумма/диапазон дат в мета |
| III. Отчёт | `reports/*.md`, `/api/journal`, `/trade`, `/robots` | собирается из I+II; человеку — смысл и деньги; технические ID — по раскрытию; не пишется сервисами |

Практические шаги: сделать `/api/journal` единственным источником чтения для панели;
перевести `live_orders_view()` (`instances_api.py:566`) и счёт G2/G3 с CSV на
уровень I; оставить CSV только для ручного просмотра/старых скриптов; добавить
ежедневную проверку «зеркало == источник» (сейчас расхождений 0 — зафиксировать
это как тест/метрику).

## 6. Предложения по SQL (только предложение, не применялось)

```sql
-- trades.db: быстрые срезы и защита от повторных событий
CREATE UNIQUE INDEX IF NOT EXISTS ux_events_marker
  ON order_events(client_order_id, status, detail);
CREATE INDEX IF NOT EXISTS idx_trades_cid ON trades(client_order_id, ts);
CREATE INDEX IF NOT EXISTS idx_trades_ts  ON trades(ts);
CREATE INDEX IF NOT EXISTS idx_orders_status_ts ON orders(status, ts DESC);
CREATE INDEX IF NOT EXISTS idx_orders_config_ts ON orders(config, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_ts ON order_events(ts);

-- robots.db: история версий/событий/запусков
CREATE UNIQUE INDEX IF NOT EXISTS ux_param_versions
  ON param_versions(instance_id, version);
CREATE INDEX IF NOT EXISTS idx_instance_events_inst
  ON instance_events(instance_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scheduler_runs_status
  ON scheduler_runs(status, slot DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_updated ON runtime_state(updated_at);
```

Перед накатыванием — проверить дубли (сейчас 0) и сделать консистентный бэкап.
FK и `UNIQUE(trades.client_order_id, order_id, ts)` — отдельной миграцией с
валидацией данных, не «на ходу»: часть исполнений может быть частичными и
законными. Дополнительно: хранить полный ответ брокера отдельной таблицей
`order_responses(seq, response_json, received_at)` вместо обрезки до 300 символов;
Единый формат ISO-8601 UTC во всех `ts`, локальное время — только в представлении.

## 7. Политика ретенции и бэкапов (проект)

- **Источник правды:** не удалять никогда; `market.db` — до миллионов баров,
  инкрементальная загрузка; раз в квартал `PRAGMA integrity_check` на копии.
- **Зеркала:** `live.csv` — 90 дней «горячим», старше — годовой `.csv.gz`
  с контрольной суммой; `paper_metrics.db` пересобирается из `paper.csv`,
  поэтому может чиститься только вместе с метаданными пересборки.
- **Логи:** systemd `SystemMaxUse=200M`, `MaxRetentionSec=1month`;
  `logrotate` для `results/*.log`: weekly, rotate 8, compress, copytruncate;
  технические логи не смешивать с журналом сделок (он в БД).
- **Бэкапы:** systemd-таймер 03:00 — `sqlite3.backup()` для
  `trades.db`, `robots.db`, `paper_metrics.db` в `backups/db/` (0700, файлы 0600,
  **без `.env`**); 30 ежедневных + 12 месячных; `instruments.db`/`market.db` —
  еженедельно/ежемесячно; еженедельная копия вне WSL; ежеквартальный тест
  восстановления на временном пути с `PRAGMA integrity_check`.
- **Секреты:** `.env` не должен попадать ни в один бэкап; текущий tarball 0644
  нужно пере-create с режимом 0600 (отдельная задача, здесь не делалось).
- **Git:** оставить `paper.csv`/`runs.csv` под версией; `live.csv` — производный,
  восстанавливается из БД (проверить `migrate_csv()` на тестовой копии).

## 8. Как сделать журнал понятным человеку

- Заголовок строки: «Шорт 2 CNY на 49 664 ₽ · исполнено 24.11 14:00 МСК»;
  смысл → детали. `client_order_id`, `order_id`, `ORDER_STATUS_*`, JSON —
  во вторичном блоке «Технические детали» с кнопкой копирования.
- Денежная сумма = `qty × price × multiplier`, ₽; явные единицы в заголовке
  столбца, разные форматы CNY/Si не смешивать; буквальный `None` не показывать.
- Единая карта статусов: planned → sent → partial → filled/cancelled/rejected/
  uncertain → human-подписи на русском; `order_events` показывать таймлайном.
- Один источник описаний стратегий/роботов (заменит 4 дубля из брифа §5);
  счёт показывать по `label` из `accounts`, а не по номеру `2102993`.
- SQL-представление `v_orders_human` (или `/api/journal?view=human`) с
  форматированием, без изменения схемы: `status_label`, `amount_rub`,
  `ts_local`, `account_label`, `strategy_name`. Сырые поля остаются доступными
  для сверки.

## 9. Как проверить результат (после внедрения, сейчас не выполнялось)

1. `SELECT COUNT(*)` и `MIN/MAX(ts)` в orders/trades/order_events — сравнить с
   `live.csv`; ожидаемо 0 расхождений (сейчас WSL 18/18, десктоп — не эталон).
2. Повторить `EXPLAIN QUERY PLAN` из §3 — ожидаемо `SEARCH ... USING INDEX`,
   никаких `SCAN` и `USE TEMP B-TREE` на указанных запросах.
3. Сделать `POST /api/journal/backup` на тестовой копии и восстановить в
   `/tmp`, прогнать `PRAGMA integrity_check` → `ok`.
4. Проверить, что таймер бэкапа активен, а в `backups/` нет `.env` и режимы
   0700/0600; проверить `logrotate -d` и рост `results/*.log` за неделю.
5. Сверить human-view с сырой строкой по одной сделке 24.11 (2 CNY @12.288):
   сумма, время МСК, подпись статуса, scopes счёта.

## Приоритеты

1. **Высокий:** включить автоматический консистентный бэкап трёх БД и убрать
   секреты из существующих снимков; перевести панель/счёт ворот чтением из `trades.db`;
   синхронизировать или явно объявить десктоп «не источником данных».
2. **Средний:** наложить предложенные индексы и UNIQUE-ограничения после
   проверки дублей; хранить полный ответ брокера; unified UTC.
3. **Низкий:** ретенция CSV/логов, human-view, один справочник описаний,
   ежеквартальное восстановление.

Источники: `PROGRESS.md`, `docs/trade-journal.md`, `docs/autonomous-improvement-brief.md`,
`docs/decisions.md`, `algo/trade_journal.py`, `algo/broker/execution.py`,
`web/app.py`, `web/instances_api.py`, `scripts/deploy_wsl.sh`, схемы и счётчики
`infra/db/*.db` (десктоп и WSL), `results/*.csv`, состояние systemd/journald WSL.
