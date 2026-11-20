---
name: memory-index
description: Работа с индексом истории песочницы алготрейдинга (infra/db/memory.py, SQLite+FTS5): поиск по сессиям, PROGRESS.md, docs и reports, бриф, оглавление, диагностика. Загружать, когда нужен контекст из старых notes.md или когда индекс ведёт себя странно.
---

# Индекс истории песочницы

`infra/db/memory.db` — производная от markdown-файлов: `sessions/*/notes.md`,
`PROGRESS.md`, `AGENTS.md`, `docs/**`, `reports/**`. Источник правды — файлы;
базу можно удалить и пересобрать.

## Порядок обращения

1. `./infra/db/memory.py brief` — незавершённые, последние сессии (~2 КБ).
2. `./infra/db/memory.py lookup "<вопрос>"` — события + фрагменты + сущности.
3. `./infra/db/memory.py search "<слова>" [--gist]` — точный поиск / только пути.
4. `./infra/db/memory.py outline <папка-сессии>` → точечный `read` диапазона.
5. `./infra/db/memory.py entity <IP|домен|путь|инструмент>` — где упоминалось.
6. `./infra/db/memory.py timeline --since YYYY-MM-DD` — хронология событий.
7. `./infra/db/memory.py check` — расхождения INDEX.md и папок.

MCP-эквиваленты: `memory_brief`, `memory_lookup`, `memory_search`,
`memory_context`, `memory_outline`, `memory_reference`, `memory_project`,
`memory_timeline`, `memory_entity`, `memory_check`, `memory_stats`.

## Как устроено

- Корень — песочница; сессии — подпапка `sessions/` (`OC_MEMORY_SESSIONS`).
- Нарезка по заголовкам; два FTS5-индекса (слова+префиксы и триграммы).
- Сборка инкрементальная перед каждым запросом; полная — `build --force`.
- Не индексируются: `data/`, `materials/`, `cache/`, `web/`, `.venv/`, `infra/db/`.

## Грабли

- Правка с сохранением mtime не замечается: `build --force`.
- Две копии `memory.py` (hub и алго) — при изменении схемы поднимать
  `SCHEMA_VERSION` и синхронизировать оба форка.
- `INDEX.md` переписывается автоматически, бэкап `INDEX.md.bak-<дата>`.
