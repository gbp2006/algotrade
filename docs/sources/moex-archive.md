# Архив MOEX в песочнице

`/mnt/DiskD/MOEX/` (~43 ГБ, 11 разделов, 8 455 файлов) **физически
перемещён** в `/mnt/DiskD/opencode-algo/materials/moex/` rename'ом внутри
одного диска — копирование 43 ГБ не производилось. Старый путь оставлен
compatibility-симлинком `/mnt/DiskD/MOEX -> .../materials/moex`, поэтому
`data` и старые хардкод-пути продолжают работать. Каталог в `.gitignore`,
**не коммитить**. Подробности — `materials/moex/README.md`.

## Каталог

`infra/db/moex_catalog.db` (производный, не в git) — таблицы `section`,
`file` и FTS5 по имени/описанию/пути. Индексируются только имена и первая
строка текстовых файлов (`.cs`, `.txt`, `.md`, `.ini`, `.py` и др.).

```bash
./infra/db/moex_catalog.py find "пробой канала"   # Иван Коваль-Зайцев, TCBreak
./infra/db/moex_catalog.py find "Силаев"          # Трендовушки, Хитрушка
./infra/db/moex_catalog.py section ТС
./infra/db/moex_catalog.py stats
```

Обновление после изменений в архиве:

```bash
.venv/bin/python scripts/60_index_moex.py build
```

Источник индексатора — `ROOT/materials/moex` (фолбэк на старый путь).
Ключевые материалы: ТЗ Силаева (`ТС/Силаев/`), стратегии «пробой канала»
Ивана (`TCBreak*.cs`), исторические данные — через `algo.data`, не напрямую.
