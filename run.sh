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
  test)   "$PY" tests/test_engine.py ;;
  check)  "$PY" scripts/01_data_check.py "${2:-CNYRUBF.txt}" ;;
  update) "$PY" scripts/10_append_iss.py ;;
  signal) "$PY" scripts/20_mvp_signal.py ;;
  paper)  "$PY" scripts/21_mvp_paper.py ;;
  broker) "$PY" scripts/30_broker_check.py ;;
  paper-live) shift; "$PY" scripts/31_paper_live.py "$@" ;;
  report) "$PY" scripts/32_paper_report.py ;;
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

  test     юнит-тесты движка
  check    качество данных (по умолчанию CNYRUBF.txt)
  update   добрать свежие бары с MOEX ISS
  signal   сигнал Простушки на сегодня
  paper    записать сигнал в бумажный журнал (по архиву)
  broker   проверка доступа к Финаму
  paper-live  бумажная торговля по живым котировкам (6 конфигураций)
  report   отчёт: факт против бэктеста
  sweep    полная сетка параметров Простушки
  all      прогоны Простушки на Si + Универсалки
  favicon  перегенерировать иконку веб-панели
  dash     перезапустить локальную веб-панель (по умолчанию :8809)
  author-fit  подбор правил автора по истории счёта-последователя
  author-oos  те же правила на 2022–2025 (вне окна подгонки)
EOF
    ;;
esac
