# Finam API Skill: установка в песочницу algo

## 00:20 — Вопрос пользователя

Что такое Finam API Skill и установлен ли он у нас. Выяснено: в песочнице подключён
удалённый MCP-сервер `finam-mcp` (19 инструментов), но самого скилла `trade-api`
нет ни в `.opencode/skills`, ни в общих папках; в `opencode.jsonc` действует
`skill: * deny`. Скилл из https://api.finam.ru/getting-started/finam-trade-skill-dlya-ai-agenta/
отличается от MCP: инструкции + скрипты, прямой REST/gRPC/WebSocket, генерация
стратегий на `finam-sdk` и бэктест в диалоге.

## 00:24 — Решение: ставить скилл в проект

Пользователь: «поставь в algo». Выбрана проектная установка (не глобальная),
агент `opencode` — установщик `skills` determines its agent automatically.

## 00:25 — Установка

`npx -y skills add https://github.com/finamweb/finam-trade-api --skill trade-api -a opencode -y`
→ `.agents/skills/trade-api/` (SKILL.md, `.env.example`, `scripts/asset_search.py`,
`scripts/scanner.py`, `scripts/top_stocks.py`), `skills-lock.json`.
Проверка установщика: Safe / 0 alerts / Med Risk.

Изменения:
- `opencode.jsonc` — добавлен `allow` для `skill: trade-api`;
- `requirements.txt` — добавлен `finam-sdk>=2.24`;
- `.venv` — установлен `finam-sdk 2.24.0`;
- `.env` — подготовлена переменная `TRADE_API_SECRET` (значения в журнал не пишем).

## 00:30 — Проблема с токеном

Переиспользование `FINAM_SECRET` из `.env` не сработало: REST `POST /v1/sessions`
→ HTTP 401 `Invalid secret key`, SDK → `AuthError: Invalid secret key`.
`TRADE_API_SECRET` оставлен пустым.

## 00:34 — Рабочий токен

Пользователь сообщил рабочий токен (в чат, что нарушает правило «секреты не в чат» —
рекомендована ротация). Записан в `.env` в `TRADE_API_SECRET`, права файла `600`.
Проверка: REST-авторизация HTTP 200; `asset_search.py 'SBER*' --type EQUITIES`
→ exit=0, найдено 4 инструмента. Скилл подхвачен сессией (появился в списке skills).

Открытые вопросы (отложены по просьбе пользователя):
- ротировать токен, опубликованный в чате;
- старый `FINAM_SECRET` в `.env` остался невалидным (401), замену не делали;
- изменения не закоммичены: `.agents/`, `skills-lock.json`, `opencode.jsonc`,
  `requirements.txt` (`.env` в gitignore).

## 00:38 — Конец: установка Finam API Skill в algo

Скилл `trade-api` установлен в проект, разрешён в профиле `algo`, зависимости
поставлены, рабочий токен подключён и проверен поиском инструментов. Вопросы
ротации секрета, замены `FINAM_SECRET` и коммита отложены. Статус: **отложено**.
