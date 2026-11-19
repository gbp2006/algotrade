#!/usr/bin/env bash
# Короткие команды песочницы. Запуск из любой папки.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-$(dirname "$0")/.venv/bin/python}"
[ -x "$PY" ] || PY="/mnt/DiskD/opencode/venv/bin/python"

case "${1:-help}" in
  test)   "$PY" tests/test_engine.py ;;
  check)  "$PY" scripts/01_data_check.py "${2:-CNYRUBF.txt}" ;;
  update) "$PY" scripts/10_append_iss.py ;;
  signal) "$PY" scripts/20_mvp_signal.py ;;
  paper)  "$PY" scripts/21_mvp_paper.py ;;
  broker) "$PY" scripts/30_broker_check.py ;;
  paper-live) "$PY" scripts/31_paper_live.py ;;
  report) "$PY" scripts/32_paper_report.py ;;
  sweep)  "$PY" scripts/15_sweep_full.py ;;
  all)
    "$PY" scripts/09_si_check.py
    "$PY" scripts/11_universal.py
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
EOF
    ;;
esac
