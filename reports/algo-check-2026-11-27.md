# Чек алго — 27.11.2026, 13:27–13:33 МСК

Только чтение: API панели, журналы, файлы и брокер через `acc:2102993`.
Заявки, STOP, ARM и настройки не менялись. VPN `Sysinv SSTP` поднят с десктопа.

## Итог

Контур работает штатно, инцидентов нет. До 14:00 МСК идут только плановые
решения; новых заявок сегодня не было. В 13:55/13:57/14:00 запланированы
дневной прогон бумаги, тень и боевой таймер.

## Факты

- `/api/health`: `OK`, `problems=[]`, `warnings=[]`, данные `2026-11-27`, 88 строк,
  `stop=false`. `/api/state`: `ok=true`, таймеры morning/daily/web active.
- Роботы: 19 активных (17 бумажных, 2 боевых: `prostushka-test-1`,
  `money-market-fmmm`). `runtime_state` — 18 записей; у бумажных роботов
  позиции и решения от 26.11 (обновляются только миграцией/потоками, ожидаемо).
- Планировщик: 172 запуска за сегодня — 61 `ok` (задания роботов), 111 `shadow`
  (системные слоты, которые исполняют systemd-таймеры; см. раздел «Что такое
  shadow»), ошибок и пропусков нет. Канальные задания `cb-day`/`cb-day-si`
  исполнились в 13:00 (лот 0, «ожидание пробоя»); у `u-*` в 13:30 — «решения
  будут с 13:50». Следующие задачи: 13:40/13:50 entry, 13:55 daily, 13:57 shadow,
  14:00 live.
- Таймеры на WSL: `algotrading-live.timer` next 14:00, last 26.11 14:00;
  `shadow` 13:57, `daily` 13:55, `update-live`/`channel` каждые 10 мин
  (последние 13:20, данные M5 до 13:15). `algotrading-friday.timer` 18:45.
- STOP/STOP_REAL отсутствуют; `live-state`: `stop_paper=false`, `stop_real=false`,
  `allow_trading=false` (флаг веб-процесса), `live_trading_enabled=true`,
  `next_run=14:00`. Из lock-файлов только штатный `results/scheduler.lock`.
  ARM: `mm=true`, `close=false` (состояние панели, не менялось).
- Брокер (ключ `acc:2102993`, значение не выводилось): счёт `ACCOUNT_ACTIVE`,
  позиция `CNYRUBF@RTSX = -2` по 12.289, текущая 12.338, нереализованный
  убыток −98 ₽, equity 49 940,82 ₽, активных заявок 0. Совпадает с
  `runtime_state` живого робота (позиция −2, equity 49 975,26 — разница
  в нереализованном PnL).
- Журнал: 20 строк, последняя от 26.11; `live.csv` — 17 `planned`, 2 `rejected`,
  1 `filled` (первая сделка 24.11). Сегодня новых записей нет. `shadow.json`
  за 26.11: 10 `planned`, `issues=[]`.

## Что такое shadow

В проекте два разных уровня «тени» — оба означают «сделать вид, не нажать
кнопку», но решают разные задачи:

1. **Теневой прогон G3** — `scripts/33_shadow_live.py` (`./run.sh shadow`,
   таймер 13:57). Берёт уже принятые бумагой решения из `results/paper.csv`,
   считает дельты позиций и прогоняет их через `OrderGateway(dry_run=True)`.
   Заявки **не отправляются брокеру**, даже если `FINAM_ALLOW_TRADING=1`.
   Результат пишется в отдельные `results/shadow.csv` (`planned`/`rejected`),
   `results/shadow.json` и отдельный `shadow.lock` — боевой контур пользуется
   `live.csv`/`live.lock` и с тенью не пересекается. Плюс сверка ожидаемых
   позиций с брокером (`issues`): расхождения бумажного и реального счёта
   ожидаемы, тень проверяет сам конвейер расчёта, а не совпадение портфелей.

2. **Shadow-режим планировщика** — `ALGO_SCHEDULER_SHADOW=1` и
   `ALGO_SCHEDULER_ONLY_ROBOTS=1`. Внутренний планировщик видит все задания,
   но по-настоящему исполняет только `inst:...` (задания роботов, `status=ok`).
   Системные задания (`daily`, `channel`, `update_live`, `shadow`) он только
   пишет в лог как `SHADOW ...` и помечает `status=shadow`, чтобы не выполнять
   работу дважды: их реально запускают systemd-таймеры
   (`algotrading-daily.timer`, `algotrading-channel.timer`,
   `algotrading-update-live.timer`, `algotrading-shadow.timer`).

Поэтому 111 `shadow` в этом отчёте — не пропуски и не ошибки, а ожидаемые
пустые слоты системных заданий; сегодняшний теневой прогон ещё не запускался
(13:57), в `shadow.json` пока данные за 26.11.

## Замечания (не требуют действий)

- `shadow.json` содержит `reconcile_error` `GET /v1/accounts/2102993: 404` —
  это ответ на сервисный ключ; запрос с ключом счёта `acc:2102993` возвращает
  счёт и позиции нормально. Ранее зафиксировано в
  `reports/prostushka-live-audit-2026-11-25.md`.
- В `results/web.log` есть старый 500 `POST /api/instances/money-market-fmmm/trade`
  (`enable() missing 'store'`) до трёх последних перезапусков; в текущей
  выкладке `robot_trade.py` вызывает `live_control.enable(store)`, свежих 500 нет.
- После 14:00 имеет смысл повторно прочитать `/api/journal`, `live_run.json`,
  позицию и заявки брокера, `runtime_state` — проверить результат боевого прогона.

## Команды (только чтение)

```bash
curl -s http://192.168.0.230:8080/api/health
ssh wsl-algo 'systemctl list-timers --all --no-pager; ls -l ~/algotrading/results/STOP* ~/algotrading/results/*lock*'
ssh wsl-algo 'cd ~/algotrading && .venv/bin/python - <<"PY"
from algo.broker.finam import FinamBroker
from algo.broker.secrets import resolve_secret
b = FinamBroker(secret=resolve_secret("acc:2102993"), account="2102993")
print(b.account()["status"], b.account()["positions"], b.orders())
PY'

# тень G3 и shadow-слоты планировщика
ssh wsl-algo 'cd ~/algotrading && cat results/shadow.json && tail -5 results/shadow.csv && grep "^SHADOW " results/scheduler.log | tail -5'
```

## Обновление 13:51 МСК (после шага 1 упрощения)

Выше — снимок на 13:33, ниже — что изменилось за время работы.

- В 13:50 сработало задание робота `inst:prostushka-test-1:schedule`:
  `buy 2 CNY` по 12.338, статус `filled`, `client_id …12:00:buy:0`,
  order_id `2024119628774854317`. Заявки никто не отправлял вручную — это
  штатный расписанный прогон.
- Брокер: позиция `CNYRUBF@RTSX = 0` (была −2), equity 49 940,82 ₽,
  активных заявок 0. `runtime_state` живого робота пока показывает −2 —
  факт записан до исполнения; должен обновиться следующим прогоном.
- В 14:00 systemd `algotrading-live.timer` действительно сделал второй прогон:
  `live_run.json` → `counts={"noop": 1}`, `live.log` → `1 решений, статусы
  {'noop': 1}`, новых заявок в `live.csv` нет. Ожидал `duplicate`, получил
  `noop` — цель уже закрыта, так что вред был только в лишнем слое запуска.
  Это подтвердило аргумент за шаг 2.
- Шаги 1–3 сделаны в репозитории: три ADR `2026-11-27` в `docs/decisions.md`,
  один `ALGO_SCHEDULER_MODE=off|robots|all`, удалён systemd-таймер боя —
  разрешение торговли теперь через задания `inst:*` в `algo/live_control.py`;
  системные задания убраны из планировщика, старые id чистит
  `drop_system_jobs()` при старте. Тесты (`./run.sh test` — 44 блока OK,
  `npm test`, `npm run build`) зелёные.
- Панель переехала на стандартный порт 80: `http://192.168.0.230/`.
  Коммит `03fa94f` запушен, `deploy_wsl.sh --apply --restart` прошёл с md5 OK,
  новый юнит установлен на WSL, web и scheduler активны, порт 8080 освобождён.
  Галка расписания убрана из строки робота: поля расписания перенесены внутрь
  «Настроить» робота; глобальная вкладка «Расписание» удалена.
- Важно: `192.168.0.230` — адрес Windows-хоста, а не WSL (у WSL eth0
  `192.168.71.171`). Старый `:8080` пробрасывался на Windows-side portproxy;
  после переезда сервис слушает 80 внутри WSL (`curl 127.0.0.1/api/health`
  отвечает), но `http://192.168.0.230/` с десктопа пока недоступен — нужно
  добавить проброс 80 на Windows и разрешить его в файрволе.
- После Windows-проброса `192.168.0.230:80 → 192.168.71.171:80` и правила
  файрвола внешний адрес заработал: `/ui/` 200, `/api/scheduler/jobs` — 18 строк
  без системных, `/api/trading/status` — `mode=robots`, `scheduled=2`.
  `node webui/check-all.mjs http://192.168.0.230/ui/` — 7 разделов, вкладки
  на месте, JS-ошибок нет; 4 console-сообщения 503 — это `/api/health`.
- `/api/health` после 13:55 снова shows 503 из-за ложного tracking error
  (`p-base −1026 ₽` и др.): ожидание считается по статическим конфигам M5,
  а факт — по инстансам H1 с `timeframe=60`. Корень описан в
  `reports/live-first-trade-audit.md`; это не дефект упрощения и не откат торговли.
  `runtime_state` живого робота после 14:00: позиция 0, equity 49 940,82 ₽.

## Финальное состояние после доработок 27.11 (17:30 МСК)

- `/api/health`: `OK`, `problems=[]`; ложный tracking error устранён, включая
  сохранение ATR в ожидании за исторические даты (до 27.11 включительно).
- Управление сведено к СТАРТ / СТОП / ЗАКРЫТЬ ВСЁ. `FINAM_ALLOW_TRADING`,
  `--arm`, ARM фонда/закрытия и локи заявок удалены; STOP_REAL и лок
  планировщика остаются. Повторные заявки ловит `UNIQUE client_order_id`.
- Виртуальный счёт (`TEST`) не может дать реальную заявку: проверки в
  `RobotStore`, whitelist боя, `position_ops`, `live_control` и `robot_trade`.
- Бой сам считает сигнал по свежим барам (`algo/live_signal`) и пишет
  персональный журнал `robot_decisions`; `paper.csv` остался только бумаге.
  Бары M5/D1 хранятся в `market.db`, график показывает маркеры сделок/заявок.
- ATR вынесен в `algo/atr.py` и по умолчанию выключен; у всех 17 роботов
  флаг `risk_vol=false`, в настройках есть явный «Вкл/Выкл».
- Депозиты на 17 роботов: `reports/test-deposits-2026-11-27.md`
  (минимум 1 006 000 ₽, рекомендуемый тест 1 110 000 ₽, полный 3 669 851 ₽).
- Проверки: `./run.sh test` EXIT=0, `npm test` 7 тестов, `npm run build` OK,
  `check-all.mjs` — 7 разделов, 0 ошибок. Коммиты `71cfac9`, `ab83e65` запушены.
- Smoke-проверка пути сигнала на WSL (без отправки): 2 живых робота,
  1 план, 1 решение; заявок не отправлялось.
