#!/bin/bash
# Снимок прод-БД → локальный Docker MySQL. Запускается на твоей машине.
#
# Зачем: в dev лежат синтетические данные, на которые каждый раз приходится заново
# «вникать». С реальным снимком локальная проверка перестаёт врать — видно ровно то
# же, что увидят пользователи, включая объём и перекосы живых данных.
#
# ВАЖНО (проект открытый): скрипт НЕ содержит секретов. Сервер/путь/ключ — аргументами.
# Доступы к прод-БД НЕ передаются и НЕ печатаются: они читаются из `backend/.env`
# ПРЯМО НА СЕРВЕРЕ, дамп там же и делается. Локально оседает только .sql.gz, а каталог
# снимков (`deploy/snapshots/`) в .gitignore — в репозиторий он не попадёт.
#
# Использование:
#   bash deploy/pull_prod.sh \
#     --server ПОЛЬЗОВАТЕЛЬ@ХОСТ \
#     --remote-dir '~/www/твой-сайт' \      # в ОДИНАРНЫХ кавычках! (тильда)
#     --key ~/.ssh/твой_приватный_ключ \
#     [--load] [--media] [--dev-password ПАРОЛЬ] [--keep N] [--file СНИМОК.sql.gz]
#
#   --load           залить снимок в локальный Docker MySQL (иначе только скачать)
#   --media          забрать и вложения (backend/media/) — сканы/PDF к документам
#   --dev-password   после --load сбросить пароли ВСЕХ локальных пользователей на этот
#                    (иначе войти не выйдет: в дампе хэши от прод-паролей)
#   --keep N         сколько снимков хранить локально (по умолчанию 5, старые удаляются)
#   --file           не ходить на сервер, залить уже скачанный снимок (нужен --load)
#
# Типовой сценарий «освежить локальную базу перед работой»:
#   bash deploy/pull_prod.sh --server ... --remote-dir '...' --key ... \
#     --load --dev-password dev
set -e

SERVER=""
REMOTE_DIR=""
SSH_KEY=""
DO_LOAD=0
DO_MEDIA=0
DEV_PASSWORD=""
KEEP=5
SNAPSHOT_FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --server)       SERVER="$2"; shift 2 ;;
        --remote-dir)   REMOTE_DIR="$2"; shift 2 ;;
        --key)          SSH_KEY="$2"; shift 2 ;;
        --load)         DO_LOAD=1; shift ;;
        --media)        DO_MEDIA=1; shift ;;
        --dev-password) DEV_PASSWORD="$2"; shift 2 ;;
        --keep)         KEEP="$2"; shift 2 ;;
        --file)         SNAPSHOT_FILE="$2"; shift 2 ;;
        *) echo "Неизвестный аргумент: $1"; exit 1 ;;
    esac
done

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SNAP_DIR="$REPO_DIR/deploy/snapshots"
CONTAINER="plume-mysql"          # см. backend/docker-compose.yml

# --- 1. Скачать снимок с сервера ------------------------------------------------
if [ -z "$SNAPSHOT_FILE" ]; then
    if [ -z "$SERVER" ] || [ -z "$REMOTE_DIR" ] || [ -z "$SSH_KEY" ]; then
        echo "Нужны --server, --remote-dir и --key (или --file для готового снимка)."
        exit 1
    fi

    mkdir -p "$SNAP_DIR"
    STAMP="$(date +%Y%m%d-%H%M)"
    SNAPSHOT_FILE="$SNAP_DIR/prod-$STAMP.sql.gz"

    echo "==> Снимаем дамп прод-БД на сервере..."
    # Всё выполняется на сервере: читаем backend/.env, дампим, жмём в stdout.
    # Доступы не пересекают границу машины и не попадают в ps/лог локально.
    # MYSQL_PWD вместо -p — пароль не светится в списке процессов сервера.
    # --no-tablespaces обязателен: на shared-хостинге у пользователя нет привилегии
    # PROCESS, без флага mysqldump 8 падает на попытке прочитать tablespace-инфо.
    # --single-transaction — консистентный снимок InnoDB без блокировки прода.
    # Дамп идёт ЦЕЛИКОМ, включая django_migrations: именно это делает локальную
    # проверку миграций честной (состояние миграций совпадает с продом).
    ssh -i "$SSH_KEY" "$SERVER" "
        set -e
        cd $REMOTE_DIR/backend
        [ -f .env ] || { echo 'На сервере нет backend/.env' >&2; exit 1; }
        set -a; . ./.env; set +a
        MYSQL_PWD=\"\$DB_PASSWORD\" mysqldump \
            --single-transaction --quick --no-tablespaces \
            --default-character-set=utf8mb4 \
            -h \"\$DB_HOST\" -P \"\$DB_PORT\" -u \"\$DB_USER\" \"\$DB_NAME\" \
        | gzip -c
    " > "$SNAPSHOT_FILE"

    if [ ! -s "$SNAPSHOT_FILE" ]; then
        echo "Снимок пустой — дамп не удался. Файл удалён."
        rm -f "$SNAPSHOT_FILE"
        exit 1
    fi
    echo "==> Снимок: $SNAPSHOT_FILE ($(du -h "$SNAPSHOT_FILE" | cut -f1))"

    # Ротация: держим последние N снимков, остальные сносим.
    ls -1t "$SNAP_DIR"/prod-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
        echo "    удаляю старый снимок: $(basename "$old")"
        rm -f "$old"
    done
fi

# --- 2. Вложения (опционально) --------------------------------------------------
if [ "$DO_MEDIA" = "1" ]; then
    echo "==> Забираем вложения (backend/media/)..."
    # media/ в .gitignore — это пользовательские файлы, локально нужны, чтобы
    # ссылки на сканы/PDF в формах не были битыми.
    SSH_USER="${SERVER%@*}"
    SSH_HOST="${SERVER#*@}"
    mkdir -p "$REPO_DIR/backend/media"
    lftp -u "$SSH_USER", "sftp://$SSH_HOST" <<EOF
set sftp:connect-program "ssh -a -x -i $SSH_KEY -o StrictHostKeyChecking=no"
mirror --exclude-glob=.DS_Store "$REMOTE_DIR/backend/media" "$REPO_DIR/backend/media"
quit
EOF
fi

# --- 3. Залить в локальный Docker MySQL -----------------------------------------
if [ "$DO_LOAD" = "1" ]; then
    if ! docker ps --format '{{.Names}}' | grep -q "^$CONTAINER$"; then
        echo "==> Контейнер $CONTAINER не запущен — поднимаю..."
        (cd "$REPO_DIR/backend" && docker compose up -d)
        echo "    жду готовности БД..."
        for _ in $(seq 1 40); do
            if docker exec "$CONTAINER" mysqladmin ping -uroot -proot --silent 2>/dev/null; then break; fi
            sleep 2
        done
    fi

    echo "==> Заливаем снимок в локальную БД (plume) — текущее содержимое будет заменено..."
    # Пересоздаём схему целиком: снимок должен лечь на чистое место, иначе остатки
    # синтетики смешаются с реальными данными и опять будут вводить в заблуждение.
    docker exec -i "$CONTAINER" mysql -uroot -proot -e \
        "DROP DATABASE IF EXISTS plume;
         CREATE DATABASE plume CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
         GRANT ALL ON plume.* TO 'plume'@'%';"
    gunzip -c "$SNAPSHOT_FILE" | docker exec -i "$CONTAINER" mysql -uroot -proot plume
    echo "==> Снимок залит."

    if [ -n "$DEV_PASSWORD" ]; then
        echo "==> Сбрасываю пароли локальных пользователей..."
        # В дампе — прод-хэши, войти локально нечем. Меняем пароли ТОЛЬКО в локальной
        # копии; на прод это никак не влияет.
        (cd "$REPO_DIR/backend" && .venv/bin/python manage.py shell -c "
from django.contrib.auth import get_user_model
U = get_user_model()
n = 0
for u in U.objects.all():
    u.set_password('$DEV_PASSWORD'); u.save(update_fields=['password']); n += 1
print(f'    паролей сброшено: {n} (пароль: $DEV_PASSWORD)')
")
    fi

    echo
    echo "==> Локальная БД теперь = снимок прода."
    echo "    Проверь состояние миграций:  cd backend && .venv/bin/python manage.py showmigrations"
    echo "    Непримененные миграции репозитория покажут, что уедет на прод."
fi

echo "==> Готово."
