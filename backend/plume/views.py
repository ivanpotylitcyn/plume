"""API волны 1 — только read-only проекции движка (ввод данных идёт через admin).

Проекции отдаём как есть из engine.py; редактирование — в документах, не в линзе.
"""
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import engine, models


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
