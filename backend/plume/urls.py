"""API-маршруты приложения plume.

Волна 1 — read-only проекции движка. Волна 2 — записываемый кокпит комплектации.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('ping/', views.ping, name='ping'),
    path('projects/', views.projects, name='projects'),
    path('projects/<int:pk>/deficit/', views.project_deficit, name='project-deficit'),
    path('projects/<int:pk>/purchases/', views.project_purchases, name='project-purchases'),
    path('projects/<int:pk>/order/', views.project_order, name='project-order'),
    path('items/', views.items, name='items'),
    path('items/<int:pk>/', views.item_detail, name='item-detail'),
    # кокпит комплектации (записываемое ядро)
    path('kittings/', views.kittings, name='kittings'),
    path('kittings/<int:pk>/', views.kitting_detail, name='kitting-detail'),
    path('kittings/<int:pk>/lines/', views.kitting_lines, name='kitting-lines'),
    path('kittings/<int:pk>/close/', views.kitting_close, name='kitting-close'),
    path('kittings/<int:pk>/reopen/', views.kitting_reopen, name='kitting-reopen'),
    path('kitting-lines/<int:pk>/', views.kitting_line_detail, name='kitting-line'),
    # приход / УПД (записываемое ядро, волна 3) + справочник поставщиков
    path('suppliers/', views.suppliers, name='suppliers'),
    path('receipts/', views.receipts, name='receipts'),
    path('receipts/<int:pk>/', views.receipt_detail, name='receipt-detail'),
    path('receipts/<int:pk>/lots/', views.receipt_lots, name='receipt-lots'),
    path('receipts/<int:pk>/approve/', views.receipt_approve, name='receipt-approve'),
    path('receipts/<int:pk>/unapprove/', views.receipt_unapprove, name='receipt-unapprove'),
    path('receipts/<int:pk>/link/', views.receipt_link, name='receipt-link'),
    path('lots/<int:pk>/', views.receipt_lot_detail, name='lot-detail'),
    # заказ / Purchase (записываемое ядро, волна 4)
    path('purchases/', views.purchases, name='purchases'),
    path('purchases/<int:pk>/', views.purchase_detail, name='purchase-detail'),
    path('purchases/<int:pk>/lines/', views.purchase_lines, name='purchase-lines'),
    path('purchases/<int:pk>/send/', views.purchase_send, name='purchase-send'),
    path('purchases/<int:pk>/unsend/', views.purchase_unsend, name='purchase-unsend'),
    path('purchases/<int:pk>/cancel/', views.purchase_cancel, name='purchase-cancel'),
    path('purchases/<int:pk>/restore/', views.purchase_restore, name='purchase-restore'),
    path('purchase-lines/<int:pk>/', views.purchase_line_detail, name='purchase-line'),
]
