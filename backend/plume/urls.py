"""API-маршруты приложения plume (волна 1 — read-only проекции движка)."""
from django.urls import path

from . import views

urlpatterns = [
    path('ping/', views.ping, name='ping'),
    path('projects/', views.projects, name='projects'),
    path('projects/<int:pk>/deficit/', views.project_deficit, name='project-deficit'),
    path('items/', views.items, name='items'),
    path('items/<int:pk>/', views.item_detail, name='item-detail'),
]
