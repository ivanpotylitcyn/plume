"""Модель данных plume (PLM).

Строго соответствует технической ER-диаграмме в README.md (источник правды).
Схема заморожена — при любом изменении сначала правится диаграмма.

Сквозные принципы, влияющие на код (см. README / docs/JOURNAL.md):
- `Lot` — главная учётная единица; склад двигается только по `Lot`.
- `Lot` всегда из одного origin-документа (exclusive arc): поставка/изготовление/
  инвентаризация/отпочкование — ровно один FK задан.
- Авторство — на документах (`user` → auth.User), движение без документа не живёт.
- `StockMovement` — пересчитываемая проекция, не append-only журнал.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


# Денежные и количественные поля — DecimalField (не float), под MySQL.
def money(**kw):
    return models.DecimalField(max_digits=14, decimal_places=2, **kw)


def qty(**kw):
    return models.DecimalField(max_digits=14, decimal_places=4, **kw)


def _exactly_one_q(fields):
    """Q «ровно один из FK задан» (exclusive arc) — для CheckConstraint."""
    q = Q()
    for chosen in fields:
        term = Q(**{f'{chosen}__isnull': False})
        for other in fields:
            if other != chosen:
                term &= Q(**{f'{other}__isnull': True})
        q |= term
    return q


def _validate_exactly_one(instance, fields, label):
    """Прикладная проверка exclusive arc (дружелюбная ошибка в формах)."""
    filled = [f for f in fields if getattr(instance, f'{f}_id', None) is not None]
    if len(filled) != 1:
        raise ValidationError(
            f'{label}: должен быть задан ровно один из {fields} (задано: {filled}).'
        )


# exclusive-arc наборы FK (модульные — нужны и в Meta-констрейнтах, и в методах)
LOT_ORIGIN_FIELDS = ('receipt', 'kitting', 'inventory', 'requisition')
ATTACHMENT_OWNER_FIELDS = ('item', 'receipt', 'transfer', 'kitting', 'inventory',
                           'writeoff', 'requisition')
# документ-владелец знаковой строки движения (волна 13, Ф0): пока 4 FK + Check,
# в Ф2 (MTI) схлопнётся в один FK на родитель `StockDocument`.
STOCKLINE_DOC_FIELDS = ('kitting', 'transfer', 'writeoff', 'requisition')


# --------------------------------------------------------------------------- #
#  Абстрактная шапка складского документа (волна 13, Ф1)
# --------------------------------------------------------------------------- #
class DocStatus(models.TextChoices):
    """Единый мягкий замок складского документа: `draft ⇄ posted`."""
    DRAFT = 'draft', 'Черновик'
    POSTED = 'posted', 'Проведён'


class StockDocument(models.Model):
    """Конкретный MTI-родитель складского ордера (Приход/Комплектация/Инвентаризация/
    Требование/Передача/Списание) — «Ордер» в UI (волна 13, Ф2a).

    Несёт **единый мягкий замок** `status {draft ⇄ posted}` (волна 13, Ф1): свернул
    разнородные `Receipt.approved`, `Transfer.posted`, `Kitting.status{wip/closed/
    cancelled}` в одну ось. `posted` = edit-freeze (форма read-only); склад **НЕ
    гейтится** — замок чисто интерфейсный (остатки собираются независимо от статуса).
    `cancelled` снят: отмена = удаление.

    **Ф2a:** абстрактный миксин `StockDoc` схлопнут в этого конкретного родителя —
    6 документов стали MTI-наследниками, их PK = единый `id` этой таблицы (унификация
    id-пространства). Дискриминатор `kind` («Тип = поле одной сущности») мостит к режиму
    «Ордера». Специфичные поля (project/user/date/number/supplier/…) пока живут на детях;
    их подъём в родителя и коллапс дуг `Lot.origin`/`Attachment.owner`/`StockLine.document`
    в один FK на этот PK — следующими укусами Ф2.
    """

    class Kind(models.TextChoices):
        RECEIPT = 'receipt', 'Приход (УПД)'
        KITTING = 'kitting', 'Комплектация'
        INVENTORY = 'inventory', 'Инвентаризация'
        REQUISITION = 'requisition', 'Требование'
        TRANSFER = 'transfer', 'Передача'
        WRITEOFF = 'writeoff', 'Списание'
        RELOCATION = 'relocation', 'Перемещение'  # ← новый вид, дочерней таблицы пока нет

    Status = DocStatus

    # Дочерний класс объявляет свой вид (`KIND`); `save()` штампует его в `kind`.
    KIND = None

    kind = models.CharField('вид ордера', max_length=16, choices=Kind.choices,
                            blank=True, default='')
    status = models.CharField('статус', max_length=16, choices=DocStatus.choices,
                              default=DocStatus.DRAFT)

    class Meta:
        verbose_name = 'ордер'
        verbose_name_plural = 'ордера'

    @property
    def is_posted(self):
        return self.status == DocStatus.POSTED

    def save(self, *args, **kwargs):
        # MTI-дети штампуют свой вид; прямых bare-StockDocument не создаём.
        if self.KIND and not self.kind:
            self.kind = self.KIND
        super().save(*args, **kwargs)


# --------------------------------------------------------------------------- #
#  Справочники
# --------------------------------------------------------------------------- #
class Item(models.Model):
    """Изделие — единица справочника (абстракция: КД/datasheet). Едина для
    приборов, компонентов и материалов; вид — `kind`."""

    class Kind(models.TextChoices):
        DEVICE = 'device', 'Изделие'
        COMPONENT = 'component', 'Компонент'
        MATERIAL = 'material', 'Материал'

    code = models.CharField('артикул', max_length=128, unique=True)
    name = models.CharField('название', max_length=255)
    kind = models.CharField('вид', max_length=16, choices=Kind.choices,
                            default=Kind.COMPONENT)
    uom = models.CharField('ед. изм.', max_length=32, default='шт')
    estimated_cost = money(verbose_name='оценочная стоимость', null=True, blank=True)
    is_manufactured = models.BooleanField('производимое', default=False)
    active = models.BooleanField('активно', default=True)

    class Meta:
        verbose_name = 'изделие'
        verbose_name_plural = 'изделия'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} — {self.name}'


class BomLine(models.Model):
    """Строка состава изделия: parent → component (рекурсивный BOM)."""

    parent = models.ForeignKey(Item, on_delete=models.CASCADE,
                               related_name='bom_lines')
    component = models.ForeignKey(Item, on_delete=models.PROTECT,
                                  related_name='used_in')
    qty = qty(verbose_name='кол-во')
    position = models.CharField('позиция', max_length=64, blank=True, default='')

    class Meta:
        verbose_name = 'строка BOM'
        verbose_name_plural = 'строки BOM'
        constraints = [
            models.UniqueConstraint(fields=['parent', 'component'],
                                    name='bomline_uniq_parent_component'),
        ]

    def __str__(self):
        return f'{self.parent.code} ⊃ {self.component.code} ×{self.qty}'


class Supplier(models.Model):
    name = models.CharField('наименование', max_length=255)
    inn = models.CharField('ИНН', max_length=16, blank=True, default='')

    class Meta:
        verbose_name = 'поставщик'
        verbose_name_plural = 'поставщики'
        ordering = ['name']

    def __str__(self):
        return self.name


class Location(models.Model):
    """Место хранения. В MVP — один дефолтный «Основной склад»."""

    code = models.CharField('код', max_length=64, unique=True)
    name = models.CharField('название', max_length=255)
    kind = models.CharField('вид', max_length=32, blank=True, default='')

    class Meta:
        verbose_name = 'место хранения'
        verbose_name_plural = 'места хранения'
        ordering = ['code']

    def __str__(self):
        return self.name


class Project(models.Model):
    """Проект — сквозная сущность и одновременно «склад». Внутренние проекты
    (`kind`) — служебные склады-назначения (белый/серый)."""

    class Kind(models.TextChoices):
        EXTERNAL = 'external', 'Внешний (НИР/контракт)'
        INTERNAL_STOCK = 'internal_stock', 'Собственный склад (белые)'
        INTERNAL_WRITEOFF = 'internal_writeoff', 'Свободные неучтённые (серые)'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        ACTIVE = 'active', 'Активен'
        CLOSED = 'closed', 'Закрыт'

    code = models.CharField('код', max_length=64, unique=True)
    name = models.CharField('название', max_length=255)
    budget = money(verbose_name='бюджет на материалы', null=True, blank=True)
    kind = models.CharField('вид', max_length=20, choices=Kind.choices,
                            default=Kind.EXTERNAL)
    status = models.CharField('статус', max_length=16, choices=Status.choices,
                              default=Status.ACTIVE)
    started_at = models.DateField('начат', null=True, blank=True)
    closed_at = models.DateField('закрыт', null=True, blank=True)

    INTERNAL_KINDS = {Kind.INTERNAL_STOCK, Kind.INTERNAL_WRITEOFF}

    class Meta:
        verbose_name = 'проект'
        verbose_name_plural = 'проекты'
        ordering = ['code']

    def clean(self):
        # Внутренние проекты — синглтоны (одна «куча» каждого служебного вида).
        # DB-уровень на MySQL без доп. колонки/триггера неудобен (нет partial
        # unique), поэтому держим на прикладном уровне + идемпотентный сид.
        if self.kind in self.INTERNAL_KINDS:
            dup = Project.objects.filter(kind=self.kind).exclude(pk=self.pk)
            if dup.exists():
                raise ValidationError(
                    f'Внутренний проект вида «{self.get_kind_display()}» уже существует.'
                )

    def __str__(self):
        return f'{self.code} — {self.name}'


class ProjectDemand(models.Model):
    """Потребность проекта: сколько целевых изделий нужно сделать."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name='demands')
    target_item = models.ForeignKey(Item, on_delete=models.PROTECT,
                                    related_name='demanded_in')
    qty = qty(verbose_name='кол-во')

    class Meta:
        verbose_name = 'потребность проекта'
        verbose_name_plural = 'потребности проектов'

    def __str__(self):
        return f'{self.project.code}: {self.target_item.code} ×{self.qty}'


# --------------------------------------------------------------------------- #
#  Закупки (планирование → исполнение)
# --------------------------------------------------------------------------- #
class Procurement(models.Model):
    """Закупка — планирование (что и сколько решили купить; один поток общения с
    контрагентом). Без проекта — маркер командной высоты."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        SENT = 'sent', 'Отправлена'
        CANCELLED = 'cancelled', 'Отменена'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='procurements', verbose_name='автор')
    status = models.CharField('статус', max_length=16, choices=Status.choices,
                              default=Status.DRAFT)
    date = models.DateField('дата (начало переговоров)', null=True, blank=True)
    note = models.CharField('примечание', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'закупка (план)'
        verbose_name_plural = 'закупки (план)'

    def __str__(self):
        return f'Закупка #{self.pk} [{self.get_status_display()}]'


class ProcurementLine(models.Model):
    procurement = models.ForeignKey(Procurement, on_delete=models.CASCADE,
                                    related_name='lines')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+')
    qty = qty(verbose_name='кол-во (итог)')

    class Meta:
        verbose_name = 'строка закупки'
        verbose_name_plural = 'строки закупки'

    def __str__(self):
        return f'{self.item.code} ×{self.qty}'


class Purchase(models.Model):
    """Заказ — проектное исполнение (документальное обязательство)."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        SENT = 'sent', 'Отправлен'
        PARTIAL = 'partial', 'Частично получен'
        RECEIVED = 'received', 'Получен'
        CANCELLED = 'cancelled', 'Отменён'

    procurement = models.ForeignKey(Procurement, on_delete=models.PROTECT,
                                    related_name='purchases')
    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='purchases')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='purchases', verbose_name='автор')
    status = models.CharField('статус', max_length=16, choices=Status.choices,
                              default=Status.DRAFT)
    date = models.DateField('дата (оформление)', null=True, blank=True)
    note = models.CharField('примечание', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'заказ'
        verbose_name_plural = 'заказы'

    def __str__(self):
        return f'Заказ #{self.pk} ({self.project.code}) [{self.get_status_display()}]'


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE,
                                 related_name='lines')
    item = models.ForeignKey(Item, on_delete=models.PROTECT,
                             related_name='purchase_lines')
    qty = qty(verbose_name='заказано')

    class Meta:
        verbose_name = 'строка заказа'
        verbose_name_plural = 'строки заказа'
        constraints = [
            models.UniqueConstraint(fields=['purchase', 'item'],
                                    name='purchaseline_uniq_purchase_item'),
        ]

    def __str__(self):
        return f'{self.item.code} ×{self.qty}'


# --------------------------------------------------------------------------- #
#  Документы-origin партий + приёмка
# --------------------------------------------------------------------------- #
class Receipt(StockDocument):
    """Приход / УПД — приёмка по передаточному документу, рождает партии."""

    KIND = StockDocument.Kind.RECEIPT

    number = models.CharField('№ УПД', max_length=64)
    date = models.DateField('дата')
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT,
                                 related_name='receipts')
    purchase = models.ForeignKey(Purchase, on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name='receipts')
    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='receipts')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='receipts', verbose_name='автор')

    class Meta:
        verbose_name = 'приход (УПД)'
        verbose_name_plural = 'приходы (УПД)'

    def __str__(self):
        return f'УПД {self.number} от {self.date}'


class Kitting(StockDocument):
    """Комплектация — инструмент ведения сборки лота: списывает компоненты и
    рождает партию-прибор. Замок `draft → posted` (закрытие рождает лот-прибор)."""

    KIND = StockDocument.Kind.KITTING

    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='kittings')
    target_item = models.ForeignKey(Item, on_delete=models.PROTECT,
                                    related_name='kittings')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='kittings', verbose_name='автор')
    qty = qty(verbose_name='кол-во образцов')
    date = models.DateField('дата открытия', null=True, blank=True)

    class Meta:
        verbose_name = 'комплектация'
        verbose_name_plural = 'комплектации'

    def __str__(self):
        return (f'Комплектация #{self.pk} {self.target_item.code} '
                f'[{self.get_status_display()}]')


class Inventory(StockDocument):
    """Инвентаризация — рождает «найденные» партии (излишки/ре-материализация)."""

    KIND = StockDocument.Kind.INVENTORY

    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='inventories')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='inventories', verbose_name='автор')
    number = models.CharField('№ акта', max_length=64)
    date = models.DateField('дата')
    note = models.CharField('примечание', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'инвентаризация'
        verbose_name_plural = 'инвентаризации'

    def __str__(self):
        return f'Инвентаризация {self.number}'


class Requisition(StockDocument):
    """Требование/отпочкование — рождает лоты в проекте-получателе из source-лота."""

    KIND = StockDocument.Kind.REQUISITION

    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='requisitions',
                                verbose_name='проект-получатель')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='requisitions', verbose_name='автор')
    number = models.CharField('№ требования', max_length=64)
    date = models.DateField('дата')

    class Meta:
        verbose_name = 'требование'
        verbose_name_plural = 'требования'

    def __str__(self):
        return f'Требование {self.number}'


# --------------------------------------------------------------------------- #
#  Партия и движения склада
# --------------------------------------------------------------------------- #
class Lot(models.Model):
    """Партия — физическое воплощение изделия, главная учётная единица склада.
    Ровно один origin-документ (exclusive arc)."""

    ORIGIN_FIELDS = LOT_ORIGIN_FIELDS

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='lots')
    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='lots', verbose_name='home-проект')
    # origin (exclusive arc) — ровно один задан
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, null=True,
                                blank=True, related_name='lots')
    kitting = models.ForeignKey(Kitting, on_delete=models.CASCADE, null=True,
                                blank=True, related_name='lots')
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, null=True,
                                  blank=True, related_name='lots')
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, null=True,
                                    blank=True, related_name='lots')
    predecessor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name='successors')
    qty = qty(verbose_name='рождённое кол-во')
    unit_cost = money(verbose_name='цена / себестоимость', default=0)
    received_name = models.CharField('название из УПД', max_length=255,
                                     blank=True, default='')
    serial_number = models.CharField('заводской №', max_length=128,
                                     blank=True, default='')

    class Meta:
        verbose_name = 'партия'
        verbose_name_plural = 'партии'
        constraints = [
            models.CheckConstraint(condition=_exactly_one_q(LOT_ORIGIN_FIELDS),
                                   name='lot_exactly_one_origin'),
        ]

    @property
    def origin_kind(self):
        for f in self.ORIGIN_FIELDS:
            if getattr(self, f'{f}_id', None) is not None:
                return f
        return None

    @property
    def origin(self):
        kind = self.origin_kind
        return getattr(self, kind) if kind else None

    def clean(self):
        _validate_exactly_one(self, self.ORIGIN_FIELDS, 'Lot')
        # Чистота: лот по поставке живёт в проекте этой поставки.
        if self.receipt_id and self.project_id \
                and self.receipt.project_id != self.project_id:
            raise ValidationError(
                'Lot.project должен совпадать с project прихода-origin (УПД ↔ проект).'
            )

    def __str__(self):
        return f'Lot#{self.pk} {self.item.code} ({self.project.code})'


class StockMovement(models.Model):
    """Движение склада — пересчитываемая проекция из документов (не журнал).
    item и project выводятся из партии; тип — из origin+знак."""

    class Type(models.TextChoices):
        RECEIPT = 'RECEIPT', 'Приход'
        ISSUE = 'ISSUE', 'Расход'
        RETURN = 'RETURN', 'Возврат'

    lot = models.ForeignKey(Lot, on_delete=models.CASCADE, related_name='movements')
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='+')
    type = models.CharField('тип', max_length=16, choices=Type.choices)
    qty = qty(verbose_name='кол-во (со знаком)')
    source_type = models.CharField('тип документа-источника', max_length=32)
    source_id = models.IntegerField('id документа-источника')
    created_at = models.DateTimeField('штамп вставки', auto_now_add=True)

    class Meta:
        verbose_name = 'движение склада'
        verbose_name_plural = 'движения склада'
        indexes = [
            models.Index(fields=['lot']),
            models.Index(fields=['location']),
        ]

    def __str__(self):
        return f'{self.type} lot{self.lot_id} {self.qty:+}'


class StockLine(models.Model):
    """Знаковая строка движения СУЩЕСТВУЮЩЕГО лота — единая (волна 13, Ф0).

    Сворачивает четыре таблицы строк-расхода (`KittingLine`/`TransferLine`/
    `WriteoffLine`/`RequisitionLine`) в одну. `qty` со знаком (− = расход/списание/
    пайка; в Ф2 «Перемещение» даст пару −/+ между локациями). Документ-владелец —
    exclusive arc (ровно один из четырёх FK), схлопнется в один FK при MTI (Ф2).
    Рождение лотов сюда НЕ входит: born-лоты остаются на `Lot.origin` (born-direct).
    Компонент строки комплектации не храним — он выводится из `lot.item`.
    """

    DOC_FIELDS = STOCKLINE_DOC_FIELDS

    # документ-владелец (exclusive arc) — ровно один задан
    kitting = models.ForeignKey('Kitting', on_delete=models.CASCADE, null=True,
                                blank=True, related_name='lines')
    transfer = models.ForeignKey('Transfer', on_delete=models.CASCADE, null=True,
                                 blank=True, related_name='lines')
    writeoff = models.ForeignKey('Writeoff', on_delete=models.CASCADE, null=True,
                                 blank=True, related_name='lines')
    requisition = models.ForeignKey('Requisition', on_delete=models.CASCADE, null=True,
                                    blank=True, related_name='lines')
    lot = models.ForeignKey('Lot', on_delete=models.PROTECT,
                            related_name='stock_lines',
                            verbose_name='лот (расходуемый источник)')
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='+')
    qty = qty(verbose_name='кол-во (со знаком: − расход)')
    date = models.DateField('дата (пайка)', null=True, blank=True)
    display_name = models.CharField('отображаемое имя (накладная)', max_length=255,
                                    blank=True, default='')

    class Meta:
        verbose_name = 'строка движения'
        verbose_name_plural = 'строки движения'
        constraints = [
            models.CheckConstraint(condition=_exactly_one_q(STOCKLINE_DOC_FIELDS),
                                   name='stockline_exactly_one_document'),
        ]

    @property
    def doc_kind(self):
        for f in self.DOC_FIELDS:
            if getattr(self, f'{f}_id', None) is not None:
                return f
        return None

    @property
    def document(self):
        kind = self.doc_kind
        return getattr(self, kind) if kind else None

    def clean(self):
        _validate_exactly_one(self, self.DOC_FIELDS, 'StockLine')

    def __str__(self):
        return f'{self.doc_kind} lot{self.lot_id} {self.qty:+}'


# --------------------------------------------------------------------------- #
#  Выбытие / передача / закрытие
# --------------------------------------------------------------------------- #
class Transfer(StockDocument):
    """Передача — только заказчикам, по накладной в рамках проекта."""

    KIND = StockDocument.Kind.TRANSFER

    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='transfers')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='transfers', verbose_name='автор')
    date = models.DateField('дата')
    number = models.CharField('№ накладной', max_length=64)

    class Meta:
        verbose_name = 'передача'
        verbose_name_plural = 'передачи'

    def __str__(self):
        return f'Передача {self.number}'


class Writeoff(StockDocument):
    """Списание — с причиной (серый путь: → «Свободные неучтённые»)."""

    KIND = StockDocument.Kind.WRITEOFF

    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='writeoffs')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='writeoffs', verbose_name='автор')
    number = models.CharField('№ акта', max_length=64)
    date = models.DateField('дата')
    reason = models.CharField('причина', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'списание'
        verbose_name_plural = 'списания'

    def __str__(self):
        return f'Списание {self.number}'


# --------------------------------------------------------------------------- #
#  Вложения (единая таблица, exclusive arc по владельцу)
# --------------------------------------------------------------------------- #
class Attachment(models.Model):
    """PDF/скан. Файл — на диске (MEDIA_ROOT), не BLOB. Ровно один владелец."""

    OWNER_FIELDS = ATTACHMENT_OWNER_FIELDS

    file = models.FileField('файл', upload_to='attachments/%Y/%m/')
    filename = models.CharField('имя файла', max_length=255, blank=True, default='')
    size = models.IntegerField('размер, байт', default=0)
    content_type = models.CharField('тип', max_length=64, blank=True, default='')
    label = models.CharField('подпись', max_length=255, blank=True, default='')
    uploaded_at = models.DateTimeField('загружено', auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='attachments', verbose_name='загрузил')
    # владелец (exclusive arc)
    item = models.ForeignKey(Item, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='attachments')
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, null=True,
                                blank=True, related_name='attachments')
    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, null=True,
                                 blank=True, related_name='attachments')
    kitting = models.ForeignKey(Kitting, on_delete=models.CASCADE, null=True,
                                blank=True, related_name='attachments')
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, null=True,
                                  blank=True, related_name='attachments')
    writeoff = models.ForeignKey(Writeoff, on_delete=models.CASCADE, null=True,
                                 blank=True, related_name='attachments')
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, null=True,
                                    blank=True, related_name='attachments')

    class Meta:
        verbose_name = 'вложение'
        verbose_name_plural = 'вложения'
        constraints = [
            models.CheckConstraint(condition=_exactly_one_q(ATTACHMENT_OWNER_FIELDS),
                                   name='attachment_exactly_one_owner'),
        ]

    def clean(self):
        _validate_exactly_one(self, self.OWNER_FIELDS, 'Attachment')

    def __str__(self):
        return self.filename or self.file.name
