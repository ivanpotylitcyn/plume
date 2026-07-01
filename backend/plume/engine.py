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

Следующие волны: pegging, командный свод, бюджет/экономия.
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
def _purchased_on_order(item, project):
    """Σ max(0, PurchaseLine.qty − поступившее) по открытым (sent) заказам проекта."""
    total = ZERO
    lines = models.PurchaseLine.objects.filter(
        item=item, purchase__project=project,
        purchase__status=models.Purchase.Status.SENT,
    ).select_related('purchase')
    for line in lines:
        received = models.Lot.objects.filter(
            item=item, receipt__purchase=line.purchase,
        ).aggregate(s=Sum('qty'))['s'] or ZERO
        total += max(ZERO, line.qty - received)
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
        if (lot.movements.filter(qty__lt=0).exists() or lot.successors.exists()
                or lot.transfer_lines.exists() or lot.kitting_lines.exists()
                or lot.writeoff_lines.exists() or lot.requisition_lines.exists()):
            raise ValidationError(
                'Лот-прибор уже потреблён/передан ниже — переоткрытие заблокировано.')
    for lot in kitting.lots.all():
        lot.movements.all().delete()
        lot.delete()
    kitting.status = models.Kitting.Status.WIP
    kitting.save(update_fields=['status'])
