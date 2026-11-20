---
description: Проверка индекса истории и расхождений INDEX.md с папками sessions/
---

1. `cd /mnt/DiskD/opencode-algo && ./infra/db/memory.py check` — папки без
   строки в INDEX.md, строки без папки, «в работе» без финальной записи.
2. `./infra/db/memory.py stats` — размер базы и состав.
3. Странности со сборкой — `./infra/db/test_memory.py` (в своей временной копии).
4. Устаревшая база — `./infra/db/memory.py build --force`; расхождение
   INDEX — `./infra/db/memory.py index-sync`.
5. Менялось ранжирование — `./infra/db/eval.py`.
6. Отчитайся коротко: что расходится и что предлагаешь; файлы без просьбы не правь.
