"""Точка входа Phusion Passenger (reg.ru shared hosting).

Лежит в КОРНЕ сайта (docroot), не в backend/. Passenger находит файл по имени
автоматически — отдельного поля в ISPmanager нет. Раскладка на сервере:

    SITE_ROOT/                 <- docroot, здесь этот файл
      passenger_wsgi.py
      venv/                    <- python-3.10.1 -m venv venv
      backend/                 <- config/, plume/, manage.py, requirements.txt, .env
      frontend/dist/           <- собранный React (заливается с локальной машины)

Без ручного добавления site-packages venv Passenger не найдёт Django (грабля
соседнего проекта на том же хостинге).
"""
import glob
import os
import sys

SITE_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SITE_ROOT, 'backend')

# Путь site-packages venv зависит от минорной версии Python (python3.14, python3.12, …).
# Находим динамически, чтобы не привязываться к конкретной версии при её смене.
_candidates = sorted(glob.glob(
    os.path.join(SITE_ROOT, 'venv', 'lib', 'python3.*', 'site-packages')
))
VENV_SITE_PACKAGES = _candidates[0] if _candidates else os.path.join(
    SITE_ROOT, 'venv', 'lib', 'python3.14', 'site-packages'
)

for path in (VENV_SITE_PACKAGES, BACKEND_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
