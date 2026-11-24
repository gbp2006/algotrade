#!/usr/bin/env bash
# Безопасная выкладка кода на WSL: только whitelist, без --delete.
#
#   ./scripts/deploy_wsl.sh              # dry-run: что изменится (по умолчанию)
#   ./scripts/deploy_wsl.sh --apply      # скопировать + сверить md5
#   ./scripts/deploy_wsl.sh --apply --restart  # ещё и перезапустить панель
#   ./scripts/deploy_wsl.sh --list       # только список файлов whitelist'а
#
# Настройки: ALGO_WSL (по умолчанию wsl-algo), ALGO_WSL_DIR (по умолчанию
# ~/algotrading). Секреты, данные, журналы и БД НЕ передаются — только код и
# документация. Перезапуск служб — только с явным --restart.
set -euo pipefail
shopt -s nullglob

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REMOTE="${ALGO_WSL:-wsl-algo}"
REMOTE_DIR="${ALGO_WSL_DIR:-~/algotrading}"
# тильда не раскрывается в кавычках — спросим у удалённой оболочки реальный путь
REMOTE_ABS="$(ssh "$REMOTE" "cd $REMOTE_DIR && pwd")"
APPLY=0
RESTART=0
LIST=0

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --restart) RESTART=1 ;;
    --list) LIST=1 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0 ;;
    *) echo "неизвестный флаг: $arg" >&2; exit 2 ;;
  esac
done

FILES=(
  run.sh requirements.txt AGENTS.md PROGRESS.md README.md live_settings.example.json
  algo/*.py algo/broker/*.py algo/strategies/*.py
  scripts/*.py scripts/README.md scripts/deploy_wsl.sh
  tests/*.py
  web/*.py web/templates/*.html web/static/*.css web/static/*.js web/static/img/*
  webui/dist/index.html webui/dist/assets/*
  docs/*.md docs/strategies/*.md docs/sources/*.md
  infra/db/memory.py infra/db/schema.sql infra/systemd/*.service infra/systemd/*.timer
  infra/systemd/*.conf infra/logrotate/*
)

# Защита от случайного попадания секретов и состояния в выгрузку.
for f in "${FILES[@]}"; do
  case "$f" in
    /*|*..*|.env|.env.*|*/data/*|*/results/*|*/infra/db/*.db*|*/.venv/*|*/materials/*|*/cources/*|*/cache/*|*/.cache/*|*__pycache__*|*.pyc)
      echo "ОТКАЗ: файл вне whitelist-ограничений: $f" >&2
      exit 2 ;;
  esac
done

if [ "$LIST" = 1 ]; then
  printf '%s\n' "${FILES[@]}"
  exit 0
fi

if [ "$APPLY" = 1 ]; then
  FLAGS=(-aiR)             # archive, itemized, relative
else
  FLAGS=(-aniR)            # + dry-run
fi

echo "деплой ${REMOTE}:${REMOTE_DIR}, файлов ${#FILES[@]}, режим $([ "$APPLY" = 1 ] && echo APPLY || echo DRY-RUN)"
rsync "${FLAGS[@]}" "${FILES[@]}" "$REMOTE:$REMOTE_ABS/"

if [ "$APPLY" = 1 ]; then
  local_md5="$(md5sum "${FILES[@]}")"
  remote_md5="$(printf '%s\n' "${FILES[@]}" | \
    ssh "$REMOTE" "cd '$REMOTE_ABS' && xargs -d '\\n' md5sum 2>/dev/null" || true)"
  if [ "$local_md5" = "$remote_md5" ]; then
    echo "md5: OK (${#FILES[@]} файлов совпадают)"
  else
    echo "md5: РАСХОЖДЕНИЕ — сверьте файлы вручную" >&2
    diff <(printf '%s\n' "$local_md5") <(printf '%s\n' "$remote_md5") | head -20 >&2 || true
    exit 3
  fi
  if [ "$RESTART" = 1 ]; then
    ssh "$REMOTE" 'sudo -n systemctl restart algotrading-web.service && sudo -n systemctl is-active algotrading-web.service'
    echo "панель перезапущена"
  fi
fi
