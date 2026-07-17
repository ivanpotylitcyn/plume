#!/bin/bash
# Локальный скрипт деплоя. Запускается на твоей машине.
#
# ВАЖНО (проект открытый): скрипт НЕ содержит секретов. Сервер, путь и ключ
# передаются АРГУМЕНТАМИ — ничего чувствительного в репозиторий не попадает.
#
# Требования:
#   - lftp            (brew install lftp) — rsync на reg.ru shared не работает
#   - node + npm      для локальной сборки фронта (на shared-хостинге node нет,
#                     поэтому dist собираем здесь и заливаем готовым)
#   - приватный SSH-ключ, публичная часть которого уже на хостинге
#
# Использование:
#   bash deploy/deploy_local.sh \
#     --server ПОЛЬЗОВАТЕЛЬ@ХОСТ \
#     --remote-dir '~/www/твой-сайт' \      # в ОДИНАРНЫХ кавычках! (см. ниже)
#     --key ~/.ssh/твой_приватный_ключ \
#     [--init] [--seed] [--skip-build] [--python /opt/python/python-3.12.x/bin/python]
#
#   --init        первый деплой: создать venv на сервере
#   --seed        прогнать seed_demo (обычно только вместе с --init)
#   --skip-build  не пересобирать фронт (залить уже собранный frontend/dist)
#   --python      полный путь к бинарю Python на сервере для создания venv
#                 (только с --init). Стек — Django 6.0 на Python 3.14;
#                 по умолчанию deploy.sh берёт /opt/python/python-3.14/bin/python.
#
# Грабля: --remote-dir передавать в ОДИНАРНЫХ кавычках, иначе '~' раскроется в
# локальный /Users/... на маке. В кавычках тильда доедет до сервера и раскроется там.
set -e

SERVER=""
REMOTE_DIR=""
SSH_KEY=""
PYTHON_BIN=""
DO_INIT=0
DO_SEED=0
SKIP_BUILD=0

while [ $# -gt 0 ]; do
    case "$1" in
        --server)     SERVER="$2"; shift 2 ;;
        --remote-dir) REMOTE_DIR="$2"; shift 2 ;;
        --key)        SSH_KEY="$2"; shift 2 ;;
        --python)     PYTHON_BIN="$2"; shift 2 ;;
        --init)       DO_INIT=1; shift ;;
        --seed)       DO_SEED=1; shift ;;
        --skip-build) SKIP_BUILD=1; shift ;;
        *) echo "Неизвестный аргумент: $1"; exit 1 ;;
    esac
done

if [ -z "$SERVER" ] || [ -z "$REMOTE_DIR" ] || [ -z "$SSH_KEY" ]; then
    echo "Ошибка: обязательны --server, --remote-dir и --key."
    echo "Пример: bash deploy/deploy_local.sh --server user@host --remote-dir '~/www/site' --key ~/.ssh/id_ed25519_plume --init"
    exit 1
fi

SSH_USER="${SERVER%@*}"
SSH_HOST="${SERVER#*@}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Флаги, которые пробросим в серверный deploy.sh.
REMOTE_FLAGS=""
[ "$DO_INIT" = "1" ] && REMOTE_FLAGS="$REMOTE_FLAGS --init"
[ "$DO_SEED" = "1" ] && REMOTE_FLAGS="$REMOTE_FLAGS --seed"
[ -n "$PYTHON_BIN" ] && REMOTE_FLAGS="$REMOTE_FLAGS --python $PYTHON_BIN"

# --- 1. Сборка фронта локально ---
if [ "$SKIP_BUILD" = "0" ]; then
    echo "==> Собираем фронт (vite build)..."
    ( cd "$REPO_DIR/frontend" && npm run build )
fi
if [ ! -d "$REPO_DIR/frontend/dist" ]; then
    echo "Ошибка: frontend/dist не найден. Собери фронт или убери --skip-build."
    exit 1
fi

# --- 2. Заливка файлов через lftp по SFTP (ключ, без пароля) ---
# Пароль пустой (-u user,), аутентификация — SSH-ключом через connect-program.
# Простые паттерны — через --exclude-glob (не regex; иначе lftp падает на *.pyc).
# Для .env — анкерённый --exclude regex '(^|/)\.env$': исключает локальный dev-.env,
# но НЕ трогает .env.example (он нужен на сервере как образец). Проверено: glob '.env'
# мог бы зацепить и .env.example.
# БЕЗ --delete: на сервере остаётся заполненный прод-.env (живёт только там) и
# накопленный кэш; .env.example перезаливается (безвредно), .env не трогается. Чистку
# делаем осознанно вручную.
echo "==> Заливаем backend и frontend/dist на $SSH_HOST ..."
lftp -u "$SSH_USER", "sftp://$SSH_HOST" <<EOF
set sftp:connect-program "ssh -a -x -i $SSH_KEY -o StrictHostKeyChecking=no"
mirror -R \
  --exclude-glob=venv/ \
  --exclude-glob=.venv/ \
  --exclude-glob=__pycache__/ \
  --exclude-glob=*.pyc \
  --exclude '(^|/)\.env$' \
  --exclude-glob=staticfiles/ \
  --exclude-glob=*.egg-info/ \
  --exclude-glob=.DS_Store \
  --exclude-glob=db.sqlite3 \
  "$REPO_DIR/backend" "$REMOTE_DIR/backend"
# Каталог миграций синхронизируем С --delete: он обязан ТОЧНО совпадать с репо, иначе
# стухшие после сквоша файлы (напр. старый 0002_transfer_posted) остаются на сервере и
# дают «multiple leaf nodes» на migrate. Тут нет серверных файлов (.env и пр.), удаление
# безопасно; __pycache__/*.pyc исключены (их --delete не трогает).
mirror -R --delete \
  --exclude-glob=__pycache__/ \
  --exclude-glob=*.pyc \
  "$REPO_DIR/backend/plume/migrations" "$REMOTE_DIR/backend/plume/migrations"
mirror -R \
  --exclude-glob=.DS_Store \
  "$REPO_DIR/frontend/dist" "$REMOTE_DIR/frontend/dist"
put -O "$REMOTE_DIR" "$REPO_DIR/deploy/passenger_wsgi.py"
put -O "$REMOTE_DIR" "$REPO_DIR/deploy/deploy.sh"
quit
EOF

# --- 3. Запуск серверного деплоя ---
echo "==> Запускаем deploy.sh на сервере ($REMOTE_FLAGS)..."
ssh -i "$SSH_KEY" "$SERVER" "bash $REMOTE_DIR/deploy.sh$REMOTE_FLAGS"

echo "==> Локальный деплой завершён."
