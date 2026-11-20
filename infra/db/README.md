# infra/db — индекс истории песочницы

Форк индексатора из `/mnt/DiskD/opencode-hub/infra/db`, адаптированный под
эту песочницу:

- корень — проект, сессии — `sessions/` (`OC_MEMORY_SESSIONS=sessions`);
- база — `infra/db/memory.db` (`OC_MEMORY_DB` может переопределить);
- в индекс входят `sessions/*/notes.md`, `PROGRESS.md`, `AGENTS.md`, `docs/`,
  `reports/`;
- `data/`, `materials/`, `cache/`, `web/`, `.venv/` исключены.

Команды: `./infra/db/memory.py brief|lookup|search|outline|check|stats`,
пересборка — `build --force`. MCP-сервер — `memory` (конфиг в `../../opencode.jsonc`).

При изменении схемы поднять `SCHEMA_VERSION` и синхронизировать с форком в хабе.
