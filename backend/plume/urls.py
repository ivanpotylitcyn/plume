"""API-маршруты приложения plume.

Волна 1 — read-only проекции движка. Волна 2 — записываемый кокпит комплектации.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('ping/', views.ping, name='ping'),
    path('projects/', views.projects, name='projects'),
    path('projects/<int:pk>/deficit/', views.project_deficit, name='project-deficit'),
    path('items/', views.items, name='items'),
    path('items/<int:pk>/', views.item_detail, name='item-detail'),
    # кокпит комплектации (записываемое ядро)
    path('kittings/', views.kittings, name='kittings'),
    path('kittings/<int:pk>/', views.kitting_detail, name='kitting-detail'),
    path('kittings/<int:pk>/lines/', views.kitting_lines, name='kitting-lines'),
    path('kittings/<int:pk>/close/', views.kitting_close, name='kitting-close'),
    path('kittings/<int:pk>/reopen/', views.kitting_reopen, name='kitting-reopen'),
    path('kitting-lines/<int:pk>/', views.kitting_line_detail, name='kitting-line'),
]
