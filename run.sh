#!/usr/bin/env bash
# Короткие команды песочницы. Запуск из любой папки.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-$(dirname "$0")/.venv/bin/python}"
if [ ! -x "$PY" ]; then
  echo "нет .venv: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

case "${1:-help}" in
  test)   for f in tests/test_*.py; do "$PY" "$f" || exit 1; done ;;
  check)  "$PY" scripts/01_data_check.py "${2:-CNYRUBF.txt}" ;;
  data-qa) "$PY" scripts/47_data_qa.py ;;
  update) "$PY" scripts/10_append_iss.py ;;
  update-live) "$PY" scripts/10b_append_finam.py ;;
  signal) "$PY" scripts/20_mvp_signal.py ;;
  paper)  "$PY" scripts/21_mvp_paper.py ;;
  broker) "$PY" scripts/30_broker_check.py ;;
  paper-live) shift; "$PY" scripts/31_paper_live.py "$@" ;;
  shadow) "$PY" scripts/33_shadow_live.py ;;
  backup) "$PY" scripts/95_backup_db.py ;;
  migrate-pg) "$PY" scripts/97_migrate_to_postgres.py ;;
  assign-paper-accounts) "$PY" scripts/98_assign_paper_accounts.py ;;
  start-project) bash scripts/start_project.sh ;;
  check-ui) node webui/check-all.mjs "${2:-http://192.168.0.230/}" ;;
  # --arm и FINAM_ALLOW_TRADING убраны (ADR 27.11): команда задания live-run
  # отправляет заявки, если робот активен, счёт LIVE и задание включено.
  live-run) shift; "$PY" scripts/34_live_execute.py "$@" ;;
  live) shift; "$PY" scripts/34_live_execute.py "$@" ;;
  live-dry) shift; "$PY" scripts/34_live_execute.py --dry-run "$@" ;;
  rollover) shift; "$PY" scripts/35_rollover_live.py "$@" ;;
  rollover-dry) shift; "$PY" scripts/35_rollover_live.py --dry-run "$@" ;;
  report) "$PY" scripts/32_paper_report.py ;;
  store) shift; "$PY" scripts/00_store.py "$@" ;;
  sweep)  "$PY" scripts/15_sweep_full.py ;;
  all)
    "$PY" scripts/09_si_check.py
    "$PY" scripts/11_universal.py
    ;;
  favicon)
    "$PY" scripts/41_favicon.py
    ;;
  dash)
    port="${2:-8809}"
    # гасим прежние экземпляры панели: старый процесс держит старый код → 404 на новых API
    for pid in $(pgrep -f -- "-m uvicorn web.app:app" || true); do
      case "$(readlink "/proc/$pid/exe" 2>/dev/null)" in
        *python*) kill "$pid" 2>/dev/null || true ;;
      esac
    done
    sleep 1
    setsid nohup "$PY" -m uvicorn web.app:app \
      --host 127.0.0.1 --port "$port" > results/web-local.log 2>&1 &
    sleep 3
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 \
      -X POST "http://127.0.0.1:$port/api/alerts/ack" || true)
    echo "dash :$port — ack $code (200 = код свежий, 404 = старый процесс), лог results/web-local.log"
    ;;
  author-fit)
    "$PY" scripts/44_author_fit.py
    ;;
  author-oos)
    "$PY" scripts/45_author_oos.py
    ;;
  *)
    cat <<'EOF'
usage: ./run.sh <команда>

  test     юнит-тесты движка, хранилища, брокера и бумажного контура
  check    качество данных (по умолчанию CNYRUBF.txt)
  data-qa  дубли, стык месяцев, ISS против архива и живого фида
  update       добрать свежие бары с MOEX ISS (независимый архив)
  update-live  дописать M5-бары Финама на диск (как раз решает робот)
  signal   сигнал Простушки на сегодня
  paper    записать сигнал в бумажный журнал (по архиву)
  broker   проверка доступа к Финаму
  paper-live  бумажная торговля по живым котировкам (активные инстансы из store)
  report   отчёт по бумажному журналу: дни, сделки, P&L, метрики
  shadow   теневой прогон G3: плановые заявки без отправки
  backup   консистентный бэкап trades/robots/paper_metrics в backups/db (0600)
  migrate-pg  однократный перенос служебных данных SQLite в PostgreSQL
  assign-paper-accounts  развести бумажных роботов по отдельным TEST-счетам
  start-project  полный старт на WSL: PostgreSQL, миграция, панель, проверка
  check-ui   headless: 7 разделов, вкладки, правка счёта, deep-link, 0 ошибок JS
  live-run боевой контур по заданию активного LIVE-робота (заявки уходят)
  live     то же, что live-run (старое имя)
  live-dry явная репетиция боя: проверяет всё, но заявки НЕ уходят
  rollover      перекладка квартальных позиций (заявки уходят)
  rollover-dry  репетиция перекладки без отправки
  store    хранилище баров: init|import-txt|import-finam|export|import-csv|stats
  sweep    полная сетка параметров Простушки
  all      прогоны Простушки на Si + Универсалки
  favicon  перегенерировать иконку веб-панели
  dash     перезапустить локальную веб-панель (по умолчанию :8809)
  author-fit  подбор правил автора по истории счёта-последователя
  author-oos  те же правила на 2022–2025 (вне окна подгонки)
EOF
    ;;
esac
