# 28.11.2026 — удаление слоя сравнения бумаги и боя

### 11:05 — Постановка
Пользователь: «не нравится слой сравнения торгов тестовых бумах и с боевыми».
Разбор показал три разных механизма:
1. Fact/Expected (`algo/expected.py`, `scripts/32_paper_report.py`,
   `scripts/40_watchdog.py`, `/api/config/{id}`) — самопроверка бумажного
   раннера через реконструкцию ожидания; источник ложных 503 и костыля
   `COMPARE_FROM=2026-11-28` после удаления ATR.
2. `robot_compare()` + `/api/robot-compare` + `results/robot_compare.csv` —
   новые роботы против базы на бумажном журнале; кнопки в UI уже нет.
3. `/api/portfolio/reconciliation` + карточка «Сверка Plan/Test vs Fact» —
   план/лот/цена против исполнений из `live_run.json`; карточка пустая.
Защитная `broker/execution.reconcile()` (модель против позиции брокера, STOP)
к «аналитике» не относится и трогаться не должна.

### 11:10 — Решение пользователя
Удалить `robot_compare` и карточку Plan/Test; Fact/Expected — удалить совсем,
G2 убрать полностью. Мотивация: проект ведёт только тестовые и боевые торги,
а проверку корректности и расхождений исполнения считать локально по запросу,
не держать в проде. Согласовано: health остаётся индикатором живости, G3/G4
сохраняются под прежними именами, в runbook фиксируется оффлайн-разбор.

### 11:15 — Правка
- Удалены `algo/expected.py`, `tests/test_expected.py`, `results/robot_compare.csv`.
- `scripts/32_paper_report.py`: только метрики из `paper.csv`, без `expected`,
  `error`, `COMPARE_FROM`, `robot_compare` и записи `robot_compare.csv`.
- `scripts/40_watchdog.py`: убраны `tracking_errors()` и `TRACKING_TOLERANCE`;
  остались таймеры, свежесть, STOP, дубли, пропущенные решения.
- `web/app.py`: убраны `expected_pnl`, `_expected()`, поле `expected` и
  `/api/robot-compare`; `web/cash_flows_api.py` — `reconciliation_view()` и
  `/api/portfolio/reconciliation`; WebUI — карточка и клиентский метод.
- Тесты переписаны: `test_report.py`, `test_watchdog.py`, `test_http_api.py`.
- ADR в `docs/decisions.md`; переписан `docs/live-gates.md` без G2; обновлены
  `MODULES.md`, `ARCHITECTURE.md`, `ONBOARDING.md`, `panel-manual.md`,
  `panel-tabs-design.md`, `battle-roadmap.md`, `live-runbook.md`, `how-to.md`,
  `PROGRESS.md` и др.; `run.sh report` — новое описание. В `live-runbook.md`
  добавлен рецепт локального разбора по `paper.csv`, `live.csv`, `shadow.csv`,
  `trades.db`, `market.db`, `live_run.json` и версиям параметров.

### 11:25 — Проверка
`./run.sh test` — 345 тестов в 47 наборах, зелёные.
`cd webui && npm test` — 12 тестов; `npm run build` — успешно.
`./run.sh report` — печать сводки без колонок ожидания/ошибки, снимок метрик пишется.

### 11:26 — Конец: сравнение бумаги и боя вынесено из проекта
Коммит `e4355be` запушен. `deploy_wsl.sh --apply --restart`: 258 файлов,
md5 OK, панель перезапущена. `./run.sh check-ui` — 7 разделов, 0 ошибок JS;
`/api/health` — 200 OK; `/api/robot-compare` и `/api/portfolio/reconciliation`
— 404; `/api/config/p-base` — 200 без поля `expected`. Deploй без `--delete`
оставил на сервере три удалённых файла (`algo/expected.py`,
`tests/test_expected.py`, `results/robot_compare.csv`) — удалены вручную.
Тесты на WSL — зелёные. Защитная сверка с брокером и STOP не трогались.
Статус: **решено**. Решение — ADR 28.11 в `docs/decisions.md`; ворота G2
упразднены, G3/G4 сохранены; аналитика расхождений — локально по журналам.
