"""Движок-СППР plume — волна 1.

Чистые функции-проекции над документами (один движок на всю линзу). Ничего не
кэшируем: всё вычислимое держим свежим (данных мало, без Celery).

Состав волны 1:
- `rebuild_movements(lot)` — пересборка StockMovement партии из её документов.
- `lot_live_qty` / `item_available` — живые остатки.
- `project_deficit(project)` — дефицит проекта (надо − склад − заказано),
  1 уровень BOM, тройной разбор ✓/●/▲, worst-of цвет.
- `stock_map(item)` — карта остатков Item по всем складам-проектам (north-star).

Следующие волны: pegging, командный свод, бюджет/экономия, призрачный кокпит.
"""
from decimal import Decimal
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
