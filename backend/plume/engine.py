"""Движок-СППР plume.

Чистые функции-проекции над документами (один движок на всю линзу). Ничего не
кэшируем: всё вычислимое держим свежим (данных мало, без Celery).

Волна 1:
- `rebuild_movements(lot)` — пересборка StockMovement партии из её документов.
- `lot_live_qty` / `item_available` — живые остатки.
- `project_deficit(project)` — дефицит проекта (надо − склад − заказано),
  1 уровень BOM, тройной разбор ✓/●/▲, worst-of цвет.
- `stock_map(item)` — карта остатков Item по всем складам-проектам (north-star).

Волна 2 (записываемое ядро + кокпит Kitting):
- `kitting_cockpit(kitting)` — проекция кокпита сборки: BOM 1 уровень, реальные
  (пробитые) строки + призрачные строки, покрашенные по доступности + лоты-кандидаты.
- `close_kitting` / `reopen_kitting` — рождение/снятие лота-прибора (мягкий замок).

Волна 3 (записываемый приход / УПД):
- `receipt_cockpit(receipt)` — проекция кокпита прихода: строки-лоты УПД (в модели
  отдельной ReceiptLine нет — строки прихода это его лоты) + живой остаток + сумма.
- `add/update/remove_receipt_lot`, `approve/unapprove_receipt` — рождение лотов
  (`+RECEIPT`) и мягкий замок «сверено со сканом».

Волна 4 (записываемый заказ / Purchase + связь с приходом):
- `purchase_cockpit(purchase)` — шапка + строки (заказано/поступило/остаток) + приходы;
  `create_purchase`, `add/update/remove_purchase_line`, `send/unsend/cancel/restore_purchase`.
- `set_receipt_purchase(receipt, purchase)` — связь `Receipt↔Purchase` (гашение заказа).
- `add_to_project_order(...)` — мост «дефицит → заказ» (оживляет член «заказано»).

Волна 5 (записываемая передача / Transfer — отгрузка заказчику):
- `transfer_cockpit(transfer)` — шапка накладной + строки-лоты (отдаём партию заказчику,
  `−ISSUE`) + живой остаток источника + итог; `project_available_lots(project)` — пикер
  отдаваемых лотов (live>0). `create_transfer`, `add/update/remove_transfer_line`.
- Мягкий замок «отгружено» (единый `status {draft⇄posted}`, волна 13 Ф1):
  `post_transfer`/`unpost_transfer` — под замком форма read-only; снятие ничего не
  разрушает (guard по потомкам не нужен). `item_shipments(item)` — отгруженные партии
  изделия для его экрана (замыкает петлю `комплектация → передача`).

Волна 6 (закрытие проекта — сведение остатков в 0 + мягкий замок):
- `writeoff_cockpit` / `create_writeoff` / `add|update|remove_writeoff_line` — списание
  (`−ISSUE`, лот покидает учёт; серый путь). `requisition_cockpit` / `create_requisition`
  / `add|update|remove_requisition_line` — требование/отпочкование (`−ISSUE` источника +
  рождение лота-потомка в проекте-получателе, `+RECEIPT`; белый путь / заём).
- `project_closure(project)` — панель сведения остаточных лотов (live≠0) в 0 +
  готовность; `close_project`/`reopen_project` — мягкий замок статуса (active↔closed).
- Мосты панели: `writeoff_lot` (списать остаток) / `requisition_lot` (на баланс → белый).

Волна 7 (планирование закупок — командный свод + записываемый Procurement):
- `command_deficit()` — свод по оси Item через все активные внешние проекты
  (`Σ` проектных дефицитов, без перенеттинга между проектами). Витрина.
- `procurement_cockpit` / `create_procurement` / `add|update|remove_procurement_line`
  / `send|unsend|cancel|restore_procurement` — записываемый план закупки (без проекта,
  маркер командной высоты; мягкий замок `draft→sent`). Нарезка на `Purchase` — волна 8.
- `add_to_procurement(...)` — мост «свод → закупка»; `procurement_xlsx(...)` — `order.xlsx`.

Волна 8 (pegging — нарезка плана на проектные заказы):
- `procurement_pegging(proc)` — проекция: по строке плана пегнуто/остаток/статус +
  распределение по проектам (наводка из `command_deficit`) + веер проектных `Purchase`.
- `peg_procurement_line` / `unpeg_procurement_line` / `autopeg_procurement` — раскладка
  строки плана в проектные заказы под **этим** планом-родителем (ломает 1:1-заглушку
  `_solo_procurement`: план теперь родитель веера `Purchase`, а не только своих строк).

Волна 10 (бюджет/экономия — north-star окупаемости линзы):
- `project_budget(project)` — проекция денег проекта: **потрачено** (факт по
  `Receipt`-лотам, заём/свои бесплатны, только покупные) + **план** (прогноз «факт
  где есть, оценка где нет» через `estimated_cost`) + компас `budget − план` +
  позиции без оценки; **себестоимость** (Σ снимков лотов-приборов верхних целей,
  заём по реальной цене) + **экономия** = себестоимость − потрачено. Чистая витрина.

Волна 13 Ф2e (мультисклад + перемещение):
- Остаток по паре `(лот, локация)`: `lot_live_qty(lot, location)` / `item_available(…,
  location)` / `available_lots(…, location)` (опциональный фильтр, по умолчанию — тотал,
  байт-в-байт), `lot_locations(lot)` — разбивка по местам; `stock_map` несёт аддитивный
  `by_location`.
- Перемещение (`Relocation`): `create_relocation` / `relocation_cockpit` / `add|update|
  remove_relocation_line` (пара знаковых `StockLine` `−q`@источник/`+q`@приёмник на ход,
  тотал лота сохранён) / `post|unpost_relocation` / `relocation_source_lots` (пикер с
  разбивкой по местам). HTTP/React — следующим заходом («вьюхи потом»).

Следующие волны: логин-экран, UI вложений (`Attachment`).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from . import models

ZERO = Decimal('0')


# --------------------------------------------------------------------------- #
#  Категории изделий (волна 15) — канон внешней библиотеки компонентов
# --------------------------------------------------------------------------- #
# Стем имени CSV-файла → (рус. label, Codicon). Синк и сид зовут `ensure_category`;
# неизвестный стем всплывает с label=code (сырой — юзер правит в аппе/админке).
# Стартовый набор — только эти 5 (прочие классы прибор/крепёж/деталь юзер добавит сам).
LIBRARY_CATEGORIES = {
    'capacitors': ('Конденсаторы', 'symbol-constant'),
    'mcu':        ('Микроконтроллеры', 'chip'),
    'regulators': ('Стабилизаторы', 'settings'),
    'sensors':    ('Датчики', 'broadcast'),
    'interfaces': ('Интерфейсы', 'plug'),
}


def ensure_category(code):
    """get_or_create категории по стему CSV-файла. Канон label/icon — из
    `LIBRARY_CATEGORIES`; неизвестный код всплывает с сырым `label=code`. Существующую
    (юзер уже правил label/icon) НЕ перезаписываем."""
    code = (code or '').strip()
    label, icon = LIBRARY_CATEGORIES.get(code, (code, ''))
    cat, _ = models.Category.objects.get_or_create(
        code=code, defaults={'label': label, 'icon': icon})
    return cat


# --------------------------------------------------------------------------- #
#  Единый мягкий замок складского документа (волна 13, Ф1)
# --------------------------------------------------------------------------- #
def _require_draft(doc):
    """Единый guard правки: документ должен быть в черновике (замок снят).

    Свернул разнородные `_require_wip`/`_require_unapproved`/`_require_unposted` —
    один мягкий замок `status {draft⇄posted}` на всех ордерах. posted = edit-freeze.
    """
    if doc.is_posted:
        raise ValidationError('Документ проведён (замок) — снимите замок для правки.')


def _require_header(doc):
    """Гейт полноты шапки на проведении — условная валидация специфики по виду
    (волна 13, Ф2d). Единый kind-driven источник правила живёт на модели
    (`StockDocument.clean` + `REQUIRED_HEADER_BY_KIND`); проведение не выпускает
    неполный ордер независимо от пути его создания (API/админ/прямой ORM)."""
    doc.clean()


def post_document(doc, rows, empty_msg):
    """Поставить единый мягкий замок `draft → posted` (edit-freeze формы).

    `rows` — менеджер строк документа (`doc.lots` для born-only, `doc.lines` для
    расходных): нельзя провести пустой документ. Склад не гейтит (замок
    интерфейсный) — зеркалит `approve_receipt`/`post_transfer`.
    """
    if not rows.exists():
        raise ValidationError(empty_msg)
    _require_header(doc)
    doc.status = models.DocStatus.POSTED
    doc.save(update_fields=['status'])
    return doc


def unpost_document(doc):
    """Снять единый мягкий замок `posted → draft`. Ничего не разрушает (строки и
    их движения остаются) — guard по потомкам не нужен (в отличие от переоткрытия
    комплектации, где снимается рождённый лот-прибор)."""
    doc.status = models.DocStatus.DRAFT
    doc.save(update_fields=['status'])
    return doc


def delete_stock_document(doc):
    """Удалить складской ордер (отмена = удаление, канон В13 Ф1 — не копим надгробия).

    Правило удаления (единое на 6 ордеров):
    - **posted** — «сперва расфиксировать» (снять замок): удаляем только черновик;
    - **draft** — свободно, но `PROTECT` бережёт потраченные лоты: если рождённый
      документом лот (`doc.lots`, born-direct) уже потреблён/передан/отпочкован ниже
      — дружелюбный отказ вместо сырого `ProtectedError`.

    Механика (обходит грабли CHECK `lot_exactly_one_origin`, см. JOURNAL Ф1a): born-лоты
    и их движения сносим **явно** (как `reopen_kitting`), затем документ (каскад
    расходных `StockLine` + вложений), затем пересобираем движения лотов-источников
    (снять их `−ISSUE`). Файлы вложений чистим отдельно — каскад БД их бы осиротил.
    """
    if doc.is_posted:
        raise ValidationError(
            'Документ проведён (замок) — сперва снимите замок (расфиксируйте) для удаления.')
    born = list(doc.lots.all()) if hasattr(doc, 'lots') else []
    for lot in born:
        if _lot_consumed_downstream(lot):
            raise ValidationError(
                'Рождённый документом лот уже потреблён/передан ниже — '
                'удаление заблокировано (сперва снимите потребление).')
    # лоты-источники расходных строк — их движения пересобрать после каскада строк
    source_lots = ({sl.lot for sl in doc.lines.select_related('lot')}
                   if hasattr(doc, 'lines') else set())
    source_lots -= set(born)                       # born сносим сами, не пересобираем
    for att in doc.attachments.all():              # физические файлы (каскад их сиротит)
        delete_attachment(att)
    for lot in born:                               # явный снос born (обход CHECK-грабли)
        lot.movements.all().delete()
        lot.delete()
    doc.delete()                                   # каскад: StockLine + строки-вложения
    for lot in source_lots:                        # снять −ISSUE удалённых строк
        rebuild_movements(lot)


# Совместимость наружу: комплектация исторически отдавала `wip`/`closed` (фронт
# волны 2 читает эти строки). До фронт-среза (Ф1b) проецируем единый статус в старые
# значения — контракт API байт-в-байт (дисциплина «вьюхи потом»).
_KITTING_STATUS_COMPAT = {
    models.DocStatus.DRAFT: 'wip',
    models.DocStatus.POSTED: 'closed',
}


def _kitting_status_out(kitting):
    return _KITTING_STATUS_COMPAT[kitting.status]


# --------------------------------------------------------------------------- #
#  Склад: пересборка движений и живые остатки
# --------------------------------------------------------------------------- #
def _main_location():
    """Дом приходного движения. В MVP — один «Основной склад» (код MAIN)."""
    loc = models.Location.objects.filter(code='MAIN').first()
    return loc or models.Location.objects.order_by('id').first()


def rebuild_movements(lot):
    """Пересобрать StockMovement партии из её документов (чистая пересборка).

    origin-`+RECEIPT` берёт рождённое количество из `Lot.qty`; расходные `ISSUE`
    выводятся из строк-потребителей, ссылающихся на партию.
    """
    lot.movements.all().delete()
    main = _main_location()
    rows = []

    # origin: рождение партии (+). Дуга схлопнута в один FK (Ф2b): вид и id берём
    # из родителя `StockDocument` (`kind` == прежнее имя origin-FK; id == прежнему).
    if lot.origin_id and lot.qty:
        rows.append(models.StockMovement(
            lot=lot, location=main, type=models.StockMovement.Type.RECEIPT,
            qty=lot.qty, source_type=lot.origin.kind, source_id=lot.origin_id,
        ))

    # движение существующего лота: единые знаковые строки `StockLine` (волна 13, Ф0)
    # свернули 4 таблицы строк-расхода (комплектация/передача/списание/отпочкование).
    # `StockLine.qty` уже со знаком (− расход); source_type/id — из документа-владельца
    # (`document.kind`/id; дуга схлопнута в один FK в Ф2b). Статус документа склад НЕ
    # гейтит (замок чисто интерфейсный); отмена = удаление документа (каскад строк+лотов).
    for sl in lot.stock_lines.select_related('location', 'document'):
        rows.append(models.StockMovement(
            lot=lot, location=sl.location,
            type=(models.StockMovement.Type.RECEIPT if sl.qty > 0
                  else models.StockMovement.Type.ISSUE),
            qty=sl.qty, source_type=sl.document.kind, source_id=sl.document_id,
        ))

    models.StockMovement.objects.bulk_create(rows)
    return rows


def rebuild_all():
    """Пересобрать движения для всех партий (сид/тесты/детектор дрейфа)."""
    for lot in models.Lot.objects.all():
        rebuild_movements(lot)


def lot_live_qty(lot, location=None):
    """Живой остаток партии = сумма её движений (Lot.qty + Σ расход).

    Волна 13, Ф2e (мультисклад): опциональный `location` сужает до остатка партии
    **в этом месте хранения** (пара `(лот, локация)`). По умолчанию (None) — тотал по
    всем локациям, как раньше (перемещение `−q/+q` его сохраняет — двигает лишь
    распределение). Может быть отрицательным (недостача) — не клампим.
    """
    qs = lot.movements.all()
    if location is not None:
        qs = qs.filter(location=location)
    return qs.aggregate(s=Sum('qty'))['s'] or ZERO


def lot_locations(lot):
    """Разбивка остатка партии по местам хранения (волна 13, Ф2e).

    Возвращает строки `{location_id, code, name, qty}` с ненулевым остатком —
    «где физически лежит этот лот». Тотал строк == `lot_live_qty(lot)`.
    """
    rows = []
    agg = (lot.movements.values('location').annotate(q=Sum('qty'))
           .order_by('location'))
    loc_ids = [r['location'] for r in agg if r['q']]
    locs = {loc.id: loc for loc in models.Location.objects.filter(id__in=loc_ids)}
    for r in agg:
        if not r['q']:
            continue
        loc = locs.get(r['location'])
        rows.append({
            'location_id': r['location'],
            'code': loc.code if loc else '', 'name': loc.name if loc else '',
            'qty': r['q'],
        })
    return rows


# ── Место хранения как сущность (волна 13 Ф4): что лежит на складе + правка ДНК ──
def location_stock(location):
    """Лоты с живым остатком > 0 на данном месте хранения (В13 Ф4).

    Инверсия `lot_locations` («где лежит лот») → «что лежит на этом складе», с
    проектом-владельцем каждого лота (проект — свойство лота, живёт всю жизнь).
    Агрегат движений `(лот)` на этой локации; отрицательные/нулевые прячем —
    показываем физически присутствующее.
    """
    agg = (models.StockMovement.objects.filter(location=location)
           .values('lot').annotate(q=Sum('qty')).order_by('lot'))
    lot_ids = [r['lot'] for r in agg if r['q'] and r['q'] > 0]
    lots = {lot.id: lot for lot in models.Lot.objects
            .filter(id__in=lot_ids).select_related('item', 'project')}
    rows = []
    for r in agg:
        if not r['q'] or r['q'] <= 0:
            continue
        lot = lots.get(r['lot'])
        if lot is None:
            continue
        rows.append({
            'lot_id': lot.id, 'lot_label': _lot_label(lot),
            'part_number': lot.part_number, 'lot_name': lot.lot_name,
            'item_id': lot.item_id, 'item_design_item_id': lot.item.design_item_id,
            'item_description': lot.item.description, 'uom': lot.item.uom, 'qty': r['q'],
            'project_id': lot.project_id, 'project_code': lot.project.code,
            'project_name': lot.project.name,
        })
    return rows


def location_cockpit(location):
    """Проекция экрана склада: ДНК (код/название/вид) + что на нём лежит."""
    return {
        'id': location.id, 'code': location.code, 'name': location.name,
        'kind': location.kind, 'stock': location_stock(location),
    }


def create_location(code, name, kind=''):
    """Завести место хранения (В13 Ф4). Код уникален (дружелюбная проверка до IntegrityError)."""
    code = (code or '').strip()
    name = (name or '').strip()
    if not code:
        raise ValidationError('Нужен код места хранения.')
    if not name:
        raise ValidationError('Нужно название места хранения.')
    if models.Location.objects.filter(code=code).exists():
        raise ValidationError('Место с таким кодом уже есть.')
    return models.Location.objects.create(code=code, name=name, kind=(kind or '').strip())


def update_location(location, code=None, name=None, kind=None):
    """Правка ДНК места хранения (В13 Ф4) — мутабельная, под интерфейсным замком.
    Часовые `None` (поле не передано); пустой код/название отклоняем."""
    if code is not None:
        code = code.strip()
        if not code:
            raise ValidationError('Код места хранения обязателен.')
        if models.Location.objects.filter(code=code).exclude(pk=location.pk).exists():
            raise ValidationError('Место с таким кодом уже есть.')
        location.code = code
    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError('Название места хранения обязательно.')
        location.name = name
    if kind is not None:
        location.kind = kind.strip()
    location.save()
    return location


def delete_location(location):
    """Удалить склад (WAVE14 Ф2). Домен: склад с движениями бережём — friendly-guard.
    Ссылки — движения (`StockMovement`) и строки движения (`StockLine`), обе PROTECT;
    пустой справочный склад сносим свободно."""
    if (models.StockMovement.objects.filter(location=location).exists()
            or models.StockLine.objects.filter(location=location).exists()):
        raise ValidationError('На складе есть движения — удаление заблокировано.')
    try:
        location.delete()
    except ProtectedError:
        raise ValidationError('Склад связан с движениями — удаление заблокировано.')


def item_available(item, project, location=None):
    """Доступный остаток Item в проекте — Σ живых остатков своих лотов.

    Волна 13, Ф2e: опциональный `location` сужает до остатка в этом месте хранения.
    Может быть отрицательным (недостача) — не клампим, это информативно.
    """
    qs = models.StockMovement.objects.filter(lot__item=item, lot__project=project)
    if location is not None:
        qs = qs.filter(location=location)
    return qs.aggregate(s=Sum('qty'))['s'] or ZERO


def item_has_negative_lot(item, project):
    """Есть ли лот Item в проекте с отрицательным остатком (аномалия «подбей лоты»)."""
    for lot in models.Lot.objects.filter(item=item, project=project):
        if lot_live_qty(lot) < 0:
            return True
    return False


# --------------------------------------------------------------------------- #
#  «Заказано» (оранжевый член): открытый заказ или wip-комплектация
# --------------------------------------------------------------------------- #
def _line_received(line):
    """Поступило по строке заказа = Σ Lot.qty лотов её item по связанным приходам.

    Документ = УПД правда: поступившее — приход (`+RECEIPT` через `Receipt.purchase`),
    не текущий остаток (получили 100 → спаяли 40 → заказ закрыт на 100).
    """
    return models.Lot.objects.filter(
        item=line.item, origin__receipt__purchase=line.purchase,
    ).aggregate(s=Sum('qty'))['s'] or ZERO


def _purchased_on_order(item, project):
    """Σ max(0, PurchaseLine.qty − поступившее) по открытым (sent) заказам проекта."""
    total = ZERO
    lines = models.PurchaseLine.objects.filter(
        item=item, purchase__project=project,
        purchase__status=models.Purchase.Status.SENT,
    ).select_related('purchase')
    for line in lines:
        total += max(ZERO, line.qty - _line_received(line))
    return total


def _manufactured_in_progress(item, project):
    """Σ кол-во в производимых draft-комплектациях, делающих этот Item в проекте."""
    agg = models.Kitting.objects.filter(
        target_item=item, project=project, status=models.DocStatus.DRAFT,
    ).aggregate(s=Sum('qty'))
    return agg['s'] or ZERO


def item_on_order(item, project):
    """Оранжевый член, обобщённый по типу Item (покупной/производимый)."""
    if item.produced:
        return _manufactured_in_progress(item, project)
    return _purchased_on_order(item, project)


# --------------------------------------------------------------------------- #
#  Тройной разбор строки и цвет
# --------------------------------------------------------------------------- #
def _coverage(need, available, on_order):
    """Разложить потребность на ✓ есть · ● заказано · ▲ заказать (сегменты)."""
    have = min(need, max(ZERO, available))
    ordered = min(need - have, max(ZERO, on_order))
    to_order = need - have - ordered
    if to_order > 0:
        status = 'to_order'      # ▲ красный — нужна работа
    elif ordered > 0:
        status = 'on_order'      # ● оранжевый — запущен процесс, ждём
    else:
        status = 'available'     # ✓ зелёный — покрыто складом
    return {
        'need': need, 'have': have, 'on_order': ordered, 'to_order': to_order,
        'status': status,
    }


_WORST_RANK = {'to_order': 3, 'on_order': 2, 'available': 1}


def _worst_of(statuses):
    """Цвет шапки = худший из присутствующих статусов строк."""
    if not statuses:
        return 'available'
    return max(statuses, key=lambda s: _WORST_RANK[s])


def _best_of(statuses):
    """Бейдж = лучший достигнутый прогресс (для инвертированного цвета прибора)."""
    if not statuses:
        return 'available'
    return min(statuses, key=lambda s: _WORST_RANK[s])


# --------------------------------------------------------------------------- #
#  Дефицит проекта (главная проекция волны 1)
# --------------------------------------------------------------------------- #
def project_deficit(project):
    """Дефицит проекта: по каждой потребности — прибор и его компоненты (1 уровень).

    Возвращает структуру, готовую к сериализации (Decimal → строки на уровне DRF).
    """
    demands = []
    # Свод потребности по компонентам на весь проект (секция «Потребность»):
    # need по компоненту = Σ(bl.qty × demand.qty) по всем приборам. Склад/заказано —
    # общие по компоненту в проекте (не per-demand), считаем один раз ниже.
    need_by_component = {}      # component → суммарная потребность (Decimal)
    for demand in project.demands.select_related('target_item'):
        target = demand.target_item
        lines = []
        statuses = []
        for bl in target.bom_lines.select_related('component'):
            component = bl.component
            need = bl.qty * demand.qty
            need_by_component[component] = need_by_component.get(component, ZERO) + need
            available = item_available(component, project)
            on_order = item_on_order(component, project)
            cov = _coverage(need, available, on_order)
            cov.update({
                'component_id': component.id,
                'component_design_item_id': component.design_item_id,
                'component_description': component.description,
                'uom': component.uom,
                'available_raw': available,        # сырой остаток (может быть < 0)
                'anomaly': item_has_negative_lot(component, project),
            })
            lines.append(cov)
            statuses.append(cov['status'])

        # триплет прибора: готово (проведённые лоты) / делается (draft) / не начато
        done = models.StockMovement.objects.filter(
            lot__item=target, lot__project=project,
            lot__origin__kind=models.StockDocument.Kind.KITTING,
            lot__origin__status=models.DocStatus.POSTED,
        ).aggregate(s=Sum('qty'))['s'] or ZERO
        wip = _manufactured_in_progress(target, project)
        not_started = max(ZERO, demand.qty - done - wip)

        demands.append({
            'demand_id': demand.id,
            'target_id': target.id,
            'target_design_item_id': target.design_item_id,
            'target_description': target.description,
            'qty': demand.qty,
            'device': {'done': done, 'wip': wip, 'not_started': not_started},
            # цвет прибора: worst-of строк (внимание) + бейдж лучшего прогресса
            'status': _worst_of(statuses),
            'badge': _best_of(statuses),
            'lines': lines,
        })

    # Сводная таблица по компонентам (полная картина проекта, всегда видна).
    components = []
    for component, need in need_by_component.items():
        available = item_available(component, project)
        on_order = item_on_order(component, project)
        cov = _coverage(need, available, on_order)
        cov.update({
            'component_id': component.id,
            'component_design_item_id': component.design_item_id,
            'component_description': component.description,
            'uom': component.uom,
            'available_raw': available,
            'anomaly': item_has_negative_lot(component, project),
        })
        components.append(cov)
    # «Горит вперёд»: сначала ▲ к заказу, затем ● в пути, затем ✓; внутри — по коду.
    components.sort(key=lambda c: (-_WORST_RANK[c['status']], c['component_design_item_id']))

    return {
        'project_id': project.id,
        'project_code': project.code,
        'project_name': project.name,
        'demands': demands,
        'components': components,
    }


# --------------------------------------------------------------------------- #
#  Бюджет проекта: два числа денег + себестоимость/экономия (north-star окупаемости)
# --------------------------------------------------------------------------- #
def _project_spent(project):
    """Потрачено (факт) = Σ(unit_cost×qty) приходных (`Receipt`) лотов проекта.

    Точная застывшая цифра «кэша ФЛС». Заёмные/свои бесплатные лоты (origin
    requisition/inventory/kitting) сюда не входят → бесплатны в бюджете (платил
    источник). Только покупные материалы — снимок цены собранного узла (лот-прибор
    из Kitting) в бюджет не складываем (иначе двойной счёт).
    """
    total = ZERO
    for lot in project.lots.filter(origin__kind=models.StockDocument.Kind.RECEIPT):
        total += lot.qty * lot.unit_cost
    return total


def _project_estimate(project):
    """Прогнозная стоимость ещё-не-полученного покупного материала (по estimated_cost).

    Потребность агрегируем по компоненту (1 уровень BOM, как `project_deficit`),
    затем один разбор `_coverage` на компонент. Оцениваем «в пути + к заказу»
    (● заказано + ▲ заказать) — то, что ещё потребует денег; ✓ уже покрыто (склад
    приходной = в «потрачено», заём = бесплатно). Возвращает
    `(estimate, unestimated_codes)` — сумма оценки и коды покупных позиций без
    `estimated_cost` (план по ним неполон, не молчим 0).
    """
    need_by_item = {}
    for demand in project.demands.select_related('target_item'):
        for bl in demand.target_item.bom_lines.select_related('component'):
            need_by_item[bl.component] = (
                need_by_item.get(bl.component, ZERO) + bl.qty * demand.qty
            )

    estimate = ZERO
    unestimated = []
    for component, need in need_by_item.items():
        if component.produced:
            continue  # снимок себестоимости узла считаем отдельно, не в деньгах бюджета
        cov = _coverage(need, item_available(component, project),
                        item_on_order(component, project))
        remaining = cov['on_order'] + cov['to_order']
        if remaining <= 0:
            continue
        if component.estimated_cost is None:
            unestimated.append(component.design_item_id)
            continue
        estimate += remaining * component.estimated_cost
    return estimate, unestimated


def _project_cost(project):
    """Себестоимость проекта = Σ(qty×снимок) по лотам-приборам закрытых комплектаций,
    чьё изделие — цель потребности проекта (только верхние приборы, без задвоения
    подсборок: их цена уже в снимке верхнего прибора).

    Снимок `unit_cost` лота-прибора взят на закрытии (`_device_unit_cost`) и включает
    заёмные компоненты по реальной цене (Requisition-лот наследует цену предка) —
    честная цена для КП.
    """
    targets = {d.target_item_id for d in project.demands.all()}
    if not targets:
        return ZERO
    total = ZERO
    lots = project.lots.filter(
        origin__kind=models.StockDocument.Kind.KITTING,
        origin__status=models.DocStatus.POSTED, item_id__in=targets,
    )
    for lot in lots:
        total += lot.qty * lot.unit_cost
    return total


def project_budget(project):
    """Проекция бюджета проекта (north-star окупаемости линзы).

    Два числа денег (не путать): **потрачено** (факт по `Receipt`-лотам) и **план**
    (прогноз «факт где есть, оценка где нет»). Компас `budget − план` = запас/
    перерасход. **Себестоимость** (честная цена, заём по реальной цене) и **экономия**
    = себестоимость − потрачено (оцифрованная польза внутреннего заёма = польза PLM).
    """
    spent = _project_spent(project)
    estimate, unestimated = _project_estimate(project)
    plan = spent + estimate
    cost = _project_cost(project)
    budget = project.budget
    return {
        'project_id': project.id,
        'project_code': project.code,
        'project_name': project.name,
        'budget': budget,                       # может быть None
        'spent': spent,                         # потрачено (факт)
        'plan': plan,                           # прогноз полной стоимости
        'compass': (budget - plan) if budget is not None else None,
        'unestimated': unestimated,             # покупные позиции без оценки
        'cost': cost,                           # себестоимость (для КП)
        'economy': cost - spent,                # экономия = польза заёма
    }


# --------------------------------------------------------------------------- #
#  Карта остатков по складам-проектам (north-star)
# --------------------------------------------------------------------------- #
def stock_map(item):
    """Где этот Item лежит по всем складам-проектам, с доступным qty.

    Переносит знание «у кого что есть» из головы в БД. Авто-зачёта между
    проектами нет — это справка для решения «что закупить».
    """
    rows = []
    project_ids = models.Lot.objects.filter(item=item).values_list(
        'project_id', flat=True).distinct()
    for pid in project_ids:
        project = models.Project.objects.get(id=pid)
        available = item_available(item, project)
        if available == 0:
            continue
        # Волна 13, Ф2e (мультисклад): аддитивная разбивка остатка проекта по местам
        # хранения (пары `(лот, локация)` свёрнуты по локации). Ключ новый — фронт его
        # пока игнорирует (вьюхи потом); строки с нулём не показываем.
        loc_agg = (models.StockMovement.objects
                   .filter(lot__item=item, lot__project=project)
                   .values('location', 'location__code', 'location__name')
                   .annotate(q=Sum('qty')).order_by('location'))
        by_location = [
            {'location_id': r['location'], 'code': r['location__code'],
             'name': r['location__name'], 'available': r['q']}
            for r in loc_agg if r['q']
        ]
        rows.append({
            'project_id': project.id,
            'project_code': project.code,
            'project_name': project.name,
            'project_kind': project.kind,
            'available': available,
            'by_location': by_location,
        })
    # подсказка-порядок: белый → серый — мягкая сортировка по виду, потом по коду
    kind_rank = {
        models.Project.Kind.INTERNAL_STOCK: 0,
        models.Project.Kind.EXTERNAL: 1,
        models.Project.Kind.INTERNAL_WRITEOFF: 2,
    }
    rows.sort(key=lambda r: (kind_rank.get(r['project_kind'], 1), r['project_code']))
    return {
        'item_id': item.id,
        'item_design_item_id': item.design_item_id,
        'item_description': item.description,
        'uom': item.uom,
        'rows': rows,
    }


# --------------------------------------------------------------------------- #
#  Кокпит комплектации (волна 2): реальные строки + призрачные строки
# --------------------------------------------------------------------------- #
def available_lots(item, project, location=None):
    """Лоты item в проекте с живым остатком > 0 — кандидаты под пайку.

    Волна 13, Ф2e: опциональный `location` сужает до лотов с остатком > 0 **в этом
    месте хранения** (пикер под конкретную локацию). По умолчанию — как раньше
    (остаток по всем локациям), контракт кокпита комплектации байт-в-байт.
    """
    result = []
    for lot in models.Lot.objects.filter(item=item, project=project).select_related('item'):
        live = lot_live_qty(lot, location)
        if live > 0:
            result.append({
                'lot_id': lot.id, 'live_qty': live, 'unit_cost': lot.unit_cost,
                'part_number': lot.part_number,
                'origin': lot.origin_kind, 'lot_name': lot.lot_name,
            })
    return result


def kitting_cockpit(kitting):
    """Проекция кокпита сборки (1 уровень BOM целевого прибора).

    Каждая строка BOM: `надо = bom.qty × kitting.qty`, пробитые `KittingLine`
    (реальные зелёные строки) и остаток → **призрачная строка**, покрашенная по
    доступности компонента в проекте (`_coverage`, тот же словарь ✓/●/▲) с лотами-
    кандидатами под пайку. Ничего не хранит — чистая проекция.
    """
    target = kitting.target_item
    project = kitting.project
    rows = []
    statuses = []
    is_wip = kitting.status == models.DocStatus.DRAFT
    for bl in target.bom_lines.select_related('component'):
        component = bl.component
        need = bl.qty * kitting.qty
        real_lines = []
        pierced = ZERO
        # компонент строки выводится из lot.item (StockLine его не хранит);
        # qty знаковый — наружу отдаём магнитуду (положительную), проекция без изменений.
        for kl in kitting.lines.filter(lot__item=component).select_related('lot'):
            mag = -kl.qty
            pierced += mag
            real_lines.append({
                'id': kl.id, 'lot_id': kl.lot_id,
                'lot_label': f'#{kl.lot_id} {kl.lot.lot_name or component.design_item_id}',
                'qty': mag, 'date': kl.date,
            })
        remaining = max(ZERO, need - pierced)
        ghost = None
        if remaining > 0 and is_wip:
            cov = _coverage(remaining, item_available(component, project),
                            item_on_order(component, project))
            ghost = {
                'status': cov['status'], 'have': cov['have'],
                'on_order': cov['on_order'], 'to_order': cov['to_order'],
                'candidate_lots': available_lots(component, project),
            }
            statuses.append(cov['status'])
        rows.append({
            'component_id': component.id, 'component_design_item_id': component.design_item_id,
            'component_description': component.description, 'uom': component.uom,
            'need': need, 'pierced': pierced, 'remaining': remaining,
            'real_lines': real_lines, 'ghost': ghost,
        })
    born_lots = [
        {'id': lot.id, 'qty': lot.qty, 'unit_cost': lot.unit_cost,
         'lot_name': lot.lot_name, 'part_number': lot.part_number}
        for lot in kitting.lots.all()
    ]
    return {
        'id': kitting.id, **_author(kitting), 'status': _kitting_status_out(kitting),
        'project_id': project.id, 'project_code': project.code,
        'target_id': target.id, 'target_design_item_id': target.design_item_id,
        'target_description': target.description, 'uom': target.uom,
        'qty': kitting.qty, 'date': kitting.date,
        'cockpit_status': _worst_of(statuses),   # worst-of призрачных строк
        'rows': rows,
        'born_lots': born_lots,   # рождённые лоты-приборы (после закрытия)
    }


# --------------------------------------------------------------------------- #
#  Мутации кокпита (единый источник правил + пересборка проекции склада)
# --------------------------------------------------------------------------- #
def add_kitting_line(kitting, component, lot, qty, location=None, date=None):
    """Пайка: промоушн призрачной строки в реальную `KittingLine` + `-ISSUE`."""
    _require_draft(kitting)
    if lot.item_id != component.id:
        raise ValidationError('Лот не соответствует компоненту строки.')
    if lot.project_id != kitting.project_id:
        raise ValidationError('Лот из другого проекта (заём — отдельным требованием).')
    if qty is None or qty <= 0:
        raise ValidationError('Количество пайки должно быть положительным.')
    line = models.StockLine.objects.create(
        document=kitting, lot=lot,
        location=location or _main_location(), qty=-qty, date=date,
    )
    rebuild_movements(lot)
    return line


def update_kitting_line(line, qty):
    """Автосейв количества пайки (правка провизорной строки до замка)."""
    _require_draft(line.document)
    if qty is None or qty <= 0:
        raise ValidationError('Количество пайки должно быть положительным.')
    line.qty = -qty                      # знаковая строка (− расход)
    line.save(update_fields=['qty'])
    rebuild_movements(line.lot)


def remove_kitting_line(line):
    """Удалить пробитую строку (коррекция до замка) + пересобрать движения лота."""
    _require_draft(line.document)
    lot = line.lot
    line.delete()
    rebuild_movements(lot)


def _device_unit_cost(kitting):
    """Снимок себестоимости прибора на закрытии = Σ(qty×цена лотов) / кол-во."""
    total = ZERO
    for kl in kitting.lines.select_related('lot'):
        total += -kl.qty * kl.lot.unit_cost     # qty знаковый (− расход) → магнитуда
    if kitting.qty and kitting.qty != ZERO:
        return (total / kitting.qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return ZERO


def close_kitting(kitting):
    """Закрыть комплектацию: рождается лот-прибор (`+RECEIPT`), `draft → posted`."""
    _require_draft(kitting)
    if kitting.lots.exists():
        raise ValidationError('У комплектации уже есть рождённый лот-прибор.')
    lot = models.Lot.objects.create(
        item=kitting.target_item, project=kitting.project, origin=kitting,
        qty=kitting.qty, unit_cost=_device_unit_cost(kitting),
    )
    kitting.status = models.DocStatus.POSTED
    kitting.save(update_fields=['status'])
    rebuild_movements(lot)
    return lot


def reopen_kitting(kitting):
    """Переоткрыть проведённую комплектацию: снять лот-прибор, `posted → draft`.

    Guard: лот-прибор не должен быть потреблён/передан/отпочкован ниже.
    """
    if not kitting.is_posted:
        raise ValidationError('Переоткрыть можно только проведённую комплектацию.')
    for lot in kitting.lots.all():
        if _lot_consumed_downstream(lot):
            raise ValidationError(
                'Лот-прибор уже потреблён/передан ниже — переоткрытие заблокировано.')
    for lot in kitting.lots.all():
        lot.movements.all().delete()
        lot.delete()
    kitting.status = models.DocStatus.DRAFT
    kitting.save(update_fields=['status'])


# --------------------------------------------------------------------------- #
#  Кокпит прихода / УПД (волна 3): строки-лоты, рождение +RECEIPT, мягкий замок
# --------------------------------------------------------------------------- #
def _lot_consumed_downstream(lot):
    """Потреблён ли лот ниже: расход/пайка/передача/списание/отпочкование/успех.

    Общий guard: до `PROTECT`-ошибки БД даём дружелюбный отказ на разрушающую
    правку (удаление строки прихода, переоткрытие комплектации).
    """
    return (lot.movements.filter(qty__lt=0).exists() or lot.successors.exists()
            or lot.stock_lines.exists())


def receipt_cockpit(receipt):
    """Проекция кокпита прихода: шапка УПД + строки-лоты (каждая строка = Lot).

    В модели отдельной `ReceiptLine` нет — строки прихода это его лоты. Каждый лот
    показывает рождённое кол-во, живой остаток (просел ли под пайку), цену и
    название из УПД. Ничего не хранит — чистая проекция.
    """
    lots = []
    total = ZERO
    for lot in receipt.lots.select_related('item').order_by('id'):
        total += lot.qty * lot.unit_cost
        lots.append({
            'id': lot.id, 'item_id': lot.item_id, 'item_design_item_id': lot.item.design_item_id,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'qty': lot.qty, 'live_qty': lot_live_qty(lot),
            'unit_cost': lot.unit_cost, 'lot_name': lot.lot_name,
            'part_number': lot.part_number,
            'consumed': _lot_consumed_downstream(lot),
        })
    return {
        'id': receipt.id, **_author(receipt), 'number': receipt.number, 'date': receipt.date,
        'contractor_id': receipt.contractor_id,
        'contractor_name': receipt.contractor.name,
        'project_id': receipt.project_id, 'project_code': receipt.project.code,
        'project_name': receipt.project.name,
        'purchase_id': receipt.purchase_id,   # связанный заказ (закрытие строк)
        'approved': receipt.is_posted, 'total_cost': total,
        'lots': lots,
    }


def add_receipt_lot(receipt, item, qty, unit_cost=ZERO, lot_name='',
                    part_number=''):
    """Добавить строку УПД: рождается партия (`+RECEIPT`) в проекте прихода."""
    _require_draft(receipt)
    if qty is None or qty <= 0:
        raise ValidationError('Количество прихода должно быть положительным.')
    if unit_cost is not None and unit_cost < 0:
        raise ValidationError('Цена не может быть отрицательной.')
    lot = models.Lot.objects.create(
        item=item, project=receipt.project, origin=receipt, qty=qty,
        unit_cost=unit_cost or ZERO, lot_name=lot_name or '',
        part_number=part_number or '',
    )
    rebuild_movements(lot)
    return lot


def update_receipt_lot(lot, qty=None, unit_cost=None, lot_name=None,
                       part_number=None):
    """Автосейв строки УПД (кол-во/цена/название/PN). Правка до замка.

    Кол-во не клампим по потреблению: уронить ниже списанного можно — живой остаток
    уйдёт в минус (недостача информативнее, в духе мутабельной ДНК).
    """
    _require_draft(lot.origin)
    fields = []
    if qty is not None:
        if qty <= 0:
            raise ValidationError('Количество прихода должно быть положительным.')
        lot.qty = qty
        fields.append('qty')
    if unit_cost is not None:
        if unit_cost < 0:
            raise ValidationError('Цена не может быть отрицательной.')
        lot.unit_cost = unit_cost
        fields.append('unit_cost')
    if lot_name is not None:
        lot.lot_name = lot_name
        fields.append('lot_name')
    if part_number is not None:
        lot.part_number = part_number
        fields.append('part_number')
    if fields:
        lot.save(update_fields=fields)
        rebuild_movements(lot)
    return lot


def remove_receipt_lot(lot):
    """Удалить строку УПД (до замка). Guard: лот не потреблён ниже."""
    _require_draft(lot.origin)
    if _lot_consumed_downstream(lot):
        raise ValidationError(
            'Партия уже потреблена ниже (пайка/передача) — удаление заблокировано.')
    lot.movements.all().delete()
    lot.delete()


def approve_receipt(receipt):
    """Поставить замок «сверено со сканом» — форма прихода становится read-only."""
    if not receipt.lots.exists():
        raise ValidationError('Нельзя сверить пустой приход — добавьте строку.')
    _require_header(receipt)
    receipt.status = models.DocStatus.POSTED
    receipt.save(update_fields=['status'])
    return receipt


def unapprove_receipt(receipt):
    """Снять замок — снова разрешить правку. Ничего не разрушает (в отличие от
    переоткрытия комплектации), поэтому guard по потомкам не нужен."""
    receipt.status = models.DocStatus.DRAFT
    receipt.save(update_fields=['status'])
    return receipt


def set_receipt_purchase(receipt, purchase):
    """Связать приход с заказом (гасит строки заказа) или отвязать (`None`).

    Один заказ закрывается одним/несколькими приходами через `Receipt.purchase`.
    Приход закрывает только заказ **своего проекта** (чистота «один УПД ↔ один проект»).
    Лоты не двигает — `rebuild_movements` не нужен; на «заказано» влияет через
    `_line_received` (проекция).
    """
    if purchase is not None and purchase.project_id != receipt.project_id:
        raise ValidationError(
            'Заказ другого проекта — приход закрывает только заказ своего проекта.')
    receipt.purchase = purchase
    receipt.save(update_fields=['purchase'])
    return receipt


# --------------------------------------------------------------------------- #
#  Кокпит заказа / Purchase (волна 4): строки-обязательства + гашение приходом
# --------------------------------------------------------------------------- #
def _solo_procurement(user):
    """Тонкий draft-`Procurement` под одиночный проектный заказ.

    `Purchase.procurement` — обязательный FK, но командный свод отложен: пока каждый
    проектный заказ получает свою закупку-родителя (вырожденный 1:1). Будущая
    командная волна введёт общие Procurement, веерно нарезаемые на проектные Purchase.
    """
    return models.Procurement.objects.create(
        user=user, status=models.Procurement.Status.DRAFT,
        note='авто (проектный заказ)')


def create_purchase(project, user, date=None, note=''):
    """Создать заказ проекта (черновик) с авто-`Procurement`-родителем."""
    proc = _solo_procurement(user)
    return models.Purchase.objects.create(
        procurement=proc, project=project, user=user,
        status=models.Purchase.Status.DRAFT, date=date, note=note or '')


def purchase_cockpit(purchase):
    """Проекция кокпита заказа: шапка + строки (заказано/поступило/остаток) + приходы.

    Закрытость строки красится тем же словарём ✓/●/▲, что дефицит/кокпиты:
    получено полностью → ✓ (available), частично → ● (on_order), ничего → ▲ (to_order).
    Статусы `partial`/`received` не храним — это вычисляемая закрытость. Ничего не
    хранит (чистая проекция).
    """
    is_draft = purchase.status == models.Purchase.Status.DRAFT
    rows = []
    statuses = []
    total_ordered = ZERO
    total_received = ZERO
    for line in purchase.lines.select_related('item').order_by('id'):
        received = _line_received(line)
        remaining = max(ZERO, line.qty - received)
        total_ordered += line.qty
        total_received += received
        if line.qty > 0 and received >= line.qty:
            st = 'available'      # ✓ получено полностью
        elif received > 0:
            st = 'on_order'       # ● частично получено
        else:
            st = 'to_order'       # ▲ ждём поставки
        statuses.append(st)
        rows.append({
            'id': line.id, 'item_id': line.item_id, 'item_design_item_id': line.item.design_item_id,
            'item_description': line.item.description, 'uom': line.item.uom,
            'qty': line.qty, 'received': received, 'remaining': remaining,
            'status': st,
        })
    receipts = [
        {'id': r.id, 'number': r.number, 'date': r.date,
         'contractor_name': r.contractor.name, 'lines': r.lots.count()}
        for r in purchase.receipts.select_related('contractor').order_by('id')
    ]
    return {
        'id': purchase.id, **_author(purchase), 'status': purchase.status,
        'project_id': purchase.project_id, 'project_code': purchase.project.code,
        'project_name': purchase.project.name,
        'procurement_id': purchase.procurement_id,   # якорь #A: закупка-план (Ф2k)
        'date': purchase.date, 'note': purchase.note,
        'editable': is_draft,                       # строки правятся только в черновике
        'cockpit_status': _worst_of(statuses),      # worst-of закрытости строк
        'total_ordered': total_ordered, 'total_received': total_received,
        'rows': rows, 'receipts': receipts,
    }


def _require_purchase_draft(purchase):
    if purchase.status != models.Purchase.Status.DRAFT:
        raise ValidationError(
            'Строки правятся только в черновике заказа — снимите отправку (unsend).')


def add_purchase_line(purchase, item, qty):
    """Добавить строку заказа (только в черновике). `(purchase, item)` уникальна."""
    _require_purchase_draft(purchase)
    if qty is None or qty <= 0:
        raise ValidationError('Количество заказа должно быть положительным.')
    if purchase.lines.filter(item=item).exists():
        raise ValidationError(
            f'Изделие {item.design_item_id} уже в заказе — правьте существующую строку.')
    return models.PurchaseLine.objects.create(purchase=purchase, item=item, qty=qty)


def update_purchase_line(line, qty):
    """Автосейв количества строки заказа (только в черновике)."""
    _require_purchase_draft(line.purchase)
    if qty is None or qty <= 0:
        raise ValidationError('Количество заказа должно быть положительным.')
    line.qty = qty
    line.save(update_fields=['qty'])
    return line


def remove_purchase_line(line):
    """Удалить строку заказа (только в черновике)."""
    _require_purchase_draft(line.purchase)
    line.delete()


def send_purchase(purchase):
    """Отправить заказ (`draft → sent`) — мягкий замок: теперь считается в «заказано»,
    строки становятся read-only. Снятие (`unsend`) ничего не разрушает."""
    if purchase.status == models.Purchase.Status.CANCELLED:
        raise ValidationError('Отменённый заказ нельзя отправить — восстановите его.')
    if not purchase.lines.exists():
        raise ValidationError('Нельзя отправить пустой заказ — добавьте строку.')
    purchase.status = models.Purchase.Status.SENT
    purchase.save(update_fields=['status'])
    return purchase


def unsend_purchase(purchase):
    """Вернуть заказ в черновик (`sent → draft`). Purchase лотов не рождает —
    снятие обязательства ничего не разрушает (связанные приходы остаются, заказ
    просто выходит из счёта «заказано»), guard по потомкам не нужен."""
    purchase.status = models.Purchase.Status.DRAFT
    purchase.save(update_fields=['status'])
    return purchase


def cancel_purchase(purchase):
    """Отменить заказ — выводит из счёта «заказано» (не удаляет)."""
    purchase.status = models.Purchase.Status.CANCELLED
    purchase.save(update_fields=['status'])
    return purchase


def restore_purchase(purchase):
    """Восстановить отменённый заказ в черновик."""
    purchase.status = models.Purchase.Status.DRAFT
    purchase.save(update_fields=['status'])
    return purchase


def delete_purchase(purchase):
    """Удалить заказ (WAVE14 Ф2). Мягкий замок как у ордеров: отправленный/полученный
    сперва вернуть в черновик (снять отправку); привязанный приход (`Receipt.purchase`,
    SET_NULL) держит — иначе удаление молча обнулило бы ссылку у поставок. Строки
    заказа (`PurchaseLine`) — каскад."""
    if purchase.status not in (models.Purchase.Status.DRAFT,
                               models.Purchase.Status.CANCELLED):
        raise ValidationError(
            'Заказ отправлен — сперва верните его в черновик (снимите отправку), затем удаляйте.')
    if purchase.receipts.exists():
        raise ValidationError('К заказу привязаны поставки (приход) — удаление заблокировано.')
    try:
        purchase.delete()                          # каскад: строки заказа
    except ProtectedError:
        raise ValidationError('Заказ связан с другими записями — удаление заблокировано.')


def add_to_project_order(project, item, qty, user):
    """Мост «дефицит → заказ»: положить позицию в draft-заказ проекта.

    Находит последний черновик-заказ проекта (или создаёт новый с авто-`Procurement`)
    и добавляет строку; если строка item уже есть — инкрементит её `qty`. Возвращает
    заказ (UI ведёт в кокпит). Оживляет ▲-член «заказано» дашборда дефицита.
    """
    if qty is None or qty <= 0:
        raise ValidationError('Количество должно быть положительным.')
    purchase = (project.purchases.filter(status=models.Purchase.Status.DRAFT)
                .order_by('-id').first())
    if purchase is None:
        purchase = create_purchase(project, user)
    line = purchase.lines.filter(item=item).first()
    if line:
        line.qty = line.qty + qty
        line.save(update_fields=['qty'])
    else:
        models.PurchaseLine.objects.create(purchase=purchase, item=item, qty=qty)
    return purchase


# --------------------------------------------------------------------------- #
#  Кокпит передачи / Transfer (волна 5): отдаём партию заказчику (−ISSUE)
# --------------------------------------------------------------------------- #
def project_available_lots(project):
    """Лоты проекта с живым остатком > 0 — кандидаты на отгрузку заказчику.

    Пикер строки передачи: любой лот проекта, где ещё что-то лежит (обычно
    готовое железо — приборы из комплектации, но модель не ограничивает).
    """
    result = []
    for lot in (models.Lot.objects.filter(project=project)
                .select_related('item').order_by('item__design_item_id', 'id')):
        live = lot_live_qty(lot)
        if live > 0:
            result.append({
                'lot_id': lot.id, 'item_id': lot.item_id,
                'item_design_item_id': lot.item.design_item_id, 'item_description': lot.item.description,
                'uom': lot.item.uom, 'live_qty': live, 'origin': lot.origin_kind,
                'part_number': lot.part_number,
                'lot_name': lot.lot_name,
            })
    return result


def _lot_label(lot):
    """Человекочитаемая метка лота для накладной/строки (название / PN / артикул)."""
    tail = lot.lot_name or lot.part_number or lot.item.design_item_id
    return f'#{lot.id} {tail}'


def _author(doc):
    """Автор документа для проекции кокпита (Ф2j): id + человеческое имя (для
    пикера авторства в шапке формы). `user` NOT NULL на всех ордерах/закупках."""
    u = doc.user
    if u is None:                        # страховка на легаси-строки
        return {'user_id': None, 'user_name': ''}
    return {'user_id': u.id, 'user_name': u.get_full_name() or u.get_username()}


def transfer_cockpit(transfer):
    """Проекция кокпита передачи: шапка накладной + строки-лоты + итог.

    Каждая строка отдаёт партию заказчику (`−ISSUE`); показываем живой остаток
    источника (просел ли под передачу, не ушёл ли в минус). Ничего не хранит.
    """
    lines = []
    total_qty = ZERO
    for line in transfer.lines.select_related('lot__item').order_by('id'):
        lot = line.lot
        mag = -line.qty                       # знаковая строка (− расход) → магнитуда
        total_qty += mag
        lines.append({
            'id': line.id, 'lot_id': lot.id,
            'lot_label': _lot_label(lot),
            'item_id': lot.item_id, 'item_design_item_id': lot.item.design_item_id,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'qty': mag, 'display_name': line.display_name,
            'lot_live_qty': lot_live_qty(lot),   # остаток источника после отгрузки
            'lot_name': lot.lot_name,
        })
    return {
        'id': transfer.id, **_author(transfer), 'number': transfer.number, 'date': transfer.date,
        'contractor_id': transfer.contractor_id,
        'contractor_name': transfer.contractor.name if transfer.contractor_id else '',
        'project_id': transfer.project_id, 'project_code': transfer.project.code,
        'project_name': transfer.project.name, 'posted': transfer.is_posted,
        'total_qty': total_qty, 'lines': lines,
    }


def item_shipments(item):
    """Отгруженные партии изделия — где и по какой накладной ушло заказчику.

    Read-only проекция для экрана изделия: строки передач его лотов (замыкает
    петлю `комплектация → передача`). Порядок — свежие сверху.
    """
    rows = []
    for line in (models.StockLine.objects
                 .filter(document__kind=models.StockDocument.Kind.TRANSFER,
                         lot__item=item)
                 .select_related('document__transfer__project', 'lot')
                 .order_by('-document__transfer__date', '-id')):
        t = line.document.transfer
        rows.append({
            'transfer_id': t.id, 'number': t.number, 'date': t.date,
            'project_code': t.project.code, 'posted': t.is_posted,
            'lot_id': line.lot_id, 'qty': -line.qty,     # знаковый → магнитуда
            'display_name': line.display_name,
            'lot_name': line.lot.lot_name,
        })
    return rows


def create_transfer(project, user, number, date=None, contractor=None):
    """Создать передачу (накладную) проекта. Строки добавляются в кокпите.

    `Transfer.date` не nullable — пустую дату замыкаем на сегодня. `contractor` —
    контрагент-заказчик (опционален: получатель может быть проставлен позже в кокпите).
    """
    if not (number or '').strip():
        raise ValidationError('Нужен № накладной.')
    return models.Transfer.objects.create(
        project=project, user=user, number=number.strip(),
        date=date or timezone.localdate(), contractor=contractor)


def add_transfer_line(transfer, lot, qty, display_name=''):
    """Отгрузить партию заказчику: строка передачи (`−ISSUE` на лоте).

    Лот — того же проекта (передаём своё, чужое — через требование). Кол-во не
    клампим по остатку: переотдать можно, лот уйдёт в минус (недостача информативна,
    в духе мутабельной ДНК).
    """
    _require_draft(transfer)
    if lot.project_id != transfer.project_id:
        raise ValidationError('Лот из другого проекта — передаём только своё.')
    if qty is None or qty <= 0:
        raise ValidationError('Количество передачи должно быть положительным.')
    line = models.StockLine.objects.create(
        document=transfer, lot=lot, location=_main_location(), qty=-qty,
        display_name=(display_name or '').strip() or _lot_label(lot))
    rebuild_movements(lot)
    return line


def update_transfer_line(line, qty=None, display_name=None):
    """Автосейв строки передачи (кол-во / отображаемое имя для накладной)."""
    _require_draft(line.document)
    fields = []
    if qty is not None:
        if qty <= 0:
            raise ValidationError('Количество передачи должно быть положительным.')
        line.qty = -qty                   # знаковая строка (− расход)
        fields.append('qty')
    if display_name is not None:
        line.display_name = display_name
        fields.append('display_name')
    if fields:
        line.save(update_fields=fields)
        if 'qty' in fields:
            rebuild_movements(line.lot)
    return line


def remove_transfer_line(line):
    """Убрать строку передачи (коррекция) — источник возвращает остаток."""
    _require_draft(line.document)
    lot = line.lot
    line.delete()
    rebuild_movements(lot)


def post_transfer(transfer):
    """Поставить замок «отгружено» — накладная становится read-only (зеркалит
    `approve_receipt`). Сюда позже ляжет подписанная накладная (Attachment)."""
    if not transfer.lines.exists():
        raise ValidationError('Нельзя отгрузить пустую накладную — добавьте строку.')
    _require_header(transfer)
    transfer.status = models.DocStatus.POSTED
    transfer.save(update_fields=['status'])
    return transfer


def unpost_transfer(transfer):
    """Снять замок — снова разрешить правку. Ничего не разрушает (строки и их
    `−ISSUE` остаются), поэтому guard по потомкам не нужен."""
    transfer.status = models.DocStatus.DRAFT
    transfer.save(update_fields=['status'])
    return transfer


# --------------------------------------------------------------------------- #
#  Закрытие проекта (волна 6): списание / требование + панель + мягкий замок
# --------------------------------------------------------------------------- #
def _internal_project(kind):
    """Найти-или-создать внутренний проект-склад (белый/серый) — синглтон.

    Целевая «куча» для постановки на баланс (белый «Собственный склад») —
    `INTERNAL_KINDS` синглтоны (см. `Project.clean`), сид их заводит; здесь мягко
    добираем, чтобы движок был робастен и в голой БД/тестах.
    """
    proj = models.Project.objects.filter(kind=kind).first()
    if proj is not None:
        return proj
    code, name = {
        models.Project.Kind.INTERNAL_STOCK: ('WHITE', 'Собственный склад'),
        models.Project.Kind.INTERNAL_WRITEOFF: ('GREY', 'Свободные неучтённые'),
    }[kind]
    return models.Project.objects.create(
        code=code, name=name, kind=kind, status=models.Project.Status.ACTIVE)


def _auto_number(prefix, project):
    """Авто-№ документа для мостов панели (акт списания/требование одним кликом)."""
    return f'{prefix}-{project.code}-{timezone.localdate():%Y%m%d}'


def all_available_lots():
    """Лоты всех проектов с живым остатком > 0 — пикер источника требования.

    Требование тянет из любого проекта (постановка своего на баланс, заём у
    соседнего активного) — поэтому пикер сквозной, с кодом проекта-источника.
    """
    result = []
    for lot in (models.Lot.objects.select_related('item', 'project')
                .order_by('project__code', 'item__design_item_id', 'id')):
        live = lot_live_qty(lot)
        if live > 0:
            result.append({
                'lot_id': lot.id, 'item_id': lot.item_id,
                'item_design_item_id': lot.item.design_item_id, 'item_description': lot.item.description,
                'uom': lot.item.uom, 'live_qty': live, 'origin': lot.origin_kind,
                'project_id': lot.project_id, 'project_code': lot.project.code,
                'part_number': lot.part_number,
                'lot_name': lot.lot_name,
            })
    return result


# ── Списание / Writeoff (серый путь: чистый −ISSUE, лот покидает учёт) ──
def writeoff_cockpit(writeoff):
    """Проекция кокпита списания: шапка акта + строки-лоты (`−ISSUE`) + итог.

    Списание — чистое выбытие из проекта (born-лота нет, `Writeoff` не origin);
    «в серый склад» — конвенция учёта, ре-материализация серых остатков — актом
    `Inventory` (следующая волна). Живой остаток источника показываем — просел ли.
    """
    lines = []
    total_qty = ZERO
    for line in writeoff.lines.select_related('lot__item').order_by('id'):
        lot = line.lot
        mag = -line.qty                       # знаковая строка (− расход) → магнитуда
        total_qty += mag
        lines.append({
            'id': line.id, 'lot_id': lot.id, 'lot_label': _lot_label(lot),
            'item_id': lot.item_id, 'item_design_item_id': lot.item.design_item_id,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'qty': mag, 'lot_live_qty': lot_live_qty(lot),
            'lot_name': lot.lot_name,
        })
    return {
        'id': writeoff.id, **_author(writeoff), 'number': writeoff.number, 'date': writeoff.date,
        'reason': writeoff.reason,
        'project_id': writeoff.project_id, 'project_code': writeoff.project.code,
        'project_name': writeoff.project.name, 'posted': writeoff.is_posted,
        'total_qty': total_qty, 'lines': lines,
    }


def create_writeoff(project, user, number, date=None, reason=''):
    """Создать акт списания проекта. Строки добавляются в кокпите."""
    if not (number or '').strip():
        raise ValidationError('Нужен № акта списания.')
    return models.Writeoff.objects.create(
        project=project, user=user, number=number.strip(),
        date=date or timezone.localdate(), reason=(reason or '').strip())


def add_writeoff_line(writeoff, lot, qty, location=None):
    """Списать партию из проекта: строка списания (`−ISSUE` на лоте).

    Списываем только своё (`lot.project == writeoff.project`). Кол-во не клампим по
    остатку (как приход/передача): пересписать можно, лот уйдёт в минус — недостача
    информативнее нуля (мутабельная ДНК).
    """
    _require_draft(writeoff)
    if lot.project_id != writeoff.project_id:
        raise ValidationError('Лот из другого проекта — списываем только своё.')
    if qty is None or qty <= 0:
        raise ValidationError('Количество списания должно быть положительным.')
    line = models.StockLine.objects.create(
        document=writeoff, lot=lot, location=location or _main_location(), qty=-qty)
    rebuild_movements(lot)
    return line


def update_writeoff_line(line, qty):
    """Автосейв количества строки списания. Только черновик (замок)."""
    _require_draft(line.document)
    if qty is None or qty <= 0:
        raise ValidationError('Количество списания должно быть положительным.')
    line.qty = -qty                      # знаковая строка (− расход)
    line.save(update_fields=['qty'])
    rebuild_movements(line.lot)
    return line


def remove_writeoff_line(line):
    """Убрать строку списания (коррекция) — источник возвращает остаток."""
    _require_draft(line.document)
    lot = line.lot
    line.delete()
    rebuild_movements(lot)


def post_writeoff(writeoff):
    """Провести списание (замок «списано», форма read-only)."""
    return post_document(writeoff, writeoff.lines,
                         'Нельзя провести пустой акт списания — добавьте строку.')


def unpost_writeoff(writeoff):
    """Снять замок списания — снова разрешить правку."""
    return unpost_document(writeoff)


# ── Требование / Requisition (белый путь: −ISSUE источника + рождение потомка) ──
def _requisition_born_lot(requisition, source_lot):
    """Порождённый требованием лот-потомок источника (пара строки).

    Один источник = одна строка (guard в `add_requisition_line`), поэтому пара
    `(requisition, predecessor)` однозначна.
    """
    return requisition.lots.filter(predecessor=source_lot,
                                   item=source_lot.item).first()


def requisition_cockpit(requisition):
    """Проекция кокпита требования: шапка (проект-получатель) + строки + итог.

    Каждая строка тянет из лота-источника (`−ISSUE`) и рождает лот-потомок в
    проекте-получателе (`+RECEIPT`, наследует item/цену/провенанс через
    `predecessor`). Показываем живой остаток источника (просел ли).
    """
    lines = []
    total_qty = ZERO
    for line in (requisition.lines
                 .select_related('lot__item', 'lot__project')
                 .order_by('id')):
        src = line.lot                        # StockLine.lot = лот-источник расхода
        mag = -line.qty                       # знаковая строка (− расход) → магнитуда
        total_qty += mag
        born = _requisition_born_lot(requisition, src)
        lines.append({
            'id': line.id, 'source_lot_id': src.id, 'lot_label': _lot_label(src),
            'source_project_code': src.project.code,
            'item_id': src.item_id, 'item_design_item_id': src.item.design_item_id,
            'item_description': src.item.description, 'uom': src.item.uom,
            'qty': mag, 'source_live_qty': lot_live_qty(src),
            'born_lot_id': born.id if born else None,
            'lot_name': src.lot_name,
        })
    return {
        'id': requisition.id, **_author(requisition), 'number': requisition.number, 'date': requisition.date,
        'project_id': requisition.project_id, 'project_code': requisition.project.code,
        'project_name': requisition.project.name, 'posted': requisition.is_posted,
        'total_qty': total_qty, 'lines': lines,
    }


def create_requisition(project, user, number, date=None):
    """Создать требование в проект-получатель (`project` = куда кладём потомков)."""
    if not (number or '').strip():
        raise ValidationError('Нужен № требования.')
    return models.Requisition.objects.create(
        project=project, user=user, number=number.strip(),
        date=date or timezone.localdate())


def add_requisition_line(requisition, source_lot, qty, location=None):
    """Отпочкование: `−ISSUE` от источника + рождение лота-потомка у получателя.

    Источник — из любого проекта (постановка своего на баланс → белый, заём у
    соседнего активного B→A). Потомок наследует item/цену/название/PN источника,
    `predecessor` → источник (генеалогия/провенанс для kitting из остатков). Один
    источник = одна строка (пара строки↔потомок однозначна). Кол-во не клампим.
    """
    _require_draft(requisition)
    if qty is None or qty <= 0:
        raise ValidationError('Количество требования должно быть положительным.')
    if source_lot.project_id == requisition.project_id:
        raise ValidationError('Источник и получатель — один проект (перекладывать некуда).')
    if requisition.lines.filter(lot=source_lot).exists():
        raise ValidationError('Этот лот уже в требовании — правьте существующую строку.')
    line = models.StockLine.objects.create(
        document=requisition, lot=source_lot,
        location=location or _main_location(), qty=-qty)
    born = models.Lot.objects.create(
        item=source_lot.item, project=requisition.project, origin=requisition,
        predecessor=source_lot, qty=qty, unit_cost=source_lot.unit_cost,
        lot_name=source_lot.lot_name, part_number=source_lot.part_number)
    rebuild_movements(source_lot)   # −ISSUE у источника
    rebuild_movements(born)         # +RECEIPT у потомка
    return line


def update_requisition_line(line, qty):
    """Автосейв количества: правит и строку-источник (`−ISSUE`), и потомок (`+RECEIPT`).
    Только черновик (замок)."""
    _require_draft(line.document)
    if qty is None or qty <= 0:
        raise ValidationError('Количество требования должно быть положительным.')
    line.qty = -qty                      # знаковая строка (− расход) у источника
    line.save(update_fields=['qty'])
    born = _requisition_born_lot(line.document, line.lot)
    if born is not None:
        born.qty = qty                   # рождённый лот-потомок — положительное кол-во
        born.save(update_fields=['qty'])
        rebuild_movements(born)
    rebuild_movements(line.lot)
    return line


def remove_requisition_line(line):
    """Убрать строку требования: снять потомок + вернуть остаток источнику.

    Guard: потомок не должен быть потреблён ниже (спаян/передан/списан из белого).
    """
    _require_draft(line.document)
    src = line.lot
    born = _requisition_born_lot(line.document, src)
    if born is not None and _lot_consumed_downstream(born):
        raise ValidationError(
            'Поставленный на баланс лот уже потреблён ниже — удаление заблокировано.')
    line.delete()
    if born is not None:
        born.movements.all().delete()
        born.delete()
    rebuild_movements(src)


def post_requisition(requisition):
    """Провести требование (замок, форма read-only)."""
    return post_document(requisition, requisition.lines,
                         'Нельзя провести пустое требование — добавьте строку.')


def unpost_requisition(requisition):
    """Снять замок требования — снова разрешить правку."""
    return unpost_document(requisition)


# ── Перемещение / Relocation (мультисклад: лот между локациями внутри проекта) ──
def _relocation_pair(relocation, lot):
    """Пара знаковых строк одного хода: (источник `−q`, приёмник `+q`). Один лот =
    один ход в перемещении (guard в `add_relocation_line`), поэтому пара однозначна."""
    lines = list(relocation.lines.filter(lot=lot).select_related('location'))
    src = next((l for l in lines if l.qty < 0), None)
    dst = next((l for l in lines if l.qty > 0), None)
    return src, dst


def relocation_cockpit(relocation):
    """Проекция кокпита перемещения: шапка + ходы (лот, откуда→куда, кол-во) + итог.

    Каждый ход — пара строк (`−q`@источник, `+q`@приёмник, волна 13 Ф2e). Показываем
    остаток лота в источнике и приёмнике (пары `(лот,локация)`) — куда и сколько ушло.
    Перемещение не меняет тотал лота/проекта, только распределение по местам.
    """
    moves = []
    total_qty = ZERO
    seen = set()
    for line in relocation.lines.select_related('lot__item').order_by('id'):
        if line.lot_id in seen:
            continue
        seen.add(line.lot_id)
        lot = line.lot
        src, dst = _relocation_pair(relocation, lot)
        mag = (-src.qty) if src else (dst.qty if dst else ZERO)
        total_qty += mag
        moves.append({
            'lot_id': lot.id, 'lot_label': _lot_label(lot),
            'item_id': lot.item_id, 'item_design_item_id': lot.item.design_item_id,
            'item_description': lot.item.description, 'uom': lot.item.uom, 'qty': mag,
            'from_location_id': src.location_id if src else None,
            'from_location': src.location.code if src else '',
            'to_location_id': dst.location_id if dst else None,
            'to_location': dst.location.code if dst else '',
            'from_live_qty': lot_live_qty(lot, src.location) if src else ZERO,
            'to_live_qty': lot_live_qty(lot, dst.location) if dst else ZERO,
        })
    return {
        'id': relocation.id, **_author(relocation), 'number': relocation.number, 'date': relocation.date,
        'project_id': relocation.project_id, 'project_code': relocation.project.code,
        'project_name': relocation.project.name, 'posted': relocation.is_posted,
        'total_qty': total_qty, 'moves': moves,
    }


def create_relocation(project, user, number, date=None):
    """Создать перемещение внутри проекта (`project` — где двигаем лоты по местам)."""
    if not (number or '').strip():
        raise ValidationError('Нужен № перемещения.')
    return models.Relocation.objects.create(
        project=project, user=user, number=number.strip(),
        date=date or timezone.localdate())


def add_relocation_line(relocation, lot, qty, from_location, to_location):
    """Ход перемещения: пара знаковых строк (`−q` на источнике, `+q` на приёмнике).

    Двигаем только свой лот (`lot.project == relocation.project`) между двумя РАЗНЫМИ
    местами хранения. Один лот = один ход (правьте существующий). Кол-во не клампим по
    остатку источника (как передача/списание): пересместить можно, источник уйдёт в
    минус — недостача информативнее нуля (мутабельная ДНК). Тотал лота сохранён
    (`−q+q=0`) — двигаем распределение, не остаток.
    """
    _require_draft(relocation)
    if lot.project_id != relocation.project_id:
        raise ValidationError('Лот из другого проекта — перемещаем только своё.')
    if qty is None or qty <= 0:
        raise ValidationError('Количество перемещения должно быть положительным.')
    if from_location is None or to_location is None:
        raise ValidationError('Нужны место-источник и место-приёмник.')
    if from_location.id == to_location.id:
        raise ValidationError('Источник и приёмник — одно место (перемещать некуда).')
    if relocation.lines.filter(lot=lot).exists():
        raise ValidationError('Этот лот уже в перемещении — правьте существующий ход.')
    src = models.StockLine.objects.create(
        document=relocation, lot=lot, location=from_location, qty=-qty)
    dst = models.StockLine.objects.create(
        document=relocation, lot=lot, location=to_location, qty=qty)
    rebuild_movements(lot)
    return src, dst


def update_relocation_line(relocation, lot, qty=None, from_location=None,
                           to_location=None):
    """Автосейв хода перемещения (кол-во/места). Только черновик (замок)."""
    _require_draft(relocation)
    src, dst = _relocation_pair(relocation, lot)
    if src is None or dst is None:
        raise ValidationError('Ход перемещения не найден.')
    if qty is not None:
        if qty <= 0:
            raise ValidationError('Количество перемещения должно быть положительным.')
        src.qty = -qty
        dst.qty = qty
    if from_location is not None:
        src.location = from_location
    if to_location is not None:
        dst.location = to_location
    if src.location_id == dst.location_id:
        raise ValidationError('Источник и приёмник — одно место (перемещать некуда).')
    src.save(update_fields=['qty', 'location'])
    dst.save(update_fields=['qty', 'location'])
    rebuild_movements(lot)
    return src, dst


def remove_relocation_line(relocation, lot):
    """Убрать ход перемещения (обе строки пары) + пересобрать движения лота."""
    _require_draft(relocation)
    relocation.lines.filter(lot=lot).delete()
    rebuild_movements(lot)


def post_relocation(relocation):
    """Провести перемещение (замок, форма read-only)."""
    return post_document(relocation, relocation.lines,
                         'Нельзя провести пустое перемещение — добавьте ход.')


def unpost_relocation(relocation):
    """Снять замок перемещения — снова разрешить правку."""
    return unpost_document(relocation)


def relocation_source_lots(project):
    """Лоты проекта с живым остатком > 0 — кандидаты на перемещение, с разбивкой по
    местам хранения (`lot_locations`): пикер видит, где лот лежит и сколько."""
    result = []
    for lot in (models.Lot.objects.filter(project=project)
                .select_related('item').order_by('item__design_item_id', 'id')):
        live = lot_live_qty(lot)
        if live > 0:
            result.append({
                'lot_id': lot.id, 'item_id': lot.item_id,
                'item_design_item_id': lot.item.design_item_id, 'item_description': lot.item.description,
                'uom': lot.item.uom, 'live_qty': live,
                'part_number': lot.part_number,
                'lot_name': lot.lot_name,
                'by_location': lot_locations(lot),
            })
    return result


# ── Панель закрытия проекта + мягкий замок статуса ──
def project_closure(project):
    """Панель сведения остатков проекта к 0 + готовность к закрытию.

    Остаточные лоты (live≠0) — то, что мешает закрытию: положительные сводим в 0
    выходами (передача/списание/на баланс), отрицательные — аномалия «подбей лоты»
    (недостача, чинится правкой документа-потребителя). Закрыть можно **внешний**
    проект, когда остатков нет (внутренние склады постоянны — не закрываются).
    """
    residuals = []
    positive = ZERO
    anomaly_count = 0
    for lot in project.lots.select_related('item').order_by('item__design_item_id', 'id'):
        live = lot_live_qty(lot)
        if live == 0:
            continue
        residuals.append({
            'lot_id': lot.id, 'lot_label': _lot_label(lot),
            'item_id': lot.item_id, 'item_design_item_id': lot.item.design_item_id,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'live_qty': live, 'anomaly': live < 0,
        })
        if live > 0:
            positive += live
        else:
            anomaly_count += 1
    is_external = project.kind == models.Project.Kind.EXTERNAL
    is_closed = project.status == models.Project.Status.CLOSED
    can_close = is_external and not is_closed and not residuals
    if not is_external:
        blocker = 'Внутренний склад постоянный — не закрывается.'
    elif is_closed:
        blocker = ''
    elif residuals:
        blocker = 'Есть остаточные лоты — сведите их в 0.'
    else:
        blocker = ''
    return {
        'project_id': project.id, 'project_code': project.code,
        'project_name': project.name, 'kind': project.kind,
        'status': project.status, 'closed_at': project.closed_at,
        'is_external': is_external,
        'residuals': residuals, 'residual_positive': positive,
        'anomaly_count': anomaly_count,
        'can_close': can_close, 'blocker': blocker,
    }


def close_project(project):
    """Закрыть проект (`active → closed`) — мягкий замок-веха.

    Gate: внешний проект без остаточных лотов (всё сведено в 0). Ничего не
    разрушает — статус-веха «проект отработан», реюз/переоткрытие свободны.
    """
    if project.kind != models.Project.Kind.EXTERNAL:
        raise ValidationError('Закрывать можно только внешний проект (НИР/контракт).')
    if project.status == models.Project.Status.CLOSED:
        raise ValidationError('Проект уже закрыт.')
    if project_closure(project)['residuals']:
        raise ValidationError('Нельзя закрыть: есть остаточные лоты — сведите их в 0.')
    project.status = models.Project.Status.CLOSED
    project.closed_at = timezone.localdate()
    project.save(update_fields=['status', 'closed_at'])
    return project


def reopen_project(project):
    """Переоткрыть закрытый проект (`closed → active`). Замок ничего не разрушал."""
    if project.status != models.Project.Status.CLOSED:
        raise ValidationError('Переоткрыть можно только закрытый проект.')
    project.status = models.Project.Status.ACTIVE
    project.closed_at = None
    project.save(update_fields=['status', 'closed_at'])
    return project


# ── Мосты панели закрытия (один клик = свести остаточный лот в 0) ──
def writeoff_lot(project, lot, qty, user):
    """Мост «списать остаток»: найти-или-создать акт списания проекта + строка.

    Оживляет действие панели: один клик уводит остаток лота в 0 (`−ISSUE`).
    Переиспользует последний акт проекта (если этого лота в нём ещё нет).
    """
    if lot.project_id != project.id:
        raise ValidationError('Лот из другого проекта.')
    # Ф2c: `project` поднят в StockDocument (реверс — `project.documents`); типизированный
    # доступ через дочерний менеджер (прозрачно фильтрует по родительскому полю).
    writeoff = models.Writeoff.objects.filter(project=project).order_by('-id').first()
    if writeoff is None or writeoff.lines.filter(lot=lot).exists():
        writeoff = create_writeoff(
            project, user, _auto_number('СПИС', project), reason='закрытие проекта')
    add_writeoff_line(writeoff, lot, qty)
    return writeoff


def requisition_lot(project, lot, qty, user, dest_kind=None):
    """Мост «на баланс»: отпочковать остаток проекта в белый «Собственный склад».

    Один клик панели: остаток лота уходит в 0 у проекта (`−ISSUE`) и рождается
    лот-потомок на балансе (`+RECEIPT`). Переиспользует последнее требование в
    целевой склад (если этого источника в нём ещё нет).
    """
    if lot.project_id != project.id:
        raise ValidationError('Лот из другого проекта.')
    dest = _internal_project(dest_kind or models.Project.Kind.INTERNAL_STOCK)
    requisition = models.Requisition.objects.filter(project=dest).order_by('-id').first()
    if requisition is None or requisition.lines.filter(lot=lot).exists():
        requisition = create_requisition(dest, user, _auto_number('ТРБ', dest))
    add_requisition_line(requisition, lot, qty)
    return requisition


# --------------------------------------------------------------------------- #
#  Правка шапки кокпитов (сквозная, все документы): номер/дата/мягкие поля
# --------------------------------------------------------------------------- #
# Инлайн-правка несруктурных полей шапки прямо в кокпите (автосейв по полю,
# read-only под замком). Структурные якоря (проект/поставщик — дом лотов) не
# трогаем: их смена переселяет лоты, это отдельная операция, не инлайн.
def _apply(instance, updates):
    """Присвоить непустые поля (None → не трогаем) и сохранить изменённые."""
    fields = []
    for name, value in updates.items():
        if value is not None:
            setattr(instance, name, value)
            fields.append(name)
    if fields:
        instance.save(update_fields=fields)
    return instance


# `_require_number`/`_require_date` — фаст-фейл входного слоя правки (дружелюбно
# отклоняют попытку обнулить непустое поле в PATCH). Авторитетная per-kind политика
# обязательности живёт на модели (`StockDocument.REQUIRED_HEADER_BY_KIND`/`clean`,
# волна 13, Ф2d) и повторно гейтится на проведении (`_require_header`).
def _require_number(number):
    if number is not None and not str(number).strip():
        raise ValidationError('Номер не может быть пустым.')


def _require_date(date):
    if date is not None and not str(date).strip():
        raise ValidationError('Дата не может быть пустой.')


_UNSET = object()   # часовой «поле не передано» (отличает от «выставить None»)


def _set_author(doc, user):
    """Сменить автора документа (Ф2j) — сквозная правка шапки под замком.

    `user` — часовой: `_UNSET` → не трогаем; `User` → выставить. Автор обязателен
    (FK `StockDocument.user` NOT NULL), поэтому `None` отклоняем. Замок проверяет
    вызывающий (`update_*` уже гейтит `_require_draft`/черновик заказа)."""
    if user is _UNSET:
        return
    if user is None:
        raise ValidationError('Автор документа обязателен.')
    doc.user = user
    doc.save(update_fields=['user'])


def _set_project(doc, project):
    """Сменить проект-якорь ордера (Ф2k) — вторая связка «Свода расхождений #A».

    Проект — **якорь**: `Lot.project` выводится из ордера-origin, а строки движения
    (`StockLine`) ссылаются на лоты того же проекта (движок гейтит эту чистоту при
    добавлении). Поэтому менять якорь можно только у **пустого** ордера — без
    born-лотов (`lots`) и строк (`lines`); иначе дружелюбный отказ: сперва удалить
    зависимые. `_UNSET` → не трогаем; `None` → отказ (FK NOT NULL); тот же проект →
    ноль-оп. Замок проверяет вызывающий (`update_*` уже гейтит `_require_draft`)."""
    if project is _UNSET:
        return
    if project is None:
        raise ValidationError('Проект ордера обязателен.')
    if project.pk == doc.project_id:
        return
    if doc.lots.exists() or doc.lines.exists():
        raise ValidationError(
            'Проект — якорь ордера: лоты и строки следуют за ним. Сначала удалите '
            'строки/лоты ордера, затем меняйте проект.')
    doc.project = project
    doc.save(update_fields=['project'])


def _set_target_item(kitting, item):
    """Сменить целевое изделие комплектации (Ф2k) — якорь #A, специфичный для kitting.

    Целевое изделие определяет состав (призрачные строки BOM-потребности) и рождаемый
    прибор, поэтому менять его можно только пока у комплектации нет строк пайки
    (`lines`) и рождённого прибора (`lots`). Иначе дружелюбный отказ."""
    if item is _UNSET:
        return
    if item is None:
        raise ValidationError('Целевое изделие комплектации обязательно.')
    if item.pk == kitting.target_item_id:
        return
    if kitting.lines.exists() or kitting.lots.exists():
        raise ValidationError(
            'Целевое изделие определяет состав — сначала удалите строки пайки '
            'и рождённый прибор.')
    kitting.target_item = item
    kitting.save(update_fields=['target_item'])


def update_receipt(receipt, number=None, date=None, user=_UNSET, project=_UNSET):
    """Правка шапки прихода (№ УПД / дата / автор / проект-якорь). До замка «сверено»."""
    _require_draft(receipt)
    _require_number(number)
    _require_date(date)
    _set_author(receipt, user)
    _set_project(receipt, project)
    return _apply(receipt, {'number': number and number.strip(), 'date': date})


def update_purchase(purchase, date=None, note=None, user=_UNSET, project=_UNSET,
                    procurement=_UNSET):
    """Правка шапки заказа (дата / примечание / автор / проект / закупка). Только в черновике.

    Дата заказа nullable — пустая строка очищает её в NULL (в отличие от
    документов с обязательной датой). `project`/`procurement` — якоря #A (Ф2k):
    заказ — проектное исполнение закупки-плана. Смена проекта у заказа со связанными
    приходами ломает инвариант «УПД ↔ проект заказа» → дружелюбный отказ (сперва
    отвязать приходы). Оба поля NOT NULL → `None` отклоняем.
    """
    _require_purchase_draft(purchase)
    _set_author(purchase, user)
    fields = []
    if project is not _UNSET:
        if project is None:
            raise ValidationError('Проект заказа обязателен.')
        if project.pk != purchase.project_id and purchase.receipts.exists():
            raise ValidationError(
                'К заказу привязаны приходы (УПД ↔ проект) — сначала отвяжите их, '
                'затем меняйте проект.')
        purchase.project = project
        fields.append('project')
    if procurement is not _UNSET:
        if procurement is None:
            raise ValidationError('Закупка-план заказа обязательна.')
        purchase.procurement = procurement
        fields.append('procurement')
    if date is not None:
        purchase.date = date or None
        fields.append('date')
    if note is not None:
        purchase.note = note.strip()
        fields.append('note')
    if fields:
        purchase.save(update_fields=fields)
    return purchase


def update_transfer(transfer, number=None, date=None, contractor=_UNSET, user=_UNSET,
                    project=_UNSET):
    """Правка шапки передачи (№ накладной / дата / заказчик / автор / проект). До «отгружено».

    `contractor` — часовой: не передан → не трогаем; `Counterparty` → выставить;
    `None` → снять получателя (nullable).
    """
    _require_draft(transfer)
    _require_number(number)
    _require_date(date)
    _set_author(transfer, user)
    _set_project(transfer, project)
    if contractor is not _UNSET:
        transfer.contractor = contractor
        transfer.save(update_fields=['contractor'])
    return _apply(transfer, {'number': number and number.strip(), 'date': date})


def update_writeoff(writeoff, number=None, date=None, reason=None, user=_UNSET,
                    project=_UNSET):
    """Правка шапки списания (№ акта / дата / причина / автор / проект). Только черновик."""
    _require_draft(writeoff)
    _require_number(number)
    _require_date(date)
    _set_author(writeoff, user)
    _set_project(writeoff, project)
    return _apply(writeoff, {'number': number and number.strip(), 'date': date,
                             'reason': None if reason is None else reason.strip()})


def update_requisition(requisition, number=None, date=None, user=_UNSET, project=_UNSET):
    """Правка шапки требования (№ / дата / автор / проект-получатель). Только черновик (замок)."""
    _require_draft(requisition)
    _require_number(number)
    _require_date(date)
    _set_author(requisition, user)
    _set_project(requisition, project)
    return _apply(requisition, {'number': number and number.strip(), 'date': date})


def update_relocation(relocation, number=None, date=None, user=_UNSET, project=_UNSET):
    """Правка шапки перемещения (№ / дата / автор / проект-якорь). Только черновик (замок).

    Проект — якорь (`_set_project`): у перемещения строки-ходы ссылаются на лоты этого
    же проекта, поэтому сменить его можно лишь у пустого ордера."""
    _require_draft(relocation)
    _require_number(number)
    _require_date(date)
    _set_author(relocation, user)
    _set_project(relocation, project)
    return _apply(relocation, {'number': number and number.strip(), 'date': date})


def update_kitting(kitting, qty=None, date=None, user=_UNSET, project=_UNSET,
                   target_item=_UNSET):
    """Правка шапки комплектации (кол-во образцов / дата / автор / проект / цель). Только «в работе».

    Кол-во образцов пересчитывает потребности BOM — правится, пока `wip`. `project`/
    `target_item` — якоря #A (Ф2k): меняются только у пустой комплектации.
    """
    _require_draft(kitting)
    _set_author(kitting, user)
    _set_project(kitting, project)
    _set_target_item(kitting, target_item)
    if qty is not None and qty <= 0:
        raise ValidationError('Количество образцов должно быть положительным.')
    fields = []
    if qty is not None:
        kitting.qty = qty
        fields.append('qty')
    if date is not None:                 # дата комплектации nullable
        kitting.date = date or None
        fields.append('date')
    if fields:
        kitting.save(update_fields=fields)
    return kitting


# --------------------------------------------------------------------------- #
#  Волна 7 — планирование закупок: командный свод + записываемый Procurement
# --------------------------------------------------------------------------- #
def command_deficit():
    """Командный свод: суммарный дефицит по оси Item через все активные внешние проекты.

    Консолидация-проекция (не таблица): для каждого проекта считаем потребность по
    каждому компоненту (Σ через потребности BOM, 1 уровень) и покрываем её складом/
    заказами **этого** проекта (`_coverage`, как дефицит проекта — покрытие на уровне
    Item в проекте, агрегат), затем складываем сегменты по Item через проекты. Между
    проектами **не** перенеттим (чужие ФЛС/склады не смешиваем): профицит проекта A не
    гасит нужду проекта B. Итог по Item: `to_order` = сколько всего докупить (▲ красный
    член), `have`/`on_order` — контекст. Только внешние проекты (внутренние склады —
    источник покрытия, не потребитель). Read-only витрина.
    """
    acc = {}  # item_id → агрегат по Item через проекты
    projects = (models.Project.objects
                .filter(kind=models.Project.Kind.EXTERNAL,
                        status=models.Project.Status.ACTIVE)
                .order_by('code'))
    for project in projects:
        # потребность проекта по компоненту (Σ через потребности BOM, 1 уровень)
        need_by_item = {}
        for demand in project.demands.select_related('target_item'):
            for bl in demand.target_item.bom_lines.select_related('component'):
                need_by_item[bl.component] = (
                    need_by_item.get(bl.component, ZERO) + bl.qty * demand.qty)
        for component, need in need_by_item.items():
            cov = _coverage(need, item_available(component, project),
                            item_on_order(component, project))
            row = acc.setdefault(component.id, {
                'item_id': component.id, 'item_design_item_id': component.design_item_id,
                'item_description': component.description, 'uom': component.uom,
                'produced': component.produced,
                'need': ZERO, 'have': ZERO, 'on_order': ZERO, 'to_order': ZERO,
                'by_project': [],
            })
            row['need'] += cov['need']
            row['have'] += cov['have']
            row['on_order'] += cov['on_order']
            row['to_order'] += cov['to_order']
            row['by_project'].append({
                'project_id': project.id, 'project_code': project.code,
                'project_name': project.name, 'need': cov['need'],
                'have': cov['have'], 'on_order': cov['on_order'],
                'to_order': cov['to_order'], 'status': cov['status'],
            })
    rows = []
    for row in acc.values():
        # статус Item = тот же словарь по сегментам итога (worst-of)
        if row['to_order'] > 0:
            row['status'] = 'to_order'
        elif row['on_order'] > 0:
            row['status'] = 'on_order'
        else:
            row['status'] = 'available'
        rows.append(row)
    # худшее наверх (красное просит внимания), потом по артикулу
    rows.sort(key=lambda r: (-_WORST_RANK[r['status']], r['item_design_item_id']))
    return {'rows': rows}


def procurement_cockpit(procurement):
    """Проекция кокпита закупки-плана: шапка + строки (`item`, `qty`) + итог.

    `Procurement` в волне 7 — самостоятельный план без проекта (маркер командной
    высоты); нарезка на проектные `Purchase` (pegging) — волна 8. Мягкий замок
    `status` зеркалит заказ: строки правятся только в черновике. Чистая проекция.
    """
    is_draft = procurement.status == models.Procurement.Status.DRAFT
    rows = []
    total_qty = ZERO
    for line in procurement.lines.select_related('item').order_by('id'):
        total_qty += line.qty
        rows.append({
            'id': line.id, 'item_id': line.item_id, 'item_design_item_id': line.item.design_item_id,
            'item_description': line.item.description, 'uom': line.item.uom, 'qty': line.qty,
        })
    return {
        'id': procurement.id, **_author(procurement), 'status': procurement.status,
        'date': procurement.date, 'note': procurement.note,
        'editable': is_draft,                       # строки правятся только в черновике
        'total_qty': total_qty, 'lines': rows,
    }


def create_procurement(user, date=None, note=''):
    """Создать закупку-план (черновик) без проекта."""
    return models.Procurement.objects.create(
        user=user, status=models.Procurement.Status.DRAFT,
        date=date, note=(note or '').strip())


def _require_procurement_draft(procurement):
    if procurement.status != models.Procurement.Status.DRAFT:
        raise ValidationError(
            'Строки правятся только в черновике закупки — снимите отправку (unsend).')


def add_procurement_line(procurement, item, qty):
    """Добавить строку закупки-плана (только в черновике). `(procurement, item)` — одна строка."""
    _require_procurement_draft(procurement)
    if qty is None or qty <= 0:
        raise ValidationError('Количество закупки должно быть положительным.')
    if procurement.lines.filter(item=item).exists():
        raise ValidationError(
            f'Изделие {item.design_item_id} уже в закупке — правьте существующую строку.')
    return models.ProcurementLine.objects.create(
        procurement=procurement, item=item, qty=qty)


def update_procurement_line(line, qty):
    """Автосейв количества строки закупки-плана (только в черновике)."""
    _require_procurement_draft(line.procurement)
    if qty is None or qty <= 0:
        raise ValidationError('Количество закупки должно быть положительным.')
    line.qty = qty
    line.save(update_fields=['qty'])
    return line


def remove_procurement_line(line):
    """Удалить строку закупки-плана (только в черновике)."""
    _require_procurement_draft(line.procurement)
    line.delete()


def send_procurement(procurement):
    """Отправить закупку-план (`draft → sent`) — мягкий замок: строки read-only."""
    if procurement.status == models.Procurement.Status.CANCELLED:
        raise ValidationError('Отменённую закупку нельзя отправить — восстановите её.')
    if not procurement.lines.exists():
        raise ValidationError('Нельзя отправить пустую закупку — добавьте строку.')
    procurement.status = models.Procurement.Status.SENT
    procurement.save(update_fields=['status'])
    return procurement


def unsend_procurement(procurement):
    """Вернуть закупку-план в черновик (`sent → draft`) — ничего не разрушает."""
    procurement.status = models.Procurement.Status.DRAFT
    procurement.save(update_fields=['status'])
    return procurement


def cancel_procurement(procurement):
    """Отменить закупку-план (не удаляет)."""
    procurement.status = models.Procurement.Status.CANCELLED
    procurement.save(update_fields=['status'])
    return procurement


def restore_procurement(procurement):
    """Восстановить отменённую закупку-план в черновик."""
    procurement.status = models.Procurement.Status.DRAFT
    procurement.save(update_fields=['status'])
    return procurement


def update_procurement(procurement, date=None, note=None, user=_UNSET):
    """Правка шапки закупки-плана (дата / примечание / автор). Только в черновике.

    Дата закупки nullable — пустая строка очищает её в NULL (как заказ).
    """
    _require_procurement_draft(procurement)
    _set_author(procurement, user)
    fields = []
    if date is not None:
        procurement.date = date or None
        fields.append('date')
    if note is not None:
        procurement.note = note.strip()
        fields.append('note')
    if fields:
        procurement.save(update_fields=fields)
    return procurement


def delete_procurement(procurement):
    """Удалить закупку-план (WAVE14 Ф2). Мягкий замок: отправленную сперва вернуть в
    черновик (снять отправку); привязанные заказы (`Purchase.procurement`, PROTECT)
    держат — их сперва открепить/удалить. Строки плана (`ProcurementLine`) — каскад."""
    if procurement.status not in (models.Procurement.Status.DRAFT,
                                  models.Procurement.Status.CANCELLED):
        raise ValidationError(
            'Закупка отправлена — сперва верните её в черновик (снимите отправку), затем удаляйте.')
    if procurement.purchases.exists():
        raise ValidationError('К закупке привязаны заказы — удаление заблокировано.')
    try:
        procurement.delete()                       # каскад: строки закупки
    except ProtectedError:
        raise ValidationError('Закупка связана с другими записями — удаление заблокировано.')


def _plan_procurements():
    """Закупки-планы = `Procurement`, записанные на командной высоте (волна 7+).

    После pegging (волна 8) план становится родителем веера проектных `Purchase`, поэтому
    старый признак «нет привязанных заказов» больше не годится (пегнутый план исчезал бы
    из списка). Различаем структурно: **solo-заглушка** `_solo_procurement` (родитель
    одиночного проектного заказа, волна 4) — это `Procurement` с ≥1 `Purchase` и **без**
    строк плана (`ProcurementLine`); план же всегда либо имеет строки, либо пуст-и-без-
    заказов (свежесозданный). Отсекаем ровно заглушки — веер пегнутого плана остаётся.
    """
    return (models.Procurement.objects
            .annotate(_n_purch=Count('purchases', distinct=True),
                      _n_lines=Count('lines', distinct=True))
            .exclude(_n_purch__gt=0, _n_lines=0))


def add_to_procurement(item, qty, user):
    """Мост «командный свод → закупка»: положить позицию в draft-закупку-план.

    Находит последний черновик-план (или создаёт) и добавляет строку; если строка
    item уже есть — инкрементит `qty` (как «дефицит → заказ»). Возвращает закупку
    (UI ведёт в кокпит). Заглушки проектных заказов не трогаем (см. `_plan_procurements`).
    """
    if qty is None or qty <= 0:
        raise ValidationError('Количество должно быть положительным.')
    procurement = (_plan_procurements()
                   .filter(status=models.Procurement.Status.DRAFT)
                   .order_by('-id').first())
    if procurement is None:
        procurement = create_procurement(user)
    line = procurement.lines.filter(item=item).first()
    if line:
        line.qty = line.qty + qty
        line.save(update_fields=['qty'])
    else:
        models.ProcurementLine.objects.create(
            procurement=procurement, item=item, qty=qty)
    return procurement


def procurement_xlsx(procurement):
    """Сгенерировать `order.xlsx` закупки-плана (bytes) — файл поставщику.

    Базовый формат: артикул / наименование / кол-во / ед. Синхронно в запросе
    (файл небольшой, тяжёлых рантаймов нет). openpyxl — импорт ленивый (зависимость
    только ради экспорта).
    """
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = 'Заказ'
    headers = ['Артикул', 'Наименование', 'Кол-во', 'Ед.']
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for line in procurement.lines.select_related('item').order_by('id'):
        ws.append([line.item.design_item_id, line.item.description, float(line.qty), line.item.uom])
    widths = [22, 48, 12, 8]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = width
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
#  Волна 8 — pegging: нарезка плана (Procurement) на проектные заказы (Purchase)
# --------------------------------------------------------------------------- #
def _procurement_pegs(procurement):
    """Σ пегнутого по `(item_id, project_id)` под этим планом: `{(item, project): qty}`.

    Пег = строка проектного заказа (`PurchaseLine`), чей заказ висит на этом плане.
    Отменённые заказы (`cancelled`) не в счёте — обязательство снято.
    """
    pegs = {}
    rows = (models.PurchaseLine.objects
            .filter(purchase__procurement=procurement)
            .exclude(purchase__status=models.Purchase.Status.CANCELLED)
            .values_list('item_id', 'purchase__project_id')
            .annotate(total=Sum('qty')))
    for item_id, project_id, total in rows:
        pegs[(item_id, project_id)] = total
    return pegs


def procurement_pegging(procurement):
    """Проекция pegging: по строке плана — распределение по проектам + веер заказов.

    По каждой строке плана `(item, qty)`: сколько уже пегнуто (`pegged`), остаток плана
    (`remaining`), статус ✓/●/▲ (полностью/частично/не разложено) и разбивка по проектам
    с **наводкой** из командного свода (`command_deficit` — сколько проекту ещё докупить
    по этому Item) плюс фактически пегнутым. Внизу — веер проектных `Purchase` под этим
    планом (навигация в их кокпиты). Read-only проекция; правит peg/unpeg/autopeg.
    """
    editable = procurement.status != models.Procurement.Status.CANCELLED
    pegs = _procurement_pegs(procurement)
    suggest = {row['item_id']: row['by_project'] for row in command_deficit()['rows']}
    rows = []
    for line in procurement.lines.select_related('item').order_by('id'):
        by_project = {}
        for bp in suggest.get(line.item_id, []):     # проекты, которым ещё надо
            by_project[bp['project_id']] = {
                'project_id': bp['project_id'], 'project_code': bp['project_code'],
                'project_name': bp['project_name'],
                'suggest': bp['to_order'], 'pegged': ZERO,
            }
        for (item_id, project_id), qty in pegs.items():    # фактически пегнутое
            if item_id != line.item_id:
                continue
            slot = by_project.get(project_id)
            if slot is None:
                p = models.Project.objects.get(pk=project_id)
                slot = {'project_id': project_id, 'project_code': p.code,
                        'project_name': p.name, 'suggest': ZERO, 'pegged': ZERO}
                by_project[project_id] = slot
            slot['pegged'] = qty
        pegged_total = sum((s['pegged'] for s in by_project.values()), ZERO)
        if pegged_total <= 0:
            st = 'to_order'
        elif pegged_total >= line.qty:
            st = 'available'
        else:
            st = 'on_order'
        rows.append({
            'line_id': line.id, 'item_id': line.item_id,
            'item_design_item_id': line.item.design_item_id, 'item_description': line.item.description,
            'uom': line.item.uom, 'qty': line.qty,
            'pegged': pegged_total, 'remaining': line.qty - pegged_total, 'status': st,
            'by_project': sorted(by_project.values(), key=lambda s: s['project_code']),
        })
    fan = []
    for pu in (procurement.purchases.select_related('project')
               .order_by('project__code', 'id')):
        fan.append({
            'purchase_id': pu.id, 'status': pu.status,
            'project_id': pu.project_id, 'project_code': pu.project.code,
            'project_name': pu.project.name, 'lines': pu.lines.count(),
            'total': pu.lines.aggregate(s=Sum('qty'))['s'] or ZERO,
        })
    return {
        'id': procurement.id, 'status': procurement.status, 'editable': editable,
        'rows': rows, 'fan': fan,
    }


def _require_procurement_peggable(procurement):
    if procurement.status == models.Procurement.Status.CANCELLED:
        raise ValidationError('Отменённую закупку нельзя пегать — восстановите её.')


def _project_purchase_under(procurement, project, user):
    """Найти-или-создать **черновиковый** проектный заказ под этим планом-родителем.

    Ломает 1:1-заглушку `_solo_procurement`: заказ рождается с `procurement=<план>`
    (веер проектных обязательств висит на общем плане), а не с throwaway-родителем.
    """
    pu = (procurement.purchases
          .filter(project=project, status=models.Purchase.Status.DRAFT)
          .order_by('-id').first())
    if pu is None:
        pu = models.Purchase.objects.create(
            procurement=procurement, project=project, user=user,
            status=models.Purchase.Status.DRAFT)
    return pu


def peg_procurement_line(procurement, item, project, qty, user):
    """Пегнуть кол-во строки плана на проект: строка проектного заказа под этим планом.

    Находит-или-создаёт draft-`Purchase` проекта под планом и добавляет/инкрементит
    `PurchaseLine(item, qty)`. item — из строк плана; проект — активный внешний. Кол-во
    не клампим по остатку плана (перепегнуть можно — расхождение информативнее, в духе
    мутабельной ДНК). Возвращает план.
    """
    _require_procurement_peggable(procurement)
    if qty is None or qty <= 0:
        raise ValidationError('Количество должно быть положительным.')
    if not procurement.lines.filter(item=item).exists():
        raise ValidationError(
            f'Изделие {item.design_item_id} не в плане закупки — сначала добавьте строку плана.')
    if project.kind != models.Project.Kind.EXTERNAL:
        raise ValidationError('Пегать можно только на внешний проект (НИР/контракт).')
    if project.status != models.Project.Status.ACTIVE:
        raise ValidationError('Пегать можно только на активный проект.')
    pu = _project_purchase_under(procurement, project, user)
    line = pu.lines.filter(item=item).first()
    if line:
        line.qty = line.qty + qty
        line.save(update_fields=['qty'])
    else:
        models.PurchaseLine.objects.create(purchase=pu, item=item, qty=qty)
    return procurement


def unpeg_procurement_line(procurement, item, project):
    """Снять пег `(item, project)` под этим планом — удалить строку проектного заказа.

    Реверс пега (разложить можно всегда — разметить обратно тоже). Удаляем строку в
    черновиковых заказах проекта под планом; если пег в **отправленном** заказе —
    просим сначала снять отправку (не рушим обязательство молча). Возвращает план.
    """
    _require_procurement_peggable(procurement)
    lines = models.PurchaseLine.objects.filter(
        purchase__procurement=procurement, purchase__project=project, item=item)
    if lines.filter(purchase__status=models.Purchase.Status.SENT).exists():
        raise ValidationError(
            'Пег в отправленном заказе — снимите отправку заказа, потом снимайте пег.')
    lines.filter(purchase__status=models.Purchase.Status.DRAFT).delete()
    return procurement


def autopeg_procurement(procurement, user):
    """Разрезать план по проектам в один клик: топ-ап каждой `(item, project)` до наводки.

    По каждой строке плана и каждому проекту из наводки свода (`command_deficit`) догоняет
    пегнутое до `to_order` проекта (`delta = to_order − уже_пегнуто`, пегаем только
    положительную дельту). Идемпотентно (повтор ничего не добавит) и не трогает ручной
    перепег (delta<0 → пропуск). Возвращает план.
    """
    _require_procurement_peggable(procurement)
    suggest = {row['item_id']: row['by_project'] for row in command_deficit()['rows']}
    pegs = _procurement_pegs(procurement)
    for line in procurement.lines.select_related('item'):
        for bp in suggest.get(line.item_id, []):
            delta = bp['to_order'] - pegs.get((line.item_id, bp['project_id']), ZERO)
            if delta > 0:
                project = models.Project.objects.get(pk=bp['project_id'])
                peg_procurement_line(procurement, line.item, project, delta, user)
    return procurement


# --------------------------------------------------------------------------- #
#  Волна 9 — инвентаризация (Inventory): 4-й origin партии + серая ре-материализация
# --------------------------------------------------------------------------- #
# `Inventory` рождает «найденные» партии — излишки, всплывшие при пересчёте, и
# ре-материализацию серых остатков (списанное → −ISSUE «в серый»; найдено физически
# → возвращаем на баланс новым лотом с `predecessor` → списанный, наследуя
# item/цену/название/зав.№). Отдельной `InventoryLine` в модели нет: строки акта =
# его лоты (`inventory.lots`, как приход/УПД). Origin `inventory` несёт единый
# `Lot.origin` (Ф2b) и знает `rebuild_movements` — волна добавила записываемую надстройку.
# Замка нет (у модели нет поля-статуса, как у Writeoff/Requisition): правимо всегда,
# корректность держат guard'ы + PROTECT.
def inventory_cockpit(inventory):
    """Проекция кокпита инвентаризации: шапка акта + строки-лоты (`+RECEIPT`) + итог.

    Каждая строка — рождённый актом лот («найденная» партия): кол-во, живой остаток
    (просел ли под последующий расход), цена/название, зав.№ и провенанс
    (`predecessor` — из какого списанного лота ре-материализован). Чистая проекция.
    """
    lots = []
    total = ZERO
    for lot in (inventory.lots.select_related('item', 'predecessor__project')
                .order_by('id')):
        total += lot.qty * lot.unit_cost
        pred = lot.predecessor
        lots.append({
            'id': lot.id, 'item_id': lot.item_id, 'item_design_item_id': lot.item.design_item_id,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'qty': lot.qty, 'live_qty': lot_live_qty(lot),
            'unit_cost': lot.unit_cost, 'lot_name': lot.lot_name,
            'part_number': lot.part_number,
            'predecessor_id': lot.predecessor_id,
            'predecessor_label': _lot_label(pred) if pred else '',
            'consumed': _lot_consumed_downstream(lot),
        })
    return {
        'id': inventory.id, **_author(inventory), 'number': inventory.number, 'date': inventory.date,
        'note': inventory.note,
        'project_id': inventory.project_id, 'project_code': inventory.project.code,
        'project_name': inventory.project.name, 'posted': inventory.is_posted,
        'total_cost': total, 'lots': lots,
    }


def create_inventory(project, user, number, date=None, note=''):
    """Создать акт инвентаризации в проект-дом (куда рождаются найденные лоты)."""
    if not (number or '').strip():
        raise ValidationError('Нужен № акта инвентаризации.')
    return models.Inventory.objects.create(
        project=project, user=user, number=number.strip(),
        date=date or timezone.localdate(), note=(note or '').strip())


def add_inventory_lot(inventory, item, qty, unit_cost=ZERO, lot_name='',
                      part_number='', predecessor=None):
    """Добавить строку акта: рождается «найденная» партия (`+RECEIPT`) в его проекте.

    `predecessor` (опц.) связывает найденный лот со списанным-источником
    (ре-материализация серого остатка — провенанс/генеалогия). Кол-во не клампим.
    """
    _require_draft(inventory)
    if qty is None or qty <= 0:
        raise ValidationError('Количество должно быть положительным.')
    if unit_cost is not None and unit_cost < 0:
        raise ValidationError('Цена не может быть отрицательной.')
    lot = models.Lot.objects.create(
        item=item, project=inventory.project, origin=inventory, qty=qty,
        unit_cost=unit_cost or ZERO, lot_name=lot_name or '',
        part_number=part_number or '', predecessor=predecessor)
    rebuild_movements(lot)
    return lot


def update_inventory_lot(lot, qty=None, unit_cost=None, lot_name=None,
                         part_number=None):
    """Автосейв строки акта (кол-во/цена/название/PN). Кол-во не клампим по расходу.
    Только черновик (замок)."""
    _require_draft(lot.origin)
    fields = []
    if qty is not None:
        if qty <= 0:
            raise ValidationError('Количество должно быть положительным.')
        lot.qty = qty
        fields.append('qty')
    if unit_cost is not None:
        if unit_cost < 0:
            raise ValidationError('Цена не может быть отрицательной.')
        lot.unit_cost = unit_cost
        fields.append('unit_cost')
    if lot_name is not None:
        lot.lot_name = lot_name
        fields.append('lot_name')
    if part_number is not None:
        lot.part_number = part_number
        fields.append('part_number')
    if fields:
        lot.save(update_fields=fields)
        rebuild_movements(lot)
    return lot


def remove_inventory_lot(lot):
    """Удалить строку акта (коррекция). Guard: черновик + найденный лот не потреблён ниже."""
    _require_draft(lot.origin)
    if _lot_consumed_downstream(lot):
        raise ValidationError(
            'Найденная партия уже потреблена ниже — удаление заблокировано.')
    lot.movements.all().delete()
    lot.delete()


def post_inventory(inventory):
    """Провести инвентаризацию (замок, форма read-only)."""
    return post_document(inventory, inventory.lots,
                         'Нельзя провести пустой акт инвентаризации — добавьте строку.')


def unpost_inventory(inventory):
    """Снять замок инвентаризации — снова разрешить правку."""
    return unpost_document(inventory)


def update_inventory(inventory, number=None, date=None, note=None, user=_UNSET,
                     project=_UNSET):
    """Правка шапки инвентаризации (№ акта / дата / примечание / автор / проект). Только черновик."""
    _require_draft(inventory)
    _require_number(number)
    _require_date(date)
    _set_author(inventory, user)
    _set_project(inventory, project)
    return _apply(inventory, {'number': number and number.strip(), 'date': date,
                              'note': None if note is None else note.strip()})


def written_off_lots():
    """Списанные лоты (серый путь) — кандидаты ре-материализации инвентаризацией.

    Списание — чистый `−ISSUE`: лот покинул учёт «в серый». Если серую партию нашли
    физически, инвентаризация возвращает её на баланс лотом-потомком (`predecessor` →
    списанный, наследование item/цены/названия/зав.№). Показываем суммарно списанное
    с лота (сколько «серого» доступно вернуть).
    """
    result = []
    wo = models.StockDocument.Kind.WRITEOFF
    for lot in (models.Lot.objects.filter(stock_lines__document__kind=wo).distinct()
                .select_related('item', 'project').order_by('project__code',
                                                            'item__design_item_id', 'id')):
        # qty знаковый (− расход) → магнитуда списанного = −Σ
        written = -(lot.stock_lines.filter(document__kind=wo)
                    .aggregate(s=Sum('qty'))['s'] or ZERO)
        result.append({
            'lot_id': lot.id, 'item_id': lot.item_id,
            'item_design_item_id': lot.item.design_item_id, 'item_description': lot.item.description,
            'uom': lot.item.uom, 'written_qty': written,
            'project_code': lot.project.code, 'unit_cost': lot.unit_cost,
            'lot_name': lot.lot_name, 'part_number': lot.part_number,
        })
    return result


# --------------------------------------------------------------------------- #
#  Справочники: создание изделий и проектов (канон «＋ Новая», 2026-07-03)
# --------------------------------------------------------------------------- #
def _resolve_category(category_id):
    """Категория изделия из справочника по PK (обязательна). Волна 15: `kind`-enum
    сменён FK-справочником `Category`."""
    if not category_id:
        raise ValidationError('Нужно выбрать категорию изделия.')
    try:
        return models.Category.objects.get(pk=category_id)
    except (models.Category.DoesNotExist, ValueError, TypeError):
        raise ValidationError('Неизвестная категория изделия.')


def item_is_used(item):
    """Изделие «используется» = есть хотя бы одна живая ссылка на него. Волна 15:
    заменяет снятое хранимое `active` вычисляемым признаком (спящий = 0 ссылок =
    кандидат на удаление). Зеркалит guard'ы `delete_item` (used ⇔ неудаляемо):
    вхождение в чужой BOM, лоты, строки заказа/закупки-плана, потребность проекта,
    цель комплектации. Дёшево — набор `Exists` с коротким замыканием на `or`."""
    return (item.used_in.exists() or item.lots.exists()
            or item.purchase_lines.exists() or item.demanded_in.exists()
            or item.kittings.exists()
            or models.ProcurementLine.objects.filter(item=item).exists())


def create_item(design_item_id, description, category_id=None, uom='шт',
                produced=False, estimated_cost=None, temperature=''):
    """Создать изделие справочника из мини-формы «＋ Новое». `design_item_id`
    (заказной PN, канон библиотеки) уникален; категория обязательна (FK-справочник)."""
    design_item_id = (design_item_id or '').strip()
    description = (description or '').strip()
    if not design_item_id:
        raise ValidationError('Нужно изделие (Design Item Id).')
    if not description:
        raise ValidationError('Нужно описание изделия.')
    if models.Item.objects.filter(design_item_id=design_item_id).exists():
        raise ValidationError(f'Изделие {design_item_id} уже есть.')
    category = _resolve_category(category_id)
    return models.Item.objects.create(
        design_item_id=design_item_id, description=description, category=category,
        uom=(uom or '').strip() or 'шт',
        temperature=(temperature or '').strip(),
        produced=bool(produced),
        estimated_cost=estimated_cost)


def update_item(item, changes):
    """Правка свойств изделия под замком формы (§6). `changes` — только присланные
    поля (частичный PATCH). `design_item_id` уникален; категория из справочника
    (ключ `category_id`); описание непустое."""
    fields = []
    if 'design_item_id' in changes:
        v = (changes['design_item_id'] or '').strip()
        if not v:
            raise ValidationError('Нужно изделие (Design Item Id).')
        if models.Item.objects.filter(design_item_id=v).exclude(pk=item.pk).exists():
            raise ValidationError(f'Изделие {v} уже есть.')
        item.design_item_id = v
        fields.append('design_item_id')
    if 'description' in changes:
        v = (changes['description'] or '').strip()
        if not v:
            raise ValidationError('Нужно описание изделия.')
        item.description = v
        fields.append('description')
    if 'category_id' in changes:
        item.category = _resolve_category(changes['category_id'])
        fields.append('category')
    if 'uom' in changes:
        item.uom = (changes['uom'] or '').strip() or 'шт'
        fields.append('uom')
    if 'temperature' in changes:
        item.temperature = (changes['temperature'] or '').strip()
        fields.append('temperature')
    if 'estimated_cost' in changes:
        item.estimated_cost = changes['estimated_cost']    # Decimal или None (сброс)
        fields.append('estimated_cost')
    if 'produced' in changes:
        item.produced = bool(changes['produced'])
        fields.append('produced')
    if fields:
        item.save(update_fields=fields)
    return item


def delete_item(item):
    """Удалить изделие из справочника (WAVE14 Ф2). Friendly-guard переводит `PROTECT`
    в человеческий отказ вместо 500: изделие держат партии, вхождение в чужой BOM,
    потребность проекта, строки заказа/закупки, цель комплектации. Свой состав (строки
    BOM, где изделие — parent) и вложения — каскад; файлы вложений сносим явно, иначе
    каскад БД осиротит их на диске (как в `delete_stock_document`)."""
    if item.lots.exists():
        raise ValidationError('У изделия есть партии на складе — удаление заблокировано.')
    if item.used_in.exists():
        raise ValidationError('Изделие входит в состав других изделий — удаление заблокировано.')
    if item.demanded_in.exists():
        raise ValidationError('На изделие есть потребность проекта — удаление заблокировано.')
    if item.purchase_lines.exists():
        raise ValidationError('Изделие есть в заказах — удаление заблокировано.')
    if item.kittings.exists():
        raise ValidationError('Изделие — цель комплектации — удаление заблокировано.')
    if models.ProcurementLine.objects.filter(item=item).exists():
        raise ValidationError('Изделие есть в закупках-планах — удаление заблокировано.')
    for att in item.attachments.all():             # физические файлы (каскад их сиротит)
        delete_attachment(att)
    try:
        item.delete()                              # каскад: свои строки BOM (parent)
    except ProtectedError:
        raise ValidationError('Изделие связано с другими записями — удаление заблокировано.')


def create_project(code, name, budget=None, started_at=None):
    """Создать внешний проект (НИР/контракт) из мини-формы «＋ Новый». Код уникален.

    Только `kind=external`: внутренние склады (WHITE/GREY) — синглтоны из сида
    (`Project.clean`), формой «＋ Новый» не заводятся.
    """
    code = (code or '').strip()
    name = (name or '').strip()
    if not code:
        raise ValidationError('Нужен код проекта.')
    if not name:
        raise ValidationError('Нужно название проекта.')
    if models.Project.objects.filter(code=code).exists():
        raise ValidationError(f'Проект с кодом {code} уже есть.')
    return models.Project.objects.create(
        code=code, name=name, kind=models.Project.Kind.EXTERNAL,
        status=models.Project.Status.ACTIVE,
        budget=budget, started_at=started_at or None)


def update_project(project, changes):
    """Правка реквизитов проекта под замком формы (§6): код, название, бюджет, дата начала.
    Статус (закрытие/переоткрытие) — отдельным путём, здесь не трогаем. Код правим всем
    проектам (WAVE14 Ф1): он не PK, переименование безопасно; guard как в update_item."""
    fields = []
    if 'code' in changes:
        code = (changes['code'] or '').strip()
        if not code:
            raise ValidationError('Нужен код проекта.')
        if models.Project.objects.filter(code=code).exclude(pk=project.pk).exists():
            raise ValidationError(f'Проект с кодом {code} уже есть.')
        project.code = code
        fields.append('code')
    if 'name' in changes:
        name = (changes['name'] or '').strip()
        if not name:
            raise ValidationError('Нужно название проекта.')
        project.name = name
        fields.append('name')
    if 'budget' in changes:
        project.budget = changes['budget']                 # Decimal или None (сброс)
        fields.append('budget')
    if 'started_at' in changes:
        project.started_at = changes['started_at'] or None
        fields.append('started_at')
    if fields:
        project.save(update_fields=fields)
    return project


def delete_project(project):
    """Удалить проект (WAVE14 Ф2) — только пустой (решение Ивана): внутренние склады
    неудаляемы (системные синглтоны); непустой проект уходит из жизни закрытием, не
    удалением. Держат: лоты, заказы, потребности; ссылку из ордеров (StockDocument.
    project PROTECT) ловит catch-all — переводим в человеческий отказ вместо 500."""
    if project.kind in models.Project.INTERNAL_KINDS:
        raise ValidationError('Внутренний склад удалять нельзя — это системный проект.')
    if project.lots.exists():
        raise ValidationError(
            'В проекте есть партии — удаление заблокировано; закройте проект закрывающими документами.')
    if project.purchases.exists():
        raise ValidationError('К проекту привязаны заказы — удаление заблокировано.')
    if project.demands.exists():
        raise ValidationError('В проекте есть потребности (приборы) — сперва уберите их.')
    try:
        project.delete()
    except ProtectedError:
        raise ValidationError('Проект связан с документами — удаление заблокировано; закройте проект.')


# --------------------------------------------------------------------------- #
#  Потребность проекта (секция «Приборы» формы проекта): что и сколько делаем
# --------------------------------------------------------------------------- #
def _editable_project(project):
    """Потребность правится только у активного внешнего проекта (не склад, не закрыт)."""
    if project.kind in models.Project.INTERNAL_KINDS:
        raise ValidationError('У внутреннего склада нет потребностей.')
    if project.status == models.Project.Status.CLOSED:
        raise ValidationError('Проект закрыт — переоткройте, чтобы править потребность.')


def add_project_demand(project, item, qty):
    """Добавить прибор в потребность проекта. Пара (проект, изделие) уникальна."""
    _editable_project(project)
    if qty is None or qty <= ZERO:
        raise ValidationError('Кол-во приборов должно быть больше нуля.')
    if models.ProjectDemand.objects.filter(project=project, target_item=item).exists():
        raise ValidationError(f'Прибор {item.design_item_id} уже в потребности проекта.')
    return models.ProjectDemand.objects.create(
        project=project, target_item=item, qty=qty)


def update_project_demand(demand, qty):
    """Правка кол-ва приборов в потребности (автосейв)."""
    _editable_project(demand.project)
    if qty is None or qty <= ZERO:
        raise ValidationError('Кол-во приборов должно быть больше нуля.')
    demand.qty = qty
    demand.save(update_fields=['qty'])
    return demand


def remove_project_demand(demand):
    """Убрать прибор из потребности проекта."""
    _editable_project(demand.project)
    demand.delete()


# --------------------------------------------------------------------------- #
#  Состав изделия / BOM (редактор на экране изделия)
# --------------------------------------------------------------------------- #
def _bom_would_cycle(parent, component):
    """True, если component (через свой BOM вглубь) содержит parent → цикл."""
    seen = set()
    stack = [component]
    while stack:
        cur = stack.pop()
        if cur.id == parent.id:
            return True
        if cur.id in seen:
            continue
        seen.add(cur.id)
        stack.extend(bl.component for bl in cur.bom_lines.select_related('component'))
    return False


def add_bom_line(parent, component, qty, position=''):
    """Добавить компонент в состав изделия. Без самоссылки, циклов и дублей."""
    if qty is None or qty <= ZERO:
        raise ValidationError('Кол-во должно быть больше нуля.')
    if component.id == parent.id:
        raise ValidationError('Изделие не может входить само в себя.')
    if models.BomLine.objects.filter(parent=parent, component=component).exists():
        raise ValidationError(f'Компонент {component.design_item_id} уже в составе.')
    if _bom_would_cycle(parent, component):
        raise ValidationError(f'Цикл в составе: {component.design_item_id} уже содержит {parent.design_item_id}.')
    return models.BomLine.objects.create(
        parent=parent, component=component, qty=qty,
        position=(position or '').strip())


def update_bom_line(line, qty=None, position=None):
    """Правка строки состава (кол-во/позиция, автосейв)."""
    fields = []
    if qty is not None:
        if qty <= ZERO:
            raise ValidationError('Кол-во должно быть больше нуля.')
        line.qty = qty
        fields.append('qty')
    if position is not None:
        line.position = (position or '').strip()
        fields.append('position')
    if fields:
        line.save(update_fields=fields)
    return line


def remove_bom_line(line):
    """Убрать строку из состава изделия."""
    line.delete()


# --------------------------------------------------------------------------- #
#  Вложения (волна 11): PDF/сканы к документам и изделиям (exclusive-arc владелец)
# --------------------------------------------------------------------------- #
# Владелец вложения. API-контракт `owner_type` неизменён (стабильные строки:
# 'item' + виды ордера) — но после коллапса дуги (Ф2b) физических владельцев два:
# `Attachment.item` (изделие) и `Attachment.document` (ордер, любой вид). Разрешаем
# owner_type в КОНКРЕТНУЮ модель (строгая проверка «не найден»/несовпадение вида),
# а храним в `item` (для 'item') или `document` (для видов ордера).
ATTACHMENT_OWNER_MODELS = {
    'item': models.Item, 'receipt': models.Receipt, 'transfer': models.Transfer,
    'kitting': models.Kitting, 'inventory': models.Inventory,
    'writeoff': models.Writeoff, 'requisition': models.Requisition,
    'relocation': models.Relocation,
}


def _attachment_owner_field(owner_type):
    """Поле-владелец под owner_type: 'item' → item; вид ордера → document."""
    return 'item' if owner_type == 'item' else 'document'


def resolve_attachment_owner(owner_type, owner_id):
    """Найти владельца по типу (имя из API) и id. Ошибка на неизвестный тип."""
    model = ATTACHMENT_OWNER_MODELS.get(owner_type)
    if model is None:
        raise ValidationError(f'Неизвестный тип владельца вложения: {owner_type}.')
    try:
        return model.objects.get(pk=owner_id)
    except model.DoesNotExist:
        raise ValidationError('Документ-владелец вложения не найден.')


def attachment_row(att):
    """Проекция вложения для витрины (путь к файлу не отдаём — качаем эндпоинтом)."""
    return {
        'id': att.id, 'filename': att.filename or att.file.name,
        'size': att.size, 'content_type': att.content_type,
        'label': att.label, 'uploaded_at': att.uploaded_at,
        'user': att.user.get_username() if att.user_id else '',
        'url': f'/api/attachments/{att.id}/download/',
    }


def attachments_for(owner_type, owner_id):
    """Список вложений владельца (свежие сверху)."""
    if owner_type not in ATTACHMENT_OWNER_MODELS:
        raise ValidationError(f'Неизвестный тип владельца вложения: {owner_type}.')
    if owner_type == 'item':
        flt = {'item_id': owner_id}
    else:
        # id ордеров глобально уникален (Ф2a) → document_id однозначен; фильтр по
        # kind сохраняет прежнюю строгость (несовпадение вида → пусто).
        flt = {'document_id': owner_id, 'document__kind': owner_type}
    qs = (models.Attachment.objects.filter(**flt)
          .select_related('user').order_by('-id'))
    return [attachment_row(a) for a in qs]


def add_attachment(owner_type, owner, upload, user, label=''):
    """Прикрепить файл к владельцу: файл на диск, метаданные из upload (не с клиента).

    filename/size/content_type заполняет сервер из загруженного файла. Владелец
    ровно один (exclusive arc item↔document) — поле задаётся по owner_type. Синхронно.
    """
    if owner_type not in ATTACHMENT_OWNER_MODELS:
        raise ValidationError(f'Неизвестный тип владельца вложения: {owner_type}.')
    if upload is None:
        raise ValidationError('Нужен файл вложения.')
    limit = settings.MAX_ATTACHMENT_SIZE
    if upload.size and upload.size > limit:
        raise ValidationError(f'Файл больше лимита ({limit // (1024 * 1024)} МБ).')
    att = models.Attachment(
        file=upload, filename=upload.name or '', size=upload.size or 0,
        content_type=getattr(upload, 'content_type', '') or '',
        label=(label or '').strip(), user=user,
        **{_attachment_owner_field(owner_type): owner})
    att.full_clean(exclude=['file'])   # exclusive-arc + длины полей (file уже валиден)
    att.save()
    return att


def update_attachment(att, label=None):
    """Правка подписи вложения (label). Метаданные файла неизменны."""
    if label is not None:
        att.label = (label or '').strip()
        att.save(update_fields=['label'])
    return att


def delete_attachment(att):
    """Удалить вложение: строку в БД и физический файл с диска."""
    att.file.delete(save=False)
    att.delete()
