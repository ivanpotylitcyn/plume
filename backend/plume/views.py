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


@api_view(['GET'])
def projects(request):
    """Список проектов для дерева навигации."""
    data = [
        {'id': p.id, 'code': p.code, 'name': p.name, 'kind': p.kind,
         'status': p.status}
        for p in models.Project.objects.all()
    ]
    return Response(data)


@api_view(['GET'])
def items(request):
    """Список изделий для дерева/карты."""
    data = [
        {'id': i.id, 'code': i.code, 'name': i.name, 'kind': i.kind,
         'uom': i.uom, 'is_manufactured': i.is_manufactured}
        for i in models.Item.objects.filter(active=True)
    ]
    return Response(data)


@api_view(['GET'])
def project_deficit(request, pk):
    """Дефицит проекта (дашборд): тройной разбор ✓/●/▲, worst-of цвет."""
    project = get_object_or_404(models.Project, pk=pk)
    return Response(engine.project_deficit(project))


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


@api_view(['GET'])
def kitting_detail(request, pk):
    """Кокпит комплектации: BOM 1 уровень, реальные + призрачные строки."""
    k = get_object_or_404(models.Kitting, pk=pk)
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


@api_view(['GET'])
def receipt_detail(request, pk):
    """Кокпит прихода: строки-лоты УПД + живой остаток + сумма."""
    r = get_object_or_404(models.Receipt, pk=pk)
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


@api_view(['GET'])
def purchase_detail(request, pk):
    """Кокпит заказа: строки (заказано/поступило/остаток) + связанные приходы."""
    p = get_object_or_404(models.Purchase, pk=pk)
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


@api_view(['GET'])
def transfer_detail(request, pk):
    """Кокпит передачи: строки-лоты накладной + живой остаток источника + итог."""
    t = get_object_or_404(models.Transfer, pk=pk)
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
    """Лоты проекта с остатком > 0 — пикер строки передачи."""
    project = get_object_or_404(models.Project, pk=pk)
    return Response(engine.project_available_lots(project))
