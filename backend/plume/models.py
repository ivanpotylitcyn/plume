"""Модель данных plume (PLM).

Строго соответствует технической ER-диаграмме в README.md (источник правды) — и по
составу полей, и по их **порядку**: канон §13.4a UI_GUIDE («идентичность → замок →
якори → внешние атрибуты → автор → специфика вида») задаёт порядок объявлений здесь,
а формы наследуют его от модели. Правка схемы — обычная работа (CLAUDE.md, «Три
опоры»): диаграммы правятся в том же изменении, что и код.

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
# их exclusive-arc наборы и Check умерли. У `Attachment` дуга остаётся: ордера
# схлопнуты в `document`, но всё остальное в MTI не входит и держит своё поле.
# Волна 19, Ф12b: файлы нужны не только изделию и ордеру — проекту (ТЗ, договор),
# закупке/заказу (бланк запроса, счёт, КП) и контрагенту («карточка предприятия»:
# сегодня она болтается по чатам). `Location`/`Category` намеренно НЕ владельцы —
# заведём, когда заболит (решение Ивана 2026-07-26).
ATTACHMENT_OWNER_FIELDS = ('item', 'document', 'project', 'procurement',
                           'purchase', 'counterparty')


# --------------------------------------------------------------------------- #
#  Абстрактная шапка складского документа (волна 13, Ф1)
# --------------------------------------------------------------------------- #
# Виды ордера живут на уровне модуля, а не внутри `StockDocument`: тело вложенного
# `Meta` не видит пространство имён внешнего класса, а CHECK-констрейнты Ф14 обязаны
# ссылаться на конкретные виды. Внутри модели остаётся привычный алиас
# `StockDocument.Kind` — все обращения в коде продолжают читаться как раньше.
class DocumentKind(models.TextChoices):
    # Ярлыки — источник правды и для админки, и для фолбэка кода («Поставка 12»,
    # Ф12e): человекочитаемое имя вида живёт в ОДНОМ месте и совпадает с
    # `ORDER_KINDS` во фронте. «Приход (УПД)» → «Поставка» по глоссарию волны 14
    # (долг Ф8: подпись отстала от словаря на пять волн).
    RECEIPT = 'receipt', 'Поставка'
    KITTING = 'kitting', 'Комплектация'
    INVENTORY = 'inventory', 'Инвентаризация'
    REQUISITION = 'requisition', 'Требование'
    TRANSFER = 'transfer', 'Передача'
    WRITEOFF = 'writeoff', 'Списание'
    RELOCATION = 'relocation', 'Перемещение'


# Виды, у которых поле специфики вообще применимо (источник правды и для CHECK,
# и для прикладных проверок). Ф14: «пустая колонка не у своего вида» — не стиль,
# а инвариант БД.
CONTRACTOR_KINDS = (DocumentKind.RECEIPT, DocumentKind.TRANSFER)

# «Комплектуем только своё» (решение Ивана 2026-07-31, клик-проход комплектации):
# целью комплектации может быть лишь НАШЕ изделие (`Item.native`) — покупное мы не
# собираем, у него и состава нет. Текст один на все слои (движок гейтит дружелюбно,
# `StockDocument.clean` страхует), поэтому живёт константой, а не тремя копиями.
KITTING_TARGET_NATIVE = ('Комплектуем только свои изделия — целью может быть '
                         'производимое изделие, не покупное.')


# Волна 19, Ф1c: строковый `DocStatus {draft,posted}` снят — ось стала `bool locked`
# на всех пяти сущностях (Item / StockDocument / Procurement / Purchase / Project).
# Мотив — понятность модели: два состояния, которые не надо запоминать словами
# («доверять или проверять»). Подписи («Зафиксировать»/«Расфиксировать») живут во
# фронте: смена слова больше не стоит миграции. Даром закрылась дыра валидации —
# `choices` не проверяются в `.save()`, а `tinyint(1)` мусор принять не может.


class StockDocument(models.Model):
    """**Единая таблица** складского ордера (Поставка/Комплектация/Инвентаризация/
    Требование/Передача/Списание/Перемещение) — «Ордер» в UI (волна 13, Ф2a).

    Несёт **единый мягкий замок** `locked` (волна 13, Ф1; строка → bool в волне 19,
    Ф1c): свернул разнородные `Receipt.approved`, `Transfer.posted`,
    `Kitting.status{wip/closed/cancelled}` в одну ось. `cancelled` снят: отмена =
    удаление.

    **Волна 19, Ф15 — замок гейтит склад.** `locked=False` (черновик) = документ
    правится и **ничего не двигает**: его партии не лежат на складе, его строки не
    расходуют чужие, бюджет проекта его не видит. `locked=True` = форма read-only И
    документ материализован в `StockMovement` — «зафиксировано = видно всем и
    участвует в расчётах». До Ф15 замок был **чисто интерфейсным** (склад двигался
    сразу на добавление строки), и по правилу работала одна комплектация из семи
    видов — фаза убрала исключения, а не завела новое правило. Единственный писатель
    движений — `engine.rebuild_movements`, там же и гейт.

    **Ф2a:** абстрактный миксин `StockDoc` схлопнут в этого конкретного родителя —
    6 документов стали MTI-наследниками, их PK = единый `id` этой таблицы (унификация
    id-пространства). Дискриминатор `kind` («Тип = поле одной сущности») мостит к режиму
    «Ордера».
    **Ф2b:** дуги `Lot.origin` (4 FK) / `StockLine.document` (4 FK) схлопнуты в один FK
    на этот PK (реверс — `lots`/`lines`), `Attachment.document` — один FK (владелец теперь
    Item ИЛИ ордер).
    **Ф2c:** общие поля `project`/`user`/`date`/`number` подняты сюда с 6 детей (дедуп;
    реверс — `project.documents`/`user.documents`).

    **Волна 19, Ф14 — MTI снят.** Семь детских таблиц ради шести колонок специфики
    (три из них были пусты — только свой PK) схлопнуты сюда же: специфика стала
    nullable-колонками этой таблицы, дети — `proxy`-моделями с kind-фильтрующим
    менеджером. Уходят JOIN на каждом чтении, второй INSERT на записи и семь
    downcast-сайтов; `Lot.origin`/`StockLine.document`/`Attachment.document` уже
    указывали на родителя (Ф2b сделала тяжёлую часть заранее), перевязывать нечего.
    Форма правильной аналогии — не `Item.category` (категории это ДАННЫЕ: приезжают
    из библиотеки, растут, правятся), а `Item.native`: одна таблица + дискриминатор.
    Вид ордера — это КОД (зашитое поведение движка), из интерфейса его не завести,
    поэтому таблицы видов документов нет и не будет.

    **Контрагент — одна колонка** (решение Ивана 2026-07-27): у поставки он поставщик,
    у передачи — заказчик, направление читается из `kind` и двусмысленным быть не может.
    Тот же приём, что уже применён к `Lot.origin` в волне 13 (четыре типизированных FK
    → один, вид из `kind`).
    """

    Kind = DocumentKind
    CONTRACTOR_KINDS = CONTRACTOR_KINDS

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

    # Порядок объявлений — канон §13.4a: идентичность → замок → якори → внешние
    # атрибуты → автор → специфика вида. Формы читают порядок отсюда (Ф17).
    kind = models.CharField('вид ордера', max_length=16, choices=Kind.choices,
                            blank=True, default='')
    # Волна 19, Ф10: единый интерфейс идентичности — пара `code` + `description` у ВСЕХ
    # сущностей, включая документы. `code` («Нева ДЗЗ 1») — наш ярлык в списки; `number`
    # — внешний номер накладной (юридическое поле, заполняем по необходимости);
    # `description` — развёрнутое имя. `code` вводится человеком (авто-фолбэка нет) →
    # `null=True, unique=True`. Мёртвое `note` удалено везде (ни разу не пригодилось).
    code = models.CharField('код', max_length=64, unique=True, null=True, blank=True)
    description = models.CharField('описание', max_length=255, blank=True, default='')
    locked = models.BooleanField('зафиксирован', default=False)

    # --- якори: связи документа одним блоком сразу под идентичностью (§13.4a) --- #
    # Ф2c — общие поля подняты с 6 детей в родителя (дедуп). `project` строкой
    # ('Project' определён ниже), `user` — settings-строкой. Реверс-аксессор —
    # `documents`.
    #
    # Специфика видов (Ф14): шесть полей на семь видов, все nullable. Применимость
    # стережёт CHECK по `kind` (см. Meta.constraints), а обязательность — ФИКСАЦИЯ,
    # а не рождение: черновик имеет право быть неполным (решение Ивана 2026-07-27,
    # см. `REQUIRED_HEADER_BY_KIND`). Якори вида стоят здесь же, в блоке связей;
    # атрибуты вида (`target_item`/`qty`/`reason`) — хвостом, как в форме.
    project = models.ForeignKey('Project', on_delete=models.PROTECT,
                                related_name='documents', verbose_name='проект')
    # Поставка: заказ, который она закрывает.
    purchase = models.ForeignKey('Purchase', on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name='receipts')
    # Поставка → поставщик, передача → заказчик. Направление задаёт `kind`.
    contractor = models.ForeignKey('Counterparty', on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='documents',
                                   verbose_name='контрагент')

    # --- внешние атрибуты (юридическая обвязка) → автор --- #
    # `number` blank (Kitting без номера) — его видимость по `kind` рулит форма/матрица.
    # `date` nullable (Kitting-черновик мог быть без даты; строгий per-kind NOT NULL —
    # условная валидация, Ф2c #2).
    number = models.CharField('номер', max_length=64, blank=True, default='')
    date = models.DateField('дата', null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='documents', verbose_name='автор')

    # --- атрибуты вида (хвостом) --- #
    # Комплектация: прибор-цель и сколько образцов собираем.
    target_item = models.ForeignKey('Item', on_delete=models.PROTECT, null=True,
                                    blank=True, related_name='kittings',
                                    verbose_name='прибор-цель')
    qty = qty(null=True, blank=True, verbose_name='кол-во образцов')
    # Списание: причина.
    reason = models.CharField('причина', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'ордер'
        verbose_name_plural = 'ордера'
        constraints = [
            # --- обязательность у СВОЕГО вида: гейт на фиксации, не на рождении ---
            models.CheckConstraint(
                condition=(~Q(kind=DocumentKind.RECEIPT) | Q(locked=False)
                           | Q(contractor__isnull=False)),
                name='doc_locked_receipt_has_contractor',
            ),
            models.CheckConstraint(
                condition=(~Q(kind=DocumentKind.KITTING) | Q(locked=False)
                           | (Q(target_item__isnull=False) & Q(qty__isnull=False))),
                name='doc_locked_kitting_has_target',
            ),
            # --- неприменимость у ЧУЖОГО вида: колонка обязана быть пустой ---
            models.CheckConstraint(
                condition=(Q(kind__in=CONTRACTOR_KINDS) | Q(contractor__isnull=True)),
                name='doc_contractor_only_own_kinds',
            ),
            models.CheckConstraint(
                condition=(Q(kind=DocumentKind.RECEIPT) | Q(purchase__isnull=True)),
                name='doc_purchase_only_receipt',
            ),
            models.CheckConstraint(
                condition=(Q(kind=DocumentKind.KITTING)
                           | (Q(target_item__isnull=True) & Q(qty__isnull=True))),
                name='doc_target_only_kitting',
            ),
        ]

    def clean(self):
        """Условная валидация шапки по виду (Ф2d): восстанавливает per-kind
        обязательность `date`/`number`, ослабленную подъёмом полей в родителя (Ф2c).
        Ошибки — по полям (дружелюбны и в админ-форме, и через `e.messages` в API).

        Здесь же второй слой правила «комплектуем только своё» (решение Ивана
        2026-07-31). Обычно второй слой — CHECK в БД, но это правило смотрит в ЧУЖУЮ
        таблицу (`Item.native`), а MySQL в CHECK подзапросы запрещает. Поэтому
        страховкой служит `clean()`: его зовёт и админ-форма, и фиксация
        (`_require_header`) — то есть путь мимо движка (прямой ORM, админка) правило
        всё равно проходит, пусть и позже, чем дружелюбный гейт `_set_target_item`.
        """
        super().clean()
        required = self.REQUIRED_HEADER_BY_KIND.get(self.KIND or self.kind, ())
        errors = {}
        if 'date' in required and self.date is None:
            errors['date'] = 'Дата обязательна для этого вида ордера.'
        if 'number' in required and not (self.number or '').strip():
            errors['number'] = 'Номер обязателен для этого вида ордера.'
        if ((self.KIND or self.kind) == DocumentKind.KITTING
                and self.target_item_id and not self.target_item.native):
            errors['target_item'] = KITTING_TARGET_NATIVE
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
    Классы редактируемы, рост библиотеки = 0 правок схемы; `description` отдаётся в
    сериализации Item. Синк делает `get_or_create` по `code` на лету (новый класс
    всплывает с сырым описанием, юзер правит).

    Волна 19, Ф10: единый интерфейс идентичности — пара `code` + `description`
    (`label` → `description`). Поле `icon` (коды Codicon) удалено: per-категорийный
    глиф отпал (различение разрешилось режимами Изделия/Компоненты), заодно снята
    протечка темы в API (Ф7)."""

    code = models.CharField('код', max_length=64, unique=True)
    description = models.CharField('описание', max_length=128)

    class Meta:
        verbose_name = 'категория'
        verbose_name_plural = 'категории'
        ordering = ['code']

    def __str__(self):
        return self.description or self.code


class Item(models.Model):
    """Изделие — единица справочника (абстракция: КД/datasheet). Едина для
    приборов, компонентов и материалов. Класс — `category` (FK-справочник).

    Три ортогональных бул-оси (волна 19, Ф3a), каждая — самостоятельный смысл:
    - `native`  — наше авторское / внешнее покупное (замена `produced`, волна 15).
      Делит справочник на режимы «Изделия» (native) / «Компоненты» (not native);
      прилагательное-свойство, ⟂ category.
    - `synced`  — из библиотеки компонентов / заведено руками. Ставит СИНК, руками
      не снять. У библиотечного правится только цена (см. `update_item`).
    - `locked`  — ФИКСАЦИЯ (та же ось, что у `StockDocument`): форма read-only,
      мутации гейтятся в движке. Слабее, чем у документов: только заморозка, без
      арифметики. Библиотечное (`synced`) **не запирается** (свои две оси защиты
      взаимоисключающи — см. второй инвариант): новое рождается `locked=False`, а
      синк, помечая существующее `synced`, снимает стухший замок.

    Инварианты (`CheckConstraint` ниже):
    - `synced ⟹ not native` (библиотека = библиотека *компонентов*; наше производимое
      в неё не попадает);
    - `synced ⟹ not locked` (библиотечное защищено матрицей «правь только цену», а не
      замком; две оси защиты взаимоисключающи, «библиотечный+зафиксирован» — невозможен).

    Ключ `code` — единый интерфейс идентичности всех сущностей (волна 19: `code` +
    `description`). Значение = канон внешней библиотеки компонентов (колонка
    `Design Item Id` = заказной PN). Прежнее имя поля `design_item_id` (Ф3b,
    2026-07-25) брали, чтобы не столкнуться с Django FK-PK аксессором `item_id`
    в рукописном JSON-API (JOURNAL 2026-07-12); `code` этой коллизии не создаёт."""

    # Порядок объявлений — канон §13.4a (Ф17): идентичность → оси/замок → якорь →
    # внешние атрибуты. Синхронно с блоком `ITEM` технической диаграммы README.
    code = models.CharField('код', max_length=128, unique=True)
    description = models.CharField('описание', max_length=255)
    native = models.BooleanField('производимое', default=False)
    locked = models.BooleanField('зафиксировано', default=False)
    synced = models.BooleanField('из библиотеки', default=False)
    # Волна 19, Ф12e: категория nullable — но обязательность не исчезла, а
    # переехала с РОЖДЕНИЯ на ФИКСАЦИЮ (тот же приём, что у `contractor`/
    # `target_item` в Ф14). Фолбэк «первая запись справочника» отвергнут: это не
    # пустота, а ложные данные, которые выглядят заполненными.
    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True,
                                 blank=True, related_name='items',
                                 verbose_name='категория')
    uom = models.CharField('ед. изм.', max_length=32, default='шт')
    temperature = models.CharField('температурный диапазон', max_length=64,
                                   blank=True, default='')
    estimated_cost = money(verbose_name='оценочная стоимость', null=True, blank=True)

    class Meta:
        verbose_name = 'изделие'
        verbose_name_plural = 'изделия'
        ordering = ['code']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(synced=False) | models.Q(native=False),
                name='item_synced_implies_not_native'),
            models.CheckConstraint(
                condition=models.Q(synced=False) | models.Q(locked=False),
                name='item_synced_implies_not_locked'),
            # Ф12e: категория обязательна у ЗАФИКСИРОВАННОГО изделия. Черновик
            # имеет право быть неполным — гейт на фиксации, а не на рождении.
            models.CheckConstraint(
                condition=models.Q(locked=False) | models.Q(category__isnull=False),
                name='item_locked_has_category'),
        ]

    def __str__(self):
        return f'{self.code} — {self.description}'


class BomLine(models.Model):
    """Строка состава изделия: parent → component (рекурсивный BOM)."""

    parent = models.ForeignKey(Item, on_delete=models.CASCADE,
                               related_name='bom_lines')
    component = models.ForeignKey(Item, on_delete=models.PROTECT,
                                  related_name='used_in')
    qty = qty(verbose_name='кол-во')

    class Meta:
        verbose_name = 'строка BOM'
        verbose_name_plural = 'строки BOM'
        constraints = [
            models.UniqueConstraint(fields=['parent', 'component'],
                                    name='bomline_uniq_parent_component'),
        ]

    def __str__(self):
        return f'{self.parent.code} ⊃ {self.component.code} ×{self.qty}'


class Counterparty(models.Model):
    """Контрагент — единая внешняя сторона документооборота (волна 13, Ф2f+).

    Свернул `Supplier` (был только поставщиком) в одну сущность: у поставки он
    поставщик, у передачи — заказчик, направление читается из **вида документа**, а
    не из свойства справочника. Закрывает отложенную симметрию «передача =
    перемещение к внешней точке» — у передачи структурный получатель, а не текст в
    строке накладной.

    **Ролей-флагов здесь нет** (снесены 2026-07-30, волна 20 Ф3): `is_supplier` /
    `is_customer` были декларацией о намерениях, которую человек обязан был
    поддерживать руками, а система тем временем знала правду из документов. Сторона
    контрагента — **факт**: есть закупки/заказы/поставки → закупочная сторона, есть
    передачи → передачная (`engine.counterparty_sides`). Пикеры больше не фильтруют
    по флагу (это прятало нужную запись), а поднимают «своих» наверх.
    """

    # Волна 19, Ф10: единый интерфейс идентичности — пара `code` + `description`
    # (`name` → `description`, + `code`). `code` вводится человеком (напр. `КОМПЭЛ`),
    # авто-фолбэка нет → `null=True, unique=True` (в MySQL несколько NULL не конфликтуют,
    # существующие контрагенты живут с пустым кодом, уникальность стережёт непустые).
    code = models.CharField('код', max_length=64, unique=True, null=True, blank=True)
    description = models.CharField('описание', max_length=255)
    inn = models.CharField('ИНН', max_length=16, blank=True, default='')

    class Meta:
        verbose_name = 'контрагент'
        verbose_name_plural = 'контрагенты'
        ordering = ['description']

    def __str__(self):
        return self.description


class Location(models.Model):
    """Место хранения. Волна 13, Ф2e — мультисклад активирован: мест может быть
    несколько (напр. «Основной склад 103» и «Место пайки 105»), движок считает
    остаток по паре `(лот, локация)`, «Перемещение» (`Relocation`) двигает лот
    между ними. Синглтон-заглушка MVP снята (справочник редактируем)."""

    code = models.CharField('код', max_length=64, unique=True)
    description = models.CharField('описание', max_length=255)
    kind = models.CharField('вид', max_length=32, blank=True, default='')

    class Meta:
        verbose_name = 'склад'
        verbose_name_plural = 'склады'
        ordering = ['code']

    def __str__(self):
        return self.description


class Project(models.Model):
    """Проект — сквозная сущность и одновременно «склад». Внутренние проекты
    (`kind`) — служебные склады-назначения (белый/серый)."""

    class Kind(models.TextChoices):
        EXTERNAL = 'external', 'Внешний (НИР/контракт)'
        INTERNAL_STOCK = 'internal_stock', 'Собственный склад (белые)'
        INTERNAL_WRITEOFF = 'internal_writeoff', 'Свободные неучтённые (серые)'

    code = models.CharField('код', max_length=64, unique=True)
    description = models.CharField('описание', max_length=255)
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
        return f'{self.code} — {self.description}'


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
    контрагентом). Охват (какие проекты обслуживает) — **вычисляемый**: это проекты её
    заказов, см. `engine.procurement_scope`."""

    # Порядок объявлений — канон §13.4a (Ф17): идентичность → замок → якори (охват,
    # контрагент) → внешние атрибуты → автор. Синхронно с блоком `PROCUREMENT` в README.
    #
    # Волна 19, Ф10: единый интерфейс идентичности — пара `code` + `description`
    # (`code` = «Нева ДЗЗ 1» в списки; вводится человеком → `null=True, unique=True`).
    # Мёртвое `note` удалено.
    code = models.CharField('код', max_length=64, unique=True, null=True, blank=True)
    description = models.CharField('описание', max_length=255, blank=True, default='')
    # Замок — общая ось `locked` (волна 19: Ф1 свела enum к draft/posted, Ф1c сделала
    # его bool): тот же замок, что у ордеров и изделия. Отмена = удаление (Р1).
    # Подпись («Зафиксирована») — забота представления, живёт во фронте.
    locked = models.BooleanField('зафиксирована', default=False)
    # Охвата-поля здесь БОЛЬШЕ НЕТ (2026-08-05). M2M `projects` (Ф13) задавал область
    # расчёта галочками — и был вторым источником правды о том же самом: проект у
    # закупки уже есть через её заказы (`Purchase.project`), и две дороги молча
    # расходились (заказ под закупкой, чей проект в охвате не отмечен, — законная и
    # никем не замеченная ситуация). Охват стал вычисляемым (`engine.procurement_scope`
    # = проекты моих заказов): задаётся тем же жестом, которым и работают — заводят
    # заказ под проект и привязывают его к закупке. Хранить нечего, значит нечему и
    # разойтись.
    # Контрагент-поставщик закупки (волна 19, Ф4) — **намерение плана**: у кого мы
    # собираемся это купить. Ф17 отменила развилку Р3: источником поставщика для
    # «Заказ → УПД» он больше НЕ является (там читается `Purchase.contractor`).
    # Наследование — копией при рождении: нарезая план в заказ, движок копирует это
    # значение в `Purchase.contractor`, дальше поля живут независимо (одна закупка
    # законно уходит нескольким поставщикам). Здесь он может быть NULL: при подсчёте
    # компонентов до контрагента ещё не дошли. `SET_NULL` (не `PROTECT`, как у заказа
    # и поставки) осознанно: закупка — план/черновик, удаление контрагента её не
    # должно ронять — поле просто опустеет.
    contractor = models.ForeignKey(Counterparty, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='procurements',
                                   verbose_name='контрагент')
    date = models.DateField('дата (начало переговоров)', null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='procurements', verbose_name='автор')

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
        return f'{self.item.code} ×{self.qty}'


class Purchase(models.Model):
    """Заказ — проектное исполнение (документальное обязательство).

    **Заказ = У КОГО купить** (волна 19, Ф17): средний уровень закупочного контура
    между планом («ЧТО купить», `Procurement`) и приёмкой («КТО привёз», `Receipt`).
    Контрагент есть у всех трёх уровней, каждый свой; ссылка наверх опциональна на
    каждом. До Ф17 контрагента у заказа не было, и «Заказ → УПД» читал его сквозь
    цепочку `purchase.procurement.contractor` (развилка Р3, **отменена**) — заказ,
    оформленный без закупки, своего поставщика физически не знал. Заодно снят платёж
    за отсутствующий nullable: `procurement` был NOT NULL, поэтому одиночный заказ
    тихо рождал закупку-пустышку (`_solo_procurement`), а список закупок прятал их
    эвристикой (`_plan_procurements`) — обе конструкции удалены.
    """

    # Порядок объявлений — канон §13.4a (Ф17): идентичность → замок → якори →
    # внешние атрибуты → автор. Синхронно с блоком `PURCHASE` в README.
    # Волна 19, Ф10: единый интерфейс идентичности — пара `code` + `description`.
    code = models.CharField('код', max_length=64, unique=True, null=True, blank=True)
    description = models.CharField('описание', max_length=255, blank=True, default='')
    # Замок — общая ось `locked` (волна 19: Ф1 + Ф1c). Мёртвые `partial`/`received`
    # убраны: «получено» — величина ВЫЧИСЛЯЕМАЯ из приходов (`_line_received`), а не
    # замок. Две оси не путать: замок (`locked`) и покрытие (▲/●/✓).
    # У заказа замок проявляется СИЛЬНО: зафиксированный заказ считается в «заказано».
    locked = models.BooleanField('зафиксирован', default=False)
    # Проект — верхний якорь всего закупочного контура (как у ордера): заказ проектный
    # по определению, поле NOT NULL.
    project = models.ForeignKey(Project, on_delete=models.PROTECT,
                                related_name='purchases', verbose_name='проект')
    # Ф17: закупка-план **опциональна** — заказ бывает и без плана (мелкая покупка,
    # срочный доп). `PROTECT` остаётся: план с живыми заказами не удаляется молча.
    procurement = models.ForeignKey(Procurement, on_delete=models.PROTECT, null=True,
                                    blank=True, related_name='purchases',
                                    verbose_name='закупка-план')
    # Ф17: контрагент заказа — у кого купили. `PROTECT` (обязательство, как у поставки).
    # Обязателен к ФИКСАЦИИ, а не к рождению (канон Ф12e/Ф14): нарезанному пеггингом
    # заказу копировать нечего, если у плана контрагента ещё нет. Держат CHECK
    # `purchase_locked_has_contractor` + прикладной гейт в `engine.lock_purchase`.
    contractor = models.ForeignKey(Counterparty, on_delete=models.PROTECT, null=True,
                                   blank=True, related_name='purchases',
                                   verbose_name='контрагент')
    date = models.DateField('дата (оформление)', null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='purchases', verbose_name='автор')

    class Meta:
        verbose_name = 'заказ'
        verbose_name_plural = 'заказы'
        constraints = [
            # Ф17: зафиксированного заказа без контрагента не существует — черновик
            # имеет право быть неполным. Тот же приём, что у `Item.category` (Ф12e)
            # и специфики ордера (Ф14).
            models.CheckConstraint(
                condition=Q(locked=False) | Q(contractor__isnull=False),
                name='purchase_locked_has_contractor'),
        ]

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
        return f'{self.item.code} ×{self.qty}'


# --------------------------------------------------------------------------- #
#  Документы-origin партий + приёмка
# --------------------------------------------------------------------------- #
class _KindManager(models.Manager):
    """Менеджер proxy-вида: сужает выборку до своего `kind` (Ф14).

    Держит иллюзию семи таблиц там, где она полезна: `Receipt.objects.filter(...)`
    по-прежнему видит только поставки, поэтому 108 обращений к `models.<Вид>.objects`
    и все per-kind функции движка пережили снос MTI без единой правки. Базовый
    менеджер (`_base_manager`) Django заводит себе сам, нефильтрованным — обратные
    связи и каскады работают поверх всей таблицы, как и должны.
    """

    def get_queryset(self):
        return super().get_queryset().filter(kind=self.model.KIND)


class Receipt(StockDocument):
    """Приход / УПД — приёмка по передаточному документу, рождает партии.

    Ф14: proxy над `StockDocument`. Своих колонок нет — `contractor` (здесь он
    поставщик) и `purchase` живут в родителе.
    """

    KIND = DocumentKind.RECEIPT

    objects = _KindManager()

    class Meta:
        proxy = True
        verbose_name = 'поставка'
        verbose_name_plural = 'поставки'

    def __str__(self):
        return f'УПД {self.number} от {self.date}'


class Kitting(StockDocument):
    """Комплектация — инструмент ведения сборки лота: списывает компоненты и
    рождает партию-прибор. Замок `locked` (фиксация рождает лот-прибор).

    Ф14: proxy над `StockDocument` (`target_item`/`qty` — в родителе).
    """

    KIND = DocumentKind.KITTING

    objects = _KindManager()

    class Meta:
        proxy = True
        verbose_name = 'комплектация'
        verbose_name_plural = 'комплектации'

    def __str__(self):
        target = self.target_item.code if self.target_item_id else '—'
        return (f'Комплектация #{self.pk} {target}'
                + (' 🔒' if self.locked else ''))


class Inventory(StockDocument):
    """Инвентаризация — рождает «найденные» партии (излишки/ре-материализация).

    Ф14: proxy — своих колонок у вида нет и не было (таблица содержала только PK).
    """

    KIND = DocumentKind.INVENTORY

    objects = _KindManager()

    class Meta:
        proxy = True
        verbose_name = 'инвентаризация'
        verbose_name_plural = 'инвентаризации'

    def __str__(self):
        return f'Инвентаризация {self.number}'


class Requisition(StockDocument):
    """Требование/отпочкование — рождает лоты в проекте-получателе из source-лота.

    Ф14: proxy — своих колонок у вида нет и не было (таблица содержала только PK).
    """

    KIND = DocumentKind.REQUISITION

    objects = _KindManager()

    class Meta:
        proxy = True
        verbose_name = 'требование'
        verbose_name_plural = 'требования'

    def __str__(self):
        return f'Требование {self.number}'


# --------------------------------------------------------------------------- #
#  Партия и движения склада
# --------------------------------------------------------------------------- #
class Lot(models.Model):
    """Партия — физическое воплощение изделия, главная учётная единица склада.
    Ровно один origin-документ (`origin` → `StockDocument`).

    Волна 19, Ф15: партия черновика существует в справочнике, но на складе не лежит
    — её `+RECEIPT` рождается фиксацией origin-документа (живой остаток до неё 0)."""

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
    # варьируются от поставки; `Item.code` — абстрактный артикул.
    # Порядок — от диаграммы (§13.4a): машинный PN, затем человеческое имя. Так же
    # идут колонки в строках формы поставки.
    part_number = models.CharField('part number', max_length=128,
                                   blank=True, default='')
    lot_name = models.CharField('название партии', max_length=255,
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
        return f'Lot#{self.pk} {self.item.code} ({self.project.code})'


class StockMovement(models.Model):
    """Движение склада — пересчитываемая проекция из документов (не журнал).
    item и project выводятся из партии; тип — из origin+знак.

    Волна 19, Ф15: проекция собирается **только по зафиксированным** ордерам —
    черновик в неё не попадает (см. `StockDocument.locked` и
    `engine.rebuild_movements`, единственного писателя этой таблицы)."""

    class Type(models.TextChoices):
        """Два типа, и оба выводятся из знака — третьего быть не может.

        Аудит-1 (Б1а-2): `RETURN` жил здесь значением, которого движок никогда не
        писал. Возврат — не отдельная природа движения, а знак: расфиксация ордера
        просто убирает его строки из проекции, а физический возврат заводится
        встречным документом и приходит в `RECEIPT`. Лишнее значение обещало
        сценарий, которого нет, — снято.
        """

        RECEIPT = 'RECEIPT', 'Приход'
        ISSUE = 'ISSUE', 'Расход'

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

    Волна 19, Ф15: строка сама по себе склад не двигает — в `StockMovement` она
    попадает, когда её документ **зафиксирован** (до того это намерение, а не факт).
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
    """Передача — только заказчикам, по накладной в рамках проекта.

    Ф14: proxy над `StockDocument`. Структурный получатель (Ф2f+) — общая колонка
    `contractor` родителя, у этого вида она читается как «заказчик». Пустой она
    бывает законно: исторические передачи получателя-сущности не имели (текст жил
    в `StockLine.display_name`).
    """

    KIND = DocumentKind.TRANSFER

    objects = _KindManager()

    class Meta:
        proxy = True
        verbose_name = 'передача'
        verbose_name_plural = 'передачи'

    def __str__(self):
        return f'Передача {self.number}'


class Writeoff(StockDocument):
    """Списание — с причиной (серый путь: → «Свободные неучтённые»).

    Ф14: proxy над `StockDocument` (`reason` — в родителе).
    """

    KIND = DocumentKind.WRITEOFF

    objects = _KindManager()

    class Meta:
        proxy = True
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
    `StockMovement`; лот меняет распределение по локациям, не тотал.

    Ф14: proxy — своих колонок у вида нет и не было (таблица содержала только PK).
    """

    KIND = DocumentKind.RELOCATION

    objects = _KindManager()

    class Meta:
        proxy = True
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

    file = models.FileField('файл', upload_to='attachments/%Y/%m/', max_length=255)
    filename = models.CharField('имя файла', max_length=255, blank=True, default='')
    # Волна 19 (Ф12a): `label` → `description` — та же пара «идентичность + описание»,
    # что у всех сущностей (Ф10). Идентичность вложения — `filename` (своего `code`
    # у файла нет), поэтому описание идёт сразу за ним.
    description = models.CharField('описание', max_length=255, blank=True, default='')
    size = models.IntegerField('размер, байт', default=0)
    # 255 — предел MIME по RFC 6838 (127+1+127). Прежние 64 казались щедрыми, пока не
    # пришёл Office: xlsx = 65 символов, docx = 71, pptx = 73 — вложение отвергалось
    # не по сути, а по длине служебной строки.
    content_type = models.CharField('тип', max_length=255, blank=True, default='')
    uploaded_at = models.DateTimeField('загружено', auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='attachments', verbose_name='загрузил')
    # владелец (exclusive arc, ровно один из шести): изделие, ордер, проект, закупка,
    # заказ или контрагент. Волна 13, Ф2b схлопнула 6 документных FK в один
    # `document` → `StockDocument` (MTI-родитель); остальные в MTI не входят и держат
    # своё поле. Все владельцы — `CASCADE`: вложение без владельца не существует
    # (физический файл при удалении владельца снимает движок, `delete_attachment`).
    item = models.ForeignKey(Item, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='attachments')
    document = models.ForeignKey(StockDocument, on_delete=models.CASCADE, null=True,
                                 blank=True, related_name='attachments',
                                 verbose_name='ордер-владелец')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True,
                                blank=True, related_name='attachments')
    procurement = models.ForeignKey(Procurement, on_delete=models.CASCADE, null=True,
                                    blank=True, related_name='attachments')
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, null=True,
                                 blank=True, related_name='attachments')
    counterparty = models.ForeignKey(Counterparty, on_delete=models.CASCADE, null=True,
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


# --------------------------------------------------------------------------- #
#  Настройки интерфейса пользователя (волна 21)
# --------------------------------------------------------------------------- #
# Слаги тем и тема по умолчанию — ЗДЕСЬ, рядом с полем: это тот же вид знания, что
# `choices` прочих сущностей, и второго списка в `engine.py` быть не должно (движок
# импортирует). Человеческих ярлыков («Тёмная») в списке нет намеренно (Р8): ярлык,
# палитра и набор CSS-файлов — знание ВЬЮ, движок про них не знает и знать не обязан.
# Слаги плоские (`dark`/`light`, а не `ide-dark`): их всего две, и слово получается
# одно на три места — слаг, файл `themes/light.css`, ярлык.
THEMES = ('dark', 'light')
DEFAULT_THEME = 'dark'


class UserProfile(models.Model):
    """Настройки интерфейса пользователя — ПРИСТАВКА к ДНК Django, а не её замена.

    Первая таблица приложения `plume`, прицепленная к чужой сущности. Кастомную модель
    пользователя вводить поздно и незачем, `localStorage` хранит состояние вью (какой
    таб открыт), а тема — свойство ЧЕЛОВЕКА: она едет за ним между машинами, и форма
    про человека обязана показывать то, что действительно про человека. Key/value-таблицы
    настроек тоже нет — это запас на будущее; одна настройка = одна колонка.

    `CASCADE` (а не `PROTECT`, как у авторства документов): профиль без пользователя
    бессмыслен. Автора мы деактивируем, а не удаляем, — здесь же удалять нечего.

    **`CheckConstraint` на `theme` сознательно НЕ ставим**, вопреки привычке продукта
    стеречь `choices` в БД (`doc_contractor_only_own_kinds` и родня). Причина: каждая
    новая тема — это набор ФАЙЛОВ ВЬЮ, и требовать под неё миграцию значит вписать вью
    в схему. Валидация живёт в движке (`engine.set_theme` отказывает на неизвестном
    слаге) — это правильный уровень.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='profile', verbose_name='пользователь')
    theme = models.CharField('тема интерфейса', max_length=32, default=DEFAULT_THEME)

    class Meta:
        verbose_name = 'профиль пользователя'
        verbose_name_plural = 'профили пользователей'

    def __str__(self):
        return f'Профиль {self.user.username}'
