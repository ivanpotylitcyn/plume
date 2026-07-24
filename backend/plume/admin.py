"""Админка plume — основная поверхность ввода данных в волне 1.

Строки документов редактируются инлайнами под заголовком; справочники — обычными
формами. Витрины движка (React) — read-only поверх этого.
"""
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

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


# Строки движения — единая `StockLine` (волна 13, Ф0). После коллапса дуги (Ф2b)
# владелец — один FK `document` → `StockDocument`; инлайн-FK указывает на родителя
# MTI, а Django принимает его через `get_parent_list()` (StockDocument ∈ предки
# Kitting/Transfer/…). `qty` знаковый (− расход).
class KittingLineInline(admin.TabularInline):
    model = models.StockLine
    fk_name = 'document'
    fields = ('lot', 'location', 'qty', 'date')
    extra = 0


class TransferLineInline(admin.TabularInline):
    model = models.StockLine
    fk_name = 'document'
    fields = ('lot', 'location', 'qty', 'display_name')
    extra = 0


class WriteoffLineInline(admin.TabularInline):
    model = models.StockLine
    fk_name = 'document'
    fields = ('lot', 'location', 'qty')
    extra = 0


class RequisitionLineInline(admin.TabularInline):
    model = models.StockLine
    fk_name = 'document'
    fields = ('lot', 'location', 'qty')
    extra = 0


# Перемещение (волна 13, Ф2e): пара знаковых строк на ход (`−q`@источник, `+q`@приёмник).
# В инлайне это две строки с одним `lot` и разными `location`; `qty` знаковый.
class RelocationLineInline(admin.TabularInline):
    model = models.StockLine
    fk_name = 'document'
    fields = ('lot', 'location', 'qty')
    extra = 0


# --- справочники ---------------------------------------------------------- #
@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'description')
    search_fields = ('code', 'description')


@admin.register(models.Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('design_item_id', 'description', 'category', 'uom',
                    'temperature', 'produced')
    list_filter = ('category', 'produced')
    search_fields = ('design_item_id', 'description')
    list_select_related = ('category',)
    inlines = [BomLineInline]


@admin.register(models.Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'kind', 'locked', 'budget')
    list_filter = ('kind', 'locked')
    search_fields = ('code', 'description')
    inlines = [ProjectDemandInline]


@admin.register(models.Counterparty)
class CounterpartyAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'inn', 'is_supplier', 'is_customer')
    list_filter = ('is_supplier', 'is_customer')
    search_fields = ('code', 'description', 'inn')


@admin.register(models.Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'kind')


# --- закупки -------------------------------------------------------------- #
@admin.register(models.Procurement)
class ProcurementAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'locked', 'date', 'user')
    list_filter = ('locked',)
    inlines = [ProcurementLineInline]


@admin.register(models.Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'project', 'locked', 'date', 'user')
    list_filter = ('locked', 'project')
    inlines = [PurchaseLineInline]


# --- ордера: гибрид «обзор + правка по типу» (волна 13, Ф2h) --------------- #
# Родитель `StockDocument` — **read-only обзор «все ордера»** (зеркало режима «Ордер»
# во фронте): смешанный список 7 видов с фильтром по `kind`/`locked`/проекту,
# новейшие сверху, строки некликабельны. Правка — в дочерних админках ниже (по типу,
# с инлайнами строк). Bare-родитель не создаём (вид штампуют дети через `save()`),
# менять/удалять через эту витрину нельзя — только смотреть.
@admin.register(models.StockDocument)
class StockDocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'kind', 'number', 'open_child', 'date', 'project', 'locked', 'user')
    list_filter = ('kind', 'locked', 'project')
    search_fields = ('number',)
    ordering = ('-id',)              # новейшие сверху — зеркалит OrderList
    list_display_links = None        # строки некликабельны: правка — в дочерних админках
    list_select_related = ('project', 'user')

    @admin.display(description='форма')
    def open_child(self, obj):
        # Ссылка на дочернюю форму (правка/удаление). `kind` дословно = имя дочерней
        # модели, а в MTI pk ребёнка == pk родителя → URL собираем без запроса к БД.
        url = reverse(f'admin:plume_{obj.kind}_change', args=[obj.pk])
        return format_html('<a href="{}">✎ открыть</a>', url)

    def has_add_permission(self, request):
        return False                 # вид штампует ребёнок; bare-родителя не создаём

    def has_change_permission(self, request, obj=None):
        return False                 # витрина только для просмотра (view-perm держит список)

    def has_delete_permission(self, request, obj=None):
        # ВАЖНО: разрешаем удаление РОДИТЕЛЯ. Иначе MTI-каскад из дочерней админки
        # (удаление Перемещения/Прихода/…) блокируется: Django при сборе связанных
        # объектов проверяет право на StockDocument, и жёсткий `False` рубит даже
        # суперюзера («нет прав на удаление ордер»). Прямое удаление из витрины при
        # этом закрыто иначе: строки некликабельны (list_display_links=None),
        # change-страницы нет (has_change_permission=False), а bulk-action снят ниже.
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        # Витрина — «только смотреть»: убираем массовое «удалить выбранные», чтобы
        # родителя нельзя было снести оптом в обход дочерних guard'ов движка.
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


# --- документы-origin ----------------------------------------------------- #
@admin.register(models.Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('number', 'date', 'contractor', 'project', 'locked')
    list_filter = ('locked', 'project')
    search_fields = ('number',)


@admin.register(models.Kitting)
class KittingAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'project', 'target_item', 'qty', 'locked', 'date')
    list_filter = ('locked', 'project')
    inlines = [KittingLineInline]


@admin.register(models.Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('number', 'project', 'date', 'locked')
    list_filter = ('locked',)
    search_fields = ('number',)


@admin.register(models.Requisition)
class RequisitionAdmin(admin.ModelAdmin):
    list_display = ('number', 'project', 'date', 'locked')
    list_filter = ('locked',)
    search_fields = ('number',)
    inlines = [RequisitionLineInline]


# --- партии / движения ---------------------------------------------------- #
@admin.register(models.Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = ('id', 'item', 'project', 'origin_kind', 'unit_cost',
                    'part_number', 'lot_name')
    list_filter = ('project',)
    search_fields = ('item__design_item_id', 'part_number', 'lot_name')


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
    list_display = ('number', 'project', 'contractor', 'date', 'locked')
    list_filter = ('locked',)
    inlines = [TransferLineInline]


@admin.register(models.Writeoff)
class WriteoffAdmin(admin.ModelAdmin):
    list_display = ('number', 'project', 'date', 'reason', 'locked')
    list_filter = ('locked',)
    inlines = [WriteoffLineInline]


@admin.register(models.Relocation)
class RelocationAdmin(admin.ModelAdmin):
    list_display = ('number', 'project', 'date', 'locked')
    list_filter = ('locked', 'project')
    search_fields = ('number',)
    inlines = [RelocationLineInline]


# --- вложения ------------------------------------------------------------- #
@admin.register(models.Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'content_type', 'size', 'uploaded_at', 'user')
