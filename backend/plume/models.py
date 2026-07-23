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


# exclusive-arc наборы FK (модульные — нужны и в Meta-констрейнтах, и в методах).
# Волна 13, Ф2b: дуги `Lot.origin` (4 FK) и `StockLine.document` (4 FK) СХЛОПНУТЫ в
# один FK на MTI-родителя `StockDocument` (id-пространство унифицировано в Ф2a) —
# их exclusive-arc наборы и Check умерли. У `Attachment` владельца два (Item — не
# ордер — не поднимается в MTI), поэтому дуга остаётся, но всего из двух полей.
ATTACHMENT_OWNER_FIELDS = ('item', 'document')


# --------------------------------------------------------------------------- #
#  Абстрактная шапка складского документа (волна 13, Ф1)
# --------------------------------------------------------------------------- #
# Волна 19, Ф1c: строковый `DocStatus {draft,posted}` снят — ось стала `bool locked`
# на всех пяти сущностях (Item / StockDocument / Procurement / Purchase / Project).
# Мотив — понятность модели: два состояния, которые не надо запоминать словами
# («доверять или проверять»). Подписи («Зафиксировать»/«Расфиксировать») живут во
# фронте: смена слова больше не стоит миграции. Даром закрылась дыра валидации —
# `choices` не проверяются в `.save()`, а `tinyint(1)` мусор принять не может.


class StockDocument(models.Model):
    """Конкретный MTI-родитель складского ордера (Приход/Комплектация/Инвентаризация/
    Требование/Передача/Списание) — «Ордер» в UI (волна 13, Ф2a).

    Несёт **единый мягкий замок** `locked` (волна 13, Ф1; строка → bool в волне 19,
    Ф1c): свернул разнородные `Receipt.approved`, `Transfer.posted`,
    `Kitting.status{wip/closed/cancelled}` в одну ось. `locked=True` = edit-freeze
    (форма read-only); склад **НЕ гейтится** — замок чисто интерфейсный (остатки
    собираются независимо от него). `cancelled` снят: отмена = удаление.

    **Ф2a:** абстрактный миксин `StockDoc` схлопнут в этого конкретного родителя —
    6 документов стали MTI-наследниками, их PK = единый `id` этой таблицы (унификация
    id-пространства). Дискриминатор `kind` («Тип = поле одной сущности») мостит к режиму
    «Ордера».
    **Ф2b:** дуги `Lot.origin` (4 FK) / `StockLine.document` (4 FK) схлопнуты в один FK
    на этот PK (реверс — `lots`/`lines`), `Attachment.document` — один FK (владелец теперь
    Item ИЛИ ордер).
    **Ф2c:** общие поля `project`/`user`/`date`/`number`/`note` подняты сюда с 6 детей
    (дедуп; реверс — `project.documents`/`user.documents`). Специфика осталась на детях:
    `Receipt.contractor`/`purchase`, `Kitting.target_item`/`qty`, `Writeoff.reason`,
    `Transfer.contractor` (контрагент-заказчик, Ф2f+).
    """

    class Kind(models.TextChoices):
        RECEIPT = 'receipt', 'Приход (УПД)'
        KITTING = 'kitting', 'Комплектация'
        INVENTORY = 'inventory', 'Инвентаризация'
        REQUISITION = 'requisition', 'Требование'
        TRANSFER = 'transfer', 'Передача'
        WRITEOFF = 'writeoff', 'Списание'
        RELOCATION = 'relocation', 'Перемещение'  # ← новый вид, дочерней таблицы пока нет

    # Дочерний класс объявляет свой вид (`KIND`); `save()` штампует его в `kind`.
    KIND = None

    # Волна 13, Ф2d — условная валидация специфики по виду. Ф2c подняла общие поля в
    # родителя, осознанно ослабив их: `date` → nullable, `number` → blank (одной колонкой
    # на общий MTI-родитель per-kind NOT NULL не выразить). До Ф2c пять видов несли
    # `date`(NOT NULL)+`number`(required non-blank), а kitting — nullable-дату и вовсе без
    # поля номера (см. reverse-часть миграции 0007). Здесь это правило живёт **одним
    # kind-driven источником**: `clean()` зовёт `full_clean` админ-ModelForm; движок
    # дублирует его гейтом полноты на фиксации (`lock_document`/`lock_receipt`/
    # `lock_transfer`). `relocation` (дочерней таблицы пока нет) — без обязательной шапки.
    REQUIRED_HEADER_BY_KIND = {
        Kind.RECEIPT:     ('date', 'number'),
        Kind.INVENTORY:   ('date', 'number'),
        Kind.REQUISITION: ('date', 'number'),
        Kind.TRANSFER:    ('date', 'number'),
        Kind.WRITEOFF:    ('date', 'number'),
        Kind.RELOCATION:  ('date', 'number'),  # Ф2e: реальный документ с номером — строгий
        Kind.KITTING:     (),
    }

    kind = models.CharField('вид ордера', max_length=16, choices=Kind.choices,
                            blank=True, default='')
    locked = models.BooleanField('зафиксирован', default=False)

    # Ф2c — общие поля подняты с 6 детей в родителя (дедуп). Специфика (contractor/
    # purchase/target_item/qty/reason) осталась на детях. `project` строкой ('Project'
    # определён ниже), `user` — settings-строкой. `date` nullable (Kitting-черновик
    # мог быть без даты; строгий per-kind NOT NULL — условная валидация, Ф2c #2).
    # `number`/`note` blank (Kitting без номера, note только у инвентаризации) — их
    # видимость по `kind` рулит форма/матрица (Ф2c #7). Реверс-аксессор — `documents`.
    project = models.ForeignKey('Project', on_delete=models.PROTECT,
                                related_name='documents', verbose_name='проект')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='documents', verbose_name='автор')
    date = models.DateField('дата', null=True, blank=True)
    number = models.CharField('номер', max_length=64, blank=True, default='')
    note = models.CharField('примечание', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'ордер'
        verbose_name_plural = 'ордера'

    def clean(self):
        """Условная валидация шапки по виду (Ф2d): восстанавливает per-kind
        обязательность `date`/`number`, ослабленную подъёмом полей в родителя (Ф2c).
        Ошибки — по полям (дружелюбны и в админ-форме, и через `e.messages` в API)."""
        super().clean()
        required = self.REQUIRED_HEADER_BY_KIND.get(self.KIND or self.kind, ())
        errors = {}
        if 'date' in required and self.date is None:
            errors['date'] = 'Дата обязательна для этого вида ордера.'
        if 'number' in required and not (self.number or '').strip():
            errors['number'] = 'Номер обязателен для этого вида ордера.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # MTI-дети штампуют свой вид; прямых bare-StockDocument не создаём.
        if self.KIND and not self.kind:
            self.kind = self.KIND
        super().save(*args, **kwargs)


# --------------------------------------------------------------------------- #
#  Справочники
# --------------------------------------------------------------------------- #
class Category(models.Model):
    """Категория изделия — физический класс (конденсатор/микросхема/стабилизатор/…).
    Волна 15: справочник (FK вместо прежнего enum `Item.kind`), синхронизируемый с
    библиотекой компонентов — `code` = стем имени CSV-файла (`capacitors`/`mcu`/…).
    Классы редактируемы, рост библиотеки = 0 правок схемы; `label`/`icon` отдаются в
    сериализации Item (снимают хардкод-карту на фронте). Синк делает `get_or_create`
    по `code` на лету (новый класс всплывает с сырым label, юзер правит)."""

    code = models.CharField('код', max_length=64, unique=True)
    label = models.CharField('название', max_length=128)
    icon = models.CharField('иконка (Codicon)', max_length=64, blank=True, default='')

    class Meta:
        verbose_name = 'категория'
        verbose_name_plural = 'категории'
        ordering = ['code']

    def __str__(self):
        return self.label or self.code


class Item(models.Model):
    """Изделие — единица справочника (абстракция: КД/datasheet). Едина для
    приборов, компонентов и материалов. Класс — `category` (FK-справочник); ось
    «производим/покупаем» — `produced` (⟂ category, волна 15).

    Ключ `design_item_id` — канон внешней библиотеки компонентов (колонка `Design
    Item Id` = заказной PN); осознанно НЕ `item_id`, чтобы не столкнуться с Django
    FK-PK аксессором `item_id` в рукописном JSON-API (JOURNAL 2026-07-12)."""

    # Персистентный замок (волна 17) — та же ось `locked`, что у `StockDocument`.
    # `locked=True` = ФИКСАЦИЯ: форма read-only (свойства + BOM), мутации гейтятся
    # в движке (защита от ручного дрейфа). Проявляется слабее, чем у документов:
    # только заморозка, без арифметики (у заказа замок ещё и включает счёт
    # «заказано»). Синк библиотеки ставит `locked=True` (библиотека = источник
    # правды); заведённые руками изделия — `False`.
    design_item_id = models.CharField('изделие', max_length=128, unique=True)
    description = models.CharField('описание', max_length=255)
    category = models.ForeignKey(Category, on_delete=models.PROTECT,
                                 related_name='items', verbose_name='категория')
    uom = models.CharField('ед. изм.', max_length=32, default='шт')
    temperature = models.CharField('температурный диапазон', max_length=64,
                                   blank=True, default='')
    estimated_cost = money(verbose_name='оценочная стоимость', null=True, blank=True)
    produced = models.BooleanField('производимое', default=False)
    locked = models.BooleanField('зафиксировано', default=False)

    class Meta:
        verbose_name = 'изделие'
        verbose_name_plural = 'изделия'
        ordering = ['design_item_id']

    def __str__(self):
        return f'{self.design_item_id} — {self.description}'


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
        return f'{self.parent.design_item_id} ⊃ {self.component.design_item_id} ×{self.qty}'


class Counterparty(models.Model):
    """Контрагент — единая внешняя сторона документооборота (волна 13, Ф2f+).

    Свернул `Supplier` (был только поставщиком) в одну сущность, играющую роли:
    `is_supplier` — сторона прихода (`Receipt.contractor`, поставщик), `is_customer`
    — сторона передачи (`Transfer.contractor`, заказчик). Одно юрлицо может быть и
    тем, и другим (обе роли на одной записи). Пикеры фильтруют по роли; быстрое
    создание проставляет роль по контексту. Закрывает отложенную симметрию «передача
    = перемещение к внешней точке» — у передачи теперь структурный получатель, а не
    только текст в строке накладной.
    """

    name = models.CharField('наименование', max_length=255)
    inn = models.CharField('ИНН', max_length=16, blank=True, default='')
    is_supplier = models.BooleanField('поставщик', default=True)
    is_customer = models.BooleanField('заказчик', default=False)

    class Meta:
        verbose_name = 'контрагент'
        verbose_name_plural = 'контрагенты'
        ordering = ['name']

    def __str__(self):
        return self.name


class Location(models.Model):
    """Место хранения. Волна 13, Ф2e — мультисклад активирован: мест может быть
    несколько (напр. «Основной склад 103» и «Место пайки 105»), движок считает
    остаток по паре `(лот, локация)`, «Перемещение» (`Relocation`) двигает лот
    между ними. Синглтон-заглушка MVP снята (справочник редактируем)."""

    code = models.CharField('код', max_length=64, unique=True)
    name = models.CharField('название', max_length=255)
    kind = models.CharField('вид', max_length=32, blank=True, default='')

    class Meta:
        verbose_name = 'склад'
        verbose_name_plural = 'склады'
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

    code = models.CharField('код', max_length=64, unique=True)
    name = models.CharField('название', max_length=255)
    budget = money(verbose_name='бюджет на материалы', null=True, blank=True)
    kind = models.CharField('вид', max_length=20, choices=Kind.choices,
                            default=Kind.EXTERNAL)
    # Волна 19, Ф1c: `status {active,closed}` → та же ось `locked`, что у изделия и
    # ордеров. Проявляется слабо (заморозка, без арифметики). Хранимый, а не
    # вычисляемый: иначе разузлование гонялось бы на каждый чих — вместо этого
    # «Проверить возможность закрытия» пробегает по остаткам и открывает фиксацию.
    locked = models.BooleanField('зафиксирован', default=False)
    # Даты — чисто информационные: ни с чем не связаны, ни на что не влияют.
    # Проставляются руками (реальные сроки работы, а не формальности), поэтому
    # `close_project` их больше НЕ штампует. Суффикс `_at` снят вместе со связью.
    started = models.DateField('начат', null=True, blank=True)
    closed = models.DateField('закрыт', null=True, blank=True)

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
        return f'{self.project.code}: {self.target_item.design_item_id} ×{self.qty}'


# --------------------------------------------------------------------------- #
#  Закупки (планирование → исполнение)
# --------------------------------------------------------------------------- #
class Procurement(models.Model):
    """Закупка — планирование (что и сколько решили купить; один поток общения с
    контрагентом). Без проекта — маркер командной высоты."""

    # Замок — общая ось `locked` (волна 19: Ф1 свела enum к draft/posted, Ф1c сделала
    # его bool): тот же замок, что у ордеров и изделия. Отмена = удаление (Р1).
    # Подпись («Зафиксирована») — забота представления, живёт во фронте.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='procurements', verbose_name='автор')
    locked = models.BooleanField('зафиксирована', default=False)
    # Контрагент-поставщик (волна 19, Ф4, Р3): закупка = «один поток общения» с
    # поставщиком; отсюда берётся сторона при «Заказ → УПД» (Ф6) и шапка order.xlsx
    # (Ф4b). `SET_NULL` (не `PROTECT`, как у `Receipt.contractor`) осознанно: закупка —
    # план/черновик, удаление контрагента её не должно ронять — поле просто опустеет.
    contractor = models.ForeignKey(Counterparty, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='procurements',
                                   verbose_name='контрагент')
    date = models.DateField('дата (начало переговоров)', null=True, blank=True)
    note = models.CharField('примечание', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'закупка (план)'
        verbose_name_plural = 'закупки (план)'

    def __str__(self):
        return f'Закупка #{self.pk}' + (' 🔒' if self.locked else '')


class ProcurementLine(models.Model):
    procurement = models.ForeignKey(Procurement, on_delete=models.CASCADE,
                                    related_name='lines')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+')
    qty = qty(verbose_name='кол-во (итог)')

    class Meta:
        verbose_name = 'строка закупки'
        verbose_name_plural = 'строки закупки'

    def __str__(self):
        return f'{self.item.design_item_id} ×{self.qty}'


class Purchase(models.Model):
    """Заказ — проектное исполнение (документальное обязательство)."""

    # Замок — общая ось `locked` (волна 19: Ф1 + Ф1c). Мёртвые `partial`/`received`
    # убраны: «получено» — величина ВЫЧИСЛЯЕМАЯ из приходов (`_line_received`), а не
    # замок. Две оси не путать: замок (`locked`) и покрытие (▲/●/✓).
    # У заказа замок проявляется СИЛЬНО: зафиксированный заказ считается в «заказано».
    procurement = models.ForeignKey(Procurement, on_delete=models.PROTECT,
                                    related_name='purchases')
    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='purchases')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='purchases', verbose_name='автор')
    locked = models.BooleanField('зафиксирован', default=False)
    date = models.DateField('дата (оформление)', null=True, blank=True)
    note = models.CharField('примечание', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'заказ'
        verbose_name_plural = 'заказы'

    def __str__(self):
        return f'Заказ #{self.pk} ({self.project.code})' + (' 🔒' if self.locked else '')


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
        return f'{self.item.design_item_id} ×{self.qty}'


# --------------------------------------------------------------------------- #
#  Документы-origin партий + приёмка
# --------------------------------------------------------------------------- #
class Receipt(StockDocument):
    """Приход / УПД — приёмка по передаточному документу, рождает партии."""

    KIND = StockDocument.Kind.RECEIPT

    contractor = models.ForeignKey(Counterparty, on_delete=models.PROTECT,
                                   related_name='receipts', verbose_name='поставщик')
    purchase = models.ForeignKey(Purchase, on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name='receipts')

    class Meta:
        verbose_name = 'поставка'
        verbose_name_plural = 'поставки'

    def __str__(self):
        return f'УПД {self.number} от {self.date}'


class Kitting(StockDocument):
    """Комплектация — инструмент ведения сборки лота: списывает компоненты и
    рождает партию-прибор. Замок `locked` (фиксация рождает лот-прибор)."""

    KIND = StockDocument.Kind.KITTING

    target_item = models.ForeignKey(Item, on_delete=models.PROTECT,
                                    related_name='kittings')
    qty = qty(verbose_name='кол-во образцов')

    class Meta:
        verbose_name = 'комплектация'
        verbose_name_plural = 'комплектации'

    def __str__(self):
        return (f'Комплектация #{self.pk} {self.target_item.design_item_id}'
                + (' 🔒' if self.locked else ''))


class Inventory(StockDocument):
    """Инвентаризация — рождает «найденные» партии (излишки/ре-материализация)."""

    KIND = StockDocument.Kind.INVENTORY

    # Все поля (project/user/number/date/note) подняты в StockDocument (Ф2c).

    class Meta:
        verbose_name = 'инвентаризация'
        verbose_name_plural = 'инвентаризации'

    def __str__(self):
        return f'Инвентаризация {self.number}'


class Requisition(StockDocument):
    """Требование/отпочкование — рождает лоты в проекте-получателе из source-лота."""

    KIND = StockDocument.Kind.REQUISITION

    # Все поля (project — «проект-получатель», user/number/date) подняты в StockDocument (Ф2c).

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
    Ровно один origin-документ (`origin` → `StockDocument`)."""

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='lots')
    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='lots', verbose_name='home-проект')
    # origin: рождающий ордер (born-direct). Волна 13, Ф2b — дуга из 4 FK
    # (receipt/kitting/inventory/requisition) схлопнута в один FK на MTI-родителя;
    # вид origin читается из `origin.kind` (дискриминатор Ф2a).
    origin = models.ForeignKey(StockDocument, on_delete=models.CASCADE,
                               related_name='lots', verbose_name='ордер-origin')
    predecessor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name='successors')
    qty = qty(verbose_name='рождённое кол-во')
    unit_cost = money(verbose_name='цена / себестоимость', default=0)
    # Два идентификатора партии (Волна 13, Ф2f): человеческий и машинный.
    # `lot_name` — человеческий (имена из УПД + заводские №); `part_number` —
    # строгий машинный (MPN с datasheet / децимальный номер; для станка
    # автомонтажа). PN живёт на `Lot`, а не на `Item`: упаковка/исполнение
    # варьируются от поставки; `Item.design_item_id` — абстрактный артикул.
    lot_name = models.CharField('название партии', max_length=255,
                                blank=True, default='')
    part_number = models.CharField('part number', max_length=128,
                                   blank=True, default='')

    class Meta:
        verbose_name = 'партия'
        verbose_name_plural = 'партии'

    @property
    def origin_kind(self):
        """Вид origin-ордера ('receipt'/'kitting'/'inventory'/'requisition') —
        из дискриминатора родителя (совместим со старым именем FK)."""
        return self.origin.kind if self.origin_id else None

    def clean(self):
        # Чистота: лот по поставке живёт в проекте этой поставки.
        if self.origin_id and self.origin.kind == StockDocument.Kind.RECEIPT \
                and self.project_id \
                and self.origin.receipt.project_id != self.project_id:
            raise ValidationError(
                'Lot.project должен совпадать с project прихода-origin (УПД ↔ проект).'
            )

    def __str__(self):
        return f'Lot#{self.pk} {self.item.design_item_id} ({self.project.code})'


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
    `document` → `StockDocument`: волна 13, Ф2b схлопнула дугу из 4 FK в один FK на
    MTI-родителя (id-пространство унифицировано в Ф2a). Рождение лотов сюда НЕ входит:
    born-лоты остаются на `Lot.origin` (born-direct). Компонент строки комплектации
    не храним — он выводится из `lot.item`.
    """

    document = models.ForeignKey(StockDocument, on_delete=models.CASCADE,
                                 related_name='lines', verbose_name='ордер-владелец')
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

    @property
    def doc_kind(self):
        """Вид документа-владельца ('kitting'/'transfer'/'writeoff'/'requisition')
        — из дискриминатора родителя (совместим со старым именем FK)."""
        return self.document.kind if self.document_id else None

    def __str__(self):
        return f'{self.doc_kind} lot{self.lot_id} {self.qty:+}'


# --------------------------------------------------------------------------- #
#  Выбытие / передача / закрытие
# --------------------------------------------------------------------------- #
class Transfer(StockDocument):
    """Передача — только заказчикам, по накладной в рамках проекта."""

    KIND = StockDocument.Kind.TRANSFER

    # Все поля (project/user/date/number) подняты в StockDocument (Ф2c). Специфика —
    # структурный получатель (Ф2f+): контрагент-заказчик. Nullable — исторические
    # передачи получателя-сущности не имели (текст жил в `StockLine.display_name`).
    contractor = models.ForeignKey(Counterparty, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='transfers',
                                   verbose_name='заказчик')

    class Meta:
        verbose_name = 'передача'
        verbose_name_plural = 'передачи'

    def __str__(self):
        return f'Передача {self.number}'


class Writeoff(StockDocument):
    """Списание — с причиной (серый путь: → «Свободные неучтённые»)."""

    KIND = StockDocument.Kind.WRITEOFF

    # project/user/number/date подняты в StockDocument (Ф2c); `reason` — специфика.
    reason = models.CharField('причина', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'списание'
        verbose_name_plural = 'списания'

    def __str__(self):
        return f'Списание {self.number}'


class Relocation(StockDocument):
    """Перемещение — лот между локациями внутри проекта (волна 13, Ф2e).

    Не рождает и не выбывает лот: только двигает существующий между местами
    хранения. В отличие от `Transfer` (терминальна, отдаём заказчику), перемещение
    остаётся внутри учёта — полный остаток лота/проекта сохраняется. Механика — пара
    знаковых `StockLine` на ход (`−q` на источнике, `+q` на приёмнике), зеркалящих
    `StockMovement`; лот меняет распределение по локациям, не тотал."""

    KIND = StockDocument.Kind.RELOCATION

    # Все поля (project/user/date/number) подняты в StockDocument (Ф2c).

    class Meta:
        verbose_name = 'перемещение'
        verbose_name_plural = 'перемещения'

    def __str__(self):
        return f'Перемещение {self.number}'


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
    # владелец (exclusive arc из двух): изделие ИЛИ ордер. Волна 13, Ф2b схлопнула
    # 6 документных FK в один `document` → `StockDocument` (MTI-родитель); `item`
    # остаётся — изделие не ордер, в MTI не входит.
    item = models.ForeignKey(Item, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='attachments')
    document = models.ForeignKey(StockDocument, on_delete=models.CASCADE, null=True,
                                 blank=True, related_name='attachments',
                                 verbose_name='ордер-владелец')

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
