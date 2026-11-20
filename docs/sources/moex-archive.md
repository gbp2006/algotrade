# Архив MOEX в песочнице

`/mnt/DiskD/MOEX/` (~43 ГБ, 8 456 файлов) **физически перемещён** в
`/mnt/DiskD/opencode-algo/materials/` rename'ом внутри одного диска —
копирование 43 ГБ не производилось. Старого пути больше нет. Каталог в
`.gitignore`, **не коммитить**. Карта — `materials/MOEX-КАРТА.md`
(вне игнорируемой папки, поэтому в git и в индексе памяти).

Содержимое рассортировано по смысловым разделам:

| раздел | что |
|---|---|
| `01_Данные/` | архивы M1/M5 (на них смотрит `data/`) |
| `02_Стратегии/` | системы Силаева, Коваль-Зайцева, OsEngine, «Разобрать» |
| `03_Обучение/` | курсы, видео, книги |
| `04_Софт_и_инструменты/` | OsEngine, TSLab, LUA, Transaq, Финам |
| `05_Документы/` | канцелярия |

Пути `/mnt/DiskD/MOEX/...` в `sessions/*/notes.md` и `infra/exports/` —
исторические (до перемещения); переписывать их не нужно.

## Каталог и поиск

`infra/db/moex_catalog.db` (производный, не в git) — таблицы `section`, `file`,
`tag` (role/author/status/linked_doc/robot) и FTS5 по имени/описанию/пути.
Индексируются только имена и первая строка текстовых файлов.

```bash
./infra/db/moex_catalog.py find "пробой канала"   # Иван Коваль-Зайцев, TCBreak
./infra/db/moex_catalog.py find "Силаев"
./infra/db/moex_catalog.py section 02_Стратегии
./infra/db/moex_catalog.py author Силаев
./infra/db/moex_catalog.py status отброшен
./infra/db/moex_catalog.py stats
```

Обновление после изменений в архиве:

```bash
.venv/bin/python scripts/60_index_moex.py build
```

Источник индексатора — `ROOT/materials/moex`. Ключевые материалы и их статус
сведены в `materials/MOEX-КАРТА.md` (лежит вне игнорируемой папки архива,
поэтому попадает в git и в индекс); исторические данные читать через
`algo.data`, не напрямую.
