#!/bin/bash
# Предполётная проверка перед деплоем. Запускается на твоей машине.
#
# Зачем: привычка «выкатить на прод и посмотреть там» превращает пользователей в
# тестировщиков, а прод — в отладочный стенд. Этот скрипт ловит на земле то, что
# иначе ловится в воздухе. Он вшит в `deploy_local.sh` и выполняется ПЕРЕД заливкой;
# упал — деплой не начнётся.
#
# Секретов не содержит и не требует: работает только с локальным репозиторием и
# локальной БД в Docker.
#
# Использование:
#   bash deploy/preflight.sh              — полная проверка
#   bash deploy/preflight.sh --quick      — без тестов и сборки фронта (быстрая петля)
#
# Что проверяется:
#   1. Секреты                — .env не отслеживается git, в дифе нет ключей/паролей
#   2. Миграции: полнота      — модели и миграции согласованы (makemigrations --check)
#   3. Миграции: один лист    — нет «multiple leaf nodes» (грабля из рантбука)
#   4. Миграции: план         — что именно выполнится на проде (глазами)
#   5. Django check --deploy  — прод-настройки без DEBUG
#   6. Тесты бэкенда          — вся сюита
#   7. Фронт                  — tsc + build + oxlint
set -e

QUICK=0
[ "$1" = "--quick" ] && QUICK=1

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$REPO_DIR/backend"
PY="$BACKEND/.venv/bin/python"
CONTAINER="plume-mysql"

FAIL=0
step()  { echo; echo "── $1"; }
ok()    { echo "   ✓ $1"; }
bad()   { echo "   ✗ $1"; FAIL=1; }
warn()  { echo "   ! $1"; }

echo "════ Предполётная проверка plume ════"

# --- 1. Секреты ------------------------------------------------------------------
step "1/7  Секреты"
# Проект открытый: git-история навсегда, поэтому проверка жёсткая.
if git -C "$REPO_DIR" ls-files --error-unmatch backend/.env >/dev/null 2>&1; then
    bad "backend/.env отслеживается git — немедленно убрать из индекса"
else
    ok "backend/.env не в индексе"
fi

if git -C "$REPO_DIR" ls-files | grep -qE '(^|/)snapshots/'; then
    bad "снимки прода попали в индекс git — убрать (в них живые данные)"
else
    ok "снимков прода в индексе нет"
fi

# Ищем в незакоммиченном дифе то, чего в открытом репозитории быть не должно.
SECRET_HITS="$(git -C "$REPO_DIR" diff HEAD -U0 2>/dev/null \
    | grep -E '^\+' \
    | grep -viE '^\+\+\+' \
    | grep -inE 'BEGIN [A-Z ]*PRIVATE KEY|ssh-rsa AAAA|(password|passwd|secret|api[_-]?key|token)\s*=\s*["'"'"'][^"'"'"']{8,}' \
    | grep -viE 'example|placeholder|change-me|dev-only|ТВОЙ|ПОЛЬЗОВАТЕЛЬ' || true)"
if [ -n "$SECRET_HITS" ]; then
    bad "в дифе похоже на секрет — проверь глазами:"
    echo "$SECRET_HITS" | head -5 | sed 's/^/       /'
else
    ok "в незакоммиченном дифе секретов не видно"
fi

# --- Локальная БД ----------------------------------------------------------------
step "2/7  Локальная БД"
if ! docker info >/dev/null 2>&1; then
    bad "Docker не запущен — подними Docker Desktop и повтори"
    echo "       (локальная БД живёт в контейнере $CONTAINER, без неё проверка слепа)"
    exit 1
fi
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^$CONTAINER$"; then
    echo "   поднимаю $CONTAINER..."
    if ! (cd "$BACKEND" && docker compose up -d) >/dev/null 2>&1; then
        bad "не удалось поднять $CONTAINER — cd backend && docker compose up -d"
        exit 1
    fi
    for _ in $(seq 1 40); do
        docker exec "$CONTAINER" mysqladmin ping -uroot -proot --silent >/dev/null 2>&1 && break
        sleep 2
    done
fi
docker exec "$CONTAINER" mysqladmin ping -uroot -proot --silent >/dev/null 2>&1 \
    && ok "БД доступна" || { bad "локальная БД недоступна — дальше смысла нет"; exit 1; }

# Мягкий укол культуры: если локальная база — синтетика, проверка «как у людей»
# неполноценна. Не блокируем, но говорим вслух.
ITEMS="$(docker exec "$CONTAINER" mysql -uroot -proot -N -B plume \
        -e 'SELECT COUNT(*) FROM plume_item' 2>/dev/null || echo 0)"
if [ "$ITEMS" -lt 50 ] 2>/dev/null; then
    warn "в локальной БД всего изделий: $ITEMS — похоже на синтетику."
    warn "  Снимок прода: bash deploy/pull_prod.sh --server ... --load --dev-password dev"
else
    ok "в локальной БД изделий: $ITEMS (похоже на реальный снимок)"
fi

# --- 3. Миграции -----------------------------------------------------------------
step "3/7  Миграции: модели и файлы согласованы"
# Самая частая причина «на проде всё сломалось»: модель поправил, миграцию не создал.
if (cd "$BACKEND" && "$PY" manage.py makemigrations --check --dry-run >/dev/null 2>&1); then
    ok "несозданных миграций нет"
else
    bad "есть изменения моделей без миграции — makemigrations"
    (cd "$BACKEND" && "$PY" manage.py makemigrations --check --dry-run 2>&1 | head -10 | sed 's/^/       /') || true
fi

step "4/7  Миграции: один лист графа"
# Грабля из рантбука: стухшие после сквоша файлы дают «multiple leaf nodes» на migrate.
LEAVES="$(cd "$BACKEND" && "$PY" -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from django.db.migrations.loader import MigrationLoader
leaves = [n for a, n in MigrationLoader(None, ignore_no_migrations=True).graph.leaf_nodes() if a == 'plume']
print(len(leaves)); print(*leaves, sep='\n')
" 2>/dev/null || echo "?")"
LEAF_N="$(echo "$LEAVES" | head -1)"
if [ "$LEAF_N" = "1" ]; then
    ok "лист один: $(echo "$LEAVES" | tail -1)"
else
    bad "листьев миграций: $LEAF_N — на проде будет 'multiple leaf nodes'"
    echo "$LEAVES" | tail -n +2 | sed 's/^/       /'
fi

step "5/7  Миграции: что выполнится на проде"
# Локальная БД = снимок прода → этот план и есть план прода. Читать глазами:
# особенно опасны миграции данных на живых записях.
PLAN="$(cd "$BACKEND" && "$PY" manage.py migrate --plan 2>/dev/null | grep -v 'No planned' || true)"
if [ -z "$PLAN" ]; then
    ok "непримененных миграций нет"
else
    warn "на проде выполнится:"
    echo "$PLAN" | sed 's/^/       /'
    warn "прочитай список глазами — данные на проде живые и привычные"
fi

# --- 6. Django check --deploy ----------------------------------------------------
step "6/7  Django check --deploy"
DEPLOY_CHECK="$(cd "$BACKEND" && DJANGO_DEBUG=0 "$PY" manage.py check --deploy 2>&1 || true)"
if echo "$DEPLOY_CHECK" | grep -qE '^ERRORS|CRITICAL'; then
    bad "check --deploy нашёл ошибки:"
    echo "$DEPLOY_CHECK" | sed 's/^/       /' | head -20
else
    ok "критических замечаний нет"
    echo "$DEPLOY_CHECK" | grep -cE '^\?: \(security' >/dev/null 2>&1 \
        && warn "есть security-warnings (не блокируют): manage.py check --deploy"
fi

# --- 7. Тесты и фронт ------------------------------------------------------------
if [ "$QUICK" = "1" ]; then
    step "7/7  Тесты и фронт — ПРОПУЩЕНЫ (--quick)"
    warn "перед реальным деплоем прогони полную проверку без --quick"
else
    step "7/7  Тесты бэкенда"
    if (cd "$BACKEND" && DB_USER=root DB_PASSWORD=root "$PY" manage.py test plume 2>&1 | tail -5 | tee /tmp/plume-tests.log | grep -q '^OK'); then
        ok "сюита зелёная"
    else
        bad "тесты упали:"
        tail -15 /tmp/plume-tests.log 2>/dev/null | sed 's/^/       /'
    fi

    step "     Фронт: tsc + build + oxlint"
    if (cd "$REPO_DIR/frontend" && npm run build >/tmp/plume-build.log 2>&1); then
        ok "tsc + vite build зелёные"
    else
        bad "сборка фронта упала:"
        tail -15 /tmp/plume-build.log | sed 's/^/       /'
    fi
    if (cd "$REPO_DIR/frontend" && npm run lint >/tmp/plume-lint.log 2>&1); then
        ok "oxlint чистый"
    else
        warn "oxlint ругается (не блокирует):"
        tail -8 /tmp/plume-lint.log | sed 's/^/       /'
    fi
fi

# --- Итог ------------------------------------------------------------------------
echo
if [ "$FAIL" = "1" ]; then
    echo "════ ПРОВЕРКА НЕ ПРОЙДЕНА — деплой отменён ════"
    exit 1
fi
echo "════ Проверка пройдена ════"
echo
echo "Последний шаг — глазами, его не автоматизировать:"
echo "  • открыл локально то, что менял, и покликал?"
echo "  • посмотрел на РЕАЛЬНЫХ данных (снимок прода), а не на синтетике?"
echo "  • если есть миграция данных — понимаешь, что она сделает с живыми записями?"
echo
