"""URL-конфигурация проекта config.

Волна 1: admin (ввод данных) + /api/ (read-only проекции движка).
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('plume.urls')),
]
