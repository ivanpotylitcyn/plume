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

Следующие волны: командный свод + Procurement, pegging, бюджет/экономия.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum

from . import models

ZERO = Decimal('0')


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

    # origin: рождение партии (+)
    origin_kind = lot.origin_kind
    if origin_kind and lot.qty:
        rows.append(models.StockMovement(
            lot=lot, location=main, type=models.StockMovement.Type.RECEIPT,
            qty=lot.qty, source_type=origin_kind, source_id=getattr(lot, f'{origin_kind}_id'),
        ))

    # расход: комплектация (пайка компонента из этой партии)
    for kl in lot.kitting_lines.select_related('kitting', 'location'):
        if kl.kitting.status == models.Kitting.Status.CANCELLED:
            continue
        rows.append(models.StockMovement(
            lot=lot, location=kl.location, type=models.StockMovement.Type.ISSUE,
            qty=-kl.qty, source_type='kitting', source_id=kl.kitting_id,
        ))

    # расход: передача заказчику
    for tl in lot.transfer_lines.select_related('transfer'):
        rows.append(models.StockMovement(
            lot=lot, location=main, type=models.StockMovement.Type.ISSUE,
            qty=-tl.qty, source_type='transfer', source_id=tl.transfer_id,
        ))

    # расход: списание
    for wl in lot.writeoff_lines.select_related('location'):
        rows.append(models.StockMovement(
            lot=lot, location=wl.location, type=models.StockMovement.Type.ISSUE,
            qty=-wl.qty, source_type='writeoff', source_id=wl.writeoff_id,
        ))

    # расход: отпочкование (эта партия — источник нового лота)
    for rl in lot.requisition_lines.select_related('location'):
        rows.append(models.StockMovement(
            lot=lot, location=rl.location, type=models.StockMovement.Type.ISSUE,
            qty=-rl.qty, source_type='requisition', source_id=rl.requisition_id,
        ))

    models.StockMovement.objects.bulk_create(rows)
    return rows


def rebuild_all():
    """Пересобрать движения для всех партий (сид/тесты/детектор дрейфа)."""
    for lot in models.Lot.objects.all():
        rebuild_movements(lot)


def lot_live_qty(lot):
    """Живой остаток партии = сумма её движений (Lot.qty + Σ расход)."""
    agg = lot.movements.aggregate(s=Sum('qty'))
    return agg['s'] or ZERO


def item_available(item, project):
    """Доступный остаток Item в проекте — Σ живых остатков своих лотов.

    Может быть отрицательным (недостача) — не клампим, это информативно.
    """
    agg = models.StockMovement.objects.filter(
        lot__item=item, lot__project=project,
    ).aggregate(s=Sum('qty'))
    return agg['s'] or ZERO


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
        item=line.item, receipt__purchase=line.purchase,
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
    """Σ кол-во в производимых wip-комплектациях, делающих этот Item в проекте."""
    agg = models.Kitting.objects.filter(
        target_item=item, project=project, status=models.Kitting.Status.WIP,
    ).aggregate(s=Sum('qty'))
    return agg['s'] or ZERO


def item_on_order(item, project):
    """Оранжевый член, обобщённый по типу Item (покупной/производимый)."""
    if item.is_manufactured:
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
    for demand in project.demands.select_related('target_item'):
        target = demand.target_item
        lines = []
        statuses = []
        for bl in target.bom_lines.select_related('component'):
            component = bl.component
            need = bl.qty * demand.qty
            available = item_available(component, project)
            on_order = item_on_order(component, project)
            cov = _coverage(need, available, on_order)
            cov.update({
                'component_id': component.id,
                'component_code': component.code,
                'component_name': component.name,
                'uom': component.uom,
                'available_raw': available,        # сырой остаток (может быть < 0)
                'anomaly': item_has_negative_lot(component, project),
            })
            lines.append(cov)
            statuses.append(cov['status'])

        # триплет прибора: готово (закрытые лоты) / делается (wip) / не начато
        done = models.StockMovement.objects.filter(
            lot__item=target, lot__project=project,
            lot__kitting__status=models.Kitting.Status.CLOSED,
        ).aggregate(s=Sum('qty'))['s'] or ZERO
        wip = _manufactured_in_progress(target, project)
        not_started = max(ZERO, demand.qty - done - wip)

        demands.append({
            'demand_id': demand.id,
            'target_id': target.id,
            'target_code': target.code,
            'target_name': target.name,
            'qty': demand.qty,
            'device': {'done': done, 'wip': wip, 'not_started': not_started},
            # цвет прибора: worst-of строк (внимание) + бейдж лучшего прогресса
            'status': _worst_of(statuses),
            'badge': _best_of(statuses),
            'lines': lines,
        })
    return {
        'project_id': project.id,
        'project_code': project.code,
        'project_name': project.name,
        'demands': demands,
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
        rows.append({
            'project_id': project.id,
            'project_code': project.code,
            'project_name': project.name,
            'project_kind': project.kind,
            'available': available,
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
        'item_code': item.code,
        'item_name': item.name,
        'uom': item.uom,
        'rows': rows,
    }


# --------------------------------------------------------------------------- #
#  Кокпит комплектации (волна 2): реальные строки + призрачные строки
# --------------------------------------------------------------------------- #
def available_lots(item, project):
    """Лоты item в проекте с живым остатком > 0 — кандидаты под пайку."""
    result = []
    for lot in models.Lot.objects.filter(item=item, project=project).select_related('item'):
        live = lot_live_qty(lot)
        if live > 0:
            result.append({
                'lot_id': lot.id, 'live_qty': live, 'unit_cost': lot.unit_cost,
                'serial_number': lot.serial_number,
                'origin': lot.origin_kind, 'received_name': lot.received_name,
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
    is_wip = kitting.status == models.Kitting.Status.WIP
    for bl in target.bom_lines.select_related('component'):
        component = bl.component
        need = bl.qty * kitting.qty
        real_lines = []
        pierced = ZERO
        for kl in kitting.lines.filter(component=component).select_related('lot'):
            pierced += kl.qty
            real_lines.append({
                'id': kl.id, 'lot_id': kl.lot_id,
                'lot_label': f'#{kl.lot_id} {kl.lot.received_name or component.code}',
                'qty': kl.qty, 'date': kl.date,
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
            'component_id': component.id, 'component_code': component.code,
            'component_name': component.name, 'uom': component.uom,
            'need': need, 'pierced': pierced, 'remaining': remaining,
            'real_lines': real_lines, 'ghost': ghost,
        })
    born_lots = [
        {'id': lot.id, 'qty': lot.qty, 'unit_cost': lot.unit_cost,
         'serial_number': lot.serial_number}
        for lot in kitting.lots.all()
    ]
    return {
        'id': kitting.id, 'status': kitting.status,
        'project_id': project.id, 'project_code': project.code,
        'target_id': target.id, 'target_code': target.code,
        'target_name': target.name, 'uom': target.uom,
        'qty': kitting.qty, 'date': kitting.date,
        'cockpit_status': _worst_of(statuses),   # worst-of призрачных строк
        'rows': rows,
        'born_lots': born_lots,   # рождённые лоты-приборы (после закрытия)
    }


# --------------------------------------------------------------------------- #
#  Мутации кокпита (единый источник правил + пересборка проекции склада)
# --------------------------------------------------------------------------- #
def _require_wip(kitting):
    if kitting.status != models.Kitting.Status.WIP:
        raise ValidationError('Правка возможна только в комплектации «в работе».')


def add_kitting_line(kitting, component, lot, qty, location=None, date=None):
    """Пайка: промоушн призрачной строки в реальную `KittingLine` + `-ISSUE`."""
    _require_wip(kitting)
    if lot.item_id != component.id:
        raise ValidationError('Лот не соответствует компоненту строки.')
    if lot.project_id != kitting.project_id:
        raise ValidationError('Лот из другого проекта (заём — отдельным требованием).')
    if qty is None or qty <= 0:
        raise ValidationError('Количество пайки должно быть положительным.')
    line = models.KittingLine.objects.create(
        kitting=kitting, component=component, lot=lot,
        location=location or _main_location(), qty=qty, date=date,
    )
    rebuild_movements(lot)
    return line


def update_kitting_line(line, qty):
    """Автосейв количества пайки (правка провизорной строки до замка)."""
    _require_wip(line.kitting)
    if qty is None or qty <= 0:
        raise ValidationError('Количество пайки должно быть положительным.')
    line.qty = qty
    line.save(update_fields=['qty'])
    rebuild_movements(line.lot)


def remove_kitting_line(line):
    """Удалить пробитую строку (коррекция до замка) + пересобрать движения лота."""
    _require_wip(line.kitting)
    lot = line.lot
    line.delete()
    rebuild_movements(lot)


def _device_unit_cost(kitting):
    """Снимок себестоимости прибора на закрытии = Σ(qty×цена лотов) / кол-во."""
    total = ZERO
    for kl in kitting.lines.select_related('lot'):
        total += kl.qty * kl.lot.unit_cost
    if kitting.qty and kitting.qty != ZERO:
        return (total / kitting.qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return ZERO


def close_kitting(kitting):
    """Закрыть комплектацию: рождается лот-прибор (`+RECEIPT`), `wip → closed`."""
    _require_wip(kitting)
    if kitting.lots.exists():
        raise ValidationError('У комплектации уже есть рождённый лот-прибор.')
    lot = models.Lot.objects.create(
        item=kitting.target_item, project=kitting.project, kitting=kitting,
        qty=kitting.qty, unit_cost=_device_unit_cost(kitting),
    )
    kitting.status = models.Kitting.Status.CLOSED
    kitting.save(update_fields=['status'])
    rebuild_movements(lot)
    return lot


def reopen_kitting(kitting):
    """Переоткрыть закрытую комплектацию: снять лот-прибор, `closed → wip`.

    Guard: лот-прибор не должен быть потреблён/передан/отпочкован ниже.
    """
    if kitting.status != models.Kitting.Status.CLOSED:
        raise ValidationError('Переоткрыть можно только закрытую комплектацию.')
    for lot in kitting.lots.all():
        if _lot_consumed_downstream(lot):
            raise ValidationError(
                'Лот-прибор уже потреблён/передан ниже — переоткрытие заблокировано.')
    for lot in kitting.lots.all():
        lot.movements.all().delete()
        lot.delete()
    kitting.status = models.Kitting.Status.WIP
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
            or lot.kitting_lines.exists() or lot.transfer_lines.exists()
            or lot.writeoff_lines.exists() or lot.requisition_lines.exists())


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
            'id': lot.id, 'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_name': lot.item.name, 'uom': lot.item.uom,
            'qty': lot.qty, 'live_qty': lot_live_qty(lot),
            'unit_cost': lot.unit_cost, 'received_name': lot.received_name,
            'serial_number': lot.serial_number,
            'consumed': _lot_consumed_downstream(lot),
        })
    return {
        'id': receipt.id, 'number': receipt.number, 'date': receipt.date,
        'supplier_id': receipt.supplier_id, 'supplier_name': receipt.supplier.name,
        'project_id': receipt.project_id, 'project_code': receipt.project.code,
        'project_name': receipt.project.name,
        'purchase_id': receipt.purchase_id,   # связанный заказ (закрытие строк)
        'approved': receipt.approved, 'total_cost': total,
        'lots': lots,
    }


def _require_unapproved(receipt):
    if receipt.approved:
        raise ValidationError('Приход сверён (замок) — снимите замок для правки.')


def add_receipt_lot(receipt, item, qty, unit_cost=ZERO, received_name='',
                    serial_number=''):
    """Добавить строку УПД: рождается партия (`+RECEIPT`) в проекте прихода."""
    _require_unapproved(receipt)
    if qty is None or qty <= 0:
        raise ValidationError('Количество прихода должно быть положительным.')
    if unit_cost is not None and unit_cost < 0:
        raise ValidationError('Цена не может быть отрицательной.')
    lot = models.Lot.objects.create(
        item=item, project=receipt.project, receipt=receipt, qty=qty,
        unit_cost=unit_cost or ZERO, received_name=received_name or '',
        serial_number=serial_number or '',
    )
    rebuild_movements(lot)
    return lot


def update_receipt_lot(lot, qty=None, unit_cost=None, received_name=None,
                       serial_number=None):
    """Автосейв строки УПД (кол-во/цена/название/зав.№). Правка до замка.

    Кол-во не клампим по потреблению: уронить ниже списанного можно — живой остаток
    уйдёт в минус (недостача информативнее, в духе мутабельной ДНК).
    """
    _require_unapproved(lot.receipt)
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
    if received_name is not None:
        lot.received_name = received_name
        fields.append('received_name')
    if serial_number is not None:
        lot.serial_number = serial_number
        fields.append('serial_number')
    if fields:
        lot.save(update_fields=fields)
        rebuild_movements(lot)
    return lot


def remove_receipt_lot(lot):
    """Удалить строку УПД (до замка). Guard: лот не потреблён ниже."""
    _require_unapproved(lot.receipt)
    if _lot_consumed_downstream(lot):
        raise ValidationError(
            'Партия уже потреблена ниже (пайка/передача) — удаление заблокировано.')
    lot.movements.all().delete()
    lot.delete()


def approve_receipt(receipt):
    """Поставить замок «сверено со сканом» — форма прихода становится read-only."""
    if not receipt.lots.exists():
        raise ValidationError('Нельзя сверить пустой приход — добавьте строку.')
    receipt.approved = True
    receipt.save(update_fields=['approved'])
    return receipt


def unapprove_receipt(receipt):
    """Снять замок — снова разрешить правку. Ничего не разрушает (в отличие от
    переоткрытия комплектации), поэтому guard по потомкам не нужен."""
    receipt.approved = False
    receipt.save(update_fields=['approved'])
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
            'id': line.id, 'item_id': line.item_id, 'item_code': line.item.code,
            'item_name': line.item.name, 'uom': line.item.uom,
            'qty': line.qty, 'received': received, 'remaining': remaining,
            'status': st,
        })
    receipts = [
        {'id': r.id, 'number': r.number, 'date': r.date,
         'supplier_name': r.supplier.name, 'lines': r.lots.count()}
        for r in purchase.receipts.select_related('supplier').order_by('id')
    ]
    return {
        'id': purchase.id, 'status': purchase.status,
        'project_id': purchase.project_id, 'project_code': purchase.project.code,
        'project_name': purchase.project.name,
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
            f'Изделие {item.code} уже в заказе — правьте существующую строку.')
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
