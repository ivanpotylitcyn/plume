"""URL-конфигурация проекта config.

Волна 1: admin (ввод данных) + /api/ (read-only проекции движка) + SPA (React).
Порядок важен: admin и api идут первыми, всё остальное отдаёт React через
catch-all — так работает клиентский роутинг (перезагрузка любого пути отдаёт
index.html, дальше маршрут разбирает сам фронт).
"""
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('plume.urls')),
    # SPA-fallback: любой путь, кроме admin/api/static, отдаёт собранный index.html.
    # /static/ обслуживает WhiteNoise (в MIDDLEWARE) до того, как дойдёт сюда.
    re_path(r'^(?!api/|admin/|static/).*$',
            TemplateView.as_view(template_name='index.html')),
]
