# Аудит человекочитаемости UI панели

Дата: 2026-11-24. Тип: research-only (код, шаблоны и API не менялись; `data/`, `materials/`, `cache/` не читались).

Метод: прочитаны `AGENTS.md`, `PROGRESS.md`, `docs/autonomous-improvement-brief.md` §3.5,
`web/templates/{index,robots,trade,accounts,health,nav}.html`, `web/static/{sidebar,ui-state}.js`,
`web/app.py`, `web/instances_api.py`, `algo/instruments_catalog.py`, `algo/strategy_descriptions.py`.
Выводы сделаны только по открытому коду; живые запросы к брокеру не делались.

## 1. Инвентарь технического шума

| Шум | Где (шаблон / API) | Пример, что видит человек | Почему мешает |
|---|---|---|---|
| Raw id робота | `robots.html:340`, `trade.html:142,192-194`, `sidebar.js:15`, `/api/instances` | `p-base`, `6b3b…`, `<b>${i.id}</b>` | Первое, что бросается в глаза; смысла не несёт |
| `spec_id` как подпись | `robots.html:302,341,555`, `trade.html:142`, `sidebar.js:15,21` | `prostushka / CNY`, иконки `П`/`У` | Внутренний слаг вместо названия стратегии |
| `ORDER_STATUS_*` / статусы | `/api/journal`, `/api/logs:759-762` → `trade.html:108`, `health.html` | `filled`, `partial`, `cancelled`, `planned`, `ok` | Код вместо русского «Исполнена / Частично / Отменена» |
| JSON в тексте | `robots.html:267` (`JSON.stringify(r.by_type)`), `:486` (`s.counts`), `:592` | `{"FUTURES":3,"EQUITIES":2}` | Сырая сериализация в строке статуса |
| `response`/`stdout`/`detail` | `robots.html:488,525`, `/api/live-run:496-497`, `/api/instruments/params:441` | `HTTPError: …`, `${r.stdout}`, `KeyError: 'x'` | Стек/код ошибки без человеческой формулировки |
| MIC и служебные типы | `instruments_catalog.py:236-260`, `/api/instruments`, `robots.html:267` | `MISX`, `RTSX`, `EQUITIES`, `FUTURES`, `CURRENCIES` | Код биржи и тип из API смешаны в одной вьюхе |
| Внутренние поля в elapsed | `trade.html:150,153,217,262`, `robots.html:346` | `o.side`, `o.status`, `j.command`, `last_decision`, `slot`, `spec_id` | Пользователь видит имя поля, а не значение |
| Флаги/переменные | `robots.html:94,151`, `index.html` (хардкод счёта, `FINAM_ALLOW_TRADING`) | `FINAM_ALLOW_TRADING=1`, `--arm`, `STOP_REAL`, `Счёт 2102993` | Инженерная кухня в клиентском экране |
| Ключи/рефы | `robots.html:444,513-514`, `/api/service-key:378-379` | `robot:xxx`, `acc:2102993`, `env_fallback FINAM_SECRET`, `key_ref` | Служебные идентификаторы вместо «ключ подключён» |
| `nan` / `None` / `undefined` | `accounts.html:43` (частично обработано), `/api/accounts/analytics:699-726`, `index.html:348,358` | `equity: null`, `last_price: None`, `—` | Смесь «нет данных», «0» и «не загрузилось» |
| Смешанные единицы | `index.html:471-474,607-609`, `/api/config/{id}:462-470` | `net` в ₽, `pnl_pct` в %, `DD, дней`, `PF`, `qty` в контрактах | Без подписи единицы сравнить невозможно |
| Режимы/статусы без перевода | `robots.html:343,323-334`, `trade.html:262`, `/api/instances:190` | `draft/active/paused/stopped/archived`, `paper/live`, `dry_run=true` | Требуют знания внутр. модели состояний |

Итого: шум сконцентрирован в `robots.html` (управление инстансами), `trade.html` (заявки/планировщик)
и в сырых полях `/api/instances`, `/api/logs`, `/api/accounts/analytics`. `accounts.html` и
`health.html` уже частично «очеловечены» (`num()`, `label`, «Нет зарегистрированных счетов»).

## 2. Группировка инструментов по типу и ликвидности

**Сейчас.** `/api/instruments` (`instruments_catalog.py:185-203`) отдаёт плоский список с полями
`symbol / ticker / mic / type / name / lot_size`, где `type` — код из брокерского справочника
`EQUITIES | FUTURES | CURRENCIES` (`:236-260`), а `scope` — `liquid | favorites | all`.
`/api/instruments/stats` возвращает `by_type` с теми же кодами; `robots.html:267` печатает его как JSON.
MIC-коды (`MISX`, `RTSX`) соседствуют с типоми инструмента и с служебными `scope`.

**Предложение.** Ввести слой human-readable классификации между API и вьюхой.

| Технический `type` / признак | Человекочитаемая группа | Порядок |
|---|---|---|
| `CURRENCIES` | Валютные фьючерсы | 1 |
| `FUTURES` (индексные) | Индексы | 2 |
| `EQUITIES` | Акции | 3 |
| `FUTURES` (сырьё/золото) | Сырьё и золото | 4 |
| `FUTURES`/`EQUITIES` (`money_market`, паи) | Фонды и паи | 5 |

Правила:
- В одной вьюхе показывать только «Валютные фьючерсы / Индексы / Акции / Сырьё / Фонды»; MIC (`MISX`, `RTSX`)
  убрать в secondary-текст или в `title` иконки — не в основную строку.
- Внутри группы сортировка: избранное → ликвидные (`liquid=1`) → остальные; счёт показывается отдельным
  измерением (фильтр «все счета / конкретный»), а не смешивается с типом.
- `by_type` заменить в UI на фразы: «Ликвидных: 42 — валютные фьючерсы 8, индексы 4, акции 30».
  JSON оставить в `details`/`title` для разработчика.
- Служебные `scope=favorites`/`all` переименовать в UI в «Избранное» / «Все инструменты».

## 3. Иерархия «стратегия → робот → инстанс»

**Сейчас.** Три уровня существуют в данных, но в UI размазаны: стратегия — `spec_id` + `about`
(`/api/specs`), робот — логический конфиг (`display`, `comment`, `id` в `/api/state.strategies`),
инстанс — запись `/api/instances` с полями `id`, `spec_id`, `instrument`, `mode`, `status`.
`sidebar.js:15,21` делает заголовок инстанса из `i.id`, а иконку — из `spec_id` (`П`/`У`);
`robots.html:340` ставит `<b>${i.id}</b>` над `note`. В итоге пользователь видит плоский список id.

**Предложение.** Явная трёхуровневая модель с единым правилом имени:

1. **Стратегия** — human-readable имя из `strategy_descriptions.describe()` (`Простушка`,
   `Универсалка`, `Пробой канала`, `Donchian`, `Фонд денежного рынка`). Это заголовок раздела.
2. **Робот** — имя конфигурации (`display` / `note`, например «Простушка CNY база»). Подпись под стратегией;
   generic `id` (`p-base`) — приглушённым шрифтом с кнопкой копирования.
3. **Инстанс** — конкретный запуск: `<имя робота> · <режим> · <статус> · <инструмент>`.
   Пример: «Простушка CNY база · бой · активен · CNY (фьючерс)».

Правила отображения:
- Один robot может иметь несколько инстансов (paper/live) — группировать их под одним заголовком робота,
  а не выводить отдельными строками в сайдбаре.
- Стратегия не отображается как строка списка наравне с инстансом: она — заголовок/фильтр.
- `spec_id`, `id`, `version`, `key_ref` — второстепенный слой (серый текст, `title`, копирование по клику).
- `about` (описание стратегии) уже приходит в `/api/instances:100-104` — использовать его в карточке,
  а не дублировать `note`.

## 4. Таблица «было → стало»

| Контекст | Было | Стало |
|---|---|---|
| Заголовок инстанса | `p-base` | `Простушка CNY база` (id — серым + копирование) |
| Подпись стратегии | `prostushka` / иконка `П` | `Простушка — тренд по SMA, 1 решение в день` |
| Статус заявки | `filled` | `Исполнена` (partial → `Частично`, cancelled → `Отменена`, rejected → `Отклонена`, planned → `Запланирована`) |
| Направление | `LONG` / `SHORT` | `Лонг` / `Шорт` (внутри сделки: `Шорт 2 CNY на 49 988 ₽`) |
| Статус робота | `active` / `paused` / `archived` | `Работает` / `На паузе` / `В архиве` (`draft` → `Черновик`, `stopped` → `Остановлен`) |
| Режим | `paper` / `live` | `Бумажный` / `Боевой` |
| Статистика инструментов | `ликвидных: 42 ({"FUTURES":3,...})` | `Ликвидных: 42 — валютные фьючерсы 8, акции 30` |
| Ключ | `env_fallback FINAM_SECRET` | `Ключ не задан, используется переменная окружения` |
| Прогон | `(s.counts ? JSON.stringify(...) : '')` | `Заявок: 3 · Исполнено: 2 · Ошибок: 1` |
| Закрытие позиций | `dry_run=true`, `${r.qty} ${r.symbol}` | `Репетиция: сделка не отправлена` / `Закрыто 2 CNY` |
| Planning job | `${j.id} … ${j.command} … ${last.slot}` | `Утренний прогон · 13:55 МСК · последний запуск успешен` |
| Метрики | `PF`, `win rate`, `DD, дней`, `net` | `Профит-фактор`, `Доля прибыльных`, `Макс. простой, дней`, `Чистая прибыль, ₽` |
| Health | `OK` / `PROBLEMS` | `Всё в порядке` / `Есть проблемы` |
| Ошибка API | `HTTP 400`, `KeyError: x` | `Не удалось сохранить: <человеческая причина>` (детали — в раскрытии) |
| Пустой список | `[]` / пустое место | `Роботов пока нет — создайте первого` |

## 5. Постепенное раскрытие и пустые состояния

**Постепенное раскрытие (уровни):**
- **Уровень 0 (всегда):**human-readable имя, статус, ключевая цифра с единицей (`+1 240 ₽`, `2 контракта`).
- **Уровень 1 (по клику/раскрытию):**параметры стратегии, instrument label, description/about, последнее решение.
- **Уровень 2 (`details` / `title` / кнопка «Технические детали»):**`id`, `spec_id`, `version`, `key_ref`,
  MIC, `command`, JSON `params`, stdout/stderr, коды ошибок.
- Правило: сырой `JSON.stringify`, `stdout`, traceback и `response` не выводятся на level 0 — только level 2.
- Число всегда с единицей; `null`/`undefined`/`nan` → `—` с подсказкой «нет данных» (уже есть в `accounts.html:43`).

**Пустые состояния** (вместо тишины/«—»/пустого `<tbody>`):
- Нет роботов: «Роботов пока нет. Создайте первого из библиотеки стратегий» + кнопка «Создать робота».
- Нет заявок: «Заявок сегодня не было» (уже близко в `trade.html:153` — «заявок нет»).
- Нет счетов: «Нет зарегистрированных счетов» (уже в `accounts.html:51`).
- Нет проблем: «Проблем не обнаружено» (вместо пустого списка в `health.html`).
- Нет данных брокера: «Данные ещё не пришли — обновим автоматически», а не `None`/`equity: null`.
- Ошибка загрузки: «Не удалось загрузить список» + кнопка «Повторить»; детали — в level 2.

## 6. Пять правок с максимальным эффектом и минимальным риском

1. **Словари статусов в JS-хелпер и их применение в `robots.html:343`, `trade.html:108,262`,
   `health.html:56-58`, `index.html:429`.** Чисто презентационный слой, не трогает API/бэкенд;
   снимает сразу `ORDER_STATUS_*`, `active/paused`, `OK/PROBLEMS`.
2. **Заголовок из `note`/`label`/`about` вместо `id`/`spec_id` в `sidebar.js:15,21,34-36`,
   `robots.html:302,340`, `trade.html:142,193`.** Поля уже приходят в `/api/instances:100-104` и
   `/api/state`; меняется только `textContent`, логика и id остаются для ключей/навигации.
3. **Скрыть технический слой в `<details>` в `robots.html:341,346` и `trade.html:150,217`.**
   Параметры, `last_decision`, `command`, `spec_id` уезжают в раскрытие; нет риска сломать данные.
4. **Заменить `JSON.stringify(by_type/counts)` в `robots.html:267,486` на фразы из п. 2.**
   Локальная замена форматирования, API `/api/instruments/stats` и `/live-control` не меняются.
5. **Единый `fmtMoney/fmtQty` с единицами и `—` для `null` в `accounts.html:43`,
   `trade.html:120`, `index.html:471-474,607-609`.** Убирает `nan`/`None` и смешанные единицы;
   не влияет на расчёты (только вывод).

Все пять — правки level 0/1 в шаблонах; не меняют контракты API, модель исполнения и издержки,
поэтому ADR по `docs/decisions.md` не требуется. Глубокая переработка API (переименование полей,
добавление `display_name` в `/api/instances`) — отдельная тема с ADR.

## 7. Карта мест (быстрый индекс)

- `web/templates/robots.html` — id/spec_id, статусы, dry-run, key_ref, JSON by_type/counts/params, stdout.
- `web/templates/trade.html` — o.status/side/symbol, j.command/last.status/slot, архив id/mode/status/strategy.
- `web/templates/index.html` — config ids как пункты меню, `LONG/SHORT`, `PF/win rate/DD, дней`, хардкод счёта.
- `web/templates/accounts.html` — `a.id`/`v.id`, `a.status` (тип исключения), `last_decision`; уже есть `num()`.
- `web/templates/health.html` — `h.status` `OK/PROBLEMS`, `x.source`/`x.text` единого лога.
- `web/static/sidebar.js` — заголовок = `i.id`, иконки `П/У`, `title = i.spec_id`.
- `web/app.py` — `/api/state` (`config_stats`, `status: live/waiting/offline`), `/api/config/{id}` (`dir: LONG/SHORT`).
- `web/instances_api.py` — `/api/instances` (id/spec_id/mode/status), `/api/logs` (source/text),
  `/api/accounts/analytics` (status = имя исключения, equity=None), `/api/service-key` (env_fallback).
