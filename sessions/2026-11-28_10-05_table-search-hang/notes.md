# 28.11.2026 — поиск по строкам таблицы вешал страницу

## 09:5x — воспроизведение

Пользователь: «Поиск по строкам таблицы подвешивает всю страницу». Поле с таким
placeholder есть только в `webui/src/components/ui.tsx` → `DataTable searchable`,
подключено на вкладке «Счета» (`Accounts.tsx`).

Собрал `webui/dist`, поднял `vite preview` на 5181 и через puppeteer-core +
`/usr/bin/google-chrome` замокал `/api/*`. Ввод одного символа в поиск убивал
вкладку: `framedetached`, `Target closed` (renderer падал). Контрольные опыты:
поиск в «Логах» и «Поиск по имени» в «Роботах» работали — баг только в
`searchable`-таблице.

## 10:0x — причина

`DataTable` строил отфильтрованный массив заново на каждой перерисовке.
@tanstack/react-table v8 в `getCoreRowModel`/`getSortedRowModel` на новую ссылку
`data` вызывает `_autoResetPageIndex` → очередь микротаска → `resetPageIndex()` →
`setState` (pagination) → перерисовка `DataTable` → снова новая ссылка массива →
снова `setState`. Бесконечный цикл, renderer падает по памяти.

Эксперимент подтвердил: `useMemo` на отфильтрованные строки убирает зависание.
Дополнительно выключен `autoResetPageIndex` (пагинации в таблице нет) — цикл
невозможен даже при нестабильной ссылке `data` от родителя.

## 10:1x — правки

- `webui/src/components/ui.tsx`: `useMemo([data, query, searchable])`,
  `autoResetPageIndex: false`, поиск через `rowMatches`.
- `webui/src/lib/tableFilter.ts`: `rowMatches`/`rowText` — рекурсивный текст
  простых полей, вложенных объектов и массивов (глубина 3, `WeakSet` от
  ссылок), регистронезависимо. Раньше вложенное давало `[object Object]`.
- `webui/src/lib/tableFilter.test.ts`: 5 тестов (вложенность, пустой запрос,
  цикл, null/undefined).
- `webui/check-all.mjs`: headless-регрессия — ввод в поиск по строкам таблицы
  счетов с таймаутом 5 с.
- `docs/MODULES.md` — строки про `components/ui.tsx`, `lib/tableFilter.ts`,
  регрессию; `docs/decisions.md` — ADR 27.11. Оба файла попали в чужой коммит
  `96e99fa` (параллельная сессия коммитила дневной лимит убытка).

## 10:2x — проверки и выкладка

- `npm test` — 12 зелёных, `npm run build` — ок, `./run.sh test` — зелёный.
- Коммит `ea9520c`, push в master.
- WSL был недоступен: десктоп в сети 192.168.1.x, маршрута до 192.168.0.0/24 не
  было. Поднял VPN по `docs/ONBOARDING.md`: `nmcli con up "Sysinv SSTP"` (ppp0,
  192.168.100.193) — после этого `192.168.0.230` пингуется.
- `./scripts/deploy_wsl.sh --apply --restart` — md5 OK (265 файлов), панель
  перезапущена.
- `./run.sh check-ui` — 7 разделов, `problems: []` (новая регрессия прошла).
- `curl /api/health` — OK, 0 проблем. Прод-бандл `index-DNcHc2jg.js`.
- Живая проверка на панели: 20 счетов → поиск «Cче» → 1 строка (все видимые
  строки содержат запрос), очистка → снова 20, ошибок JS нет.

### 10:25 — Конец: поиск по строкам таблицы больше не вешает страницу

Поиск по строкам таблицы (вкладка «Счета») вешал всю страницу: react-table
уходил в бесконечный цикл `setState` на нестабильной ссылке отфильтрованного
массива. Исправлено мемоизацией строк, выключенным `autoResetPageIndex` и
вынесенным `lib/tableFilter.ts` с тестами; добавлена headless-регрессия в
`check-all.mjs`. Коммит `ea9520c`, выложено на WSL, `check-ui` и `/api/health`
чистые. Статус: **решено**.
