# Сессия — проверка WSL-контура и доступ через Sysinv SSTP

## 23:09 — старт: «проверь наш проект»

Проверил локальную песочницу: `./run.sh test` — 296 тестов в 42 файлах, 0 падений;
`npm test` — 4 зелёных; `npm run build` — OK (warning: бандл 720 КБ > 500 КБ);
`./run.sh check` и `./run.sh data-qa` — дублей 0, ISS/live совпали 100%, отчёт
`reports/data-qa-2026-11-25.md`. Локальный `results/health.json` показал `ok=false`
только потому, что локальные `paper.csv` / `finam_m5_CNY.csv` заканчиваются
23.11 — это проверяющая копия, а не боевой контур.

## 23:12 — уточнение: проект — в первую очередь WSL algo

`curl :8080` сначала не прошёл; затем пинг и порты открылись. Выяснено: доступ к
`192.168.0.230` идёт через VPN NetworkManager `Sysinv SSTP` (интерфейс `ppp0`,
сейчас `192.168.100.193`). SSH-алиас `wsl-algo`: `192.168.0.230:2222`, user `zt`,
ключ `~/.ssh/wsl_algotrading`. Команда `nmcli con up "Sysinv SSTP"` выполняется
без sudo (если уже активна — NetworkManager сообщает об этом).

## 23:12–23:15 — проверка на WSL

- `/api/health`: `status OK`, `problems=[]`, `warnings=[]`, `data_date=2026-11-25`, `rows=69`, `stop=false`.
- `algotrading-web.service` active; таймеры daily/morning/friday/update-live/shadow/channel/live/backup активны, последние прогоны 25.11 по расписанию. `algotrading-live.service` inactive между запусками — норма.
- `./run.sh check-ui` через WSL: 7 разделов, вкладки, `errors=0`, `problems=[]`.
- `./scripts/deploy_wsl.sh` (dry-run): расхождения только в `webui/dist/index.html`, `index-C8zCuHCX.js`, `index-KSd3VsVq.css` после локального `npm run build`; Python-код, тесты и docs совпадают.
- Репозиторий на WSL: HEAD `4d92240 deploy: whitelist-синхронизация...`, 192 отслеживаемых файла, рабочее дерево грязное (rsync-деплой без коммитов) — ожидаемое состояние, не сигнал о рассинхроне.
- `results/shadow.json` за 25.11: 9 planned, 1 issue — `GET /v1/accounts/2102993: 404 Account with id ...`, то есть сверка позиций по реальному счёту недоступна. Ранее по 20/23/24.11 тоже были расхождения (2/3/1). Для тени это не блокировщик, но стоит проверить причину 404.
- `results/live.csv`: 24.11 14:00 реальная заявка `prostushka-test-1` filled (2 CNY); 25.11 14:00 заявка rejected — «номинал 49308 выше лимита 24967» (лимит по `max_exposure=0.5` и equity). `/api/live-state`: `allow_trading=false`, `live_trading_enabled=true`, `stop_real=false` — флаг веб-процесса и состояние таймера, по ONBOARDING это штатно.

## 23:16 — решение пользователя

«Доступ к WSL (панель/алго) через SSTP Sysinv — подключайся сам, запиши и запомни».
Зафиксировано в `docs/ONBOARDING.md` (блок перед адресами) и одной строкой ADR в
`docs/decisions.md`. Секреты VPN/SSH в проект и чат не писались. Индекс памяти
пересобран `python3 infra/db/memory.py build`, `INDEX.md` — `index-sync`.

### 23:18 — Конец: проверка WSL-контура и фиксация доступа

Статус: **решено**. WSL-контур здоров (health OK, UI 7/0, код в синхроне), способ
подключения задокументирован и попадёт в память через индекс. Открытые вопросы
для отде тем: 404 при сверке позиций в shadow и повторный отказ реальной заявки
25.11 по лимиту номинала; расхождение `webui/dist` с локальной сборкой — перед
выкладкой нужен `deploy_wsl.sh --apply --restart` после commit/push.
