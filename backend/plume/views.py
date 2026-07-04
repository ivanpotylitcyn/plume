"""API движка plume.

Волна 1 — read-only проекции (дефицит, карта остатков, экран изделия).
Волна 2 — записываемое ядро: кокпит комплектации (пайка = промоушн призрачной
строки в `KittingLine`, автосейв qty, закрытие/переоткрытие). Правила мутаций
живут в `engine.py`; вьюхи только разбирают запрос и маппят ошибки в 400.
Волна 3 — приход/УПД (рождение лотов, замок). Волна 4 — заказ (Purchase) +
связь `Receipt↔Purchase` + мост «дефицит → заказ».
"""
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import engine, models


def _dec(value):
    """Разобрать количество в Decimal (через str — без float-погрешности)."""
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def _actor(request):
    """Автор документа: залогиненный пользователь или дефолтный суперюзер.

    Логин-экран — отдельная волна; во MVP пишем от суперюзера, чтобы кокпит
    работал без формы входа. Авторство остаётся «на документах».
    """
    if request.user and request.user.is_authenticated:
        return request.user
    User = get_user_model()
    return User.objects.filter(is_superuser=True).order_by('id').first()


def _bad(exc):
    return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def ping(request):
    return Response({'status': 'ok', 'app': 'plume'})


def _project_row(p):
    return {'id': p.id, 'code': p.code, 'name': p.name, 'kind': p.kind,
            'status': p.status}


@api_view(['GET', 'POST'])
def projects(request):
    """Список проектов (дерево) / создание нового внешнего проекта (канон «＋ Новый»)."""
    if request.method == 'POST':
        d = request.data
        try:
            p = engine.create_project(
                d.get('code'), d.get('name'), budget=_dec(d.get('budget')),
                started_at=d.get('started_at') or None)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
        return Response(_project_row(p), status=http.HTTP_201_CREATED)

    return Response([_project_row(p) for p in models.Project.objects.all()])


def _item_row(i):
    return {'id': i.id, 'code': i.code, 'name': i.name, 'kind': i.kind,
            'uom': i.uom, 'is_manufactured': i.is_manufactured}


@api_view(['GET', 'POST'])
def items(request):
    """Список изделий (дерево/карта) / создание нового изделия (канон «＋ Новое»)."""
    if request.method == 'POST':
        d = request.data
        try:
            i = engine.create_item(
                d.get('code'), d.get('name'), kind=d.get('kind') or None,
                uom=d.get('uom') or 'шт',
                is_manufactured=bool(d.get('is_manufactured')),
                estimated_cost=_dec(d.get('estimated_cost')))
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
        return Response(_item_row(i), status=http.HTTP_201_CREATED)

    return Response([_item_row(i) for i in models.Item.objects.filter(active=True)])


@api_view(['GET'])
def project_deficit(request, pk):
    """Дефицит проекта (дашборд): тройной разбор ✓/●/▲, worst-of цвет."""
    project = get_object_or_404(models.Project, pk=pk)
    return Response(engine.project_deficit(project))


@api_view(['GET'])
def project_budget(request, pk):
    """Бюджет проекта (north-star окупаемости): потрачено/план/компас + себестоимость/экономия."""
    project = get_object_or_404(models.Project, pk=pk)
    return Response(engine.project_budget(project))


@api_view(['GET'])
def item_detail(request, pk):
    """Экран изделия: свойства + окружение из связей (where-used, лоты) + карта."""
    item = get_object_or_404(models.Item, pk=pk)
    where_used = [
        {'parent_id': bl.parent_id, 'parent_code': bl.parent.code,
         'parent_name': bl.parent.name, 'qty': bl.qty}
        for bl in item.used_in.select_related('parent')
    ]
    bom = [
        {'component_id': bl.component_id, 'component_code': bl.component.code,
         'component_name': bl.component.name, 'qty': bl.qty}
        for bl in item.bom_lines.select_related('component')
    ]
    lots = [
        {'id': lot.id, 'project_code': lot.project.code, 'origin': lot.origin_kind,
         'qty_born': lot.qty, 'live_qty': engine.lot_live_qty(lot),
         'unit_cost': lot.unit_cost, 'serial_number': lot.serial_number}
        for lot in item.lots.select_related('project')
    ]
    return Response({
        'id': item.id, 'code': item.code, 'name': item.name, 'kind': item.kind,
        'uom': item.uom, 'is_manufactured': item.is_manufactured,
        'estimated_cost': item.estimated_cost,
        'bom': bom, 'where_used': where_used, 'lots': lots,
        'shipments': engine.item_shipments(item),
    })


# --------------------------------------------------------------------------- #
#  Кокпит комплектации (волна 2 — записываемое ядро)
# --------------------------------------------------------------------------- #
def _kitting_row(k):
    """Строка списка комплектаций для дерева навигации."""
    return {
        'id': k.id, 'project_code': k.project.code,
        'target_code': k.target_item.code, 'target_name': k.target_item.name,
        'qty': k.qty, 'status': k.status, 'date': k.date,
    }


@api_view(['GET', 'POST'])
def kittings(request):
    """Список комплектаций (дерево) / создание новой (призрачная строка)."""
    if request.method == 'POST':
        d = request.data
        try:
            project = models.Project.objects.get(pk=d['project_id'])
            target = models.Item.objects.get(pk=d['target_item_id'])
            k = models.Kitting.objects.create(
                project=project, target_item=target, user=_actor(request),
                qty=d.get('qty') or 1, date=timezone.localdate(),
                status=models.Kitting.Status.WIP)
        except (KeyError, models.Project.DoesNotExist, models.Item.DoesNotExist) as e:
            return _bad(f'Нужны project_id и target_item_id ({e}).')
        return Response(engine.kitting_cockpit(k), status=http.HTTP_201_CREATED)

    rows = [_kitting_row(k) for k in models.Kitting.objects
            .select_related('project', 'target_item').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH'])
def kitting_detail(request, pk):
    """Кокпит комплектации: BOM 1 уровень, реальные + призрачные строки.
    PATCH — правка шапки (кол-во образцов / дата) прямо в кокпите."""
    k = get_object_or_404(models.Kitting, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_kitting(
                k, qty=_dec(d['qty']) if 'qty' in d else None,
                date=d['date'] if 'date' in d else None)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(engine.kitting_cockpit(k))


@api_view(['POST'])
def kitting_lines(request, pk):
    """Пайка: промоушн призрачной строки в реальную `KittingLine`."""
    k = get_object_or_404(models.Kitting, pk=pk)
    d = request.data
    try:
        component = models.Item.objects.get(pk=d['component_id'])
        lot = models.Lot.objects.get(pk=d['lot_id'])
        engine.add_kitting_line(k, component, lot, _dec(d.get('qty')),
                                date=timezone.localdate())
    except (KeyError, models.Item.DoesNotExist, models.Lot.DoesNotExist) as e:
        return _bad(f'Нужны component_id, lot_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.kitting_cockpit(k), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def kitting_line_detail(request, pk):
    """Автосейв количества пайки (PATCH) / удаление строки (DELETE)."""
    line = get_object_or_404(models.KittingLine.objects.select_related('kitting', 'lot'), pk=pk)
    kitting = line.kitting
    try:
        if request.method == 'DELETE':
            engine.remove_kitting_line(line)
        else:
            engine.update_kitting_line(line, _dec(request.data.get('qty')))
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.kitting_cockpit(kitting))


@api_view(['POST'])
def kitting_close(request, pk):
    """Закрыть комплектацию — рождается лот-прибор (`+RECEIPT`)."""
    k = get_object_or_404(models.Kitting, pk=pk)
    try:
        engine.close_kitting(k)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.kitting_cockpit(k))


@api_view(['POST'])
def kitting_reopen(request, pk):
    """Переоткрыть комплектацию (мягкий замок, guard по потомкам)."""
    k = get_object_or_404(models.Kitting, pk=pk)
    try:
        engine.reopen_kitting(k)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.kitting_cockpit(k))


# --------------------------------------------------------------------------- #
#  Приход / УПД (волна 3 — записываемое ядро) + справочник поставщиков
# --------------------------------------------------------------------------- #
@api_view(['GET', 'POST'])
def suppliers(request):
    """Список поставщиков (пикер) / быстрое создание мелкой сущности."""
    if request.method == 'POST':
        name = (request.data.get('name') or '').strip()
        if not name:
            return _bad('Нужно наименование поставщика.')
        s = models.Supplier.objects.create(
            name=name, inn=(request.data.get('inn') or '').strip())
        return Response({'id': s.id, 'name': s.name, 'inn': s.inn},
                        status=http.HTTP_201_CREATED)
    data = [{'id': s.id, 'name': s.name, 'inn': s.inn}
            for s in models.Supplier.objects.all()]
    return Response(data)


def _receipt_row(r):
    """Строка списка приходов для дерева навигации."""
    return {
        'id': r.id, 'number': r.number, 'date': r.date,
        'supplier_name': r.supplier.name, 'project_code': r.project.code,
        'approved': r.approved, 'lines': r.lots.count(),
    }


@api_view(['GET', 'POST'])
def receipts(request):
    """Список приходов (дерево) / создание нового УПД (призрачная строка)."""
    if request.method == 'POST':
        d = request.data
        number = (d.get('number') or '').strip()
        if not number:
            return _bad('Нужен № УПД.')
        try:
            supplier = models.Supplier.objects.get(pk=d['supplier_id'])
            project = models.Project.objects.get(pk=d['project_id'])
            r = models.Receipt.objects.create(
                number=number, date=d.get('date') or timezone.localdate(),
                supplier=supplier, project=project, user=_actor(request))
        except (KeyError, models.Supplier.DoesNotExist,
                models.Project.DoesNotExist) as e:
            return _bad(f'Нужны supplier_id, project_id, number ({e}).')
        return Response(engine.receipt_cockpit(r), status=http.HTTP_201_CREATED)

    rows = [_receipt_row(r) for r in models.Receipt.objects
            .select_related('supplier', 'project').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH'])
def receipt_detail(request, pk):
    """Кокпит прихода: строки-лоты УПД + живой остаток + сумма.
    PATCH — правка шапки (№ УПД / дата) прямо в кокпите."""
    r = get_object_or_404(models.Receipt, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_receipt(
                r, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(engine.receipt_cockpit(r))


@api_view(['POST'])
def receipt_lots(request, pk):
    """Добавить строку УПД — рождается партия (`+RECEIPT`)."""
    r = get_object_or_404(models.Receipt, pk=pk)
    d = request.data
    try:
        item = models.Item.objects.get(pk=d['item_id'])
        engine.add_receipt_lot(
            r, item, _dec(d.get('qty')),
            unit_cost=_dec(d.get('unit_cost')) or engine.ZERO,
            received_name=d.get('received_name') or '',
            serial_number=d.get('serial_number') or '')
    except (KeyError, models.Item.DoesNotExist) as e:
        return _bad(f'Нужны item_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.receipt_cockpit(r), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def receipt_lot_detail(request, pk):
    """Автосейв строки УПД (PATCH) / удаление строки (DELETE)."""
    lot = get_object_or_404(
        models.Lot.objects.select_related('receipt', 'item'), pk=pk)
    if lot.receipt_id is None:
        return _bad('Партия не из прихода — правка через её origin-документ.')
    receipt = lot.receipt
    try:
        if request.method == 'DELETE':
            engine.remove_receipt_lot(lot)
        else:
            d = request.data
            engine.update_receipt_lot(
                lot,
                qty=_dec(d['qty']) if 'qty' in d else None,
                unit_cost=_dec(d['unit_cost']) if 'unit_cost' in d else None,
                received_name=d['received_name'] if 'received_name' in d else None,
                serial_number=d['serial_number'] if 'serial_number' in d else None)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.receipt_cockpit(receipt))


@api_view(['POST'])
def receipt_approve(request, pk):
    """Поставить замок «сверено со сканом» (форма read-only)."""
    r = get_object_or_404(models.Receipt, pk=pk)
    try:
        engine.approve_receipt(r)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.receipt_cockpit(r))


@api_view(['POST'])
def receipt_unapprove(request, pk):
    """Снять замок — снова разрешить правку."""
    r = get_object_or_404(models.Receipt, pk=pk)
    engine.unapprove_receipt(r)
    return Response(engine.receipt_cockpit(r))


@api_view(['POST'])
def receipt_link(request, pk):
    """Связать приход с заказом (закрытие строк заказа) или отвязать (purchase_id=null)."""
    r = get_object_or_404(models.Receipt, pk=pk)
    pid = request.data.get('purchase_id')
    try:
        purchase = models.Purchase.objects.get(pk=pid) if pid else None
        engine.set_receipt_purchase(r, purchase)
    except models.Purchase.DoesNotExist:
        return _bad('Заказ не найден.')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.receipt_cockpit(r))


# --------------------------------------------------------------------------- #
#  Заказ / Purchase (волна 4 — записываемое ядро) + мост «дефицит → заказ»
# --------------------------------------------------------------------------- #
def _purchase_row(p):
    """Строка списка заказов для дерева навигации."""
    return {
        'id': p.id, 'project_code': p.project.code, 'status': p.status,
        'date': p.date, 'note': p.note, 'lines': p.lines.count(),
    }


@api_view(['GET', 'POST'])
def purchases(request):
    """Список заказов (дерево) / создание нового (призрачная строка)."""
    if request.method == 'POST':
        d = request.data
        try:
            project = models.Project.objects.get(pk=d['project_id'])
        except (KeyError, models.Project.DoesNotExist) as e:
            return _bad(f'Нужен project_id ({e}).')
        p = engine.create_purchase(project, _actor(request),
                                   date=d.get('date') or None,
                                   note=(d.get('note') or '').strip())
        return Response(engine.purchase_cockpit(p), status=http.HTTP_201_CREATED)

    rows = [_purchase_row(p) for p in models.Purchase.objects
            .select_related('project').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH'])
def purchase_detail(request, pk):
    """Кокпит заказа: строки (заказано/поступило/остаток) + связанные приходы.
    PATCH — правка шапки (дата / примечание) прямо в кокпите."""
    p = get_object_or_404(models.Purchase, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_purchase(
                p, date=d['date'] if 'date' in d else None,
                note=d['note'] if 'note' in d else None)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(engine.purchase_cockpit(p))


@api_view(['POST'])
def purchase_lines(request, pk):
    """Добавить строку заказа (только в черновике)."""
    p = get_object_or_404(models.Purchase, pk=pk)
    d = request.data
    try:
        item = models.Item.objects.get(pk=d['item_id'])
        engine.add_purchase_line(p, item, _dec(d.get('qty')))
    except (KeyError, models.Item.DoesNotExist) as e:
        return _bad(f'Нужны item_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.purchase_cockpit(p), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def purchase_line_detail(request, pk):
    """Автосейв количества строки заказа (PATCH) / удаление строки (DELETE)."""
    line = get_object_or_404(
        models.PurchaseLine.objects.select_related('purchase'), pk=pk)
    purchase = line.purchase
    try:
        if request.method == 'DELETE':
            engine.remove_purchase_line(line)
        else:
            engine.update_purchase_line(line, _dec(request.data.get('qty')))
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.purchase_cockpit(purchase))


def _purchase_transition(request, pk, fn):
    """Общий обработчик перехода статуса заказа (send/unsend/cancel/restore)."""
    p = get_object_or_404(models.Purchase, pk=pk)
    try:
        fn(p)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.purchase_cockpit(p))


@api_view(['POST'])
def purchase_send(request, pk):
    """Отправить заказ (draft → sent) — мягкий замок, счёт в «заказано»."""
    return _purchase_transition(request, pk, engine.send_purchase)


@api_view(['POST'])
def purchase_unsend(request, pk):
    """Вернуть заказ в черновик (sent → draft)."""
    return _purchase_transition(request, pk, engine.unsend_purchase)


@api_view(['POST'])
def purchase_cancel(request, pk):
    """Отменить заказ (выводит из счёта «заказано»)."""
    return _purchase_transition(request, pk, engine.cancel_purchase)


@api_view(['POST'])
def purchase_restore(request, pk):
    """Восстановить отменённый заказ в черновик."""
    return _purchase_transition(request, pk, engine.restore_purchase)


@api_view(['GET'])
def project_purchases(request, pk):
    """Заказы проекта (не отменённые) — пикер связи прихода с заказом."""
    project = get_object_or_404(models.Project, pk=pk)
    rows = [
        {'id': p.id, 'status': p.status, 'date': p.date, 'note': p.note,
         'lines': p.lines.count()}
        for p in project.purchases.exclude(status=models.Purchase.Status.CANCELLED)
        .order_by('-id')
    ]
    return Response(rows)


@api_view(['POST'])
def project_order(request, pk):
    """Мост «дефицит → заказ»: положить позицию в draft-заказ проекта.

    Возвращает id заказа (UI ведёт в кокпит). Оживляет ▲-член «заказано» дефицита.
    """
    project = get_object_or_404(models.Project, pk=pk)
    d = request.data
    try:
        item = models.Item.objects.get(pk=d['item_id'])
        p = engine.add_to_project_order(project, item, _dec(d.get('qty')),
                                        _actor(request))
    except (KeyError, models.Item.DoesNotExist) as e:
        return _bad(f'Нужны item_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response({'purchase_id': p.id}, status=http.HTTP_201_CREATED)


# --------------------------------------------------------------------------- #
#  Передача / Transfer (волна 5 — записываемое ядро): отгрузка заказчику
# --------------------------------------------------------------------------- #
def _transfer_row(t):
    """Строка списка передач для дерева навигации."""
    return {
        'id': t.id, 'number': t.number, 'date': t.date,
        'project_code': t.project.code, 'posted': t.posted,
        'lines': t.lines.count(),
    }


@api_view(['GET', 'POST'])
def transfers(request):
    """Список передач (дерево) / создание новой накладной (призрачная строка)."""
    if request.method == 'POST':
        d = request.data
        try:
            project = models.Project.objects.get(pk=d['project_id'])
            t = engine.create_transfer(
                project, _actor(request), d.get('number') or '',
                date=d.get('date') or timezone.localdate())
        except (KeyError, models.Project.DoesNotExist) as e:
            return _bad(f'Нужны project_id, number ({e}).')
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
        return Response(engine.transfer_cockpit(t), status=http.HTTP_201_CREATED)

    rows = [_transfer_row(t) for t in models.Transfer.objects
            .select_related('project').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH'])
def transfer_detail(request, pk):
    """Кокпит передачи: строки-лоты накладной + живой остаток источника + итог.
    PATCH — правка шапки (№ накладной / дата) прямо в кокпите."""
    t = get_object_or_404(models.Transfer, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_transfer(
                t, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(engine.transfer_cockpit(t))


@api_view(['POST'])
def transfer_lines(request, pk):
    """Добавить строку передачи — отгрузка партии заказчику (`−ISSUE`)."""
    t = get_object_or_404(models.Transfer, pk=pk)
    d = request.data
    try:
        lot = models.Lot.objects.get(pk=d['lot_id'])
        engine.add_transfer_line(t, lot, _dec(d.get('qty')),
                                 display_name=d.get('display_name') or '')
    except (KeyError, models.Lot.DoesNotExist) as e:
        return _bad(f'Нужны lot_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.transfer_cockpit(t), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def transfer_line_detail(request, pk):
    """Автосейв строки передачи (кол-во/имя) (PATCH) / удаление строки (DELETE)."""
    line = get_object_or_404(
        models.TransferLine.objects.select_related('transfer', 'lot'), pk=pk)
    transfer = line.transfer
    try:
        if request.method == 'DELETE':
            engine.remove_transfer_line(line)
        else:
            d = request.data
            engine.update_transfer_line(
                line,
                qty=_dec(d['qty']) if 'qty' in d else None,
                display_name=d['display_name'] if 'display_name' in d else None)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.transfer_cockpit(transfer))


@api_view(['POST'])
def transfer_post(request, pk):
    """Поставить замок «отгружено» — накладная read-only."""
    t = get_object_or_404(models.Transfer, pk=pk)
    try:
        engine.post_transfer(t)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.transfer_cockpit(t))


@api_view(['POST'])
def transfer_unpost(request, pk):
    """Снять замок — снова разрешить правку накладной."""
    t = get_object_or_404(models.Transfer, pk=pk)
    engine.unpost_transfer(t)
    return Response(engine.transfer_cockpit(t))


@api_view(['GET'])
def project_available_lots(request, pk):
    """Лоты проекта с остатком > 0 — пикер строки передачи/списания."""
    project = get_object_or_404(models.Project, pk=pk)
    return Response(engine.project_available_lots(project))


# --------------------------------------------------------------------------- #
#  Закрытие проекта (волна 6): списание / требование + панель + мягкий замок
# --------------------------------------------------------------------------- #
@api_view(['GET'])
def available_lots(request):
    """Лоты всех проектов с остатком > 0 — сквозной пикер источника требования."""
    return Response(engine.all_available_lots())


# ── Списание / Writeoff ──
def _writeoff_row(w):
    return {
        'id': w.id, 'number': w.number, 'date': w.date,
        'project_code': w.project.code, 'reason': w.reason, 'lines': w.lines.count(),
    }


@api_view(['GET', 'POST'])
def writeoffs(request):
    """Список списаний (дерево) / создание нового акта (призрачная строка)."""
    if request.method == 'POST':
        d = request.data
        try:
            project = models.Project.objects.get(pk=d['project_id'])
            w = engine.create_writeoff(
                project, _actor(request), d.get('number') or '',
                date=d.get('date') or timezone.localdate(),
                reason=d.get('reason') or '')
        except (KeyError, models.Project.DoesNotExist) as e:
            return _bad(f'Нужны project_id, number ({e}).')
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
        return Response(engine.writeoff_cockpit(w), status=http.HTTP_201_CREATED)

    rows = [_writeoff_row(w) for w in models.Writeoff.objects
            .select_related('project').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH'])
def writeoff_detail(request, pk):
    """Кокпит списания: строки-лоты (`−ISSUE`) + живой остаток источника + итог.
    PATCH — правка шапки (№ акта / дата / причина) прямо в кокпите."""
    w = get_object_or_404(models.Writeoff, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_writeoff(
                w, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None,
                reason=d['reason'] if 'reason' in d else None)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(engine.writeoff_cockpit(w))


@api_view(['POST'])
def writeoff_lines(request, pk):
    """Добавить строку списания — выбытие партии из проекта (`−ISSUE`)."""
    w = get_object_or_404(models.Writeoff, pk=pk)
    d = request.data
    try:
        lot = models.Lot.objects.get(pk=d['lot_id'])
        engine.add_writeoff_line(w, lot, _dec(d.get('qty')))
    except (KeyError, models.Lot.DoesNotExist) as e:
        return _bad(f'Нужны lot_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.writeoff_cockpit(w), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def writeoff_line_detail(request, pk):
    """Автосейв количества строки списания (PATCH) / удаление строки (DELETE)."""
    line = get_object_or_404(
        models.WriteoffLine.objects.select_related('writeoff', 'lot'), pk=pk)
    writeoff = line.writeoff
    try:
        if request.method == 'DELETE':
            engine.remove_writeoff_line(line)
        else:
            engine.update_writeoff_line(line, _dec(request.data.get('qty')))
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.writeoff_cockpit(writeoff))


# ── Требование / Requisition ──
def _requisition_row(r):
    return {
        'id': r.id, 'number': r.number, 'date': r.date,
        'project_code': r.project.code, 'lines': r.lines.count(),
    }


@api_view(['GET', 'POST'])
def requisitions(request):
    """Список требований (дерево) / создание нового (проект-получатель)."""
    if request.method == 'POST':
        d = request.data
        try:
            project = models.Project.objects.get(pk=d['project_id'])
            r = engine.create_requisition(
                project, _actor(request), d.get('number') or '',
                date=d.get('date') or timezone.localdate())
        except (KeyError, models.Project.DoesNotExist) as e:
            return _bad(f'Нужны project_id, number ({e}).')
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
        return Response(engine.requisition_cockpit(r), status=http.HTTP_201_CREATED)

    rows = [_requisition_row(r) for r in models.Requisition.objects
            .select_related('project').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH'])
def requisition_detail(request, pk):
    """Кокпит требования: строки (источник → потомок) + живой остаток источника.
    PATCH — правка шапки (№ / дата) прямо в кокпите."""
    r = get_object_or_404(models.Requisition, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_requisition(
                r, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(engine.requisition_cockpit(r))


@api_view(['POST'])
def requisition_lines(request, pk):
    """Добавить строку требования — отпочкование (`−ISSUE` источника + `+RECEIPT`)."""
    r = get_object_or_404(models.Requisition, pk=pk)
    d = request.data
    try:
        source = models.Lot.objects.get(pk=d['source_lot_id'])
        engine.add_requisition_line(r, source, _dec(d.get('qty')))
    except (KeyError, models.Lot.DoesNotExist) as e:
        return _bad(f'Нужны source_lot_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.requisition_cockpit(r), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def requisition_line_detail(request, pk):
    """Автосейв количества строки требования (PATCH) / удаление строки (DELETE)."""
    line = get_object_or_404(
        models.RequisitionLine.objects.select_related('requisition', 'source_lot'),
        pk=pk)
    requisition = line.requisition
    try:
        if request.method == 'DELETE':
            engine.remove_requisition_line(line)
        else:
            engine.update_requisition_line(line, _dec(request.data.get('qty')))
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.requisition_cockpit(requisition))


# ── Инвентаризация / Inventory (записываемое ядро, волна 9) ──
def _inventory_row(i):
    return {
        'id': i.id, 'number': i.number, 'date': i.date,
        'project_code': i.project.code, 'note': i.note, 'lines': i.lots.count(),
    }


@api_view(['GET', 'POST'])
def inventories(request):
    """Список инвентаризаций (дерево) / создание нового акта (проект-дом)."""
    if request.method == 'POST':
        d = request.data
        try:
            project = models.Project.objects.get(pk=d['project_id'])
            i = engine.create_inventory(
                project, _actor(request), d.get('number') or '',
                date=d.get('date') or timezone.localdate(),
                note=d.get('note') or '')
        except (KeyError, models.Project.DoesNotExist) as e:
            return _bad(f'Нужны project_id, number ({e}).')
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
        return Response(engine.inventory_cockpit(i), status=http.HTTP_201_CREATED)

    rows = [_inventory_row(i) for i in models.Inventory.objects
            .select_related('project').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH'])
def inventory_detail(request, pk):
    """Кокпит инвентаризации: строки-лоты (`+RECEIPT`) + провенанс + итог.
    PATCH — правка шапки (№ акта / дата / примечание) прямо в кокпите."""
    i = get_object_or_404(models.Inventory, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_inventory(
                i, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None,
                note=d['note'] if 'note' in d else None)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(engine.inventory_cockpit(i))


@api_view(['POST'])
def inventory_lots(request, pk):
    """Добавить строку акта — рождается «найденная» партия (`+RECEIPT`).

    `predecessor_id` (опц.) — списанный лот-источник (ре-материализация серого
    остатка): item/цена/название/зав.№ наследуются, если не заданы явно.
    """
    i = get_object_or_404(models.Inventory, pk=pk)
    d = request.data
    try:
        pred = None
        if d.get('predecessor_id'):
            pred = models.Lot.objects.select_related('item').get(pk=d['predecessor_id'])
        if pred is not None:
            item = pred.item
            unit_cost = _dec(d.get('unit_cost'))
            unit_cost = pred.unit_cost if unit_cost is None else unit_cost
            received_name = d['received_name'] if 'received_name' in d else pred.received_name
            serial_number = d['serial_number'] if 'serial_number' in d else pred.serial_number
        else:
            item = models.Item.objects.get(pk=d['item_id'])
            unit_cost = _dec(d.get('unit_cost')) or engine.ZERO
            received_name = d.get('received_name') or ''
            serial_number = d.get('serial_number') or ''
        engine.add_inventory_lot(
            i, item, _dec(d.get('qty')), unit_cost=unit_cost,
            received_name=received_name, serial_number=serial_number,
            predecessor=pred)
    except (KeyError, models.Item.DoesNotExist, models.Lot.DoesNotExist) as e:
        return _bad(f'Нужны item_id (или predecessor_id), qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.inventory_cockpit(i), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def inventory_lot_detail(request, pk):
    """Автосейв строки акта (PATCH) / удаление строки (DELETE)."""
    lot = get_object_or_404(
        models.Lot.objects.select_related('inventory', 'item'), pk=pk)
    if lot.inventory_id is None:
        return _bad('Партия не из инвентаризации — правка через её origin-документ.')
    inventory = lot.inventory
    try:
        if request.method == 'DELETE':
            engine.remove_inventory_lot(lot)
        else:
            d = request.data
            engine.update_inventory_lot(
                lot,
                qty=_dec(d['qty']) if 'qty' in d else None,
                unit_cost=_dec(d['unit_cost']) if 'unit_cost' in d else None,
                received_name=d['received_name'] if 'received_name' in d else None,
                serial_number=d['serial_number'] if 'serial_number' in d else None)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.inventory_cockpit(inventory))


@api_view(['GET'])
def written_off_lots(request):
    """Списанные лоты — пикер ре-материализации (серый остаток → на баланс)."""
    return Response(engine.written_off_lots())


# ── Панель закрытия проекта + мосты + мягкий замок ──
@api_view(['GET'])
def project_closure(request, pk):
    """Панель закрытия проекта: остаточные лоты (live≠0) + готовность к закрытию."""
    project = get_object_or_404(models.Project, pk=pk)
    return Response(engine.project_closure(project))


@api_view(['POST'])
def project_writeoff_lot(request, pk):
    """Мост «списать остаток»: свести лот проекта в 0 актом списания (`−ISSUE`)."""
    project = get_object_or_404(models.Project, pk=pk)
    d = request.data
    try:
        lot = models.Lot.objects.get(pk=d['lot_id'])
        engine.writeoff_lot(project, lot, _dec(d.get('qty')), _actor(request))
    except (KeyError, models.Lot.DoesNotExist) as e:
        return _bad(f'Нужны lot_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.project_closure(project))


@api_view(['POST'])
def project_stock_lot(request, pk):
    """Мост «на баланс»: отпочковать остаток проекта в белый «Собственный склад»."""
    project = get_object_or_404(models.Project, pk=pk)
    d = request.data
    try:
        lot = models.Lot.objects.get(pk=d['lot_id'])
        engine.requisition_lot(project, lot, _dec(d.get('qty')), _actor(request))
    except (KeyError, models.Lot.DoesNotExist) as e:
        return _bad(f'Нужны lot_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.project_closure(project))


@api_view(['POST'])
def project_close(request, pk):
    """Закрыть проект (`active → closed`) — мягкий замок-веха (gate: остатков нет)."""
    project = get_object_or_404(models.Project, pk=pk)
    try:
        engine.close_project(project)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.project_closure(project))


@api_view(['POST'])
def project_reopen(request, pk):
    """Переоткрыть закрытый проект (`closed → active`)."""
    project = get_object_or_404(models.Project, pk=pk)
    try:
        engine.reopen_project(project)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.project_closure(project))


# --------------------------------------------------------------------------- #
#  Планирование закупок (волна 7): командный свод + записываемый Procurement
# --------------------------------------------------------------------------- #
@api_view(['GET'])
def command_deficit(request):
    """Командный свод: суммарный дефицит по оси Item через все активные внешние проекты."""
    return Response(engine.command_deficit())


@api_view(['POST'])
def command_deficit_add(request):
    """Мост «свод → закупка»: положить позицию в draft-`Procurement` (создаст при нужде).

    Возвращает id закупки (UI ведёт в кокпит плана).
    """
    d = request.data
    try:
        item = models.Item.objects.get(pk=d['item_id'])
        p = engine.add_to_procurement(item, _dec(d.get('qty')), _actor(request))
    except (KeyError, models.Item.DoesNotExist) as e:
        return _bad(f'Нужны item_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response({'procurement_id': p.id}, status=http.HTTP_201_CREATED)


def _procurement_row(p):
    """Строка списка закупок-планов для дерева навигации."""
    return {
        'id': p.id, 'status': p.status, 'date': p.date, 'note': p.note,
        'lines': p.lines.count(),
    }


@api_view(['GET', 'POST'])
def procurements(request):
    """Список закупок-планов (дерево) / создание новой (призрачная строка)."""
    if request.method == 'POST':
        d = request.data
        p = engine.create_procurement(_actor(request),
                                      date=d.get('date') or None,
                                      note=(d.get('note') or '').strip())
        return Response(engine.procurement_cockpit(p), status=http.HTTP_201_CREATED)

    # только закупки-планы (без 1:1-заглушек проектных заказов, см. engine)
    rows = [_procurement_row(p)
            for p in engine._plan_procurements().order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH'])
def procurement_detail(request, pk):
    """Кокпит закупки-плана: строки (item, qty) + итог.
    PATCH — правка шапки (дата / примечание) прямо в кокпите."""
    p = get_object_or_404(models.Procurement, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_procurement(
                p, date=d['date'] if 'date' in d else None,
                note=d['note'] if 'note' in d else None)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(engine.procurement_cockpit(p))


@api_view(['POST'])
def procurement_lines(request, pk):
    """Добавить строку закупки-плана (только в черновике)."""
    p = get_object_or_404(models.Procurement, pk=pk)
    d = request.data
    try:
        item = models.Item.objects.get(pk=d['item_id'])
        engine.add_procurement_line(p, item, _dec(d.get('qty')))
    except (KeyError, models.Item.DoesNotExist) as e:
        return _bad(f'Нужны item_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.procurement_cockpit(p), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def procurement_line_detail(request, pk):
    """Автосейв количества строки закупки-плана (PATCH) / удаление (DELETE)."""
    line = get_object_or_404(
        models.ProcurementLine.objects.select_related('procurement'), pk=pk)
    procurement = line.procurement
    try:
        if request.method == 'DELETE':
            engine.remove_procurement_line(line)
        else:
            engine.update_procurement_line(line, _dec(request.data.get('qty')))
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.procurement_cockpit(procurement))


def _procurement_transition(request, pk, fn):
    """Общий обработчик перехода статуса закупки-плана (send/unsend/cancel/restore)."""
    p = get_object_or_404(models.Procurement, pk=pk)
    try:
        fn(p)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.procurement_cockpit(p))


@api_view(['POST'])
def procurement_send(request, pk):
    """Отправить закупку-план (draft → sent) — мягкий замок, строки read-only."""
    return _procurement_transition(request, pk, engine.send_procurement)


@api_view(['POST'])
def procurement_unsend(request, pk):
    """Вернуть закупку-план в черновик (sent → draft)."""
    return _procurement_transition(request, pk, engine.unsend_procurement)


@api_view(['POST'])
def procurement_cancel(request, pk):
    """Отменить закупку-план (не удаляет)."""
    return _procurement_transition(request, pk, engine.cancel_procurement)


@api_view(['POST'])
def procurement_restore(request, pk):
    """Восстановить отменённую закупку-план в черновик."""
    return _procurement_transition(request, pk, engine.restore_procurement)


@api_view(['GET'])
def procurement_order_xlsx(request, pk):
    """Выгрузка `order.xlsx` закупки-плана — файл поставщику (attachment)."""
    p = get_object_or_404(models.Procurement, pk=pk)
    data = engine.procurement_xlsx(p)
    resp = HttpResponse(
        data,
        content_type=('application/vnd.openxmlformats-officedocument'
                      '.spreadsheetml.sheet'))
    resp['Content-Disposition'] = (
        f'attachment; filename="order-{p.id}.xlsx"')
    return resp


# --------------------------------------------------------------------------- #
#  Pegging (волна 8): нарезка плана-`Procurement` на проектные заказы-`Purchase`
# --------------------------------------------------------------------------- #
@api_view(['GET'])
def procurement_pegging(request, pk):
    """Проекция pegging плана: распределение строк по проектам + веер заказов."""
    p = get_object_or_404(models.Procurement, pk=pk)
    return Response(engine.procurement_pegging(p))


@api_view(['POST'])
def procurement_peg(request, pk):
    """Пегнуть кол-во строки плана на проект (строка проектного заказа под этим планом)."""
    p = get_object_or_404(models.Procurement, pk=pk)
    d = request.data
    try:
        item = models.Item.objects.get(pk=d['item_id'])
        project = models.Project.objects.get(pk=d['project_id'])
        engine.peg_procurement_line(p, item, project, _dec(d.get('qty')),
                                    _actor(request))
    except (KeyError, models.Item.DoesNotExist, models.Project.DoesNotExist) as e:
        return _bad(f'Нужны item_id, project_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.procurement_pegging(p))


@api_view(['POST'])
def procurement_unpeg(request, pk):
    """Снять пег (item, project) под этим планом — удалить строку проектного заказа."""
    p = get_object_or_404(models.Procurement, pk=pk)
    d = request.data
    try:
        item = models.Item.objects.get(pk=d['item_id'])
        project = models.Project.objects.get(pk=d['project_id'])
        engine.unpeg_procurement_line(p, item, project)
    except (KeyError, models.Item.DoesNotExist, models.Project.DoesNotExist) as e:
        return _bad(f'Нужны item_id, project_id ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.procurement_pegging(p))


@api_view(['POST'])
def procurement_autopeg(request, pk):
    """Разрезать план по проектам в один клик (топ-ап до наводки свода)."""
    p = get_object_or_404(models.Procurement, pk=pk)
    try:
        engine.autopeg_procurement(p, _actor(request))
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.procurement_pegging(p))
