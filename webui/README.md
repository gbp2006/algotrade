# Autopilot WebUI (параллельный фронт)

React 18 + TypeScript `strict` + Vite + Tailwind/Radix. Работает с теми же
FastAPI-эндпоинтами, что и старая панель Jinja/JS. Старый контур не переписан:
он по-прежнему доступен на `/`, `/trade`, `/robots`, `/accounts`, `/health`.

## Запуск

```bash
cd webui
npm install
npm run dev        # http://127.0.0.1:5180, /api проксируется на :80
npm run build      # dist/ — отдаётся тем же FastAPI по /ui
npm test           # Vitest
```

Переменная `VITE_API_TARGET` задаёт адрес бэкенда для прокси (по умолчанию
`http://127.0.0.1`).

## Состав

- 7 разделов с вкладками: портфель, графики, роботы, симуляция, счета,
  операции, логи.
- Тёмная/светлая темы и плотность таблиц — `localStorage` (`algo.ui.v1`),
  `font-variant-numeric: tabular-nums` для всех чисел.
- TanStack Query — серверные данные; Zustand — контекст интерфейса;
  React Hook Form + Zod — мастер робота; `lightweight-charts` — кривая капитала
  с маркерами потоков и свечи с маркерами сделок; `@tanstack/react-table` —
  таблицы; Dexie/IndexedDB — офлайн-кэш.
- Доменные расчёты не дублируются: сайзинг, валидация и метрики считает
  Python-бэкенд (`/api/cash-flows/preview`, `/api/portfolio/*`).

## Связь с бэкендом

Новые маршруты добавляются в `web/cash_flows_api.py`. Снимки equity, денежные
потоки из транзакций Финам и влияние на лотность пишутся в новые таблицы
`robots.db`; схема существующих счетов и роботов не менялась.

Целевая схема PostgreSQL/TimescaleDB описана в `infra/db/schema_timescale.sql`
и пока не применяется.
