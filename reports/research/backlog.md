# Сводный бэклог автономного исследования (24.11.2026)

Источники: `reports/research/{gui-ux-patterns,logic-audit,perf-reliability,
storage-audit,human-readable-ui,testing-gaps}.md`. Одна строка = одна тема сессии.
Приоритет: **P0** — до прогона 25.11 14:00; **P1** — на этой неделе; **P2** — планово.

## P0 — критично до 25.11

| # | Проблема | Источник | Статус |
|---|---|---|---|
| 1 | `filled`-заявки выпадали из модели позиций → ложный STOP 25.11 | logic-audit (PRE-FIX) | ✅ исправлено `f634d18` |
| 2 | F02: partial(2)→filled(5) давал `executed_qty=7` (SUM вместо MAX) | logic-audit | ✅ исправлено, тест, ADR |
| 3 | F01: недетерминированный `client_id` → повторный `--arm` создаёт дубль | logic-audit | ✅ исправлено, тест, ADR |
| 4 | F03: любой `uncertain` ставит STOP даже при подтверждённом filled | logic-audit | ⬜ ADR: оставить консервативно или опрашивать брокера перед STOP |
| 5 | Shadow (13:57) и live (14:00) делят `live.lock`/журнал → тихая потеря заявки при затяжке | perf-reliability | ⬜ разделить `shadow.lock`/журнал ИЛИ защитить по времени |
| 6 | Stale-локи без PID/возраста блокируют заявки до ручного удаления | perf-reliability | ⬜ перенести `_stale_lock()` из `scheduler.py` |

## P1 — человекочитаемость и надёжность

| # | Проблема | Источник | Выгода |
|---|---|---|---|
| 7 | Raw id (`p-base`, `6b3b…`), `ORDER_STATUS_*`, JSON, `None` в UI | human-readable-ui, gui-ux | общий JS-словарь статусов + имена вместо id; 5 правок без API |
| 8 | Инструменты не сгруппированы по типу; MIC-коды в основной строке | human-readable-ui, gui-ux | валюта/индексы/акции/сырьё/фонды, MIC в secondary |
| 9 | `JSON.stringify(r.by_type/counts)` в `robots.html` | gui-ux, human-readable-ui | фразы «Ликвидных: 42 — акции 30…» |
| 10 | `robots.db` без WAL и индексов; DDL в read-path | perf-reliability, storage-audit | WAL + `busy_timeout`, 4 индекса, вынести схему из чтений |
| 11 | Нет автоматического бэкапа БД; tarball 0644 с `.env` | storage-audit | timer 03:00, 0700/0600, без секретов; пересоздать текущий |
| 12 | Нет ротации логов (`web.log` 1.1 МБ, journald 24 МБ) | storage-audit | logrotate weekly×8 + `SystemMaxUse=200M` |
| 13 | Cold `/api/state` 526–800 мс, «первый клик» 288 мс | perf-reliability | фоновый refresh + stale-while-revalidate |
| 14 | Cold analytics 190–1252 мс; кэш не инвалидируется при смене инстансов | perf-reliability | фон + `invalidate_analytics()` во всех мутациях |
| 15 | F05/F09: тень и панель используют статические конфиги, не store | logic-audit | единый список `active_configs()` |

## P2 — плановая уборка

| # | Проблема | Источник |
|---|---|---|
| 16 | F04: `expiry_allows` проверяет дату `--day`, а не дату прогона | logic-audit |
| 17 | F07/F08: TZ-сдвиг в shadow и `configs_at` (naive `datetime.now()`) | logic-audit |
| 18 | F10: watchdog с захардкоженным `DECISION_CONFIGS` | logic-audit |
| 19 | F11: ролл в `paper.csv` портит P&L (цена старого символа) | logic-audit |
| 20 | F12/F13: цена в `mark_execution` не обновляется; `size_contracts` возвращает 1 при equity≤0 | logic-audit |
| 21 | Нет UNIQUE на `order_events`, FK в `trades.db`, полного ответа брокера | storage-audit |
| 22 | Дубли описаний: `Config.comment`, `RobotSpec.description`, `strategy_descriptions.py`, docs | storage-audit, бриф |
| 23 | HTTP-тесты через `TestClient` для `/api/archive`, `/analytics`, `/logs`, ACK | testing-gaps |
| 24 | Тесты gateway STOP mid-session, `journal_positions` partial/uncertain, `expected(cfg_for)` | testing-gaps |
| 25 | Comparative panel «портфель vs депозит» в счетах; KPI-полоса в торговле | gui-ux |

## Что НЕ делать (антипаттерны из gui-ux)

- Отсоединяемые панели без дефолта/сброса; TWS как эталон сложности.
- Красный/зелёный для подсветки строк (цвет = направление).
- Тумблер buy/sell вместо двух видимых форм; «Ещё…» без числа.
- Разные слова для одного состояния; сырые id и JSON как главный текст.

## Правило цикла

После каждого пункта: одна сессия → отчёт/ADR → тест → commit+push → deploy →
smoke (`/`, `/trade`, `/robots`, `/accounts`, `/health`, `/api/health`) → строка в `PROGRESS.md`.
Торговлю researched-изменениями не останавливать.
