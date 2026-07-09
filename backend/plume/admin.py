"""Админка plume — основная поверхность ввода данных в волне 1.

Строки документов редактируются инлайнами под заголовком; справочники — обычными
формами. Витрины движка (React) — read-only поверх этого.
"""
from django.contrib import admin

from . import models


# --- инлайны строк -------------------------------------------------------- #
class BomLineInline(admin.TabularInline):
    model = models.BomLine
    fk_name = 'parent'
    extra = 0


class ProjectDemandInline(admin.TabularInline):
    model = models.ProjectDemand
    extra = 0


class ProcurementLineInline(admin.TabularInline):
    model = models.ProcurementLine
    extra = 0


class PurchaseLineInline(admin.TabularInline):
    model = models.PurchaseLine
    extra = 0


# Строки движения — единая `StockLine` (волна 13, Ф0). Один инлайн на каждый
# документ-владелец через `fk_name`; `qty` знаковый (− расход).
class KittingLineInline(admin.TabularInline):
    model = models.StockLine
    fk_name = 'kitting'
    fields = ('lot', 'location', 'qty', 'date')
    extra = 0


class TransferLineInline(admin.TabularInline):
    model = models.StockLine
    fk_name = 'transfer'
    fields = ('lot', 'location', 'qty', 'display_name')
    extra = 0


class WriteoffLineInline(admin.TabularInline):
    model = models.StockLine
    fk_name = 'writeoff'
    fields = ('lot', 'location', 'qty')
    extra = 0


class RequisitionLineInline(admin.TabularInline):
    model = models.StockLine
    fk_name = 'requisition'
    fields = ('lot', 'location', 'qty')
    extra = 0


# --- справочники ---------------------------------------------------------- #
@admin.register(models.Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'uom', 'is_manufactured', 'active')
    list_filter = ('kind', 'is_manufactured', 'active')
    search_fields = ('code', 'name')
    inlines = [BomLineInline]


@admin.register(models.Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'status', 'budget')
    list_filter = ('kind', 'status')
    search_fields = ('code', 'name')
    inlines = [ProjectDemandInline]


@admin.register(models.Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'inn')
    search_fields = ('name', 'inn')


@admin.register(models.Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind')


# --- закупки -------------------------------------------------------------- #
@admin.register(models.Procurement)
class ProcurementAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'status', 'date', 'user')
    list_filter = ('status',)
    inlines = [ProcurementLineInline]


@admin.register(models.Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'project', 'status', 'date', 'user')
    list_filter = ('status', 'project')
    inlines = [PurchaseLineInline]


# --- документы-origin ----------------------------------------------------- #
@admin.register(models.Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('number', 'date', 'supplier', 'project', 'status')
    list_filter = ('status', 'project')
    search_fields = ('number',)


@admin.register(models.Kitting)
class KittingAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'project', 'target_item', 'qty', 'status', 'date')
    list_filter = ('status', 'project')
    inlines = [KittingLineInline]


@admin.register(models.Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('number', 'project', 'date', 'status')
    list_filter = ('status',)
    search_fields = ('number',)


@admin.register(models.Requisition)
class RequisitionAdmin(admin.ModelAdmin):
    list_display = ('number', 'project', 'date', 'status')
    list_filter = ('status',)
    search_fields = ('number',)
    inlines = [RequisitionLineInline]


# --- партии / движения ---------------------------------------------------- #
@admin.register(models.Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = ('id', 'item', 'project', 'origin_kind', 'unit_cost',
                    'serial_number')
    list_filter = ('project',)
    search_fields = ('item__code', 'serial_number', 'received_name')


@admin.register(models.StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('id', 'lot', 'location', 'type', 'qty', 'source_type',
                    'source_id', 'created_at')
    list_filter = ('type', 'location')


@admin.register(models.StockLine)
class StockLineAdmin(admin.ModelAdmin):
    list_display = ('id', 'doc_kind', 'lot', 'location', 'qty')
    list_filter = ('location',)


# --- выбытие / передача --------------------------------------------------- #
@admin.register(models.Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ('number', 'project', 'date', 'status')
    list_filter = ('status',)
    inlines = [TransferLineInline]


@admin.register(models.Writeoff)
class WriteoffAdmin(admin.ModelAdmin):
    list_display = ('number', 'project', 'date', 'reason', 'status')
    list_filter = ('status',)
    inlines = [WriteoffLineInline]


# --- вложения ------------------------------------------------------------- #
@admin.register(models.Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'content_type', 'size', 'uploaded_at', 'user')
