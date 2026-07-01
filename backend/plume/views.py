"""API движка plume.

Волна 1 — read-only проекции (дефицит, карта остатков, экран изделия).
Волна 2 — записываемое ядро: кокпит комплектации (пайка = промоушн призрачной
строки в `KittingLine`, автосейв qty, закрытие/переоткрытие). Правила мутаций
живут в `engine.py`; вьюхи только разбирают запрос и маппят ошибки в 400.
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
        'stock_map': engine.stock_map(item),
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
