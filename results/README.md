# results/ — машиночитаемые результаты

- `runs.csv` — журнал всех прогонов (через `algo.results.record`).
- `paper.csv`, `paper-legacy.csv` — бумажный контур.
- `health.json`, `alerts_seen.json` — состояние панели/алертов (рантайм, в git не коммитится).
- `live.csv` + `infra/db/trades.db` — аудит заявок/сделок; `shadow.csv` — отдельная репетиция.
- `live_run.json` — сводка последнего прогона боя; `live_manual.log` — ручные прогоны.
- `trading_toggle.jsonl` — аудит включения/выключения торговли из панели.
- `market.db` (в `infra/db`) — бары M5/D1 для графика; персональные решения роботов лежат в `robots.db` → `robot_decisions`.
- `web-local.log` — лог локальной панели (не коммитить).

Файлы с рантайм-состоянием (`*.log`, `health.json`, `token_usage.json`,
`context_cleanup_state.json`, `alerts_seen.json`, `arm_state.json`,
`trading_toggle.jsonl`) в git не нужны и добавлены в `.gitignore`.
