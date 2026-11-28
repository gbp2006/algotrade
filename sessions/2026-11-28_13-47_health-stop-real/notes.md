# 28.11.2026 — STOP_REAL в health-проверке

### 13:47 — Постановка
Последнее наблюдение аудита надёжности: `/api/health` показывал только бумажный
STOP, тогда как STOP_REAL был виден в панели и `/api/live-state`. Для внешних
мониторов это означало «всё OK» при включённом аварийном тормозе.

### 13:50 — Правка
- `scripts/40_watchdog.py`: путь `results/STOP_REAL`, предупреждение в `warnings`
  и поле `stop_real` в `results/health.json`.
- `web/app.py`: поле `stop_real` пробрасывается в ответ `/api/health`.
- Тесты: `test_watchdog.py::test_stop_real_is_warning`,
  `test_http_api.py::test_health_exposes_stop_real`; регрессия в `check-all.mjs`.
- Строка в `docs/MODULES.md`, ADR, отметка в `PROGRESS.md`.
Проверки: `./run.sh test` зелёный.

### 13:51 — Конец: STOP_REAL виден в health
**решено**. Аварийный флаг теперь отражается и в health-ответе, и в предупреждении
стоража; заявки и STOP не трогались.
