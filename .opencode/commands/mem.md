---
description: Поиск по индексу истории песочницы (sessions/, PROGRESS, docs, reports)
---

Поиск по прошлым сессиям через `infra/db/memory.py` — без чтения notes.md целиком.

Запрос: `$ARGUMENTS`

Порядок:

1. Если запрос пустой — `cd /mnt/DiskD/opencode-algo && ./infra/db/memory.py brief`.
2. Иначе — `./infra/db/memory.py lookup "$ARGUMENTS"`; точнее —
   `./infra/db/memory.py search "$ARGUMENTS" --limit 8` (или `--gist`).
3. Мало или мимо — уточни формулировку (`--mode trigram`, другой набор слов,
   `--project <папка>`).
4. Для разбора темы — `./infra/db/memory.py context "<тема>" --budget 4000`.
5. Ответь коротко: папка, файл, строки, 1–2 вывода.
6. Полный текст — через `outline <папка-сессии>` и точечное чтение.
