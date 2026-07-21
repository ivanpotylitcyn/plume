"""API-маршруты приложения plume.

Волна 1 — read-only проекции движка. Волна 2 — записываемый кокпит комплектации.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('ping/', views.ping, name='ping'),
    # Аутентификация (волна 12): вход/выход сессией + «кто я» (ставит CSRF-cookie).
    path('auth/me/', views.me, name='auth-me'),
    path('auth/login/', views.login_view, name='auth-login'),
    path('auth/logout/', views.logout_view, name='auth-logout'),
    path('users/', views.users, name='users'),
    path('projects/', views.projects, name='projects'),
    path('projects/<int:pk>/', views.project_detail, name='project-detail'),
    path('projects/<int:pk>/deficit/', views.project_deficit, name='project-deficit'),
    path('projects/<int:pk>/demands/', views.project_demands, name='project-demands'),
    path('project-demands/<int:pk>/', views.project_demand_detail, name='project-demand'),
    path('projects/<int:pk>/budget/', views.project_budget, name='project-budget'),
    path('projects/<int:pk>/purchases/', views.project_purchases, name='project-purchases'),
    path('projects/<int:pk>/order/', views.project_order, name='project-order'),
    path('projects/<int:pk>/available-lots/', views.project_available_lots, name='project-available-lots'),
    # закрытие проекта (волна 6): панель сведения остатков + мосты + мягкий замок
    path('projects/<int:pk>/closure/', views.project_closure, name='project-closure'),
    path('projects/<int:pk>/writeoff-lot/', views.project_writeoff_lot, name='project-writeoff-lot'),
    path('projects/<int:pk>/stock-lot/', views.project_stock_lot, name='project-stock-lot'),
    path('projects/<int:pk>/lock/', views.project_lock, name='project-lock'),
    path('projects/<int:pk>/unlock/', views.project_unlock, name='project-unlock'),
    path('available-lots/', views.available_lots, name='available-lots'),
    path('categories/', views.categories, name='categories'),
    path('items/', views.items, name='items'),
    path('items/<int:pk>/', views.item_detail, name='item-detail'),
    path('items/<int:pk>/bom/', views.item_bom, name='item-bom'),
    path('items/<int:pk>/recalc-cost/', views.item_recalc_cost, name='item-recalc-cost'),
    # фиксация изделия (волна 17). Волна 19 Ф1c: единый глагол замка
    # `lock`/`unlock` на ВСЕХ сущностях — approve/unapprove и close/reopen ушли.
    path('items/<int:pk>/lock/', views.item_lock, name='item-lock'),
    path('items/<int:pk>/unlock/', views.item_unlock, name='item-unlock'),
    # синхронизация справочника с библиотекой компонентов (волна 15): диф → применение
    path('library/diff/', views.library_diff, name='library-diff'),
    path('library/apply/', views.library_apply, name='library-apply'),
    path('bom-lines/<int:pk>/', views.bom_line_detail, name='bom-line'),
    # кокпит комплектации (записываемое ядро)
    path('kittings/', views.kittings, name='kittings'),
    path('kittings/<int:pk>/', views.kitting_detail, name='kitting-detail'),
    path('kittings/<int:pk>/lines/', views.kitting_lines, name='kitting-lines'),
    path('kittings/<int:pk>/lock/', views.kitting_lock, name='kitting-lock'),
    path('kittings/<int:pk>/unlock/', views.kitting_unlock, name='kitting-unlock'),
    path('kitting-lines/<int:pk>/', views.kitting_line_detail, name='kitting-line'),
    # приход / УПД (записываемое ядро, волна 3) + справочник контрагентов
    path('counterparties/', views.counterparties, name='counterparties'),
    path('receipts/', views.receipts, name='receipts'),
    path('receipts/<int:pk>/', views.receipt_detail, name='receipt-detail'),
    path('receipts/<int:pk>/lots/', views.receipt_lots, name='receipt-lots'),
    path('receipts/<int:pk>/lock/', views.receipt_lock, name='receipt-lock'),
    path('receipts/<int:pk>/unlock/', views.receipt_unlock, name='receipt-unlock'),
    path('receipts/<int:pk>/link/', views.receipt_link, name='receipt-link'),
    path('lots/<int:pk>/', views.receipt_lot_detail, name='lot-detail'),
    # заказ / Purchase (записываемое ядро, волна 4)
    path('purchases/', views.purchases, name='purchases'),
    path('purchases/<int:pk>/', views.purchase_detail, name='purchase-detail'),
    path('purchases/<int:pk>/lines/', views.purchase_lines, name='purchase-lines'),
    path('purchases/<int:pk>/lock/', views.purchase_lock, name='purchase-lock'),
    path('purchases/<int:pk>/unlock/', views.purchase_unlock, name='purchase-unlock'),
    path('purchase-lines/<int:pk>/', views.purchase_line_detail, name='purchase-line'),
    # передача / Transfer (записываемое ядро, волна 5)
    path('transfers/', views.transfers, name='transfers'),
    path('transfers/<int:pk>/', views.transfer_detail, name='transfer-detail'),
    path('transfers/<int:pk>/lines/', views.transfer_lines, name='transfer-lines'),
    path('transfers/<int:pk>/lock/', views.transfer_lock, name='transfer-lock'),
    path('transfers/<int:pk>/unlock/', views.transfer_unlock, name='transfer-unlock'),
    path('transfer-lines/<int:pk>/', views.transfer_line_detail, name='transfer-line'),
    # списание / Writeoff (записываемое ядро, волна 6)
    path('writeoffs/', views.writeoffs, name='writeoffs'),
    path('writeoffs/<int:pk>/', views.writeoff_detail, name='writeoff-detail'),
    path('writeoffs/<int:pk>/lines/', views.writeoff_lines, name='writeoff-lines'),
    path('writeoffs/<int:pk>/lock/', views.writeoff_lock, name='writeoff-lock'),
    path('writeoffs/<int:pk>/unlock/', views.writeoff_unlock, name='writeoff-unlock'),
    path('writeoff-lines/<int:pk>/', views.writeoff_line_detail, name='writeoff-line'),
    # требование / Requisition (записываемое ядро, волна 6)
    path('requisitions/', views.requisitions, name='requisitions'),
    path('requisitions/<int:pk>/', views.requisition_detail, name='requisition-detail'),
    path('requisitions/<int:pk>/lines/', views.requisition_lines, name='requisition-lines'),
    path('requisitions/<int:pk>/lock/', views.requisition_lock, name='requisition-lock'),
    path('requisitions/<int:pk>/unlock/', views.requisition_unlock, name='requisition-unlock'),
    path('requisition-lines/<int:pk>/', views.requisition_line_detail, name='requisition-line'),
    # инвентаризация / Inventory (записываемое ядро, волна 9)
    path('inventories/', views.inventories, name='inventories'),
    path('inventories/<int:pk>/', views.inventory_detail, name='inventory-detail'),
    path('inventories/<int:pk>/lots/', views.inventory_lots, name='inventory-lots'),
    path('inventories/<int:pk>/lock/', views.inventory_lock, name='inventory-lock'),
    path('inventories/<int:pk>/unlock/', views.inventory_unlock, name='inventory-unlock'),
    path('inventory-lots/<int:pk>/', views.inventory_lot_detail, name='inventory-lot'),
    path('written-off-lots/', views.written_off_lots, name='written-off-lots'),
    # перемещение / Relocation (записываемое ядро, волна 13 Ф3) + справочник мест
    path('locations/', views.locations, name='locations'),
    path('locations/<int:pk>/', views.location_detail, name='location-detail'),
    path('relocations/', views.relocations, name='relocations'),
    path('relocations/<int:pk>/', views.relocation_detail, name='relocation-detail'),
    path('relocations/<int:pk>/lines/', views.relocation_lines, name='relocation-lines'),
    path('relocations/<int:pk>/lock/', views.relocation_lock, name='relocation-lock'),
    path('relocations/<int:pk>/unlock/', views.relocation_unlock, name='relocation-unlock'),
    path('relocations/<int:pk>/source-lots/', views.relocation_source_lots, name='relocation-source-lots'),
    path('relocations/<int:pk>/lines/<int:lot_pk>/', views.relocation_line_detail, name='relocation-line'),
    # планирование закупок (волна 7): командный свод + записываемый Procurement + order.xlsx
    path('command-deficit/', views.command_deficit, name='command-deficit'),
    path('command-deficit/add-to-procurement/', views.command_deficit_add, name='command-deficit-add'),
    path('procurements/', views.procurements, name='procurements'),
    path('procurements/<int:pk>/', views.procurement_detail, name='procurement-detail'),
    path('procurements/<int:pk>/lines/', views.procurement_lines, name='procurement-lines'),
    path('procurements/<int:pk>/lock/', views.procurement_lock, name='procurement-lock'),
    path('procurements/<int:pk>/unlock/', views.procurement_unlock, name='procurement-unlock'),
    path('procurements/<int:pk>/order.xlsx', views.procurement_order_xlsx, name='procurement-order-xlsx'),
    path('procurement-lines/<int:pk>/', views.procurement_line_detail, name='procurement-line'),
    # pegging (волна 8): нарезка плана на проектные заказы
    path('procurements/<int:pk>/pegging/', views.procurement_pegging, name='procurement-pegging'),
    path('procurements/<int:pk>/peg/', views.procurement_peg, name='procurement-peg'),
    path('procurements/<int:pk>/unpeg/', views.procurement_unpeg, name='procurement-unpeg'),
    path('procurements/<int:pk>/autopeg/', views.procurement_autopeg, name='procurement-autopeg'),
    # вложения (волна 11): PDF/сканы к документам и изделиям. download/detail (int)
    # идут раньше owner-маршрута (str) — коллизии нет, но порядок нагляднее.
    path('attachments/<int:pk>/download/', views.attachment_download, name='attachment-download'),
    path('attachments/<int:pk>/', views.attachment_detail, name='attachment-detail'),
    path('attachments/<str:owner_type>/<int:owner_id>/', views.attachments, name='attachments'),
]
