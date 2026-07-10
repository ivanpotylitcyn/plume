"""API движка plume.

Волна 1 — read-only проекции (дефицит, карта остатков, экран изделия).
Волна 2 — записываемое ядро: кокпит комплектации (пайка = промоушн призрачной
строки в `KittingLine`, автосейв qty, закрытие/переоткрытие). Правила мутаций
живут в `engine.py`; вьюхи только разбирают запрос и маппят ошибки в 400.
Волна 3 — приход/УПД (рождение лотов, замок). Волна 4 — заказ (Purchase) +
связь `Receipt↔Purchase` + мост «дефицит → заказ».
"""
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status as http
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import engine, models

User = get_user_model()


def _dec(value):
    """Разобрать количество в Decimal (через str — без float-погрешности)."""
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def _actor(request):
    """Автор документа — залогиненный пользователь.

    Волна 12: весь /api/ за `IsAuthenticated`, так что в мутационных вьюхах
    `request.user` всегда настоящий пользователь (fallback на суперюзера, живший
    до логин-экрана, убран). Авторство остаётся «на документах».
    """
    return request.user


def _resolve_author(d):
    """Автор из PATCH-тела (Ф2j): ключ `user_id` прислан → этот `User` (авторство
    правится на форме под замком); ключа нет → часовой `_UNSET` (не трогаем).
    `User.DoesNotExist` пробрасывается — ловит вызывающий (→ 400)."""
    if 'user_id' not in d:
        return engine._UNSET
    return User.objects.get(pk=d['user_id'])


def _bad(exc):
    return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)


def _delete_order(doc):
    """DELETE складского ордера с единым friendly-guard (В13 Ф1b): draft — свободно;
    posted — «сперва расфиксировать»; `PROTECT` бережёт потраченные лоты. 204 при
    успехе, 400 с текстом — при отказе."""
    try:
        engine.delete_stock_document(doc)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(status=http.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([AllowAny])
def ping(request):
    return Response({'status': 'ok', 'app': 'plume'})


# --------------------------------------------------------------------------- #
#  Аутентификация (волна 12): вход/выход сессией + «кто я».
# --------------------------------------------------------------------------- #
def _user_payload(u):
    return {'id': u.id, 'username': u.username,
            'full_name': u.get_full_name() or u.username,
            'is_superuser': u.is_superuser}


@api_view(['GET'])
def users(request):
    """Список пользователей — пикер авторства шапки ордера (Ф2j). Активные,
    по человеческому имени; авторство правится на форме под замком."""
    rows = [_user_payload(u) for u in
            User.objects.filter(is_active=True).order_by('first_name', 'username')]
    return Response(rows)


@ensure_csrf_cookie
@api_view(['GET'])
@permission_classes([AllowAny])
def me(request):
    """Текущий пользователь (или 401). Заодно ставит CSRF-cookie — фронт зовёт
    этот эндпоинт на старте, чтобы получить токен до POST-логина/мутаций."""
    if not request.user.is_authenticated:
        return Response({'detail': 'not authenticated'},
                        status=http.HTTP_401_UNAUTHORIZED)
    return Response(_user_payload(request.user))


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """Вход по логину/паролю → сессия. Пользователи заводятся в admin
    (внутренний инструмент, сам-регистрации нет)."""
    username = (request.data.get('username') or '').strip()
    password = request.data.get('password') or ''
    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({'detail': 'Неверный логин или пароль'},
                        status=http.HTTP_400_BAD_REQUEST)
    login(request, user)
    return Response(_user_payload(user))


@api_view(['POST'])
def logout_view(request):
    """Выход — гасит сессию (требует логина; CSRF форсится SessionAuth)."""
    logout(request)
    return Response(status=http.HTTP_204_NO_CONTENT)


def _project_row(p):
    return {'id': p.id, 'code': p.code, 'name': p.name, 'kind': p.kind,
            'status': p.status}


def _project_detail_row(p):
    """Полный ряд проекта для формы (шапка под замком §6): + бюджет и дата начала."""
    return {**_project_row(p), 'budget': p.budget, 'started_at': p.started_at}


@api_view(['GET', 'PATCH'])
def project_detail(request, pk):
    """Реквизиты проекта для шапки формы (GET) / правка под замком §6 (PATCH):
    название, бюджет, дата начала — частичный, только присланные поля."""
    project = get_object_or_404(models.Project, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        changes = {k: d[k] for k in ('name', 'started_at') if k in d}
        if 'budget' in d:
            changes['budget'] = _dec(d['budget'])
        try:
            engine.update_project(project, changes)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(_project_detail_row(project))


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


@api_view(['POST'])
def project_demands(request, pk):
    """Добавить прибор в потребность проекта (секция «Приборы»). Возвращает дефицит."""
    project = get_object_or_404(models.Project, pk=pk)
    d = request.data
    try:
        item = models.Item.objects.get(pk=d['target_item_id'])
        engine.add_project_demand(project, item, _dec(d.get('qty')))
    except (KeyError, models.Item.DoesNotExist) as e:
        return _bad(f'Нужны target_item_id и qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.project_deficit(project), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def project_demand_detail(request, pk):
    """Автосейв кол-ва приборов (PATCH) / удаление прибора из потребности (DELETE)."""
    demand = get_object_or_404(
        models.ProjectDemand.objects.select_related('project'), pk=pk)
    project = demand.project
    try:
        if request.method == 'DELETE':
            engine.remove_project_demand(demand)
        else:
            engine.update_project_demand(demand, _dec(request.data.get('qty')))
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.project_deficit(project))


@api_view(['GET'])
def project_budget(request, pk):
    """Бюджет проекта (north-star окупаемости): потрачено/план/компас + себестоимость/экономия."""
    project = get_object_or_404(models.Project, pk=pk)
    return Response(engine.project_budget(project))


def _item_detail_payload(item):
    """Проекция экрана изделия: свойства + окружение из связей (where-used, лоты)."""
    where_used = [
        {'parent_id': bl.parent_id, 'parent_code': bl.parent.code,
         'parent_name': bl.parent.name, 'qty': bl.qty}
        for bl in item.used_in.select_related('parent')
    ]
    bom = [
        {'id': bl.id, 'component_id': bl.component_id,
         'component_code': bl.component.code,
         'component_name': bl.component.name, 'component_uom': bl.component.uom,
         'qty': bl.qty, 'position': bl.position}
        for bl in item.bom_lines.select_related('component')
    ]
    lots = [
        {'id': lot.id, 'project_code': lot.project.code, 'origin': lot.origin_kind,
         'qty_born': lot.qty, 'live_qty': engine.lot_live_qty(lot),
         'unit_cost': lot.unit_cost, 'part_number': lot.part_number,
         'lot_name': lot.lot_name}
        for lot in item.lots.select_related('project', 'origin')
    ]
    return {
        'id': item.id, 'code': item.code, 'name': item.name, 'kind': item.kind,
        'uom': item.uom, 'is_manufactured': item.is_manufactured,
        'estimated_cost': item.estimated_cost,
        'bom': bom, 'where_used': where_used, 'lots': lots,
        'shipments': engine.item_shipments(item),
    }


_ITEM_TEXT_FIELDS = ('code', 'name', 'kind', 'uom', 'is_manufactured')


@api_view(['GET', 'PATCH'])
def item_detail(request, pk):
    """Экран изделия: свойства + окружение из связей (where-used, лоты) + карта.
    PATCH — правка свойств под замком формы (§6): частичный, только присланные поля."""
    item = get_object_or_404(models.Item, pk=pk)
    if request.method == 'PATCH':
        d = request.data
        changes = {k: d[k] for k in _ITEM_TEXT_FIELDS if k in d}
        if 'estimated_cost' in d:
            changes['estimated_cost'] = _dec(d['estimated_cost'])
        try:
            engine.update_item(item, changes)
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
    return Response(_item_detail_payload(item))


@api_view(['POST'])
def item_bom(request, pk):
    """Добавить компонент в состав изделия (редактор BOM). Возвращает экран изделия."""
    parent = get_object_or_404(models.Item, pk=pk)
    d = request.data
    try:
        component = models.Item.objects.get(pk=d['component_id'])
        engine.add_bom_line(parent, component, _dec(d.get('qty')),
                            position=d.get('position') or '')
    except (KeyError, models.Item.DoesNotExist) as e:
        return _bad(f'Нужны component_id и qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(_item_detail_payload(parent), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def bom_line_detail(request, pk):
    """Автосейв кол-ва/позиции строки состава (PATCH) / удаление (DELETE)."""
    line = get_object_or_404(models.BomLine.objects.select_related('parent'), pk=pk)
    parent = line.parent
    try:
        if request.method == 'DELETE':
            engine.remove_bom_line(line)
        else:
            d = request.data
            engine.update_bom_line(
                line,
                qty=_dec(d['qty']) if 'qty' in d else None,
                position=d['position'] if 'position' in d else None)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(_item_detail_payload(parent))


# --------------------------------------------------------------------------- #
#  Кокпит комплектации (волна 2 — записываемое ядро)
# --------------------------------------------------------------------------- #
def _kitting_row(k):
    """Строка списка комплектаций для дерева навигации."""
    return {
        'id': k.id, 'project_code': k.project.code,
        'target_code': k.target_item.code, 'target_name': k.target_item.name,
        'qty': k.qty, 'status': engine._kitting_status_out(k), 'date': k.date,
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
                qty=d.get('qty') or 1, date=timezone.localdate())
        except (KeyError, models.Project.DoesNotExist, models.Item.DoesNotExist) as e:
            return _bad(f'Нужны project_id и target_item_id ({e}).')
        return Response(engine.kitting_cockpit(k), status=http.HTTP_201_CREATED)

    rows = [_kitting_row(k) for k in models.Kitting.objects
            .select_related('project', 'target_item').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH', 'DELETE'])
def kitting_detail(request, pk):
    """Кокпит комплектации: BOM 1 уровень, реальные + призрачные строки.
    PATCH — правка шапки (кол-во образцов / дата) прямо в кокпите. DELETE — удаление."""
    k = get_object_or_404(models.Kitting, pk=pk)
    if request.method == 'DELETE':
        return _delete_order(k)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_kitting(
                k, qty=_dec(d['qty']) if 'qty' in d else None,
                date=d['date'] if 'date' in d else None, user=_resolve_author(d))
        except User.DoesNotExist:
            return _bad('Пользователь не найден.')
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
    line = get_object_or_404(
        models.StockLine.objects.select_related('document__kitting', 'lot'),
        pk=pk, document__kind=models.StockDocument.Kind.KITTING)
    kitting = line.document.kitting
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
def _counterparty_row(c):
    return {'id': c.id, 'name': c.name, 'inn': c.inn,
            'is_supplier': c.is_supplier, 'is_customer': c.is_customer}


@api_view(['GET', 'POST'])
def counterparties(request):
    """Контрагенты (пикер) с фильтром по роли + быстрое создание.

    GET `?role=supplier|customer` сужает список под пикер (приход → поставщики,
    передача → заказчики); без `role` — все. POST создаёт с ролью по контексту
    (`role`), по умолчанию поставщик (историческая роль сущности).
    """
    if request.method == 'POST':
        name = (request.data.get('name') or '').strip()
        if not name:
            return _bad('Нужно наименование контрагента.')
        role = request.data.get('role') or 'supplier'
        c = models.Counterparty.objects.create(
            name=name, inn=(request.data.get('inn') or '').strip(),
            is_supplier=(role == 'supplier'), is_customer=(role == 'customer'))
        return Response(_counterparty_row(c), status=http.HTTP_201_CREATED)
    qs = models.Counterparty.objects.all()
    role = request.GET.get('role')
    if role == 'supplier':
        qs = qs.filter(is_supplier=True)
    elif role == 'customer':
        qs = qs.filter(is_customer=True)
    return Response([_counterparty_row(c) for c in qs])


def _receipt_row(r):
    """Строка списка приходов для дерева навигации."""
    return {
        'id': r.id, 'number': r.number, 'date': r.date,
        'contractor_name': r.contractor.name, 'project_code': r.project.code,
        'approved': r.is_posted, 'lines': r.lots.count(),
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
            contractor = models.Counterparty.objects.get(pk=d['contractor_id'])
            project = models.Project.objects.get(pk=d['project_id'])
            r = models.Receipt.objects.create(
                number=number, date=d.get('date') or timezone.localdate(),
                contractor=contractor, project=project, user=_actor(request))
        except (KeyError, models.Counterparty.DoesNotExist,
                models.Project.DoesNotExist) as e:
            return _bad(f'Нужны contractor_id, project_id, number ({e}).')
        return Response(engine.receipt_cockpit(r), status=http.HTTP_201_CREATED)

    rows = [_receipt_row(r) for r in models.Receipt.objects
            .select_related('contractor', 'project').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH', 'DELETE'])
def receipt_detail(request, pk):
    """Кокпит прихода: строки-лоты УПД + живой остаток + сумма.
    PATCH — правка шапки (№ УПД / дата) прямо в кокпите. DELETE — удаление."""
    r = get_object_or_404(models.Receipt, pk=pk)
    if request.method == 'DELETE':
        return _delete_order(r)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_receipt(
                r, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None, user=_resolve_author(d))
        except User.DoesNotExist:
            return _bad('Пользователь не найден.')
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
            lot_name=d.get('lot_name') or '',
            part_number=d.get('part_number') or '')
    except (KeyError, models.Item.DoesNotExist) as e:
        return _bad(f'Нужны item_id, qty ({e}).')
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.receipt_cockpit(r), status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
def receipt_lot_detail(request, pk):
    """Автосейв строки УПД (PATCH) / удаление строки (DELETE)."""
    lot = get_object_or_404(
        models.Lot.objects.select_related('origin__receipt', 'item'), pk=pk)
    if lot.origin.kind != models.StockDocument.Kind.RECEIPT:
        return _bad('Партия не из прихода — правка через её origin-документ.')
    receipt = lot.origin.receipt
    try:
        if request.method == 'DELETE':
            engine.remove_receipt_lot(lot)
        else:
            d = request.data
            engine.update_receipt_lot(
                lot,
                qty=_dec(d['qty']) if 'qty' in d else None,
                unit_cost=_dec(d['unit_cost']) if 'unit_cost' in d else None,
                lot_name=d['lot_name'] if 'lot_name' in d else None,
                part_number=d['part_number'] if 'part_number' in d else None)
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
                note=d['note'] if 'note' in d else None, user=_resolve_author(d))
        except User.DoesNotExist:
            return _bad('Пользователь не найден.')
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
        'project_code': t.project.code, 'posted': t.is_posted,
        'lines': t.lines.count(),
    }


@api_view(['GET', 'POST'])
def transfers(request):
    """Список передач (дерево) / создание новой накладной (призрачная строка)."""
    if request.method == 'POST':
        d = request.data
        try:
            project = models.Project.objects.get(pk=d['project_id'])
            contractor = None
            if d.get('contractor_id'):
                contractor = models.Counterparty.objects.get(pk=d['contractor_id'])
            t = engine.create_transfer(
                project, _actor(request), d.get('number') or '',
                date=d.get('date') or timezone.localdate(), contractor=contractor)
        except (KeyError, models.Project.DoesNotExist,
                models.Counterparty.DoesNotExist) as e:
            return _bad(f'Нужны project_id, number ({e}).')
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
        return Response(engine.transfer_cockpit(t), status=http.HTTP_201_CREATED)

    rows = [_transfer_row(t) for t in models.Transfer.objects
            .select_related('project', 'contractor').order_by('-id')]
    return Response(rows)


@api_view(['GET', 'PATCH', 'DELETE'])
def transfer_detail(request, pk):
    """Кокпит передачи: строки-лоты накладной + живой остаток источника + итог.
    PATCH — правка шапки (№ накладной / дата) прямо в кокпите. DELETE — удаление."""
    t = get_object_or_404(models.Transfer, pk=pk)
    if request.method == 'DELETE':
        return _delete_order(t)
    if request.method == 'PATCH':
        d = request.data
        try:
            contractor = engine._UNSET
            if 'contractor_id' in d:
                cid = d['contractor_id']
                contractor = (models.Counterparty.objects.get(pk=cid)
                              if cid else None)
            engine.update_transfer(
                t, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None, contractor=contractor,
                user=_resolve_author(d))
        except models.Counterparty.DoesNotExist:
            return _bad('Контрагент не найден.')
        except User.DoesNotExist:
            return _bad('Пользователь не найден.')
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
        models.StockLine.objects.select_related('document__transfer', 'lot'),
        pk=pk, document__kind=models.StockDocument.Kind.TRANSFER)
    transfer = line.document.transfer
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
        'project_code': w.project.code, 'reason': w.reason,
        'posted': w.is_posted, 'lines': w.lines.count(),
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


@api_view(['GET', 'PATCH', 'DELETE'])
def writeoff_detail(request, pk):
    """Кокпит списания: строки-лоты (`−ISSUE`) + живой остаток источника + итог.
    PATCH — правка шапки (№ акта / дата / причина) прямо в кокпите. DELETE — удаление."""
    w = get_object_or_404(models.Writeoff, pk=pk)
    if request.method == 'DELETE':
        return _delete_order(w)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_writeoff(
                w, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None,
                reason=d['reason'] if 'reason' in d else None, user=_resolve_author(d))
        except User.DoesNotExist:
            return _bad('Пользователь не найден.')
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
        models.StockLine.objects.select_related('document__writeoff', 'lot'),
        pk=pk, document__kind=models.StockDocument.Kind.WRITEOFF)
    writeoff = line.document.writeoff
    try:
        if request.method == 'DELETE':
            engine.remove_writeoff_line(line)
        else:
            engine.update_writeoff_line(line, _dec(request.data.get('qty')))
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.writeoff_cockpit(writeoff))


@api_view(['POST'])
def writeoff_post(request, pk):
    """Провести списание — форма read-only (единый мягкий замок)."""
    w = get_object_or_404(models.Writeoff, pk=pk)
    try:
        engine.post_writeoff(w)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.writeoff_cockpit(w))


@api_view(['POST'])
def writeoff_unpost(request, pk):
    """Снять замок списания — снова разрешить правку."""
    w = get_object_or_404(models.Writeoff, pk=pk)
    engine.unpost_writeoff(w)
    return Response(engine.writeoff_cockpit(w))


# ── Требование / Requisition ──
def _requisition_row(r):
    return {
        'id': r.id, 'number': r.number, 'date': r.date,
        'project_code': r.project.code, 'posted': r.is_posted,
        'lines': r.lines.count(),
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


@api_view(['GET', 'PATCH', 'DELETE'])
def requisition_detail(request, pk):
    """Кокпит требования: строки (источник → потомок) + живой остаток источника.
    PATCH — правка шапки (№ / дата) прямо в кокпите. DELETE — удаление."""
    r = get_object_or_404(models.Requisition, pk=pk)
    if request.method == 'DELETE':
        return _delete_order(r)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_requisition(
                r, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None, user=_resolve_author(d))
        except User.DoesNotExist:
            return _bad('Пользователь не найден.')
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
        models.StockLine.objects.select_related('document__requisition', 'lot'),
        pk=pk, document__kind=models.StockDocument.Kind.REQUISITION)
    requisition = line.document.requisition
    try:
        if request.method == 'DELETE':
            engine.remove_requisition_line(line)
        else:
            engine.update_requisition_line(line, _dec(request.data.get('qty')))
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.requisition_cockpit(requisition))


@api_view(['POST'])
def requisition_post(request, pk):
    """Провести требование — форма read-only (единый мягкий замок)."""
    r = get_object_or_404(models.Requisition, pk=pk)
    try:
        engine.post_requisition(r)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.requisition_cockpit(r))


@api_view(['POST'])
def requisition_unpost(request, pk):
    """Снять замок требования — снова разрешить правку."""
    r = get_object_or_404(models.Requisition, pk=pk)
    engine.unpost_requisition(r)
    return Response(engine.requisition_cockpit(r))


# ── Инвентаризация / Inventory (записываемое ядро, волна 9) ──
def _inventory_row(i):
    return {
        'id': i.id, 'number': i.number, 'date': i.date,
        'project_code': i.project.code, 'note': i.note,
        'posted': i.is_posted, 'lines': i.lots.count(),
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


@api_view(['GET', 'PATCH', 'DELETE'])
def inventory_detail(request, pk):
    """Кокпит инвентаризации: строки-лоты (`+RECEIPT`) + провенанс + итог.
    PATCH — правка шапки (№ акта / дата / примечание) прямо в кокпите. DELETE — удаление."""
    i = get_object_or_404(models.Inventory, pk=pk)
    if request.method == 'DELETE':
        return _delete_order(i)
    if request.method == 'PATCH':
        d = request.data
        try:
            engine.update_inventory(
                i, number=d['number'] if 'number' in d else None,
                date=d['date'] if 'date' in d else None,
                note=d['note'] if 'note' in d else None, user=_resolve_author(d))
        except User.DoesNotExist:
            return _bad('Пользователь не найден.')
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
            lot_name = d['lot_name'] if 'lot_name' in d else pred.lot_name
            part_number = d['part_number'] if 'part_number' in d else pred.part_number
        else:
            item = models.Item.objects.get(pk=d['item_id'])
            unit_cost = _dec(d.get('unit_cost')) or engine.ZERO
            lot_name = d.get('lot_name') or ''
            part_number = d.get('part_number') or ''
        engine.add_inventory_lot(
            i, item, _dec(d.get('qty')), unit_cost=unit_cost,
            lot_name=lot_name, part_number=part_number,
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
        models.Lot.objects.select_related('origin__inventory', 'item'), pk=pk)
    if lot.origin.kind != models.StockDocument.Kind.INVENTORY:
        return _bad('Партия не из инвентаризации — правка через её origin-документ.')
    inventory = lot.origin.inventory
    try:
        if request.method == 'DELETE':
            engine.remove_inventory_lot(lot)
        else:
            d = request.data
            engine.update_inventory_lot(
                lot,
                qty=_dec(d['qty']) if 'qty' in d else None,
                unit_cost=_dec(d['unit_cost']) if 'unit_cost' in d else None,
                lot_name=d['lot_name'] if 'lot_name' in d else None,
                part_number=d['part_number'] if 'part_number' in d else None)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.inventory_cockpit(inventory))


@api_view(['POST'])
def inventory_post(request, pk):
    """Провести инвентаризацию — форма read-only (единый мягкий замок)."""
    i = get_object_or_404(models.Inventory, pk=pk)
    try:
        engine.post_inventory(i)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(engine.inventory_cockpit(i))


@api_view(['POST'])
def inventory_unpost(request, pk):
    """Снять замок инвентаризации — снова разрешить правку."""
    i = get_object_or_404(models.Inventory, pk=pk)
    engine.unpost_inventory(i)
    return Response(engine.inventory_cockpit(i))


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
                note=d['note'] if 'note' in d else None, user=_resolve_author(d))
        except User.DoesNotExist:
            return _bad('Пользователь не найден.')
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


# --------------------------------------------------------------------------- #
#  Вложения (волна 11): PDF/сканы к документам и изделиям (exclusive-arc владелец)
# --------------------------------------------------------------------------- #
@api_view(['GET', 'POST'])
def attachments(request, owner_type, owner_id):
    """Список вложений владельца (GET) / загрузка файла (POST, multipart).

    owner_type — имя FK-владельца (`receipt`/`transfer`/`item`/…); файл в поле
    `file`, подпись — в `label`. Автор берётся из документа (`_actor`).
    """
    if request.method == 'POST':
        try:
            owner = engine.resolve_attachment_owner(owner_type, owner_id)
            att = engine.add_attachment(
                owner_type, owner, request.FILES.get('file'),
                _actor(request), label=request.data.get('label') or '')
        except ValidationError as e:
            return _bad(e.messages[0] if e.messages else e)
        return Response(engine.attachment_row(att), status=http.HTTP_201_CREATED)
    try:
        rows = engine.attachments_for(owner_type, owner_id)
    except ValidationError as e:
        return _bad(e.messages[0] if e.messages else e)
    return Response(rows)


@api_view(['PATCH', 'DELETE'])
def attachment_detail(request, pk):
    """Правка подписи (PATCH `label`) / удаление вложения (DELETE — файл с диска)."""
    att = get_object_or_404(models.Attachment, pk=pk)
    if request.method == 'DELETE':
        engine.delete_attachment(att)
        return Response(status=http.HTTP_204_NO_CONTENT)
    d = request.data
    engine.update_attachment(att, label=d['label'] if 'label' in d else None)
    return Response(engine.attachment_row(att))


# Inline-безопасные типы: браузер их не выполнит как код. Всё прочее (html/svg с
# JS, zip, STEP, xlsx, …) отдаём как загрузку — иначе html/svg исполнился бы в
# нашем origin (хранимый XSS: доступ к сессии/CSRF, вызовы API от лица юзера).
# Вместе с nosniff это надёжно и против подделки content_type: даже если клиент
# соврёт «image/png» для html-файла, браузер не сниффит и как HTML не отрендерит.
_INLINE_CONTENT_TYPES = frozenset({
    'application/pdf',
    'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp',
})


@api_view(['GET'])
def attachment_download(request, pk):
    """Отдать файл вложения (стрим через WSGI; публичного /media/ нет).

    Безопасные типы (PDF/картинки) — inline (смотреть во вкладке), остальное —
    принудительная загрузка + `nosniff`. Место под проверку логина/прав — здесь.
    """
    att = get_object_or_404(models.Attachment, pk=pk)
    inline = att.content_type in _INLINE_CONTENT_TYPES
    resp = FileResponse(att.file.open('rb'), as_attachment=not inline,
                        filename=att.filename or f'attachment-{att.id}')
    if att.content_type:
        resp['Content-Type'] = att.content_type
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp
