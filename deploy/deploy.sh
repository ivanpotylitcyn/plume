#!/bin/bash
# Серверный скрипт деплоя. Запускается по SSH из deploy_local.sh, лежит в корне
# сайта. Секретов не содержит — их нет и не должно быть (проект открытый).
#
# Использование (на сервере, обычно дёргается автоматически из deploy_local.sh):
#   bash deploy.sh                              — обновление (venv уже существует)
#   bash deploy.sh --init                       — первый запуск (создаёт venv)
#   bash deploy.sh --init --seed                — + сид демо-данных
#   bash deploy.sh --init --python /opt/python/python-3.14/bin/python
set -e

# Корень сайта = каталог этого скрипта. Никаких захардкоженных путей к сайту.
SITE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SITE_DIR"

# Бинарь Python для создания venv. На reg.ru shared лежит по полному пути под
# /opt/python/ (`python3.X` не в PATH — грабля: which выдаёт алиас, а не бинарь).
# Версию задаём явно через --python. Стек — Django 6.0 на Python 3.14; дефолт —
# бинарь 3.14 на хостинге (Django 6.0 требует Python >= 3.12).
PYTHON=/opt/python/python-3.14/bin/python

DO_INIT=0
DO_SEED=0
while [ $# -gt 0 ]; do
    case "$1" in
        --init)   DO_INIT=1; shift ;;
        --seed)   DO_SEED=1; shift ;;
        --python) PYTHON="$2"; shift 2 ;;
        *) echo "Неизвестный аргумент: $1"; exit 1 ;;
    esac
done

if [ "$DO_INIT" = "1" ]; then
    echo "==> Создаём виртуальное окружение через: $PYTHON"
    "$PYTHON" --version
    "$PYTHON" -m venv venv
    mkdir -p tmp
fi

echo "==> Активируем venv и ставим зависимости..."
source venv/bin/activate
pip install -q -r backend/requirements.txt

cd backend

echo "==> Применяем миграции..."
python manage.py migrate --noinput

if [ "$DO_SEED" = "1" ]; then
    echo "==> Сидируем демо-данные (seed_demo)..."
    python manage.py seed_demo
fi

echo "==> Собираем статику (backend + собранный frontend/dist)..."
python manage.py collectstatic --noinput

cd "$SITE_DIR"

echo "==> Перезапускаем Passenger..."
touch tmp/restart.txt

echo "==> Готово."
echo "    Напоминание: суперюзер создаётся вручную один раз —"
echo "    source venv/bin/activate && cd backend && python manage.py createsuperuser"
