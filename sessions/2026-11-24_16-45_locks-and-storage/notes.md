# 24.11.2026 — надёжность контура: локи, хранение, бэкапы

### 16:45 — Тема
Пункты P0 #5/#6 и P1 #10/#11 бэклога `reports/research/backlog.md`:
разделить lock/журнал shadow и live, добавить защиту от stale-локов,
включить WAL и индексы в `robots.db`, automatический бэкап без секретов.

### 16:45 — Ограничения
Лок/журнал задевают реальные заявки — только после ADR, с тестами на копиях,
деплой через git + deploy_wsl.sh, smoke `/api/health`. STOP и
`FINAM_ALLOW_TRADING` не трогать. Торговлю researched-правками не останавливать.

### 16:50 — Лок и журнал тени разделены
`33_shadow_live.py` пишет в `results/shadow.csv` под `results/shadow.lock`;
боевой контур остаётся в `live.csv`/`live.lock`. `live_state_view()` читает
оба журнала — история G3 сохраняется. `OrderGateway` пишет `pid:client_id`,
снимает аренду мёртвого PID и legacy-лок старше 5 мин (одна повторная попытка).
Тесты всех трёх сценариев лока и отдельного журнала зелёные.

### 16:55 — WAL и индексы
`robots.db`: WAL + `busy_timeout=5000`, 4 индекса, включая уникальный
`ux_param_versions` (дубли проверены — 0). Перед переключением на WSL сделан
ручной консистентный бэкап `robots_before_wal_*.db` (0600).

### 17:00 — Автобэкап
`scripts/95_backup_db.py` + systemd unit/timer 03:00 + `./run.sh backup`.
Только *.db, 0700/0600, integrity_check, ретенция 30 daily + 12 месячных,
`.env` не копируется. Тесты `test_backup.py` зелёные.

### 17:05 — Поставлен timer и проверен WAL
`algotrading-backup.timer` активен, следующий запуск 25.11 03:00 MSK; ручной
`./run.sh backup` сделал 3 консистентные копии (0600), `robots.db` в WAL,
shadow_days == 3 из legacy-журнала (история G3 сохранилась).

### 17:15 — Скорость API
`_cached()` с stale-while-revalidate + фоновая подкачка раз в 20 с; котировки и
свечи не блокируют запрос по истечении TTL. Инвалидация кэша аналитики
добавлена во все мутации инстансов, runtime, money-market и live-run.
Тесты `test_web_cache.py`, `test_mutations_invalidate_analytics`.

### 17:20 — Конец: бэклог P0/P1 по надёжности, хранению и скорости закрыт
Осталось в P2 (планово): TZ-сдвиги, захардкоженный watchdog, P&L ролла,
HTTP-тесты TestClient, единая иерархия описаний.
