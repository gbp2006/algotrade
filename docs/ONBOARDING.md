# Onboarding — точка входа для ИИ/разработчика

Этот файл читается **первым**. За 5 минут он даёт достаточно контекста, чтобы не
ломать работающий контур. Полный инвентарь частей — `docs/MODULES.md`,
решения — `docs/decisions.md`, текущий статус — `PROGRESS.md`.

## 1. Что это за проект

Песочница алготрейдинга: исследование стратегий, бэктесты, бумажная торговля,
боевой контур через Финам, web-интерфейс. Всё на одном хосте WSL
`192.168.0.230`, песочница — `/mnt/DiskD/opencode-algo`.

**Инварианты (меняются только отдельным ADR):**
- Сигнал по `close` → сделка по `open` следующего бара; `skip_weekend=True`.
- Издержки: 0.01% за сторону + 1 тик; CNY шаг 0.001 × 1000 ₽, Si шаг 1.0 × 1 ₽.
- Счета создаются/правятся/удаляются в разделе «Счета» (`/api/accounts`,
  `/api/keys`); у счёта есть `TEST/LIVE`, `enabled` и `key_ref`. Ключ вводится
  в диалоге «Ключ» и хранится в `auth.json`. Удаление запрещено, если счёт
  привязан к роботу.
- Реальная торговля включается/выключается кнопкой в панели (таймер
  `algotrading-live.timer`, 14:00 МСК). Ворота G2/G3 не являются блокировщиком:
  пользователь снял это ограничение.
- ATR-сайзинг, дневной лимит убытка и Reduce-Only выключены (ADR 19.11/23.11).
- Лотность считается **только** через `algo.portfolio.size_contracts()`.
- Секреты — только `auth.json` (600) или `{env:...}`; в API/UI/БД — имена ссылок.

## 2. Стек и адреса

| Слой | Технология | Где |
|---|---|---|
| Движок/расчёты | Python 3.14, pandas/numpy | `algo/` |
| API и раздача UI | FastAPI + uvicorn | `web/` |
| Интерфейс | React 18 + TS strict + Vite + Tailwind/Radix | `webui/`, сборка `webui/dist/` |
| Рабочее хранилище | SQLite (`robots.db`, `trades.db`, `market.db`) | `infra/db/` |
| Целевое хранилище | PostgreSQL 18 + TimescaleDB (опционален) | `infra/db/schema_timescale.sql` |
| Офлайн браузера | IndexedDB через Dexie | `webui/src/lib/offline.ts` |
| Фон | systemd-таймеры и сервисы | `infra/systemd/` |

Адреса на WSL:
- GUI: `http://192.168.0.230:8080/` (все старые пути отдают React);
- API: `http://192.168.0.230:8080/api/...`;
- локальная dev-копия фронта: `cd webui && npm run dev` → `http://localhost:5180/ui/`,
  `/api` проксируется на `VITE_API_TARGET` (по умолчанию `:8080`).

## 3. Команды

```bash
./run.sh test            # все Python-тесты
cd webui && npm test     # Vitest
cd webui && npm run build# сборка в webui/dist
./run.sh check-ui       # headless: 7 разделов, вкладки, 0 ошибок JS
./scripts/deploy_wsl.sh --apply --restart                # выкладка на WSL
./run.sh start-project   # НА WSL: PG → миграция → systemd → HTTP-проверка
./run.sh migrate-pg      # однократная миграция SQLite → PG (идемпотентна)
```

`scripts/start_project.sh` вызывается при старте/перезапуске WSL: он включает
PostgreSQL, применяет схему и миграцию, чистит `__pycache__` (rsync сохраняет
mtime — иначе сервер поднимает старый байткод) и остатки старого Jinja-UI,
устанавливает юнит `algotrading-web.service` (зависит от PostgreSQL),
перезапускает панель и проверяет HTTP-коды.

## 4. Что где лежит

- `algo/strategies/` — сигналы; ничего не знают про деньги и брокера.
- `algo/portfolio.py` — единственный расчёт лотности; `size_contracts()`.
- `algo/cash_flows.py`, `algo/portfolio_metrics.py` — чистые расчёты потоков
  и метрик (TWR/MWR/DD/Sharpe/Sortino/PF/Winrate/Expectancy).
- `algo/cash_flow_store.py` — новые таблицы в `robots.db`, идемпотентная запись.
- `algo/account_poller.py` — опрос счетов и подтверждение потоков из транзакций
  Финам; `POST /api/cash-flows/sync` и фоновый цикл панели.
- `algo/pg_store.py` — PostgreSQL с DSN только из `auth.json`.
- `web/app.py` — маршруты страниц (React) и часть API; `web/instances_api.py` —
  управление роботами/счетами; `web/cash_flows_api.py` — деньги и портфель.
- `webui/src/sections/` — 7 разделов интерфейса; состояние в Zustand и
  TanStack Query; темы/плотность — `localStorage`.
- `scripts/34_live_execute.py` — боевой контур; перед заявкой свежий equity
  через `account_equity()`; реальная отправка требует `--arm` и флага.

## 5. Данные и источники правды

- Деньги: брокер. Пользователь сам пополняет/выводит; проект обнаруживает
  изменения опросом и записывает поток по id транзакции.
- Позиции/заявки: `infra/db/trades.db` (журнал) + ответ брокера.
- Роботы/счета/версии параметров: `infra/db/robots.db`.
- История котировок: `infra/db/market.db`, данные не копируются (`data/` — symlink).
- Снимки equity и потоки: SQLite + PostgreSQL (dual-write); API читает PG,
  если настроен DSN, иначе SQLite.

## 6. Как проверять перед показом

1. `./run.sh test` — зелёный.
2. `cd webui && npm test && npm run build` — зелёный.
3. Выложить: `./scripts/deploy_wsl.sh --apply --restart`.
4. `node webui/check-all.mjs http://192.168.0.230:8080/ui/` — все 7 разделов
   и вкладки без ошибок JS. **Не давать ссылку пользователю без этого шага.**
5. `curl http://192.168.0.230:8080/api/health` — `status OK`, `problems=[]`.

## 7. Что нельзя делать

- Не дублировать формулу лотности в TypeScript — только вызов API.
- Не писать секреты в конфиги, код, логи и чат.
- Не менять модель исполнения и издержки; вкл/выкл торговли — только через
  кнопку в панели (с подтверждением), не прямой правкой `.env`.
- Не удалять старые API-ответы: добавлять поля, не ломая контракт.
- Не запускать панели/сервисы на десктопе — только код/тесты; WSL-правки
  писать и проверять на WSL после commit + push.

Оставшееся на момент написания: подключение Т‑Инвестиций после получения
токена (адаптер и маппинг готовы).
