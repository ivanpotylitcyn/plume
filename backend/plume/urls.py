"""API-маршруты приложения plume.

Волна 1 — read-only проекции движка. Волна 2 — записываемый кокпит комплектации.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('ping/', views.ping, name='ping'),
    path('projects/', views.projects, name='projects'),
    path('projects/<int:pk>/deficit/', views.project_deficit, name='project-deficit'),
    path('projects/<int:pk>/budget/', views.project_budget, name='project-budget'),
    path('projects/<int:pk>/purchases/', views.project_purchases, name='project-purchases'),
    path('projects/<int:pk>/order/', views.project_order, name='project-order'),
    path('projects/<int:pk>/available-lots/', views.project_available_lots, name='project-available-lots'),
    # закрытие проекта (волна 6): панель сведения остатков + мосты + мягкий замок
    path('projects/<int:pk>/closure/', views.project_closure, name='project-closure'),
    path('projects/<int:pk>/writeoff-lot/', views.project_writeoff_lot, name='project-writeoff-lot'),
    path('projects/<int:pk>/stock-lot/', views.project_stock_lot, name='project-stock-lot'),
    path('projects/<int:pk>/close/', views.project_close, name='project-close'),
    path('projects/<int:pk>/reopen/', views.project_reopen, name='project-reopen'),
    path('available-lots/', views.available_lots, name='available-lots'),
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
    # передача / Transfer (записываемое ядро, волна 5)
    path('transfers/', views.transfers, name='transfers'),
    path('transfers/<int:pk>/', views.transfer_detail, name='transfer-detail'),
    path('transfers/<int:pk>/lines/', views.transfer_lines, name='transfer-lines'),
    path('transfers/<int:pk>/post/', views.transfer_post, name='transfer-post'),
    path('transfers/<int:pk>/unpost/', views.transfer_unpost, name='transfer-unpost'),
    path('transfer-lines/<int:pk>/', views.transfer_line_detail, name='transfer-line'),
    # списание / Writeoff (записываемое ядро, волна 6)
    path('writeoffs/', views.writeoffs, name='writeoffs'),
    path('writeoffs/<int:pk>/', views.writeoff_detail, name='writeoff-detail'),
    path('writeoffs/<int:pk>/lines/', views.writeoff_lines, name='writeoff-lines'),
    path('writeoff-lines/<int:pk>/', views.writeoff_line_detail, name='writeoff-line'),
    # требование / Requisition (записываемое ядро, волна 6)
    path('requisitions/', views.requisitions, name='requisitions'),
    path('requisitions/<int:pk>/', views.requisition_detail, name='requisition-detail'),
    path('requisitions/<int:pk>/lines/', views.requisition_lines, name='requisition-lines'),
    path('requisition-lines/<int:pk>/', views.requisition_line_detail, name='requisition-line'),
    # инвентаризация / Inventory (записываемое ядро, волна 9)
    path('inventories/', views.inventories, name='inventories'),
    path('inventories/<int:pk>/', views.inventory_detail, name='inventory-detail'),
    path('inventories/<int:pk>/lots/', views.inventory_lots, name='inventory-lots'),
    path('inventory-lots/<int:pk>/', views.inventory_lot_detail, name='inventory-lot'),
    path('written-off-lots/', views.written_off_lots, name='written-off-lots'),
    # планирование закупок (волна 7): командный свод + записываемый Procurement + order.xlsx
    path('command-deficit/', views.command_deficit, name='command-deficit'),
    path('command-deficit/add-to-procurement/', views.command_deficit_add, name='command-deficit-add'),
    path('procurements/', views.procurements, name='procurements'),
    path('procurements/<int:pk>/', views.procurement_detail, name='procurement-detail'),
    path('procurements/<int:pk>/lines/', views.procurement_lines, name='procurement-lines'),
    path('procurements/<int:pk>/send/', views.procurement_send, name='procurement-send'),
    path('procurements/<int:pk>/unsend/', views.procurement_unsend, name='procurement-unsend'),
    path('procurements/<int:pk>/cancel/', views.procurement_cancel, name='procurement-cancel'),
    path('procurements/<int:pk>/restore/', views.procurement_restore, name='procurement-restore'),
    path('procurements/<int:pk>/order.xlsx', views.procurement_order_xlsx, name='procurement-order-xlsx'),
    path('procurement-lines/<int:pk>/', views.procurement_line_detail, name='procurement-line'),
    # pegging (волна 8): нарезка плана на проектные заказы
    path('procurements/<int:pk>/pegging/', views.procurement_pegging, name='procurement-pegging'),
    path('procurements/<int:pk>/peg/', views.procurement_peg, name='procurement-peg'),
    path('procurements/<int:pk>/unpeg/', views.procurement_unpeg, name='procurement-unpeg'),
    path('procurements/<int:pk>/autopeg/', views.procurement_autopeg, name='procurement-autopeg'),
]
