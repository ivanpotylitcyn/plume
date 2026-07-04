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
- Мягкий замок «отгружено» (`Transfer.posted`, зеркалит `Receipt.approved`):
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

Следующие волны: логин-экран, UI вложений (`Attachment`).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.utils import timezone

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
    for lot in project.lots.filter(receipt__isnull=False):
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
        if component.is_manufactured:
            continue  # снимок себестоимости узла считаем отдельно, не в деньгах бюджета
        cov = _coverage(need, item_available(component, project),
                        item_on_order(component, project))
        remaining = cov['on_order'] + cov['to_order']
        if remaining <= 0:
            continue
        if component.estimated_cost is None:
            unestimated.append(component.code)
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
        kitting__status=models.Kitting.Status.CLOSED, item_id__in=targets,
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
                .select_related('item').order_by('item__code', 'id')):
        live = lot_live_qty(lot)
        if live > 0:
            result.append({
                'lot_id': lot.id, 'item_id': lot.item_id,
                'item_code': lot.item.code, 'item_name': lot.item.name,
                'uom': lot.item.uom, 'live_qty': live, 'origin': lot.origin_kind,
                'serial_number': lot.serial_number,
                'received_name': lot.received_name,
            })
    return result


def _lot_label(lot):
    """Человекочитаемая метка лота для накладной/строки (зав.№ / название / артикул)."""
    tail = lot.serial_number or lot.received_name or lot.item.code
    return f'#{lot.id} {tail}'


def transfer_cockpit(transfer):
    """Проекция кокпита передачи: шапка накладной + строки-лоты + итог.

    Каждая строка отдаёт партию заказчику (`−ISSUE`); показываем живой остаток
    источника (просел ли под передачу, не ушёл ли в минус). Ничего не хранит.
    """
    lines = []
    total_qty = ZERO
    for line in transfer.lines.select_related('lot__item').order_by('id'):
        lot = line.lot
        total_qty += line.qty
        lines.append({
            'id': line.id, 'lot_id': lot.id,
            'lot_label': _lot_label(lot),
            'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_name': lot.item.name, 'uom': lot.item.uom,
            'qty': line.qty, 'display_name': line.display_name,
            'lot_live_qty': lot_live_qty(lot),   # остаток источника после отгрузки
            'serial_number': lot.serial_number,
        })
    return {
        'id': transfer.id, 'number': transfer.number, 'date': transfer.date,
        'project_id': transfer.project_id, 'project_code': transfer.project.code,
        'project_name': transfer.project.name, 'posted': transfer.posted,
        'total_qty': total_qty, 'lines': lines,
    }


def item_shipments(item):
    """Отгруженные партии изделия — где и по какой накладной ушло заказчику.

    Read-only проекция для экрана изделия: строки передач его лотов (замыкает
    петлю `комплектация → передача`). Порядок — свежие сверху.
    """
    rows = []
    for line in (models.TransferLine.objects
                 .filter(lot__item=item).select_related('transfer__project', 'lot')
                 .order_by('-transfer__date', '-id')):
        t = line.transfer
        rows.append({
            'transfer_id': t.id, 'number': t.number, 'date': t.date,
            'project_code': t.project.code, 'posted': t.posted,
            'lot_id': line.lot_id, 'qty': line.qty,
            'display_name': line.display_name,
            'serial_number': line.lot.serial_number,
        })
    return rows


def create_transfer(project, user, number, date=None):
    """Создать передачу (накладную) проекта. Строки добавляются в кокпите.

    `Transfer.date` не nullable — пустую дату замыкаем на сегодня.
    """
    if not (number or '').strip():
        raise ValidationError('Нужен № накладной.')
    return models.Transfer.objects.create(
        project=project, user=user, number=number.strip(),
        date=date or timezone.localdate())


def _require_unposted(transfer):
    if transfer.posted:
        raise ValidationError('Накладная отгружена (замок) — снимите замок для правки.')


def add_transfer_line(transfer, lot, qty, display_name=''):
    """Отгрузить партию заказчику: строка передачи (`−ISSUE` на лоте).

    Лот — того же проекта (передаём своё, чужое — через требование). Кол-во не
    клампим по остатку: переотдать можно, лот уйдёт в минус (недостача информативна,
    в духе мутабельной ДНК).
    """
    _require_unposted(transfer)
    if lot.project_id != transfer.project_id:
        raise ValidationError('Лот из другого проекта — передаём только своё.')
    if qty is None or qty <= 0:
        raise ValidationError('Количество передачи должно быть положительным.')
    line = models.TransferLine.objects.create(
        transfer=transfer, lot=lot, qty=qty,
        display_name=(display_name or '').strip() or _lot_label(lot))
    rebuild_movements(lot)
    return line


def update_transfer_line(line, qty=None, display_name=None):
    """Автосейв строки передачи (кол-во / отображаемое имя для накладной)."""
    _require_unposted(line.transfer)
    fields = []
    if qty is not None:
        if qty <= 0:
            raise ValidationError('Количество передачи должно быть положительным.')
        line.qty = qty
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
    _require_unposted(line.transfer)
    lot = line.lot
    line.delete()
    rebuild_movements(lot)


def post_transfer(transfer):
    """Поставить замок «отгружено» — накладная становится read-only (зеркалит
    `approve_receipt`). Сюда позже ляжет подписанная накладная (Attachment)."""
    if not transfer.lines.exists():
        raise ValidationError('Нельзя отгрузить пустую накладную — добавьте строку.')
    transfer.posted = True
    transfer.save(update_fields=['posted'])
    return transfer


def unpost_transfer(transfer):
    """Снять замок — снова разрешить правку. Ничего не разрушает (строки и их
    `−ISSUE` остаются), поэтому guard по потомкам не нужен."""
    transfer.posted = False
    transfer.save(update_fields=['posted'])
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
                .order_by('project__code', 'item__code', 'id')):
        live = lot_live_qty(lot)
        if live > 0:
            result.append({
                'lot_id': lot.id, 'item_id': lot.item_id,
                'item_code': lot.item.code, 'item_name': lot.item.name,
                'uom': lot.item.uom, 'live_qty': live, 'origin': lot.origin_kind,
                'project_id': lot.project_id, 'project_code': lot.project.code,
                'serial_number': lot.serial_number,
                'received_name': lot.received_name,
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
        total_qty += line.qty
        lines.append({
            'id': line.id, 'lot_id': lot.id, 'lot_label': _lot_label(lot),
            'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_name': lot.item.name, 'uom': lot.item.uom,
            'qty': line.qty, 'lot_live_qty': lot_live_qty(lot),
            'serial_number': lot.serial_number,
        })
    return {
        'id': writeoff.id, 'number': writeoff.number, 'date': writeoff.date,
        'reason': writeoff.reason,
        'project_id': writeoff.project_id, 'project_code': writeoff.project.code,
        'project_name': writeoff.project.name,
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
    if lot.project_id != writeoff.project_id:
        raise ValidationError('Лот из другого проекта — списываем только своё.')
    if qty is None or qty <= 0:
        raise ValidationError('Количество списания должно быть положительным.')
    line = models.WriteoffLine.objects.create(
        writeoff=writeoff, lot=lot, location=location or _main_location(), qty=qty)
    rebuild_movements(lot)
    return line


def update_writeoff_line(line, qty):
    """Автосейв количества строки списания."""
    if qty is None or qty <= 0:
        raise ValidationError('Количество списания должно быть положительным.')
    line.qty = qty
    line.save(update_fields=['qty'])
    rebuild_movements(line.lot)
    return line


def remove_writeoff_line(line):
    """Убрать строку списания (коррекция) — источник возвращает остаток."""
    lot = line.lot
    line.delete()
    rebuild_movements(lot)


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
                 .select_related('source_lot__item', 'source_lot__project')
                 .order_by('id')):
        src = line.source_lot
        total_qty += line.qty
        born = _requisition_born_lot(requisition, src)
        lines.append({
            'id': line.id, 'source_lot_id': src.id, 'lot_label': _lot_label(src),
            'source_project_code': src.project.code,
            'item_id': src.item_id, 'item_code': src.item.code,
            'item_name': src.item.name, 'uom': src.item.uom,
            'qty': line.qty, 'source_live_qty': lot_live_qty(src),
            'born_lot_id': born.id if born else None,
            'serial_number': src.serial_number,
        })
    return {
        'id': requisition.id, 'number': requisition.number, 'date': requisition.date,
        'project_id': requisition.project_id, 'project_code': requisition.project.code,
        'project_name': requisition.project.name,
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
    соседнего активного B→A). Потомок наследует item/цену/название/зав.№ источника,
    `predecessor` → источник (генеалогия/провенанс для kitting из остатков). Один
    источник = одна строка (пара строки↔потомок однозначна). Кол-во не клампим.
    """
    if qty is None or qty <= 0:
        raise ValidationError('Количество требования должно быть положительным.')
    if source_lot.project_id == requisition.project_id:
        raise ValidationError('Источник и получатель — один проект (перекладывать некуда).')
    if requisition.lines.filter(source_lot=source_lot).exists():
        raise ValidationError('Этот лот уже в требовании — правьте существующую строку.')
    line = models.RequisitionLine.objects.create(
        requisition=requisition, source_lot=source_lot,
        location=location or _main_location(), qty=qty)
    born = models.Lot.objects.create(
        item=source_lot.item, project=requisition.project, requisition=requisition,
        predecessor=source_lot, qty=qty, unit_cost=source_lot.unit_cost,
        received_name=source_lot.received_name, serial_number=source_lot.serial_number)
    rebuild_movements(source_lot)   # −ISSUE у источника
    rebuild_movements(born)         # +RECEIPT у потомка
    return line


def update_requisition_line(line, qty):
    """Автосейв количества: правит и строку-источник (`−ISSUE`), и потомок (`+RECEIPT`)."""
    if qty is None or qty <= 0:
        raise ValidationError('Количество требования должно быть положительным.')
    line.qty = qty
    line.save(update_fields=['qty'])
    born = _requisition_born_lot(line.requisition, line.source_lot)
    if born is not None:
        born.qty = qty
        born.save(update_fields=['qty'])
        rebuild_movements(born)
    rebuild_movements(line.source_lot)
    return line


def remove_requisition_line(line):
    """Убрать строку требования: снять потомок + вернуть остаток источнику.

    Guard: потомок не должен быть потреблён ниже (спаян/передан/списан из белого).
    """
    src = line.source_lot
    born = _requisition_born_lot(line.requisition, src)
    if born is not None and _lot_consumed_downstream(born):
        raise ValidationError(
            'Поставленный на баланс лот уже потреблён ниже — удаление заблокировано.')
    line.delete()
    if born is not None:
        born.movements.all().delete()
        born.delete()
    rebuild_movements(src)


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
    for lot in project.lots.select_related('item').order_by('item__code', 'id'):
        live = lot_live_qty(lot)
        if live == 0:
            continue
        residuals.append({
            'lot_id': lot.id, 'lot_label': _lot_label(lot),
            'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_name': lot.item.name, 'uom': lot.item.uom,
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
    writeoff = project.writeoffs.order_by('-id').first()
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
    if requisition is None or requisition.lines.filter(source_lot=lot).exists():
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


def _require_number(number):
    if number is not None and not str(number).strip():
        raise ValidationError('Номер не может быть пустым.')


def _require_date(date):
    if date is not None and not str(date).strip():
        raise ValidationError('Дата не может быть пустой.')


def update_receipt(receipt, number=None, date=None):
    """Правка шапки прихода (№ УПД / дата). Только до замка «сверено»."""
    _require_unapproved(receipt)
    _require_number(number)
    _require_date(date)
    return _apply(receipt, {'number': number and number.strip(), 'date': date})


def update_purchase(purchase, date=None, note=None):
    """Правка шапки заказа (дата / примечание). Только в черновике.

    Дата заказа nullable — пустая строка очищает её в NULL (в отличие от
    документов с обязательной датой).
    """
    _require_purchase_draft(purchase)
    fields = []
    if date is not None:
        purchase.date = date or None
        fields.append('date')
    if note is not None:
        purchase.note = note.strip()
        fields.append('note')
    if fields:
        purchase.save(update_fields=fields)
    return purchase


def update_transfer(transfer, number=None, date=None):
    """Правка шапки передачи (№ накладной / дата). Только до замка «отгружено»."""
    _require_unposted(transfer)
    _require_number(number)
    _require_date(date)
    return _apply(transfer, {'number': number and number.strip(), 'date': date})


def update_writeoff(writeoff, number=None, date=None, reason=None):
    """Правка шапки списания (№ акта / дата / причина)."""
    _require_number(number)
    _require_date(date)
    return _apply(writeoff, {'number': number and number.strip(), 'date': date,
                             'reason': None if reason is None else reason.strip()})


def update_requisition(requisition, number=None, date=None):
    """Правка шапки требования (№ / дата)."""
    _require_number(number)
    _require_date(date)
    return _apply(requisition, {'number': number and number.strip(), 'date': date})


def update_kitting(kitting, qty=None, date=None):
    """Правка шапки комплектации (кол-во образцов / дата). Только «в работе».

    Кол-во образцов пересчитывает потребности BOM — правится, пока `wip`.
    """
    _require_wip(kitting)
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
                'item_id': component.id, 'item_code': component.code,
                'item_name': component.name, 'uom': component.uom,
                'is_manufactured': component.is_manufactured,
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
    rows.sort(key=lambda r: (-_WORST_RANK[r['status']], r['item_code']))
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
            'id': line.id, 'item_id': line.item_id, 'item_code': line.item.code,
            'item_name': line.item.name, 'uom': line.item.uom, 'qty': line.qty,
        })
    return {
        'id': procurement.id, 'status': procurement.status,
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
            f'Изделие {item.code} уже в закупке — правьте существующую строку.')
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


def update_procurement(procurement, date=None, note=None):
    """Правка шапки закупки-плана (дата / примечание). Только в черновике.

    Дата закупки nullable — пустая строка очищает её в NULL (как заказ).
    """
    _require_procurement_draft(procurement)
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
        ws.append([line.item.code, line.item.name, float(line.qty), line.item.uom])
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
            'item_code': line.item.code, 'item_name': line.item.name,
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
            f'Изделие {item.code} не в плане закупки — сначала добавьте строку плана.')
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
# его лоты (`inventory.lots`, как приход/УПД). Origin `inventory` уже знают
# `LOT_ORIGIN_FIELDS` и `rebuild_movements` — волна добавляет записываемую надстройку.
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
            'id': lot.id, 'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_name': lot.item.name, 'uom': lot.item.uom,
            'qty': lot.qty, 'live_qty': lot_live_qty(lot),
            'unit_cost': lot.unit_cost, 'received_name': lot.received_name,
            'serial_number': lot.serial_number,
            'predecessor_id': lot.predecessor_id,
            'predecessor_label': _lot_label(pred) if pred else '',
            'consumed': _lot_consumed_downstream(lot),
        })
    return {
        'id': inventory.id, 'number': inventory.number, 'date': inventory.date,
        'note': inventory.note,
        'project_id': inventory.project_id, 'project_code': inventory.project.code,
        'project_name': inventory.project.name,
        'total_cost': total, 'lots': lots,
    }


def create_inventory(project, user, number, date=None, note=''):
    """Создать акт инвентаризации в проект-дом (куда рождаются найденные лоты)."""
    if not (number or '').strip():
        raise ValidationError('Нужен № акта инвентаризации.')
    return models.Inventory.objects.create(
        project=project, user=user, number=number.strip(),
        date=date or timezone.localdate(), note=(note or '').strip())


def add_inventory_lot(inventory, item, qty, unit_cost=ZERO, received_name='',
                      serial_number='', predecessor=None):
    """Добавить строку акта: рождается «найденная» партия (`+RECEIPT`) в его проекте.

    `predecessor` (опц.) связывает найденный лот со списанным-источником
    (ре-материализация серого остатка — провенанс/генеалогия). Кол-во не клампим.
    """
    if qty is None or qty <= 0:
        raise ValidationError('Количество должно быть положительным.')
    if unit_cost is not None and unit_cost < 0:
        raise ValidationError('Цена не может быть отрицательной.')
    lot = models.Lot.objects.create(
        item=item, project=inventory.project, inventory=inventory, qty=qty,
        unit_cost=unit_cost or ZERO, received_name=received_name or '',
        serial_number=serial_number or '', predecessor=predecessor)
    rebuild_movements(lot)
    return lot


def update_inventory_lot(lot, qty=None, unit_cost=None, received_name=None,
                         serial_number=None):
    """Автосейв строки акта (кол-во/цена/название/зав.№). Кол-во не клампим по расходу."""
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


def remove_inventory_lot(lot):
    """Удалить строку акта (коррекция). Guard: найденный лот не потреблён ниже."""
    if _lot_consumed_downstream(lot):
        raise ValidationError(
            'Найденная партия уже потреблена ниже — удаление заблокировано.')
    lot.movements.all().delete()
    lot.delete()


def update_inventory(inventory, number=None, date=None, note=None):
    """Правка шапки инвентаризации (№ акта / дата / примечание)."""
    _require_number(number)
    _require_date(date)
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
    for lot in (models.Lot.objects.filter(writeoff_lines__isnull=False).distinct()
                .select_related('item', 'project').order_by('project__code',
                                                            'item__code', 'id')):
        written = lot.writeoff_lines.aggregate(s=Sum('qty'))['s'] or ZERO
        result.append({
            'lot_id': lot.id, 'item_id': lot.item_id,
            'item_code': lot.item.code, 'item_name': lot.item.name,
            'uom': lot.item.uom, 'written_qty': written,
            'project_code': lot.project.code, 'unit_cost': lot.unit_cost,
            'received_name': lot.received_name, 'serial_number': lot.serial_number,
        })
    return result


# --------------------------------------------------------------------------- #
#  Справочники: создание изделий и проектов (канон «＋ Новая», 2026-07-03)
# --------------------------------------------------------------------------- #
def create_item(code, name, kind=None, uom='шт', is_manufactured=False,
                estimated_cost=None):
    """Создать изделие справочника из мини-формы «＋ Новое». Артикул уникален."""
    code = (code or '').strip()
    name = (name or '').strip()
    if not code:
        raise ValidationError('Нужен артикул изделия.')
    if not name:
        raise ValidationError('Нужно название изделия.')
    if models.Item.objects.filter(code=code).exists():
        raise ValidationError(f'Изделие с артикулом {code} уже есть.')
    kind = kind or models.Item.Kind.COMPONENT
    if kind not in models.Item.Kind.values:
        raise ValidationError(f'Неизвестный вид изделия: {kind}.')
    return models.Item.objects.create(
        code=code, name=name, kind=kind,
        uom=(uom or '').strip() or 'шт',
        is_manufactured=bool(is_manufactured),
        estimated_cost=estimated_cost)


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


# --------------------------------------------------------------------------- #
#  Вложения (волна 11): PDF/сканы к документам и изделиям (exclusive-arc владелец)
# --------------------------------------------------------------------------- #
# Владелец вложения — ровно один FK (как в модели, `Attachment.OWNER_FIELDS`).
# owner_type в API = имя этого поля; модель выводим из него (item→Item, …).
ATTACHMENT_OWNERS = {
    f: getattr(models, f.capitalize()) for f in models.Attachment.OWNER_FIELDS
}


def resolve_attachment_owner(owner_type, owner_id):
    """Найти документ-владельца по типу (имя FK) и id. Ошибка на неизвестный тип."""
    model = ATTACHMENT_OWNERS.get(owner_type)
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
    if owner_type not in ATTACHMENT_OWNERS:
        raise ValidationError(f'Неизвестный тип владельца вложения: {owner_type}.')
    qs = (models.Attachment.objects.filter(**{owner_type: owner_id})
          .select_related('user').order_by('-id'))
    return [attachment_row(a) for a in qs]


def add_attachment(owner_type, owner, upload, user, label=''):
    """Прикрепить файл к владельцу: файл на диск, метаданные из upload (не с клиента).

    filename/size/content_type заполняет сервер из загруженного файла. Владелец
    ровно один (exclusive arc) — задаётся по owner_type. Синхронно, без Celery.
    """
    if owner_type not in ATTACHMENT_OWNERS:
        raise ValidationError(f'Неизвестный тип владельца вложения: {owner_type}.')
    if upload is None:
        raise ValidationError('Нужен файл вложения.')
    limit = settings.MAX_ATTACHMENT_SIZE
    if upload.size and upload.size > limit:
        raise ValidationError(f'Файл больше лимита ({limit // (1024 * 1024)} МБ).')
    att = models.Attachment(
        file=upload, filename=upload.name or '', size=upload.size or 0,
        content_type=getattr(upload, 'content_type', '') or '',
        label=(label or '').strip(), user=user, **{owner_type: owner})
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
