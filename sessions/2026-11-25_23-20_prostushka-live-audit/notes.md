# Сессия — аудит Простушки в боевом режиме

## 23:20 — старт: пользователь обеспокоен работой `prostushka-test-1`

Проверил WSL через VPN `Sysinv SSTP` (см. сессию `2026-11-25_23-09_wsl-access-audit`).
В бою только один робот: `prostushka-test-1`, счёт `2102993` (LIVE), источник
сигналов `p-base`, `pricing=marketable`, `exposure=0.5`, версия 3. Сервис
`algotrading-live.service` запускается с `--arm` и `FINAM_ALLOW_TRADING=1`;
таймер 14:00 МСК активен. STOP/STOP_REAL отсутствуют.

## 23:21 — facts

- 24.11 12:00 p-base `target=-32` → в 14:00 sell 2 CNY @12.288, filled (`order_id=2024119615890117491`); в `trades.db` ровно одна сделка.
- 25.11 12:00 p-base `target=+32` → в 14:00 buy 4 CNY @12.327, `rejected`: «номинал 49308 выше лимита 24967». `live_run.json`: armed, 1 rejected, 0 fills.
- Прямой запрос к Финам через `FinamBroker` (ключ из `auth.json`, не печатался): `equity≈49 934 ₽`, `positions={'CNYRUBF@RTSX': -2}`, открытых заявок 0. Журнал `live.csv` даёт −2 — модель и брокер согласованы, STOP не нужен.
- `nmcli`/VPN и SSH работают; `python3` без venv не годится для broker-проверки (нет pandas), использован `.venv/bin/python`.

## 23:23 — причина

`plan_targets()` берёт направление из paper.csv p-base; `size_contracts()` с
потолком счёта 0.5 даёт цель +2; текущая позиция −2 → delta +4. Шлюз
(`algo/broker/execution.py:180`) сравнивает номинал delta-заявки (49 308 ₽) с
`max_notional = equity × 0.5 = 24 967 ₽` и отклоняет. Итоговая позиция после
сделки была бы +2 (в пределах лимита), но лимит применяется к «обороту», а не к
результату — развороты блокируются системно. Если придёт плоский сигнал, buy 2
пройдёт и закроет шорт.

## 23:24 — прочие наблюдения

- `params_json` инстанса (`ma_window=200`, `entry=13:50`) не участвует в расчёте сигнала: исполнение использует `source_config=p-base` и строку paper.csv. Нужно прояснить в UI/ADR, чтобы не вводить в заблуждение.
- `runtime_state` для `prostushka-test-1` нет — позиция может не отображаться в UI.
- `shadow.json` 25.11: transient 404 `/v1/accounts/2102993` в 13:57, прямой запрос позже успешен; ложное расхождение в тени.

## 23:25 — пользователь выбрал вариант 1

«1 — делай!»: ADR + правка семантики лимита. Сначала записан ADR в
`docs/decisions.md`, затем код. В `algo/broker/execution.py` у `Order` появилось
поле `result_qty` (подписанная позиция после исполнения); `_validate()` считает
номинал по `abs(result_qty)`, а не по `qty`. `None` сохраняет старую проверку для
shadow/position_ops/rollover. `scripts/34_live_execute.py` передаёт `result_qty=target`
и в рабочей заявке, и в stub-логе. Три новых теста в `tests/test_execution.py`:
разворот −2→+2 проходит, тот же заказ без `result_qty` отклоняется, закрытие в
flat проверяет нулевой номинал. `docs/MODULES.md` обновлён.

## 23:30 — проверка и выкладка

Локально `./run.sh test` — 299 зелёных в 42 файлах. Коммиты `3cd1244`
(ADR/код/отчёты/сессии) и `d7ea859` (тестовый харнесс) запушены в origin/master.
`./scripts/deploy_wsl.sh --apply --restart`: md5 247 файлов OK, панель active.
WSL `/api/health` OK. Симуляция 25.11 на WSL с реальными `paper.csv` и
`live_settings_from_store`, но с временным журналом и `dry_run=True`: цель +2,
факт −2, заявка 4, номинал итога 24 638 ₽ < лимит 24 967 ₽, статус `planned`.
Реальная заявка не отправлялась; брокер по-прежнему держит −2 CNY.

## 23:36 — попутное: зависание тестов на WSL

`./run.sh test` на WSL висел в `test_http_api.py`: новая Starlette в `FileResponse`
ждёт `http.disconnect`, а фейковый `receive()` его не отдавал. Добавлен
`spec_version=2.4` в scope теста (коммит `d7ea859`, выложен). После этого WSL
прогон дошёл до 15 файлов; оставшиеся ошибки окружения: `test_gui_v2_api.py`
читает `webui/src/*.tsx` (деплоится только `webui/dist`) и `test_instances_api.py`
не патчит `SHADOW_JOURNAL` (на WSL есть `shadow.csv`). К правке лимита это
отношения не имеет; локальный прогон зелёный.

### 23:40 — Конец: разворот Простушки исправлен и выложен

Статус: **решено**. ADR 25.11, коммиты `3cd1244`/`d7ea859`, WSL md5 OK,
health OK, симуляция 25.11 `planned`. Фактическая позиция брокера — шорт 2 CNY
(~24,6 тыс. ₽ при equity ~49,9 тыс. ₽); следующая заявка по сигналу 26.11 14:00
МСК теперь пройдёт лимит. Отчёт `reports/prostushka-live-audit-2026-11-25.md`,
пункт в `PROGRESS.md` помечен как исправленный.
