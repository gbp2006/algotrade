#!/usr/bin/env bash
# Полный старт проекта на WSL: PostgreSQL → схема/миграция → панель → проверка.
# Идемпотентно: можно вызывать после перезагрузки WSL или выкладки.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "1/5 PostgreSQL"
sudo -n systemctl enable --now postgresql >/dev/null

echo "2/5 схема и миграция SQLite -> PostgreSQL"
./.venv/bin/python scripts/97_migrate_to_postgres.py

echo "3/5 systemd-юнит панели"
sudo -n cp infra/systemd/algotrading-web.service /etc/systemd/system/algotrading-web.service
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now algotrading-web.service >/dev/null

echo "4/5 проверка HTTP"
for path in / /ui /api/health /api/cash-flows /api/portfolio/analytics; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://127.0.0.1:8080$path" || true)"
  echo "  $code $path"
  [ "$code" = "200" ] || { echo "ОШИБКА: $path вернул $code" >&2; exit 1; }
done

echo "5/5 статус сервисов"
printf '  postgresql: '; sudo -n systemctl is-active postgresql
printf '  web:        '; sudo -n systemctl is-active algotrading-web.service
echo "готово: GUI http://127.0.0.1:8080/"
