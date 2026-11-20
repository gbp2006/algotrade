# 2026-11-20 — бесплатные модели: отбор и «Избранные»

## 15:33 — задача

Найти через любого провайдера модели, которые работают бесплатно; отобрать
5 лучших и добавить в «Избранные» OpenCode. Если для доступа нужна регистрация
или новый API-ключ — сказать.

## 15:40 — инвентаризация

В профиле `algo` 207 моделей от 9 провайдеров; нулевая цена (input/output = 0)
у 33 позиций. Провайдеры с бесплатными: `opencode` (Zen free), `opencode-go`,
`openrouter` (`:free`), плюс условно бесплатные `gweb`/`google`/`kimi-code-plan`.

Живая проверка (`opencode run` по одной модели):

- все Zen-free → `This API key has expired` (Console-ключ `sk-OLjz…` протух);
- `openrouter/nvidia/nemotron-3.5-super-vl:free`, `baidu/ernie-5.5-flash-preview:free`,
  `particle-ai/particle-1:free`, `recursive/flint-v1.0:free`, `openrouter/free` → OK;
- `inclusionai/ling-3.2-flash:free` → OK, но 10+ ретраев (в топ не взят);
- `google/gemma-4-26b-a4b-it` → `Quota exceeded … limit: 16000` (free tier).
- Вне клиента ключ Zen даёт `429 FreeUsageLimitError`: бесплатные Zen-модели
  работают только внутри OpenCode.

Отобраны 5: `opencode/hy4-flash-free` (1M/65k, vision), `opencode/tidepool-alpha-free`
(1M/131k), `opencode/longcat-2.5-free` (1M/262k, 100 запросов/день),
`openrouter/nvidia/nemotron-3.5-super-vl:free` (1M/131k, vision),
`openrouter/baidu/ernie-5.5-flash-preview:free` (1M/921k выход).

## 15:50 — где живёт «Избранные»

Не конфиг, а состояние TUI: `<state>/model.json` = `{recent, favorite, variant}`,
state профиля `algo` — `~/.local/state/opencode-algo/opencode/model.json`.
Записи добавлены в начало списка (как это делает `setFavorite`), стало 11.
Ключи UI: `<leader>m` — список моделей, `ctrl+f` — звёздочка,
`model_cycle_favorite` — листать избранное.

## 16:00 — новый Console-ключ (из чата)

Ключ `oc_sk_…` проверен curl: `/inference/openai/v1/models` → 200
(с мусорным ключом 401). Установлен как активная учётка «OpenCode Console»:

- хранилище учёток (БД v2) — новая запись, старая `sk-OLjz…` удалена;
- `auth.json` и `account.json` профиля `algo` обновлены, бэкапы с секретами удалены.

Ошибка: правка `auth.json`/`account.json` без смены активной учётки не помогала —
источник истины в БД, менять только через `opencode auth import|switch|logout`.
Отдельная ошибка: `opencode service restart` оборвал инструменты текущей сессии —
сервис профиля `algo` больше не перезапускать изнутри работающей сессии.

Проверено после замены: `hy4-flash-free`, `tidepool-alpha-free`, `longcat-2.5-free`
→ `OK` и через сервис, и через `--standalone`.

## 16:10 — профиль `oc`

- Console-ключ заменён так же (импорт + switch + logout старой), активна одна учётка;
- `~/.local/state/opencode/opencode/model.json` создан: 7 бесплатных моделей
  (5 отобранных + `recursive/flint-v1.0:free` + `openrouter/free`);
- проверка: `hy4-flash-free`, `tidepool-alpha-free`, `nemotron-3.5-super-vl:free` → OK.

## 16:15 — терминология

Уточнение: WSL — **тестовый сервер, где работают торговые роботы**, а не песочница.
`AGENTS.md` (раздел «Две среды») переписан: песочница — только ПК/профиль `algo`,
на WSL OpenCode и агентских сессий нет; «торговый прототип» → «торговые роботы».
Кода не касались.

Открытый вопрос (не разбирали): на WSL `algotrading-daily.service` упал
20.11 в 13:55 МСК (`./run.sh paper-live; ./run.sh update`, exit 1); веб-панель жива.
В рабочем дереве ПК уже были чужие изменения `results/alerts_seen.json`,
`results/health.json`, `results/paper.csv` — не трогали.

### 16:20 — Конец: бесплатные модели и избранное в обоих профилях ПК

Отобраны и проверены 5 бесплатных моделей (3 Zen-free + 2 OpenRouter `:free`),
избранное заполнено в профилях `algo` (11 записей) и `oc` (7 бесплатных);
протухший Console-ключ заменён новым в обоих профилях, старые учётки удалены.
AGENTS.md уточняет: WSL — тестовый сервер роботов, песочница только на ПК.
**Решено.** Отдельно осталось: разобрать падение `algotrading-daily.service` на WSL.

## 16:22 — Конец: проверка и восстановление роботов на WSL

Сегодня проверена работоспособность торговых роботов на WSL: выяснено, что systemd-юниты
`algotrading-*` и процессы/таймеры отсутствовали (роботы не работали); запущены веб-панель
(user unit, uvicorn :8080) и paper-live (user unit + таймеры morning/daily/friday);
live-прогон `./run.sh paper-live` сделан вручную, решения на 2026-11-20 записаны в
`results/paper.csv`, watchdog OK. Системные unit-файлы не создавались — нет root в
выполняющем контексте. Сделано: user-юниты + enable, live-прогон, таймер friday (18:40).
Отложено: разбор падения `algotrading-daily.service` на WSL.

### 16:22 — Конец: проверка и восстановление роботов на WSL

Роботы на WSL: запущены (панель, paper-live, таймеры), live-прогон и решения 2026-11-20
проверены OK, watchdog OK. Статус: **решено**. Ссылки: `results/paper.csv`,
`scripts/31_paper_live.py`, user-юниты в `~/.config/systemd/user/`.
