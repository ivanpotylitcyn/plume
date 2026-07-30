"""Админка plume — служебный люк, а не рабочее место (волна 19, Ф16).

Исторически было наоборот: в волне 1 админка была **основной поверхностью ввода**,
а витрины React — read-only поверх неё. С волн 13–19 это перевёрнуто: данные вводятся
во фронте через движок (`engine.py`), а админка осталась для справочников и для
разбора полётов.

Отсюда два правила этой волны:

1. **Ордер — один пункт сайдбара.** Семь per-kind админок были единственным способом
   править семь таблиц MTI; после Ф14 таблица одна, и семёрка стала пережитком.
   Различия видов (какие поля применимы, какие строки бывают) живут в хуках
   `get_fields`/`get_inlines`/`get_readonly_fields` по `kind`.
2. **Движковое — только для чтения.** `Lot`, `StockMovement`, `StockLine` и замок
   `locked` админка НЕ правит. После Ф15 инвариант «движения ⟺ документ
   зафиксирован» держит единственный писатель — `engine.rebuild_movements`; правка
   этих таблиц мимо него нарушала бы инвариант молча, без единого следа. Смотреть —
   можно и нужно (это и есть разбор полётов), менять — через движок.

Справочники (`Item`/`Project`/`Counterparty`/`Location`/`Category`) и планирование
закупок (`Procurement`/`Purchase`) правятся как раньше: движений они не порождают.
"""
from django.contrib import admin

from . import models

Kind = models.DocumentKind


# --- базовые формы витрин ------------------------------------------------- #
class _ReadOnlyInline(admin.TabularInline):
    """Инлайн-витрина: показывает строки, но не даёт их править (Ф16).

    `max_num = 0` убирает пустые формы добавления, права — все три `False`;
    поля переводятся в readonly целиком, поэтому формы вообще не рендерятся.
    """

    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return self.fields or ()


class _ReadOnlyAdmin(admin.ModelAdmin):
    """Витрина модели, которой владеет движок: смотреть можно, править нельзя."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# --- инлайны строк (правимые: движений не порождают) ---------------------- #
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


# --- инлайны ордера (витрины: строки и партии принадлежат движку) --------- #
# Строки движения — единая `StockLine` (волна 13, Ф0); владелец — один FK `document`
# → `StockDocument`. `qty` знаковый (− расход). Различие видов свелось к набору
# осмысленных колонок: у комплектации есть дата пайки, у передачи — имя в накладной.
class StockLinesInline(_ReadOnlyInline):
    model = models.StockLine
    fk_name = 'document'
    fields = ('lot', 'location', 'qty')
    verbose_name_plural = 'строки движения (правка — во фронте, через движок)'


class KittingLinesInline(StockLinesInline):
    fields = ('lot', 'location', 'qty', 'date')


class TransferLinesInline(StockLinesInline):
    fields = ('lot', 'location', 'qty', 'display_name')


class BornLotsInline(_ReadOnlyInline):
    """Партии, рождённые этим ордером (`Lot.origin`, born-direct)."""

    model = models.Lot
    fk_name = 'origin'
    fields = ('item', 'project', 'qty', 'unit_cost', 'part_number', 'lot_name')
    verbose_name_plural = 'рождённые партии (правка — во фронте, через движок)'


# Расходные строки бывают не у всех видов; у поставки и инвентаризации их нет вовсе
# (там born-лоты). Карта — единственное место, где вид влияет на состав формы.
LINES_INLINE_BY_KIND = {
    Kind.KITTING: KittingLinesInline,
    Kind.TRANSFER: TransferLinesInline,
    Kind.WRITEOFF: StockLinesInline,
    Kind.REQUISITION: StockLinesInline,
    Kind.RELOCATION: StockLinesInline,
}

# Виды, рождающие партии (`Lot.origin` — ровно один origin-документ).
BORN_LOTS_KINDS = (Kind.RECEIPT, Kind.KITTING, Kind.INVENTORY, Kind.REQUISITION)


def specific_fields(kind):
    """Поля специфики, применимые к виду (Ф14: шесть колонок на семь видов).

    Применимость — не стиль, а инвариант БД (CHECK `doc_*_only_*`), поэтому
    контрагент берётся из `models.CONTRACTOR_KINDS`, а не переписывается здесь
    вторым списком: два списка одного инварианта разъезжаются.
    """
    fields = []
    if kind in models.CONTRACTOR_KINDS:
        fields.append('contractor')        # поставка → поставщик, передача → заказчик
    if kind == Kind.RECEIPT:
        fields.append('purchase')
    if kind == Kind.KITTING:
        fields += ['target_item', 'qty']
    if kind == Kind.WRITEOFF:
        fields.append('reason')
    return tuple(fields)


# --- справочники ---------------------------------------------------------- #
@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'description')
    search_fields = ('code', 'description')


@admin.register(models.Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'category', 'uom',
                    'temperature', 'native', 'synced', 'locked')
    list_filter = ('category', 'native', 'synced', 'locked')
    search_fields = ('code', 'description')
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
    # Ролей-флагов нет (Ф3): сторона контрагента — факт документооборота, а не
    # колонка справочника; фильтровать по ней в админке нечего.
    list_display = ('code', 'description', 'inn')
    search_fields = ('code', 'description', 'inn')


@admin.register(models.Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'kind')


# --- закупки -------------------------------------------------------------- #
@admin.register(models.Procurement)
class ProcurementAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'locked', 'contractor', 'date', 'user')
    list_filter = ('locked',)
    inlines = [ProcurementLineInline]


@admin.register(models.Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    # Ф17: контрагент — у всех трёх уровней контура; у заказа он и есть «у кого купили».
    list_display = ('__str__', 'project', 'locked', 'contractor', 'date', 'user')
    list_filter = ('locked', 'project')
    inlines = [PurchaseLineInline]


# --- ордер: ОДИН пункт на все семь видов (волна 19, Ф16) ------------------ #
@admin.register(models.StockDocument)
class StockDocumentAdmin(admin.ModelAdmin):
    """Единая админка ордера — зеркало режима «Ордера» во фронте.

    До Ф16 здесь было восемь пунктов на одну таблицу: read-only обзор «все ордера» +
    семь per-kind админок с колонкой-ссылкой `open_child`. Пережиток MTI: пока таблиц
    было семь, иначе править их было нечем. Теперь список и форма — одно место, а вид
    рулит составом полей и инлайнов.

    **Чего админка НЕ делает** (граница движка, Ф15):
    - не фиксирует и не расфиксирует — `locked` read-only. Фиксация не «галочка», а
      операция: она валидирует полноту шапки и **материализует движения**
      (`engine.lock_document` → `rebuild_movements`). Галочка мимо неё дала бы
      зафиксированный документ без движений — тихо разошедшийся инвариант.
    - не удаляет — снос ордера чистит born-лоты, их движения и **файлы** вложений
      (`engine.delete_stock_document`); каскад БД оставил бы файлы сиротами, а
      `−ISSUE` чужих лотов — непересобранными. Удаление живёт во фронте.
    - не правит строки и партии — они инлайн-витрины (см. `_ReadOnlyInline`).

    Что делает: показывает всё вперемешку с фильтрами и правит **шапку** —
    код/описание/номер/дату/проект/автора/специфику вида. Шапка движений не касается.
    """

    list_display = ('id', 'kind', 'code', 'number', 'date', 'project', 'locked', 'user')
    list_filter = ('kind', 'locked', 'project')
    search_fields = ('code', 'number', 'description')
    ordering = ('-id',)              # новейшие сверху — зеркалит OrderList
    list_select_related = ('project', 'user')

    def get_fields(self, request, obj=None):
        # На форме добавления вид ещё не выбран — специфика подтянется после
        # сохранения (сперва выбери вид, потом заполняй его поля).
        kind = obj.kind if obj else None
        base = ['kind', 'code', 'description', 'project', 'user', 'date']
        if kind != Kind.KITTING:     # у комплектации номера нет (Ф2c/Ф2d)
            base.append('number')
        base.append('locked')
        return tuple(base) + specific_fields(kind)

    def get_readonly_fields(self, request, obj=None):
        # `kind` — это КОД (поведение движка, 5 CHECK по виду), а не данные: у
        # существующего ордера он не меняется. `locked` не правится никогда.
        return ('locked', 'kind') if obj else ('locked',)

    def get_inlines(self, request, obj=None):
        if obj is None:
            return []
        inlines = []
        lines = LINES_INLINE_BY_KIND.get(obj.kind)
        if lines:
            inlines.append(lines)
        if obj.kind in BORN_LOTS_KINDS:
            inlines.append(BornLotsInline)
        return inlines

    def has_delete_permission(self, request, obj=None):
        return False                 # снос ордера — операция движка, см. docstring


# --- партии / движения: витрины движка ------------------------------------ #
@admin.register(models.Lot)
class LotAdmin(_ReadOnlyAdmin):
    list_display = ('id', 'item', 'project', 'origin_kind', 'unit_cost',
                    'part_number', 'lot_name')
    list_filter = ('project',)
    search_fields = ('item__code', 'part_number', 'lot_name')
    list_select_related = ('item', 'project', 'origin')


@admin.register(models.StockMovement)
class StockMovementAdmin(_ReadOnlyAdmin):
    """Проекция, а не журнал: строки этой таблицы пишет только
    `engine.rebuild_movements` — руками их править нечего и незачем."""

    list_display = ('id', 'lot', 'location', 'type', 'qty', 'source_type',
                    'source_id', 'created_at')
    list_filter = ('type', 'location')


@admin.register(models.StockLine)
class StockLineAdmin(_ReadOnlyAdmin):
    list_display = ('id', 'doc_kind', 'lot', 'location', 'qty')
    list_filter = ('location',)
    list_select_related = ('document', 'lot', 'location')


# --- вложения ------------------------------------------------------------- #
@admin.register(models.Attachment)
class AttachmentAdmin(_ReadOnlyAdmin):
    """Тоже витрина: запись описывает **файл на диске**, и снос мимо
    `engine.delete_attachment` оставил бы файл сиротой (а правка размера/имени —
    разошлась бы с `engine.attachment_state`)."""

    list_display = ('__str__', 'content_type', 'size', 'uploaded_at', 'user')
