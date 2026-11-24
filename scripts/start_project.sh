#!/usr/bin/env bash
# Полный старт проекта на WSL: PostgreSQL → схема/миграция → панель → проверка.
# Идемпотентно: можно вызывать после перезагрузки WSL или выкладки.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "1/6 PostgreSQL"
sudo -n systemctl enable --now postgresql >/dev/null

echo "2/6 схема и миграция SQLite -> PostgreSQL"
./.venv/bin/python scripts/97_migrate_to_postgres.py

echo "3/6 удаление остатков старого UI на сервере"
rm -f web/templates/*.html web/static/app.css web/static/ui-state.js \
      web/static/ui-labels.js web/static/sidebar.js web/static/ui-theme.js

echo "4/6 systemd-юнит панели"
# rsync сохраняет mtime: без чистки __pycache__ сервер поднимает старый байткод.
find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
sudo -n cp infra/systemd/algotrading-web.service /etc/systemd/system/algotrading-web.service
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now algotrading-web.service >/dev/null

echo "5/6 проверка HTTP"
for path in / /ui /api/health /api/cash-flows /api/portfolio/analytics; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://127.0.0.1:8080$path" || true)"
  echo "  $code $path"
  [ "$code" = "200" ] || { echo "ОШИБКА: $path вернул $code" >&2; exit 1; }
done

echo "6/6 статус сервисов"
printf '  postgresql: '; sudo -n systemctl is-active postgresql
printf '  web:        '; sudo -n systemctl is-active algotrading-web.service
echo "готово: GUI http://127.0.0.1:8080/"
