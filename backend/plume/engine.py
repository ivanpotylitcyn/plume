"""Движок-СППР plume.

Чистые функции-проекции над документами (один движок на всю линзу). Ничего не
кэшируем: всё вычислимое держим свежим (данных мало, без Celery).

Волна 1:
- `rebuild_movements(lot)` — пересборка StockMovement партии из её документов.
- `lot_live_qty` / `item_available` — живые остатки.
- `project_deficit(project)` — дефицит проекта (надо − склад − заказано),
  1 уровень BOM, тройной разбор ✓/●/▲, worst-of цвет.
- `stock_map(item)` — карта остатков Item по всем складам-проектам (north-star).

Волна 2 (записываемое ядро + форма Kitting):
- `kitting_form(kitting)` — проекция формы сборки: BOM 1 уровень, реальные
  (пробитые) строки + призрачные строки, покрашенные по доступности + лоты-кандидаты.
- `lock_kitting` / `unlock_kitting` — рождение/снятие лота-прибора (мягкий замок).

Волна 3 (записываемый приход / УПД):
- `receipt_form(receipt)` — проекция формы прихода: строки-лоты УПД (в модели
  отдельной ReceiptLine нет — строки прихода это его лоты) + живой остаток + сумма.
- `add/update/remove_receipt_lot`, `lock/unlock_receipt` — рождение лотов
  (`+RECEIPT`) и мягкий замок «сверено со сканом».

Волна 4 (записываемый заказ / Purchase + связь с приходом):
- `purchase_form(purchase)` — шапка + строки (заказано/поступило/остаток) + приходы;
  `create_purchase`, `add/update/remove_purchase_line`, `send/unsend/cancel/restore_purchase`.
- `set_receipt_purchase(receipt, purchase)` — связь `Receipt↔Purchase` (гашение заказа).
- `lines_estimate(lines)` — прогноз денег документа-намерения: `Σ(qty×estimated_cost)`
  + коды позиций без оценки. Общий для заказа и закупки-плана (поле «Оценка» в шапке).

Волна 5 (записываемая передача / Transfer — отгрузка заказчику):
- `transfer_form(transfer)` — шапка накладной + строки-лоты (отдаём партию заказчику,
  `−ISSUE`) + живой остаток источника + итог; `project_available_lots(project)` — пикер
  отдаваемых лотов (live>0). `create_transfer`, `add/update/remove_transfer_line`.
- Мягкий замок «отгружено» (единый `locked`, волна 13 Ф1):
  `lock_transfer`/`unlock_transfer` — под замком форма read-only; снятие ничего не
  разрушает (guard по потомкам не нужен). Лента `item_movements(item)` — ВСЕ ордера,
  коснувшиеся изделия (рождения партий + движения), для его экрана; заменила узкую
  `item_shipments` в волне 19 (Ф12a).

Волна 6 (закрытие проекта — сведение остатков в 0 + мягкий замок):
- `writeoff_form` / `create_writeoff` / `add|update|remove_writeoff_line` — списание
  (`−ISSUE`, лот покидает учёт; серый путь). `requisition_form` / `create_requisition`
  / `add|update|remove_requisition_line` — требование/отпочкование (`−ISSUE` источника +
  рождение лота-потомка в проекте-получателе, `+RECEIPT`; белый путь / заём).
- `project_closure(project)` — панель сведения остаточных лотов (live≠0) в 0 +
  готовность; `lock_project`/`unlock_project` — мягкий замок-веха «проект отработан».
- Мосты панели: `writeoff_lot` (списать остаток) / `requisition_lot` (на баланс → белый).

Волна 7 (планирование закупок — записываемый Procurement; с волны 24 — источник правды):
- `scope_demand(projects)` — свод покупных листьев через **заданный набор** проектов,
  колонками «Потребности» (Потр. · Компл. · Склад · Заказ · Баланс). Витрина.
- `procurement_demand(proc)` = свод по проекту закупки + отметка `in_lines` (таб
  «Потребность»). Волна 24: закупка однопроектная, охват снят; у заказа витрины нет.
- `procurement_form` / `create_procurement` / `add|update|remove_procurement_line` /
  `lock|unlock_procurement` — записываемый план закупки проекта (мягкий замок
  `locked`; зафиксированный = позиции «в плане»); количество строки ≥ 0.
- `procurement_xlsx(...)` / `purchase_xlsx(...)` — xlsx-бланк поставщику (одна форма;
  нулевые строки наружу не идут).

Волна 24 (заказ рождается из закупки):
- `create_purchase(proc, user, item_ids)` — черновой заказ, строки = выбранные позиции
  плана с количеством остатка; `procurement_remainders(proc)` — остатки строк плана;
  `purchase_candidates(pu)` — позиции плана, которые заказ ещё может взять.
- `procurement_allocation(proc)` — таб «Строки» закупки: строка плана с балансом
  проекта → её распределение по заказам (только чтение); плюс веер заказов.

Волна 10 (бюджет/экономия — north-star окупаемости линзы):
- `project_budget(project)` — проекция денег проекта: **потрачено** (★, факт) +
  **план** (прогноз «факт где есть, оценка где нет» через `estimated_cost`) + компас
  `budget − план` + доли освоения + «сверх потребности» с раскладкой + позиции без
  оценки. Себестоимость/экономия сняты в волне 26 (BACKLOG). Чистая витрина.
- `intent_money(lines, need)` (2026-08-07) — те же деньги, но у документа-намерения:
  **потребность** (нужда проекта × цена — сколько надо по-настоящему), **сумма
  документа** (`lines_estimate`) и **переплата** = их разница со знаком. Знаменатель
  даёт `demand_map(projects)` (нужда по листьям через набор проектов): у заказа и у
  закупки — их проект.
- `line_cost(item, qty)` + `mark_costs(rows)` (2026-08-07) — деньги ОТДЕЛЬНОЙ строки в
  «Строках» заказа и «Привязке» закупки: стоимость (без оценки — `None`, не ноль) и
  `cost_status` = `overpaid` (взято сверх порога `overpay_threshold` = полторы нормы,
  округлённые вверх до круглого: 5/10/50/100) > `costly` (верхняя четверть набора по
  стоимости). Ранжирование — внутри одного списка; порог едет в строку (`overpay_at`),
  чтобы вью объясняла цвет числом, а не словами.

Волна 13 Ф2e (мультисклад + перемещение):
- Остаток по паре `(лот, локация)`: `lot_live_qty(lot, location)` / `item_available(…,
  location)` / `available_lots(…, location)` (опциональный фильтр, по умолчанию — тотал,
  байт-в-байт), `lot_locations(lot)` — разбивка по местам; `stock_map` несёт аддитивный
  `by_location`.
- Перемещение (`Relocation`): `create_relocation` / `relocation_form` / `add|update|
  remove_relocation_line` (пара знаковых `StockLine` `−q`@источник/`+q`@приёмник на ход,
  тотал лота сохранён) / `post|unlock_relocation` / `relocation_source_lots` (пикер с
  разбивкой по местам). HTTP/React — следующим заходом («вьюхи потом»).

Волна 19, Ф15 (замок гейтит склад):
- `rebuild_movements` пропускает в `StockMovement` только зафиксированные документы:
  черновик создаётся/правится/удаляется, **ничего никому не двигая**; фиксация делает
  его видимым всем. Правило не новое — так с волны 2 работала комплектация (лот-прибор
  ждал замка) и фильтр «готово» в дефиците; фаза сняла шесть исключений.
- `rebuild_document_movements(doc)` — материализация/снятие склада на `lock_*`/`unlock_*`
  (партии документа + партии-источники его строк). Деньги: `_project_spent` считает
  только лоты зафиксированных поставок (единственное чтение денег мимо движений).

Волна 21 (аккаунт + тема интерфейса):
- `profile_of(user)` — ленивая приставка настроек (`UserProfile`), `set_theme` —
  единственный вход к теме (движок знает СЛАГ и список допустимых, про цвета не знает).
- `user_form(user)` — проекция формы аккаунта: ДНК Django + тема + три ленты «своих»
  документов; `update_user` / `change_password` — правка ДНК и пароля.

План закупок проекта (2026-09-15):
- `project_plan_xlsx(project)` — вкладка «Потребность» в деньгах одним листом: одна
  графа количества (`Заказ`, если он покрывает потребность, иначе `Потр.`), цена =
  `estimated_cost`, стоимость и итог «Всего». Позиция без оценки едет в файл красной
  строкой (`_xlsx_sheet(alerts=…)`), а не молча нулём.

Следующие волны: логин-экран, UI вложений (`Attachment`).
"""
import csv
import io
import os
from datetime import date as dt_date, datetime, timedelta, timezone as dt_timezone
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Sum
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from . import models

ZERO = Decimal('0')
KOPECK = Decimal('0.01')   # шаг округления денег (волна 26: и доли стоимости партии)
_UNSET = object()   # часовой «поле не передано» (отличает от «выставить None»)


def _num(value):
    """Кол-во в текст сообщения: без хвостовых нулей и без экспоненты («10», «2.5»).
    `normalize()` даёт `1E+1` на круглых числах — формат `f` возвращает его обратно."""
    return f'{Decimal(value).normalize():f}'


# --------------------------------------------------------------------------- #
#  Категории изделий (волна 15) — канон внешней библиотеки компонентов
# --------------------------------------------------------------------------- #
# Решение Ивана 2026-10-15: класс библиотеки по имени CSV-файла (`capacitors`/`mcu`/…)
# больше НЕ становится категорией — всё пришедшее из библиотеки Altium получает одну
# категорию «Электронный компонент». Резисторы от конденсаторов отделяет текстовый
# фильтр по описанию; категории делят справочник по смыслу для человека (Изделия /
# Компоненты, см. `Category.native`), а не повторяют раскладку папки библиотеки.
LIBRARY_CATEGORY = ('ЭК', 'Электронный компонент')

# Канон категорий (решения Ивана 2026-10-15): `(code, description, native)`. Заводит
# миграция 0005 (замороженная копия), здесь — для уборки `recategorize_items(prune=…)`:
# пустая категория вне канона — остаток прежней раскладки по файлам библиотеки.
CATEGORY_CANON = (
    # Компоненты — покупное (native=False)
    ('ЭК', 'Электронный компонент', False),
    ('МК', 'Механический компонент', False),
    ('ПП', 'Печатная плата', False),
    ('ДЕТ', 'Деталь', False),
    ('МАТ', 'Материал', False),
    ('КРП', 'Крепёж', False),
    ('ИНС', 'Инструмент', False),
    ('РМ-К', 'Расходный материал', False),
    ('ДР-К', 'Другое', False),
    # Изделия — наше собираемое (native=True)
    ('СИС', 'Система', True),
    ('ПРБ', 'Прибор', True),
    ('УП', 'Узел печатный', True),
    ('КС', 'Кабельная сеть', True),
    ('КПА', 'Контрольно-проверочная аппаратура', True),
    ('ОСН', 'Оснастка', True),
    ('РМ-И', 'Расходный материал', True),
    ('ДР-И', 'Другое', True),
)


# Формы числа категорий изделий — для меты проекта «21 система · 137 приборов · …»
# (волна 23, Ф4). Слова — смысл, поэтому здесь; склоняет по ним вью (`count`).
# Категория, заведённая потом в админке, получит запасную форму (`_count_forms`).
CATEGORY_COUNT_FORMS = {
    'СИС': ('система', 'системы', 'систем'),
    'ПРБ': ('прибор', 'прибора', 'приборов'),
    'УП': ('узел печатный', 'узла печатных', 'узлов печатных'),
    'КС': ('кабельная сеть', 'кабельные сети', 'кабельных сетей'),
    'КПА': ('КПА', 'КПА', 'КПА'),
    'ОСН': ('оснастка', 'оснастки', 'оснасток'),
    'РМ-И': ('набор расходников', 'набора расходников', 'наборов расходников'),
    'ДР-И': ('прочее изделие', 'прочих изделия', 'прочих изделий'),
}


def _count_forms(category):
    if category is None:
        return ('изделие без категории', 'изделия без категории', 'изделий без категории')
    forms = CATEGORY_COUNT_FORMS.get(category.code)
    if forms:
        return forms
    word = f'«{category.description}»'
    return (f'изделие {word}', f'изделия {word}', f'изделий {word}')


def recategorize_items(mapping, prune=False):
    """Разложить изделия по категориям: `mapping` — `{item_code: category_code}`.
    Разовая уборка справочника (2026-10-15), запускается командой `recategorize`
    с таблицей ВНЕ репозитория (названия изделий в открытый репо не кладём).

    Правит в обход `update_item` — как синк библиотеки: это операция администратора,
    замок и матрица `synced` её не касаются (замок держит категорию непустой — мы и не
    пустим). Сторона категории сверяется ВСЕГДА (`category.native == item.native`):
    ошибка в таблице — отказ целиком, а не полуразложенный справочник.

    `prune=True` — после раскладки удалить пустые категории вне `CATEGORY_CANON`.
    Возвращает отчёт `{changed, same, missing_items, untouched, pruned}`."""
    cats = {c.code: c for c in models.Category.objects.all()}
    items = {i.code: i for i in models.Item.objects.select_related('category')}
    unknown = sorted({c for c in mapping.values() if c not in cats})
    if unknown:
        raise ValidationError(f'Нет таких категорий: {", ".join(unknown)}.')
    wrong_side = sorted(code for code, cat in mapping.items()
                        if code in items and cats[cat].native != items[code].native)
    if wrong_side:
        raise ValidationError(f'{models.ITEM_CATEGORY_SIDE} Позиции: {", ".join(wrong_side)}.')
    report = {'changed': 0, 'same': 0, 'pruned': [],
              'missing_items': sorted(c for c in mapping if c not in items),
              'untouched': sorted(c for c in items if c not in mapping)}
    with transaction.atomic():
        for code, cat_code in mapping.items():
            item = items.get(code)
            if item is None:
                continue
            if item.category_id == cats[cat_code].id:
                report['same'] += 1
                continue
            item.category = cats[cat_code]
            item.save(update_fields=['category'])
            report['changed'] += 1
        if prune:
            canon = {code for code, _, _ in CATEGORY_CANON}
            for cat in models.Category.objects.filter(items__isnull=True).exclude(code__in=canon):
                report['pruned'].append(cat.code)
                cat.delete()
    return report


def library_category():
    """Категория всего синкаемого. Заводится миграцией 0005; `get_or_create` —
    страховка для пустой БД (тесты, свежий dev). Описание существующей не трогаем —
    справочник правят в админке."""
    code, description = LIBRARY_CATEGORY
    cat, _ = models.Category.objects.get_or_create(
        code=code, defaults={'description': description, 'native': False})
    return cat


# --------------------------------------------------------------------------- #
#  Единый мягкий замок складского документа (волна 13, Ф1)
# --------------------------------------------------------------------------- #
def _require_unlocked(doc, msg=None):
    """Единый guard правки: документ должен быть расфиксирован (замок снят).

    Свернул разнородные `_require_wip`/`_require_unapproved`/`_require_unposted` —
    один мягкий замок на всех ордерах, `locked=True` = edit-freeze. С волны 19 (Ф1)
    обслуживает и Закупку с Заказом — та же ось; своих `_require_*_draft` больше
    нет. Ф1c сделала ось булевой. `msg` уточняет формулировку по сущности.
    """
    if doc.locked:
        raise ValidationError(
            msg or 'Документ зафиксирован — расфиксируйте для правки.')


def _require_header(doc):
    """Гейт полноты шапки на фиксации — условная валидация специфики по виду
    (волна 13, Ф2d). Единый kind-driven источник правила живёт на модели
    (`StockDocument.clean` + `REQUIRED_HEADER_BY_KIND`); фиксация не выпускает
    неполный ордер независимо от пути его создания (API/админ/прямой ORM).

    Ф12e добавила сюда специфику вида. Обязательность `contractor`/`target_item`
    Ф14 выразила CHECK'ами по `locked` — но прикладного гейта у них не было, и до
    Ф12e это не проявлялось: до неё оба поля требовались при рождении, и дойти до
    фиксации с пустым было неоткуда. Теперь это штатное состояние черновика, и без
    гейта пользователь получал бы `IntegrityError 3819` вместо внятного отказа.
    """
    doc.clean()
    kind = doc.KIND or doc.kind
    if kind == models.DocumentKind.RECEIPT and doc.contractor_id is None:
        raise ValidationError('Перед фиксацией выберите поставщика.')
    if kind == models.DocumentKind.KITTING and (
            doc.target_item_id is None or doc.qty is None):
        raise ValidationError('Перед фиксацией выберите прибор-цель и кол-во.')


def rebuild_document_movements(doc):
    """Пересобрать движения ВСЕХ партий, которых касается документ (волна 19, Ф15).

    Замок гейтит склад, поэтому смена `locked` — событие склада: фиксация обязана
    материализовать движения документа, расфиксация — снять. Касается двух семейств
    партий: рождённых документом (`doc.lots`, origin-`+RECEIPT`) и упомянутых его
    знаковыми строками (`doc.lines`, расход/приём источника). Зовётся из всех
    `lock_*`/`unlock_*`; сама пересборка чистая, порядок вызовов не важен.
    """
    # Волна 26: сначала источники — стоимость рождённой партии требования/комплектации
    # выводится из стоимостей строк расхода (`_sync_born_cost`), и только потом
    # материализуется сама партия.
    sources = {sl.lot for sl in doc.lines.select_related('lot')}
    for lot in sources:
        rebuild_movements(lot)
    _sync_born_cost(doc)
    for lot in set(doc.lots.all()) - sources:
        rebuild_movements(lot)


def lock_document(doc, rows, empty_msg):
    """Поставить единый мягкий замок (edit-freeze формы) + материализовать склад.

    `rows` — менеджер строк документа (`doc.lots` для born-only, `doc.lines` для
    расходных): нельзя зафиксировать пустой документ. Ф15: фиксация — момент, когда
    документ становится виден складу (до неё его строки не двигали ничего).
    """
    if not rows.exists():
        raise ValidationError(empty_msg)
    _require_header(doc)
    doc.locked = True
    doc.save(update_fields=['locked'])
    rebuild_document_movements(doc)
    return doc


def unlock_document(doc):
    """Снять единый мягкий замок: форма снова правима, движения документа сняты.

    Ничего не разрушает (строки и рождённые лоты остаются) — guard по потомкам не
    нужен, в отличие от расфиксации комплектации, где снимается лот-прибор. Ф15:
    расфиксация возвращает документ в черновики и **со склада убирает** — расход
    источников отпускается, рождённые партии перестают лежать на складе.
    """
    doc.locked = False
    doc.save(update_fields=['locked'])
    rebuild_document_movements(doc)
    return doc


def delete_stock_document(doc):
    """Удалить складской ордер (отмена = удаление, канон В13 Ф1 — не копим надгробия).

    Правило удаления (единое на 6 ордеров):
    - **locked** — «сперва расфиксировать»: удаляем только расфиксированный;
    - **не locked** — свободно, но `PROTECT` бережёт потраченные лоты: если рождённый
      документом лот (`doc.lots`, born-direct) уже потреблён/передан/отпочкован ниже
      — дружелюбный отказ вместо сырого `ProtectedError`.

    Механика (обходит грабли CHECK `lot_exactly_one_origin`, см. JOURNAL Ф1a): born-лоты
    и их движения сносим **явно** (как `unlock_kitting`), затем документ (каскад
    расходных `StockLine` + вложений), затем пересобираем движения лотов-источников
    (снять их `−ISSUE`). Файлы вложений чистим отдельно — каскад БД их бы осиротил.
    """
    if doc.locked:
        raise ValidationError(
            'Документ зафиксирован — сперва расфиксируйте его для удаления.')
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


# Волна 19, Ф1c: слой совместимости `wip`/`closed` (комплектация отдавала эти
# строки с волны 2) снят — наружу идёт та же `locked`, что у всех сущностей.
# Фронт переехал вместе с бэком, третьего словаря статуса в API больше нет.


# --------------------------------------------------------------------------- #
#  Склад: пересборка движений и живые остатки
# --------------------------------------------------------------------------- #
def _main_location():
    """Дом приходного движения. В MVP — один «Основной склад» (код MAIN)."""
    loc = models.Location.objects.filter(code='MAIN').first()
    return loc or models.Location.objects.order_by('id').first()


def _share(cost, qty, part):
    """Доля стоимости `cost` партии из `qty` штук, приходящаяся на `part` штук, до копейки.

    Единственное деление денег на штуки в движке (волна 26, учётный канон): цена штуки
    не хранится нигде, она — промежуточная величина этой формулы."""
    if not qty:
        return ZERO
    return (cost * part / qty).quantize(KOPECK, rounding=ROUND_HALF_UP)


def lot_line_values(lot, lines=None):
    """Стоимость каждой знаковой строки партии: `{stock_line.id: стоимость со знаком}`.

    **Учётный канон** (волна 26, решение Ивана 2026-10-19; так у SAP/Odoo/1С): партия
    хранит стоимость целиком, расход получает свою долю **накопительным округлением** —
    `доля(израсходовано после) − доля(израсходовано до)` по зафиксированным расходам в
    порядке строк (`id`). Сумма долей телескопически равна `доле(всего израсходованного)`,
    поэтому исчерпанная партия списывается ровно в свою стоимость: «последний забирает
    остаток» без особого случая, хвостов в копейку не остаётся.

    Перемещение (пара ±) остаток партии не трогает — его стороны оцениваются простой
    долей и в накопление не входят. Строка черновика тоже получает простую долю: это
    предпросмотр, в склад она не входит (Ф15), и место в очереди займёт на фиксации.

    Порядок по `id` устойчив к добавлению: новая строка встаёт в хвост и уже посчитанные
    доли не трогает. Сдвиг на копейку возможен, только если расфиксировать или удалить
    расход из середины очереди — проекция мутабельна ([[mutable-dna]]).
    """
    if lines is None:
        lines = lot.stock_lines.select_related('document')
    values = {}
    drained = ZERO
    for sl in sorted(lines, key=lambda sl: sl.id):
        if sl.qty < 0 and sl.document.locked \
                and sl.document.kind != models.DocumentKind.RELOCATION:
            before = _share(lot.cost, lot.qty, drained)
            drained -= sl.qty
            values[sl.id] = before - _share(lot.cost, lot.qty, drained)
        else:
            value = _share(lot.cost, lot.qty, abs(sl.qty))
            values[sl.id] = value if sl.qty > 0 else -value
    return values


def lines_values(lines):
    """Стоимости набора строк (обычно — строк одного документа), каждая по правилу
    `lot_line_values` своей партии. Партии поднимаем один раз на набор."""
    lines = list(lines)
    by_lot = {}
    for sl in lines:
        by_lot.setdefault(sl.lot_id, sl.lot)
    # Очереди строк всех партий набора — одним запросом (форма не платит запрос за строку).
    queues = {}
    for sl in (models.StockLine.objects.filter(lot_id__in=by_lot)
               .select_related('document')):
        queues.setdefault(sl.lot_id, []).append(sl)
    values = {}
    for lot_id, lot in by_lot.items():
        values.update(lot_line_values(lot, queues.get(lot_id, [])))
    return {sl.id: values[sl.id] for sl in lines}


def outflow_money(lines):
    """Сколько стоимости уводит документ: −Σ стоимостей его расходных строк (волна 26).

    Главное число ордеров («передали / списали / перевели / переместили на сумму») — те
    же доли, что лягут в проекцию (`lot_line_values`); у черновика — предпросмотр.
    Перемещение считается один раз — по стороне «откуда» (пара ± стоимость не меняет)."""
    lines = [sl for sl in lines if sl.qty < 0]
    return -sum(lines_values(lines).values(), ZERO)


def rebuild_movements(lot):
    """Пересобрать StockMovement партии из её документов (чистая пересборка).

    origin-`+RECEIPT` берёт рождённое количество из `Lot.qty`; расходные `ISSUE`
    выводятся из строк-потребителей, ссылающихся на партию.

    **Волна 19, Ф15 — замок гейтит склад.** В движения попадает только то, что
    пришло от **зафиксированного** документа: черновик спокойно создаётся,
    заполняется и удаляется, ничего никому не двигая; фиксация делает его видимым
    всем (`lock_*` пересобирает движения, `unlock_*` их снимает). Точка врезки одна
    — эта функция единственный писатель `StockMovement`, поэтому остатки, дефицит,
    карта складов и бюджет подчиняются правилу автоматически.
    """
    lot.movements.all().delete()
    main = _main_location()
    rows = []

    # origin: рождение партии (+). Дуга схлопнута в один FK (Ф2b): вид и id берём
    # из родителя `StockDocument` (`kind` == прежнее имя origin-FK; id == прежнему).
    # Ф15: партия черновика на складе не лежит — материализуется на фиксации.
    if lot.origin_id and lot.qty and lot.origin.locked:
        rows.append(models.StockMovement(
            lot=lot, location=main, type=models.StockMovement.Type.RECEIPT,
            qty=lot.qty, cost=lot.cost,
            source_type=lot.origin.kind, source_id=lot.origin_id,
        ))

    # движение существующего лота: единые знаковые строки `StockLine` (волна 13, Ф0)
    # свернули 4 таблицы строк-расхода (комплектация/передача/списание/отпочкование).
    # `StockLine.qty` уже со знаком (− расход); source_type/id — из документа-владельца
    # (`document.kind`/id; дуга схлопнута в один FK в Ф2b). Ф15: строка расфиксированного
    # документа тоже не двигает склад; отмена = удаление документа (каскад строк+лотов).
    # Волна 26: стоимость движения — по учётному канону (`lot_line_values`).
    lines = list(lot.stock_lines.select_related('location', 'document'))
    values = lot_line_values(lot, lines)
    for sl in lines:
        if not sl.document.locked:
            continue
        rows.append(models.StockMovement(
            lot=lot, location=sl.location,
            type=(models.StockMovement.Type.RECEIPT if sl.qty > 0
                  else models.StockMovement.Type.ISSUE),
            qty=sl.qty, cost=values[sl.id],
            source_type=sl.document.kind, source_id=sl.document_id,
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


def lots_live_qty(lots, location=None):
    """`{lot_id: живой остаток}` для набора партий — одним сгруппированным запросом.

    Та же сумма движений, что `lot_live_qty`, для списков и форм, где партий десятки:
    поштучно это был запрос на строку. Партия без движений — ноль (как у поштучной).
    """
    ids = [lot.id for lot in lots]
    live = dict.fromkeys(ids, ZERO)
    if ids:
        qs = models.StockMovement.objects.filter(lot_id__in=ids)
        if location is not None:
            qs = qs.filter(location=location)
        live.update(_sum_by(qs, 'lot'))
    return live


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
            'code': loc.code if loc else '',
            'description': loc.description if loc else '',
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
           .values('lot').annotate(q=Sum('qty'), c=Sum('cost')).order_by('lot'))
    lot_ids = [r['lot'] for r in agg if r['q'] and r['q'] > 0]
    lots = {lot.id: lot for lot in models.Lot.objects
            .filter(id__in=lot_ids).select_related('item', 'project', 'origin')}
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
            'origin': lot.origin_kind,          # глиф партии (§7a): форма = откуда родилась
            'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_description': lot.item.description, 'uom': lot.item.uom, 'qty': r['q'],
            'cost': r['c'] or ZERO,             # волна 26: стоимость лежащего здесь
            'project_id': lot.project_id, 'project_code': lot.project.code,
            'project_name': lot.project.description,
        })
    return rows


def location_form(location):
    """Проекция экрана склада: ДНК (код/описание/вид) + что на нём лежит + ★ блока
    «Деньги» (волна 26): «лежит на сумму» — Σ стоимостей движений партий на этом месте,
    по тем же строкам, что таб (партии с живым остатком > 0)."""
    stock = location_stock(location)
    return {
        'id': location.id, 'code': location.code, 'description': location.description,
        'kind': location.kind, 'stock': stock,
        'total_cost': sum((r['cost'] for r in stock), ZERO),
    }


def create_location(code=None, description='', kind=''):
    """Завести место хранения (В13 Ф4). Код уникален (дружелюбная проверка до
    IntegrityError); пустой — фолбэком «Место 12» (Ф12e)."""
    code = (code or '').strip()
    if code and models.Location.objects.filter(code=code).exists():
        raise ValidationError('Место с таким кодом уже есть.')
    fields = dict(description=(description or '').strip(),
                  kind=(kind or '').strip())
    if code:
        return models.Location.objects.create(code=code, **fields)
    return create_with_fallback_code(models.Location, 'Место', **fields)


def update_location(location, code=None, description=None, kind=None):
    """Правка ДНК места хранения (В13 Ф4) — мутабельная, под интерфейсным замком.
    Часовые `None` (поле не передано); пустой код отклоняем.

    Ф12e: описание разрешено пустым — сущность рождается по клику незаполненной, и
    запрет очистки означал бы, что заполнить поле можно, а передумать нельзя.
    Идентичность держит `code` (он и остался обязательным)."""
    if code is not None:
        code = code.strip()
        if not code:
            raise ValidationError('Код места хранения обязателен.')
        if models.Location.objects.filter(code=code).exclude(pk=location.pk).exists():
            raise ValidationError('Место с таким кодом уже есть.')
        location.code = code
    if description is not None:
        location.description = description.strip()
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


# --------------------------------------------------------------------------- #
#  Снимок снабжения проекта: члены баланса по всем Item за константу запросов
# --------------------------------------------------------------------------- #
def _sum_by(qs, key):
    """`{key: Σ qty}` одним сгруппированным запросом (пустой ключ пропускаем)."""
    return {r[key]: r['s'] or ZERO
            for r in qs.values(key).annotate(s=Sum('qty')).order_by() if r[key] is not None}


def _cost_by(qs, key):
    """`{key: Σ стоимостей движений}` одним запросом — деньги по факту партий (волна 26:
    стоимость движения посчитана учётным каноном при пересборке, здесь только сумма)."""
    return {r[key]: r['s'] or ZERO
            for r in qs.values(key).annotate(s=Sum('cost')).order_by()
            if r[key] is not None}


class ProjectSupply:
    """Снимок снабжения проекта — все члены баланса (`_balance`) сразу по всем Item.

    Витрины потребности спрашивают склад/впаяно/заказано по каждому листу разузлования;
    спрашивать поштучно значило платить запрос (а у «заказано» — запрос на строку
    заказа) за каждое число, и форма проекта стоила тысячи запросов (2026-09-28).
    Снимок отвечает на те же вопросы словарями: каждый член — ОДИН сгруппированный
    запрос на проект, поднимается лениво при первом обращении.

    Это не кэш: снимок живёт одну проекцию (один запрос HTTP) и выбрасывается, так что
    «всё вычислимое держим свежим» не нарушено. Семантика членов — единственная: поштучные
    `item_*` ниже — те же снимки, спрошенные про один Item.
    """

    def __init__(self, project):
        self.project = project
        self._memo = {}

    def _get(self, name, build):
        if name not in self._memo:
            self._memo[name] = build()
        return self._memo[name]

    def _movements(self):
        return models.StockMovement.objects.filter(lot__project=self.project)

    def available(self, item):
        """Доступный остаток Item в проекте — Σ живых остатков своих лотов.

        Может быть отрицательным (недостача) — не клампим, это информативно."""
        return self._get('available', lambda: _sum_by(self._movements(), 'lot__item')
                         ).get(item.id, ZERO)

    def kitted(self, item):
        """Впаяно: Σ количеств Item, ушедших в комплектации проекта (положительное число).

        Четвёртый член баланса потребности (2026-08-05). Берём расход по **зафиксированным**
        комплектациям — тот же замок, что гейтит склад: `StockMovement` собирается только
        по запертым ордерам (`rebuild_movements`), поэтому фильтра по `locked` здесь не
        нужно, он уже в природе таблицы. Черновой акт не двигает ни склад, ни это число.

        Знак: движения расхода отрицательны, наружу отдаём магнитуду — в балансе это
        слагаемое покрытия («уже стоит в изделии»), а не вычитаемое.
        """
        return -self._get('kitted', lambda: _sum_by(self._movements().filter(
            source_type=models.DocumentKind.KITTING,
            type=models.StockMovement.Type.ISSUE,
        ), 'lot__item')).get(item.id, ZERO)

    # Деньги членов по ФАКТУ партий (волна 23, Ф2, решение Ивана: склад и впаянное —
    # «сразу по лотам», цена из УПД / себестоимость; потребность, заказ и баланс — по
    # оценке Item, там факта нет). Те же движения, что у количеств, — один запрос на член.
    def available_cost(self, item):
        """Стоимость живого остатка Item в проекте: Σ остаток лота × его цена."""
        return self._get('available_cost', lambda: _cost_by(self._movements(), 'lot__item')
                         ).get(item.id, ZERO)

    def kitted_cost(self, item):
        """Стоимость впаянного: Σ расход в зафиксированных комплектациях × цена лота."""
        return -self._get('kitted_cost', lambda: _cost_by(self._movements().filter(
            source_type=models.DocumentKind.KITTING,
            type=models.StockMovement.Type.ISSUE,
        ), 'lot__item')).get(item.id, ZERO)

    def has_negative_lot(self, item):
        """Есть ли лот Item в проекте с отрицательным остатком (аномалия «подбей лоты»)."""
        def build():
            per_lot = (self._movements().values('lot', 'lot__item')
                       .annotate(s=Sum('qty')).order_by())
            return {r['lot__item'] for r in per_lot if r['s'] is not None and r['s'] < 0}
        return item.id in self._get('negative', build)

    def done(self, item):
        """Готово: живой остаток лотов-приборов Item из зафиксированных комплектаций."""
        return self._get('done', lambda: _sum_by(self._movements().filter(
            lot__origin__kind=models.StockDocument.Kind.KITTING,
            lot__origin__locked=True,
        ), 'lot__item')).get(item.id, ZERO)

    def wip(self, item):
        """Σ кол-во в расфиксированных комплектациях проекта, делающих этот Item."""
        return self._get('wip', lambda: _sum_by(models.Kitting.objects.filter(
            project=self.project, locked=False,
        ), 'target_item')).get(item.id, ZERO)

    def purchased(self, item):
        """Σ max(0, PurchaseLine.qty − поступившее) по зафиксированным заказам проекта.

        Поступившее — `_purchase_received` каждого заказа (та же правда, что у
        `_line_received`); клампим построчно, как и раньше: перебор по одному заказу
        не гасит недопоставку по другому."""
        return self._purchase_rest()[0].get(item.id, ZERO)

    def ordered_cost(self, item):
        """Деньги ОБЕЩАННОЙ доли «Заказа» (2026-10-19): ещё не приехавшее по
        зафиксированным заказам — по счёту, `остаток строки × цена строки / кол-во`.

        Ровно те количества, что `purchased`, поэтому сумма над «Заказом» раскладывается
        без остатка: обещанное (по счёту) + план (по оценке). Приехавшее сюда не входит —
        оно уже в «Складе»/«Компл.» по цене партии; все обязательства целиком — это
        «потрачено» бюджета проекта. У производимого обещанное — `wip`, а не заказ."""
        if item.native:
            return ZERO
        return self._purchase_rest()[1].get(item.id, ZERO)

    def _purchase_rest(self):
        """Остаток зафиксированных заказов проекта по Item: (кол-во, деньги по счёту)."""
        def build():
            lines = list(models.PurchaseLine.objects.filter(
                purchase__procurement__project=self.project, purchase__locked=True,
            ).values_list('purchase_id', 'item_id', 'qty', 'price'))
            received = _received_by(models.Lot.objects.filter(
                origin__purchase__in={pu for pu, _i, _q, _p in lines}))
            qty_rest, cost_rest = {}, {}
            for pu, item_id, qty, price in lines:
                got = received.get((pu, item_id), ZERO)
                rest = max(ZERO, qty - got)
                qty_rest[item_id] = qty_rest.get(item_id, ZERO) + rest
                # Волна 26: «ждём» — то же правило, что у формы заказа (`line_flow_money`),
                # до копейки; у зафиксированного заказа цена обязательна, но страхуемся.
                if rest:
                    cost_rest[item_id] = (cost_rest.get(item_id, ZERO)
                                          + line_flow_money(price, qty, got)[1])
            return qty_rest, cost_rest
        return self._get('purchase_rest', build)

    def planned(self, item):
        """В плане (волна 24): Σ по ЗАФИКСИРОВАННЫМ закупкам проекта
        `max(0, строка плана − Σ строк её ЗАФИКСИРОВАННЫХ заказов)` по Item.

        Решили купить, но обязательства ещё нет — зона риска. Позиция, взятая
        зафиксированным заказом, переезжает отсюда в `purchased`, поэтому одно и то же
        количество не считается дважды: хотим 100, заказ на 60 зафиксирован → заказано
        60, в плане 40. Клампим по закупке: перебор заказа по одному плану не гасит
        недобор по другому. Черновая закупка — ещё обдумывание, она не считается.
        """
        def build():
            covered = {}
            for proc_id, item_id, qty in models.PurchaseLine.objects.filter(
                    purchase__procurement__project=self.project,
                    purchase__procurement__locked=True, purchase__locked=True,
            ).values_list('purchase__procurement_id', 'item_id', 'qty'):
                covered[(proc_id, item_id)] = covered.get((proc_id, item_id), ZERO) + qty
            total = {}
            for proc_id, item_id, qty in models.ProcurementLine.objects.filter(
                    procurement__project=self.project, procurement__locked=True,
            ).values_list('procurement_id', 'item_id', 'qty'):
                rest = max(ZERO, qty - covered.get((proc_id, item_id), ZERO))
                total[item_id] = total.get(item_id, ZERO) + rest
            return total
        return self._get('planned', build).get(item.id, ZERO)

    def spent(self, item):
        """«Потрачено» по Item — то же правило, что у бюджета проекта (`_project_spent`),
        разложенное по позициям: цены строк зафиксированных заказов (по счёту, включая
        приехавшее) + лоты зафиксированных поставок без заказа (по УПД)."""
        return self._spent_by_item().get(item.id, ZERO)

    def _spent_by_item(self):
        def build():
            total = {r['item']: r['s'] or ZERO for r in models.PurchaseLine.objects.filter(
                purchase__procurement__project=self.project, purchase__locked=True,
            ).values('item').annotate(s=Sum('price')).order_by()}
            for item_id, cost in models.Lot.objects.filter(
                    project=self.project, origin__kind=models.StockDocument.Kind.RECEIPT,
                    origin__locked=True, origin__purchase__isnull=True,
            ).values_list('item_id', 'cost'):
                total[item_id] = total.get(item_id, ZERO) + cost
            return total
        return self._get('spent', build)

    def spent_outside(self, item_ids):
        """«Потрачено» на позиции, которых нет в потребности (куплено не по BOM) — часть
        плана шапки, у которой нет строки в «Потребности»: без неё сверка не сойдётся."""
        return sum((v for k, v in self._spent_by_item().items() if k not in item_ids), ZERO)

    def plan_ahead(self, item, need):
        """Количество, которое план оценивает по `estimated_cost` — деньги ещё впереди:
        доля «на нас» в «Заказе» (план зафиксированных закупок ЦЕЛИКОМ, с запасом, и
        незакрытая сборка у производимого) + нехватка (минус баланса).

        Запас в зафиксированной закупке входит в план СРАЗУ (2026-10-19, решение Ивана):
        зафиксировал «берём 200 при нужде 77» — решил потратить на 200, и план обязан это
        показать до заказа, а не скачком в момент его фиксации. Это инструмент оценки,
        какие запасы проект может себе позволить. Отсюда тождество строки: Компл. + Склад +
        Заказ + нехватка = план позиции (пока факт партий равен потраченному — заёмные и
        найденные партии сознательно вне этой волны).
        Нехватка — ровно минус баланса строки (`_balance`), поэтому сходится с колонкой."""
        ours = self.planned(item) + (self.wip(item) if item.native else ZERO)
        short = max(ZERO, -self.balance(item, need)['balance'])
        return ours + short

    def on_order(self, item):
        """Член «Заказ»: всё, за что взялись, — обещанное (`wip` у производимого,
        `purchased` у покупного) плюс запланированное (`planned`, волна 24)."""
        base = self.wip(item) if item.native else self.purchased(item)
        return base + self.planned(item)

    def balance(self, item, need):
        """Строка баланса `_balance` по Item — четыре члена из снимка.

        Волна 24: строка несёт ещё и долю плана в «Заказе» (`planned`) и незакрытую
        комплектацию (`wip`, только у производимого) — то, что держится на НАС. Из них
        вью выбирает тон ящика «Заказ», а `_supply_status` — цвет «как дела».
        """
        row = _balance(need, self.kitted(item), self.available(item), self.on_order(item))
        row['planned'] = self.planned(item)
        row['wip'] = self.wip(item) if item.native else ZERO
        return row


def item_available(item, project, location=None):
    """Доступный остаток Item в проекте — Σ живых остатков своих лотов.

    Волна 13, Ф2e: опциональный `location` сужает до остатка в этом месте хранения.
    Может быть отрицательным (недостача) — не клампим, это информативно.
    """
    if location is None:
        return ProjectSupply(project).available(item)
    return models.StockMovement.objects.filter(
        lot__item=item, lot__project=project, location=location,
    ).aggregate(s=Sum('qty'))['s'] or ZERO


def item_kitted(item, project):
    """Впаяно (поштучно) — см. `ProjectSupply.kitted`."""
    return ProjectSupply(project).kitted(item)


def item_has_negative_lot(item, project):
    """Аномалия «подбей лоты» (поштучно) — см. `ProjectSupply.has_negative_lot`."""
    return ProjectSupply(project).has_negative_lot(item)


# --------------------------------------------------------------------------- #
#  «Заказано» (оранжевый член): открытый заказ или wip-комплектация
# --------------------------------------------------------------------------- #
def _received_by(lots):
    """`{(purchase_id, item_id): поступило}` по лотам зафиксированных поставок.

    Документ = УПД правда: поступившее — приход (`+RECEIPT` через `Receipt.purchase`),
    не текущий остаток (получили 100 → спаяли 40 → заказ закрыт на 100).

    Ф14: путь был `origin__receipt__purchase` — JOIN через детскую таблицу MTI. После
    схлопывания `purchase` живёт на самом ордере, а непоставки его не имеют вовсе
    (CHECK `doc_purchase_only_receipt`), поэтому сужать по виду отдельно не нужно.

    Ф6: считаем только **зафиксированные** поставки (`origin__locked`). Фильтра не было,
    и это расходилось с собственным обещанием Ф15 («черновая поставка не в потрачено и
    не на складе — её позиции остаются в в пути / к заказу»): черновой УПД гасил заказ,
    хотя товар не приехал. Один и тот же замок гейтит склад, деньги и закрытость заказа.
    """
    rows = (lots.filter(origin__locked=True)
            .values('origin__purchase', 'item').annotate(s=Sum('qty')).order_by())
    return {(r['origin__purchase'], r['item']): r['s'] or ZERO for r in rows}


def _purchase_received(purchase):
    """`{item_id: поступило}` по заказу — одним запросом на все его строки."""
    return {item_id: qty for (_pu, item_id), qty
            in _received_by(models.Lot.objects.filter(origin__purchase=purchase)).items()}


def _line_received(line):
    """Поступило по строке заказа (поштучно) — см. `_received_by`."""
    return _received_by(models.Lot.objects.filter(
        item=line.item_id, origin__purchase=line.purchase_id,
    )).get((line.purchase_id, line.item_id), ZERO)


def item_on_order(item, project):
    """Оранжевый член, обобщённый по типу Item (покупной/производимый)."""
    return ProjectSupply(project).on_order(item)


# --------------------------------------------------------------------------- #
#  Тройной разбор строки и цвет
# --------------------------------------------------------------------------- #
def _contractor_view(cp):
    """Контрагент наружу: `code` первичен, `description` — расшифровка (2026-08-05).

    [[code-identity-principle]]: идентичность несёт код («КОМПЭЛ»), а не длинное имя
    из ЕГРЮЛ — в шапках и списках он и короче, и узнаваемее. Код у контрагента
    nullable (авто-фолбэка нет), поэтому отдаём обе строки: вью показывает код, при
    пустом падает на описание и мягко просит код завести.
    """
    if cp is None:
        return {'contractor_id': None, 'contractor_code': '', 'contractor_name': ''}
    return {'contractor_id': cp.id, 'contractor_code': cp.code or '',
            'contractor_name': cp.description}


def _coverage(need, available, on_order):
    """Разложить потребность на ✓ есть · ● заказано · ▲ заказать (сегменты).

    Сегменты **клампованы потребностью**: сумма трёх членов ровно `need`. Цена клампа —
    невидимый перебор (заказали 10 при нужде 6 → в ● всё равно 6), поэтому витрина
    потребности проекта на разборе больше НЕ стоит: она считает баланс (`_balance`), где
    перебор виден знаком. Разбор остался там, где закрытие нужды и есть вопрос: свод «К
    закупке» и призрачная строка комплектации.
    """
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


def _balance(need, kitted, in_stock, on_order):
    """Баланс потребности: `(впаяно + склад + в заказе) − надо`, со знаком (2026-08-05).

    Четыре члена вместо трёх сегментов, и **ни один не клампится**: числа сырые, а
    дефицит — не отдельная формула, а невязка. Отсюда главное свойство: перебор виден
    так же ясно, как недобор, просто знаком. `−4` — не хватает четырёх, `+4` — запас.

    Тон — ось «как дела», а не «что за член» (`Status` переиспользуем как словарь
    цветов, [[engine-view-seam]]: движок даёт смысл, тема выбирает знак):
    `to_order` красный — не хватает; `on_order` оранжевый — сходится в ноль, запаса нет;
    `available` зелёный — есть запас.

    Что складываем — принципиально: **впаянное** входит в покрытие наравне со складом.
    Компонент, ушедший в изделие, потребность уже закрыл, хотя на складе его нет; без
    этого члена собранный проект показывал бы дефицит на всё, что израсходовал.
    """
    balance = kitted + in_stock + on_order - need
    if balance < 0:
        status = 'to_order'
    elif balance == 0:
        status = 'on_order'
    else:
        status = 'available'
    return {
        'need': need, 'kitted': kitted, 'in_stock': in_stock, 'on_order': on_order,
        'balance': balance, 'status': status,
    }


def _supply_status(row):
    """«Как дела» по строке баланса — ось снабжения, НЕ тон колонки «Баланс».

    Два разных вопроса не смешиваем. Колонка отвечает «сходится ли» (ноль — оранжевый:
    впритык, запаса нет), а цвет прибора и проекта — «нужна ли работа»: ровно сошлось —
    это хорошо, зелёное. Отсюда: не хватает → красный; хватает, но часть держится на
    том, что зависит ОТ НАС (позиция только в плане или незакрытая комплектация) →
    оранжевый; иначе → зелёный.

    Волна 24 (решение Ивана): зафиксированный заказ — обязательство возникло, «от нас
    всё сделано, остаётся ждать», поэтому едущее по нему уже зеленит. До волны
    оранжевым было любое «едет».
    """
    if row['balance'] < 0:
        return 'to_order'
    return 'on_order' if row.get('planned') or row.get('wip') else 'available'


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


def category_code(item):
    """Код категории изделия или `None` (Ф12e: у черновика её может не быть).

    Один ответ на два вопроса: чем изделие числится в библиотеке (синк сверяет класс
    по `code`, стему CSV-файла) и чем оно числится в строке документа — с 2026-08-10
    класс едет в проекциях строк под фильтр колонки изделия. Кодом, а не объектом:
    идентичность изделия в строке и так разложена плоскими полями (`*_code`,
    `*_description`), класс встаёт рядом с ними. `None` вью показывает отдельным
    вариантом «без категории».
    """
    return item.category.code if item.category_id else None


# --------------------------------------------------------------------------- #
#  Разузлование потребности до покупных листьев (Ф5, волна 16)
# --------------------------------------------------------------------------- #
class BomIndex:
    """Состав изделий, подгруженный поуровнево: `children(item)` без запроса на узел.

    Разузлование ходит по дереву рекурсией, и `item.bom_lines` на каждом узле стоил
    запрос — у проекта с десятком приборов это сотни запросов на одну витрину. Индекс
    при первом вопросе про узел поднимает всё его поддерево волнами (запрос на уровень
    BOM, а не на узел) и дальше отвечает из памяти. Живёт одну проекцию, как
    `ProjectSupply`. Порядок строк — по `component_id`: так их отдавал MySQL по
    уникальному индексу `(parent, component)`, пока порядок был неявным, — закрепляем.
    """

    def __init__(self):
        self._children = {}      # parent_id → [BomLine (+component, +category)]

    def children(self, item):
        if item.id not in self._children:
            self._load({item.id})
        return self._children[item.id]

    def preload(self, items):
        """Поднять поддеревья сразу нескольких изделий (приборы проекта) общими волнами."""
        self._load({item.id for item in items if item.native} - self._children.keys())

    def _load(self, frontier):
        while frontier:
            for pid in frontier:
                self._children[pid] = []
            lines = (models.BomLine.objects.filter(parent_id__in=frontier)
                     .select_related('component', 'component__category')
                     .order_by('parent_id', 'component_id'))
            nxt = set()
            for bl in lines:
                self._children[bl.parent_id].append(bl)
                if bl.component.native and bl.component_id not in self._children:
                    nxt.add(bl.component_id)
            frontier = nxt


def _explode_demand(item, qty, leaves, incomplete, visiting, bom):
    """Разузловать потребность `item × qty` до покупных листьев (структурно).

    Покупной `item` (`native=False`) — лист-терминал: копим `qty` в `leaves`.
    Производимый узел — рекурсия в детей (`qty × bl.qty`): купить его нельзя, деньги/
    заказ живут на листьях (резисторы/ИС/материалы). Нетинга подсборок здесь НЕТ
    (согласовано В16): покрытие складом/заказом считает `_coverage` на самом листе.
    Производимый узел без BOM оценить нечем → в `incomplete` (вклад 0). Циклы —
    страховка `visiting` (гасит уже `add_bom_line`), как в `_rollup_cost`.
    """
    if not item.native:
        leaves[item] = leaves.get(item, ZERO) + qty
        return
    if item.id in visiting:
        raise ValidationError(f'Цикл в составе: {item.code}.')
    visiting.add(item.id)
    lines = bom.children(item)
    if not lines:
        incomplete.append(item.code)
    for bl in lines:
        _explode_demand(bl.component, qty * bl.qty, leaves, incomplete, visiting, bom)
    visiting.discard(item.id)


def project_leaf_demand(project, bom=None):
    """Свод потребности проекта до покупных листьев: `({leaf: qty}, incomplete)`.

    Разузловывает каждую потребность (`target_item × demand.qty`) до листьев и
    складывает по Item через все приборы проекта. `incomplete` — производимые узлы
    без BOM (оценить нечем), для честного флага неполноты. `bom` — общий `BomIndex`
    проекции, если она разузловывает не один проект.
    """
    bom = bom or BomIndex()
    demands = list(project.demands.select_related('target_item'))
    bom.preload(d.target_item for d in demands)
    leaves, incomplete = {}, []
    for demand in demands:
        _explode_demand(demand.target_item, demand.qty, leaves, incomplete, set(), bom)
    return leaves, incomplete


def _project_usage_map(project):
    """Обратное разузлование проекта: `{leaf_item_id: [применения]}` — за один обход.

    Прямое разузлование отвечает «что купить», обратное — «зачем»: по сколько штук
    этого Item уходит в каждое производимое изделие проекта. Считается той же
    рекурсией (`_explode_demand`), просто пущенной от **единицы** прибора: разложение
    `target_item × 1` и есть норма на изделие (`per_unit`), а `per_unit × demand.qty` —
    вклад этой потребности в общую нужду. Третьего прохода по BOM не заводим.

    Карта строится на весь проект разом (обходов = потребностей, а не потребностей ×
    строк плана) — аккордеон закупки спрашивает её по каждой строке.
    """
    usage = {}
    bom = BomIndex()
    for demand in project.demands.select_related('target_item'):
        leaves = {}
        _explode_demand(demand.target_item, Decimal('1'), leaves, [], set(), bom)
        for leaf, per_unit in leaves.items():
            usage.setdefault(leaf.id, []).append({
                'target_item_id': demand.target_item_id,
                'target_code': demand.target_item.code,
                'target_description': demand.target_item.description,
                'per_unit': per_unit,               # норма на одно изделие (через все уровни)
                'demand_qty': demand.qty,           # сколько изделий нужно проекту
                'total': per_unit * demand.qty,     # вклад в нужду проекта по этому Item
            })
    for rows in usage.values():
        rows.sort(key=lambda r: r['target_code'])
    return usage


def item_usage_in_project(item, project):
    """«Куда идёт этот Item в проекте»: список применений (изделие, норма, вклад).

    Точечный вход в `_project_usage_map` — для одной строки; массовые витрины берут
    карту целиком, чтобы не гонять разузлование на каждую строку.
    """
    return _project_usage_map(project).get(item.id, [])


def _leaf_row(item, need, supply):
    """Строка баланса листа (`_balance` + реквизиты Item) для секций потребности.

    Ключи `component_*` сохранены (фронт/сериализатор их ждут): лист — тот же Item.
    Члены баланса — из снимка проекта (`ProjectSupply`).
    """
    row = supply.balance(item, need)
    row.update({
        'component_id': item.id,
        'component_code': item.code,
        'component_description': item.description,
        'component_native': item.native,       # глиф строки по режиму (Ф3a): native→замок,
        'component_synced': item.synced,        # not native→sync (зел. библ. / оранж. ручной)
        'component_locked': item.locked,
        'component_category': category_code(item),   # фильтр колонки «Компонент»
        'uom': item.uom,
        'supply': _supply_status(row),         # ось «как дела» (цвет прибора/проекта)
        'anomaly': supply.has_negative_lot(item),
        **_money_fields(item, supply.kitted_cost(item), supply.available_cost(item),
                        supply.ordered_cost(item), supply.spent(item),
                        supply.plan_ahead(item, need), need),
    })
    return row


def _money_fields(item, kitted_cost, in_stock_cost, ordered_cost, spent_cost, ahead, need):
    """Деньги строки потребности (волна 23, Ф2): цена-оценка (`price`, `None` — оценки
    нет), факт партий для Компл./Склада, обещанное по счёту для «Заказа». Суммы над
    колонками складывает вью по ОТФИЛЬТРОВАННЫМ строкам — фильтры живут там же.

    План позиции (2026-10-19, решение Ивана: «одинаковые числа в разных местах обязаны
    совпадать»): `plan_cost` = потрачено по позиции (`spent_cost`, по счёту/УПД) + деньги
    впереди (`ahead` — план закупки с запасом, сборка, нехватка; `plan_ahead`) по оценке —
    ровно то правило, по которому бюджет считает «план» шапки. Сумма `plan_cost` по всем
    строкам + траты вне потребности (`outside_spent` проекции) = план проекта до рубля.
    `unestimated` — позиция, у которой деньги впереди есть, а оценки нет: тот же признак,
    что «N поз. без оценки — план неполон» в шапке."""
    price = item.estimated_cost
    unestimated = ahead > 0 and price is None
    return {'price': price, 'kitted_cost': kitted_cost,
            # 2026-10-20: чистая потребность позиции (нужда × оценка, без запаса) — сумма
            # над «Потр.»; рядом с планом (над «Оценкой») она и есть «сверх потребности».
            'need_cost': None if price is None else need * price,
            'in_stock_cost': in_stock_cost, 'ordered_cost': ordered_cost,
            'spent_cost': spent_cost,
            'plan_cost': spent_cost + (ZERO if unestimated else ahead * (price or ZERO)),
            'unestimated': unestimated}


def _bom_unit_cost(item, bom, cache):
    """Оценка штуки изделия по составу через `BomIndex` — живой роллап без запроса на
    узел (тот же итог, что `_rollup_cost(write=False)`: лист без оценки идёт нулём)."""
    if item.id not in cache:
        if not item.native:
            cache[item.id] = item.estimated_cost or ZERO
        else:
            cache[item.id] = ZERO          # страховка от цикла (его гасит `add_bom_line`)
            cache[item.id] = sum((_bom_unit_cost(bl.component, bom, cache) * bl.qty
                                  for bl in bom.children(item)), ZERO)
    return cache[item.id]


def _demand_tree(item, qty, supply, bom, depth, visiting, out, unit_costs=None):
    """Плоский pre-order список узлов BOM с `depth` — древовидный аккордеон прибора
    (Ф5b, В16): видно вложенность (прибор → подсборка → лист), а не только листья.

    Покупной лист — строка баланса (`_leaf_row`) + `depth`/`is_leaf=True`. Производимый
    узел — структурная строка (купить нельзя): только `need` и дети рекурсией ниже. Цикл
    — страховка `visiting`.

    Статуса у узла-подсборки больше НЕТ (2026-08-05): он существовал ровно ради цветной
    полосы слева («где горит под свёрнутым узлом»), а полосы сняты во всём Plume. Считать
    worst-of поддерева, чтобы никто не смотрел, — мёртвая работа."""
    unit_costs = {} if unit_costs is None else unit_costs
    # 2026-10-20: оценка узла в приборе — кол-во × оценка штуки (у узла — по составу).
    est_cost = qty * _bom_unit_cost(item, bom, unit_costs)
    if not item.native:
        row = _leaf_row(item, qty, supply)
        row['need'] = qty
        row['depth'] = depth
        row['is_leaf'] = True
        row['est_cost'] = est_cost
        out.append(row)
        return
    if item.id in visiting:
        raise ValidationError(f'Цикл в составе: {item.code}.')
    visiting.add(item.id)
    row = {
        'component_id': item.id,
        'component_code': item.code,
        'component_description': item.description,
        'component_native': item.native,       # глиф строки по режиму (Ф3a)
        'component_synced': item.synced,
        'component_locked': item.locked,
        'uom': item.uom,
        'need': qty,
        'depth': depth,
        'is_leaf': False,
        'est_cost': est_cost,
    }
    out.append(row)          # pre-order: узел раньше детей
    for bl in bom.children(item):
        _demand_tree(bl.component, qty * bl.qty, supply, bom, depth + 1, visiting, out,
                     unit_costs)
    visiting.discard(item.id)


# --------------------------------------------------------------------------- #
#  Дефицит проекта (главная проекция волны 1)
# --------------------------------------------------------------------------- #
def project_deficit(project, with_tree=True, bom=None):
    """Дефицит проекта: по каждой потребности — прибор и его состав (Ф5b: аккордеон —
    дерево BOM со всеми уровнями; свод «Потребность» — плоско по покупным листьям).

    «ДО» купить нельзя — деньги/дефицит на листьях; но структуру (прибор → подсборка →
    лист) видно в дереве. Возвращает структуру под сериализацию (Decimal → строки в DRF).

    `with_tree=False` — пропустить построение дерева-аккордеона (нужно только детальной
    форме): `_project_health` считает worst-of без него, чтобы не гонять лишнее в списке.
    `bom` — общий `BomIndex`, когда проекция идёт по нескольким проектам (список).
    """
    demands = []
    # Один снимок склада/заказов и один индекс BOM на всю проекцию: члены баланса и
    # состав спрашиваются по каждому листу каждого прибора, запросом платить нельзя.
    supply, bom = ProjectSupply(project), bom or BomIndex()
    # Свод потребности по листьям на весь проект (секция «Потребность»): каждый прибор
    # разузловываем до покупных листьев, копим Σ. Склад/заказано — общие по листу.
    need_by_leaf = {}          # leaf Item → суммарная потребность (Decimal)
    demand_rows = list(project.demands.select_related('target_item', 'target_item__category'))
    bom.preload(d.target_item for d in demand_rows)
    unit_costs = {}           # оценка штуки по составу (живой роллап по индексу BOM)
    for demand in demand_rows:
        target = demand.target_item
        # Свод листьев этой потребности — для секции «Потребность» и цвета прибора.
        leaves, _incomplete = {}, []
        _explode_demand(target, demand.qty, leaves, _incomplete, set(), bom)
        statuses = []
        for leaf, need in leaves.items():
            need_by_leaf[leaf] = need_by_leaf.get(leaf, ZERO) + need
            statuses.append(_supply_status(supply.balance(leaf, need)))
        # Дерево BOM для аккордеона (все уровни, pre-order + depth). Для цвета проекта
        # (`_project_health`) дерево не нужно — пропускаем, чтобы не гонять лишнее в списке.
        tree = []
        if with_tree:
            visiting = {target.id}
            for bl in bom.children(target):
                _demand_tree(bl.component, demand.qty * bl.qty, supply, bom, 0, visiting,
                             tree, unit_costs)

        # триплет прибора: готово (зафиксированные лоты) / делается (в работе) / не начато
        done = supply.done(target)
        wip = supply.wip(target)
        not_started = max(ZERO, demand.qty - done - wip)

        demands.append({
            'demand_id': demand.id,
            'target_id': target.id,
            'target_code': target.code,
            'target_description': target.description,
            'target_native': target.native,     # глиф строки по режиму (Ф3a): прибор → замок
            'target_synced': target.synced,
            'target_locked': target.locked,
            'qty': demand.qty,
            # 2026-10-20: во сколько обойдётся строка — кол-во × оценка прибора по составу.
            # По оценке, а не по факту: счета между приборами не делятся (общие компоненты).
            'cost': demand.qty * _bom_unit_cost(target, bom, unit_costs),
            'device': {'done': done, 'wip': wip, 'not_started': not_started},
            # цвет прибора: worst-of листьев (внимание) + бейдж лучшего прогресса
            'status': _worst_of(statuses),
            'badge': _best_of(statuses),
            'tree': tree,
        })

    # Сводная таблица по листьям (полная покупная картина проекта, всегда видна).
    components = [_leaf_row(leaf, need, supply) for leaf, need in need_by_leaf.items()]
    # 2026-10-20: колонка «Оценка» — план позиции (факт по счёту, остальное по оценке);
    # оранжевые — Парето: позиции, дающие 80% стоимости проекта.
    mark_pareto(components, key='plan_cost')
    mark_pareto(demands)                    # приборы — по оценке своего состава
    # «Горит вперёд» по тону баланса: сначала недобор, затем сошедшиеся в ноль, затем
    # строки с запасом; внутри — по коду.
    components.sort(key=lambda c: (-_WORST_RANK[c['status']], c['component_code']))

    return {
        'project_id': project.id,
        'project_code': project.code,
        'project_name': project.description,
        'demands': demands,
        'components': components,
        # Траты вне потребности (2026-10-19): Σ `plan_cost` строк + это = план бюджета.
        'outside_spent': supply.spent_outside({leaf.id for leaf in need_by_leaf}),
        # Масштаб для меты формы (Ф4) — только детальной форме, список проектов его не ждёт.
        'scale': _project_scale(demand_rows, bom) if with_tree else [],
    }


def _project_scale(demand_rows, bom):
    """Масштаб работы проекта (волна 23, Ф4, вариант Ивана «А»): сколько ШТУК наших
    изделий предстоит собрать, по категориям — «21 система · 137 приборов · 116 узлов
    печатных». Разузлование по `native`-узлам: штуки перемножаются по дереву, поэтому
    дубль (МУДМ в двух системах по 2 шт.) честно даёт 4 сборки; система сама тоже
    считается — её тоже собирают. Покупное сюда не входит — его считает «Потребность».
    Порядок — канон категорий (`CATEGORY_CANON`), незнакомые — в хвосте."""
    counts, cats = {}, {}

    def add(item, qty, visiting):
        key = item.category_id
        counts[key] = counts.get(key, ZERO) + qty
        cats[key] = item.category
        if item.id in visiting:                # страховка от цикла (гасит add_bom_line)
            return
        for bl in bom.children(item):
            if bl.component.native:
                add(bl.component, qty * bl.qty, visiting | {item.id})

    for demand in demand_rows:
        add(demand.target_item, demand.qty, frozenset())
    rank = {code: i for i, (code, _, _) in enumerate(CATEGORY_CANON)}
    keys = sorted(counts, key=lambda k: (rank.get(cats[k].code, 99) if cats[k] else 100,
                                         cats[k].code if cats[k] else ''))
    return [{'category': cats[k].code if cats[k] else None, 'count': counts[k],
             'forms': _count_forms(cats[k])} for k in keys]


def project_health(project, bom=None):
    """Цвет проекта в списке (Ф1b): worst-of здоровья, вычисляемая проекция (как дефицит —
    НЕ храним в БД). Семантика: `to_order` (красный) — хоть что-то не заказано; `on_order`
    (оранжевый) — хоть что-то в пути ИЛИ прибор не собран; `available` (зелёный) — всё
    приехало и собрано. Внутренние проекты и пустые (без потребностей) — `None` (дефицит
    неприменим, глиф нейтрален). Лёгкая версия дефицита (`with_tree=False`)."""
    if project.kind != models.Project.Kind.EXTERNAL:
        return None
    d = project_deficit(project, with_tree=False, bom=bom)
    if not d['demands']:
        return None
    # Здоровье смотрит на ось снабжения (`supply`), а не на тон колонки «Баланс»:
    # сошедшийся в ноль проект здоров, хотя в колонке он оранжевый (запаса нет).
    comp = _worst_of([c['supply'] for c in d['components']]) if d['components'] else 'available'
    assembled = all(dm['device']['not_started'] <= 0 and dm['device']['wip'] <= 0
                    for dm in d['demands'])
    if comp == 'to_order':
        return 'to_order'
    if comp == 'on_order' or not assembled:
        return 'on_order'
    return 'available'


def purchase_coverage(purchase):
    """Цвет заказа в списке (Ф1b): покрытие строк лотами приходов. `to_order` (красный) —
    ни одного лота; `on_order` (оранжевый) — часть пришла; `available` (зелёный) — все
    строки закрыты остатком. Пустой заказ — `to_order` (ничего нет). Из `_line_received`
    (без разузлования — дёшево)."""
    return purchases_coverage([purchase])[purchase.id]


def purchases_coverage(purchases):
    """`{purchase_id: цвет}` для набора заказов (списки, ленты) — строки и поступления
    всех заказов поднимаются двумя запросами, а не парой на заказ."""
    ids = [p.id for p in purchases]
    lines_by_purchase = {pid: [] for pid in ids}
    for pid, item_id, qty in models.PurchaseLine.objects.filter(
            purchase__in=ids).values_list('purchase_id', 'item_id', 'qty'):
        lines_by_purchase[pid].append((item_id, qty))
    received = _received_by(models.Lot.objects.filter(origin__purchase__in=ids))
    return {pid: _coverage_status(pid, lines, received)
            for pid, lines in lines_by_purchase.items()}


def _coverage_status(purchase_id, lines, received):
    """Цвет одного заказа по его строкам `(item_id, qty)` и карте `_received_by`."""
    if not lines:
        return 'to_order'
    total_received = ZERO
    fully = True
    for item_id, qty in lines:
        received_qty = received.get((purchase_id, item_id), ZERO)
        total_received += received_qty
        if received_qty < qty:
            fully = False
    if fully:
        return 'available'
    return 'on_order' if total_received > ZERO else 'to_order'


# --------------------------------------------------------------------------- #
#  Бюджет проекта: два числа денег + себестоимость/экономия (north-star окупаемости)
# --------------------------------------------------------------------------- #
def _project_spent(project, supply=None):
    """Потрачено = **обязательства** + поставки без заказа (волна 24, решение Ивана).

    Обязательства — Σ цен строк ЗАФИКСИРОВАННЫХ заказов проекта: заказ — обязательство,
    нам его выполнять, и ждать УПД, чтобы потом узнать, что денег не хватает, — плохая
    идея. Цена у зафиксированного заказа есть всегда (гейт `lock_purchase`; старые заказы
    без цен расфиксировала миграция `0007`). Поставка, рождённая из заказа, второй раз не
    считается: её деньги уже в заказе. Поставка БЕЗ заказа по-прежнему считается по своим
    лотам (УПД) — ниже прежний канон для неё.

    Прежний канон (до волны 24 — для всех поставок) — Σ стоимостей приходных лотов:

    Точная застывшая цифра «кэша ФЛС». Заёмные/свои бесплатные лоты (origin
    requisition/inventory/kitting) сюда не входят → бесплатны в бюджете (платил
    источник). Только покупные материалы — снимок цены собранного узла (лот-прибор
    из Kitting) в бюджет не складываем (иначе двойной счёт).

    Волна 19, Ф15 (решение Ивана): считаем только лоты **зафиксированных** поставок.
    Это единственное место, где деньги читались с лотов напрямую, мимо движений, —
    поэтому гейт склада его бы не накрыл, а черновой УПД двигал бы бюджет проекта
    всем пользователям. Черновая поставка не в «потрачено» и не на складе: её
    позиции остаются в «в пути / к заказу» — картина связная.
    """
    # 2026-10-19: правило живёт в одном месте — `ProjectSupply.spent` по позициям; бюджет
    # их складывает. Так «Потр.» строки и план шапки не могут разойтись в определении.
    return sum((supply or ProjectSupply(project))._spent_by_item().values(), ZERO)


def project_budget(project):
    """Деньги проекта — блок «Деньги» его формы (волна 26).

    **Главное число — потрачено** (решение Ивана 2026-10-19): освоенные рубли — маркер
    того, что работа идёт, и объективный факт для отчёта. Правило «потрачено» живёт в
    `ProjectSupply.spent` (обязательства по счёту + поставки без заказа по УПД).

    Поддержка решений по затратам:
    - **план** — потрачено + деньги впереди по оценке (`plan_ahead`: план зафиксированных
      закупок с запасом, сборка, нехватка); тот же, что сумма над «Потр.» таба;
    - `spent_of_budget` / `spent_of_plan` — доли освоения (отчёт по контракту / ход
      работы); компас `budget − план` = запас/перерасход;
    - **сверх потребности** — `план / чистая потребность − 1`, где чистая потребность =
      нужда по BOM × оценка, без запаса. Честно смешивает причины; раскладка: запас
      закупок количеством (`reserve`, то же правило, что «в т.ч. запас» таба), куплено вне
      BOM (`outside`), остальное — разница цен счёта с оценкой и прочее (`price_gap`).
    Покупные листья без оценки с деньгами впереди — `unestimated` (план неполон).

    Себестоимость и экономия сняты (волна 26 → BACKLOG): своего не паяем ещё полгода.
    """
    leaves, _incomplete = project_leaf_demand(project)
    supply = ProjectSupply(project)
    spent = _project_spent(project, supply)
    ahead, unestimated = ZERO, []
    need_money, reserve = ZERO, ZERO
    for leaf, need in leaves.items():
        price = leaf.estimated_cost
        remaining = supply.plan_ahead(leaf, need)
        if remaining > 0:
            if price is None:
                unestimated.append(leaf.code)
            else:
                ahead += remaining * price
        if price is not None:
            need_money += need * price
            row = supply.balance(leaf, need)
            if row['planned'] > 0 and row['balance'] > 0:
                reserve += min(row['planned'], row['balance']) * price
    plan = spent + ahead
    outside = supply.spent_outside({leaf.id for leaf in leaves})
    budget = project.budget
    return {
        'project_id': project.id,
        'project_code': project.code,
        'project_name': project.description,
        'budget': budget,                       # может быть None
        'spent': spent,                         # ★ потрачено (факт)
        'plan': plan,                           # прогноз полной стоимости
        'compass': (budget - plan) if budget is not None else None,
        'spent_of_budget': spent / budget if budget else None,
        'spent_of_plan': spent / plan if plan else None,
        'need': need_money,                     # чистая потребность (нужда × оценка)
        'over_need': _ratio(plan, need_money),  # сверх потребности (+0,22 = +22%)
        'reserve': reserve,
        'outside': outside,
        'price_gap': plan - need_money - reserve - outside,
        'unestimated': unestimated,             # покупные позиции без оценки
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
                   .values('location', 'location__code', 'location__description')
                   .annotate(q=Sum('qty')).order_by('location'))
        by_location = [
            {'location_id': r['location'], 'code': r['location__code'],
             'description': r['location__description'], 'available': r['q']}
            for r in loc_agg if r['q']
        ]
        rows.append({
            'project_id': project.id,
            'project_code': project.code,
            'project_name': project.description,
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
        'item_code': item.code,
        'item_description': item.description,
        'uom': item.uom,
        'rows': rows,
    }


# --------------------------------------------------------------------------- #
#  Форма комплектации (волна 2): реальные строки + призрачные строки
# --------------------------------------------------------------------------- #
def available_lots(item, project, location=None):
    """Лоты item в проекте с живым остатком > 0 — кандидаты под пайку.

    Волна 13, Ф2e: опциональный `location` сужает до лотов с остатком > 0 **в этом
    месте хранения** (пикер под конкретную локацию). По умолчанию — как раньше
    (остаток по всем локациям), контракт формы комплектации байт-в-байт.
    """
    lots = list(models.Lot.objects.filter(item=item, project=project)
                .select_related('item', 'origin'))
    return _candidate_rows(lots, lots_live_qty(lots, location))


def _candidate_rows(lots, live_by_lot):
    """Строки пикера `available_lots` по уже поднятым партиям и их остаткам."""
    result = []
    for lot in lots:
        live = live_by_lot[lot.id]
        if live > 0:
            result.append({
                'lot_id': lot.id, 'live_qty': live, 'unit_cost': lot.unit_cost,
                'cost': lot.cost,
                'part_number': lot.part_number,
                'origin': lot.origin_kind, 'lot_name': lot.lot_name,
            })
    return result


def _require_native_target(item):
    """«Комплектуем только своё» (решение Ивана 2026-07-31): целью комплектации может
    быть лишь наше изделие. Дружелюбный гейт входного слоя; страховка — в
    `StockDocument.clean` (CHECK на чужую таблицу MySQL не умеет, см. модель)."""
    if item is not None and not item.native:
        raise ValidationError(models.KITTING_TARGET_NATIVE)


def create_kitting(project, user, target_item=None, qty=None, date=None):
    """Создать комплектацию — рождение переехало из вьюхи в движок (Ф12e).

    `target_item`/`qty` необязательны при рождении: их требует ФИКСАЦИЯ (CHECK
    `doc_locked_kitting_has_target`), потому что до выбора прибора форма всё равно
    пуста — BOM разузловать не от чего. Номера у комплектации нет
    (`REQUIRED_HEADER_BY_KIND[KITTING] = ()`), но `code` она получает общий."""
    _require_native_target(target_item)
    return _born_order(models.Kitting, project, user, date=date,
                       target_item=target_item, qty=qty)


def kitting_form(kitting):
    """Проекция формы сборки (1 уровень BOM целевого прибора).

    Каждая строка BOM: `надо = bom.qty × kitting.qty`, пробитые `KittingLine`
    (реальные зелёные строки) и остаток → **призрачная строка**, покрашенная по
    доступности компонента в проекте (`_coverage`, тот же словарь ✓/●/▲) с лотами-
    кандидатами под пайку. Ничего не хранит — чистая проекция.
    """
    # Ф12e: комплектация рождается по клику, прибор-цель выбирают уже в форме —
    # до выбора разузловывать нечего, и это не ошибка, а нормальный черновик.
    target = kitting.target_item
    project = kitting.project
    rows = []
    statuses = []
    is_wip = not kitting.locked
    # `qty` черновика может быть пустым (Ф12e: рождение по клику не спрашивает ничего),
    # а состав у цели уже есть — проекция обязана это пережить. Раньше здесь падало
    # `Decimal * None` → 500 ровно на выборе НАШЕГО изделия (у покупного состава нет,
    # цикл не заходил, и баг выглядел вывернутым наизнанку). Пустое кол-во = «потребность
    # ещё не задана» → надо 0, призраков нет; выбор цели её тут же и проставляет
    # (`_set_target_item`), так что состояние мимолётное.
    bom_lines = list(target.bom_lines.select_related('component', 'component__category')
                     if target else ())
    # Всё, что строки спрашивают про свои компоненты, поднимаем разом: пробитые строки,
    # члены покрытия (`ProjectSupply`) и лоты-кандидаты с остатками — не по запросу на строку.
    component_ids = [bl.component_id for bl in bom_lines]
    pierced_by_item = {}
    for kl in kitting.lines.filter(lot__item__in=component_ids).select_related('lot'):
        pierced_by_item.setdefault(kl.lot.item_id, []).append(kl)
    supply = ProjectSupply(project)
    lots_by_item = {}
    if is_wip:
        project_lots = list(models.Lot.objects.filter(item__in=component_ids, project=project)
                            .select_related('item', 'origin'))
        for lot in project_lots:
            lots_by_item.setdefault(lot.item_id, []).append(lot)
        live_by_lot = lots_live_qty(project_lots)
    for bl in bom_lines:
        component = bl.component
        need = bl.qty * (kitting.qty or ZERO)
        real_lines = []
        pierced = ZERO
        # компонент строки выводится из lot.item (StockLine его не хранит);
        # qty знаковый — наружу отдаём магнитуду (положительную), проекция без изменений.
        for kl in pierced_by_item.get(component.id, ()):
            mag = -kl.qty
            pierced += mag
            real_lines.append({
                'id': kl.id, 'lot_id': kl.lot_id,
                'lot_label': f'#{kl.lot_id} {kl.lot.lot_name or component.code}',
                'qty': mag, 'date': kl.date,
            })
        remaining = max(ZERO, need - pierced)
        ghost = None
        if remaining > 0 and is_wip:
            cov = _coverage(remaining, supply.available(component),
                            supply.on_order(component))
            ghost = {
                'status': cov['status'], 'have': cov['have'],
                'on_order': cov['on_order'], 'to_order': cov['to_order'],
                'candidate_lots': _candidate_rows(lots_by_item.get(component.id, []),
                                                  live_by_lot),
            }
            statuses.append(cov['status'])
        rows.append({
            'component_id': component.id, 'component_code': component.code,
            'component_description': component.description, 'uom': component.uom,
            'component_category': category_code(component),   # фильтр колонки
            # Оси компонента — под глиф строки (§7a), как в заказе и закупке-плане:
            # форма = изделие/компонент, цвет = покрытие строки складом проекта.
            'component_native': component.native, 'component_synced': component.synced,
            'component_locked': component.locked,
            'need': need, 'pierced': pierced, 'remaining': remaining,
            'real_lines': real_lines, 'ghost': ghost,
        })
    born_lots = [
        {'id': lot.id, 'qty': lot.qty, 'cost': lot.cost, 'unit_cost': lot.unit_cost,
         'lot_name': lot.lot_name, 'part_number': lot.part_number}
        for lot in kitting.lots.all()
    ]
    return {
        'id': kitting.id, **_author(kitting), 'locked': kitting.locked,
        'code': kitting.code, 'description': kitting.description,
        'project_id': project.id, 'project_code': project.code,
        'target_id': target.id if target else None,
        'target_code': target.code if target else '',
        'target_description': target.description if target else '',
        'uom': target.uom if target else '',
        'qty': kitting.qty, 'date': kitting.date,
        'worst_status': _worst_of(statuses),   # worst-of призрачных строк
        'rows': rows,
        'born_lots': born_lots,   # рождённые лоты-приборы (после закрытия)
        'total_cost': kitting_cost(kitting),   # волна 26: ★ «израсходовано на сумму»
    }


# --------------------------------------------------------------------------- #
#  Мутации формы (единый источник правил + пересборка проекции склада)
# --------------------------------------------------------------------------- #
def add_kitting_line(kitting, component, lot, qty, location=None, date=None):
    """Пайка: промоушн призрачной строки в реальную `KittingLine` + `-ISSUE`."""
    _require_unlocked(kitting)
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
    _require_unlocked(line.document)
    if qty is None or qty <= 0:
        raise ValidationError('Количество пайки должно быть положительным.')
    line.qty = -qty                      # знаковая строка (− расход)
    line.save(update_fields=['qty'])
    rebuild_movements(line.lot)


def remove_kitting_line(line):
    """Удалить пробитую строку (коррекция до замка) + пересобрать движения лота."""
    _require_unlocked(line.document)
    lot = line.lot
    line.delete()
    rebuild_movements(lot)


def kitting_cost(kitting):
    """Стоимость набора комплектации = Σ стоимостей строк пайки (учётный канон, волна 26).

    Это и «израсходовано на сумму» формы, и снимок себестоимости рождённой партии-прибора
    (`Lot.cost`) — без деления на штуки и округления: прибор стоит ровно столько, сколько
    стоили впаянные доли партий. До фиксации строки черновые — сумма их предпросмотр."""
    lines = [kl for kl in kitting.lines.select_related('lot', 'document') if kl.qty < 0]
    return -sum(lines_values(lines).values(), ZERO)


def _sync_born_cost(doc):
    """Стоимость партий, которые документ рождает ИЗ своих строк расхода (волна 26).

    Комплектация — партия-прибор стоит Σ впаянного (`kitting_cost`); требование — партия-
    потомок стоит ровно долю, ушедшую из источника её строкой. Зовётся после пересборки
    источников (`rebuild_document_movements`) и при правке черновика. Снимок: если позже
    сдвинется очередь расходов источника (расфиксировали ордер из её середины), доля
    может уйти на копейку — проекция мутабельна, снимок нет (как и прежде у прибора).
    Поставка/инвентаризация рождают партии из воздуха документа — их стоимость вводят."""
    kind = doc.KIND or doc.kind
    if kind == models.DocumentKind.KITTING:
        cost = kitting_cost(doc)
        doc.lots.exclude(cost=cost).update(cost=cost)
    elif kind == models.DocumentKind.REQUISITION:
        lines = list(doc.lines.select_related('lot', 'document'))
        values = lines_values(lines)
        for line in lines:
            doc.lots.filter(predecessor=line.lot).exclude(
                cost=-values[line.id]).update(cost=-values[line.id])


def lock_kitting(kitting):
    """Закрыть комплектацию: рождается лот-прибор (`+RECEIPT`), замок ставится.

    Ф15 сделала фиксацию единым событием склада: вместе с рождением прибора
    материализуется и **пайка** (`−ISSUE` компонентов) — до замка её строки склад не
    двигали. Раньше комплектация была наполовину по правилу: лот ждал замка, а
    компоненты списывались сразу.
    """
    _require_unlocked(kitting)
    # Ф12e: комплектация рождается без прибора-цели — гейт здесь (своей дорогой
    # мимо `lock_document`, поэтому зовём явно).
    _require_header(kitting)
    if kitting.lots.exists():
        raise ValidationError('У комплектации уже есть рождённый лот-прибор.')
    # Стоимость прибора проставит `_sync_born_cost` — после того, как пайка
    # материализуется и её доли займут место в очереди расходов источников.
    models.Lot.objects.create(
        item=kitting.target_item, project=kitting.project, origin=kitting,
        qty=kitting.qty, cost=ZERO,
    )
    kitting.locked = True
    kitting.save(update_fields=['locked'])
    rebuild_document_movements(kitting)     # лот-прибор + пайка компонентов
    return kitting.lots.first()


def unlock_kitting(kitting):
    """Расфиксировать комплектацию: снять лот-прибор + отпустить пайку (Ф15).

    Guard: лот-прибор не должен быть потреблён/передан/отпочкован ниже.
    """
    if not kitting.locked:
        raise ValidationError('Расфиксировать можно только зафиксированную комплектацию.')
    for lot in kitting.lots.all():
        if _lot_consumed_downstream(lot):
            raise ValidationError(
                'Лот-прибор уже потреблён/передан ниже — переоткрытие заблокировано.')
    for lot in kitting.lots.all():
        lot.movements.all().delete()
        lot.delete()
    kitting.locked = False
    kitting.save(update_fields=['locked'])
    rebuild_document_movements(kitting)     # снять `−ISSUE` компонентов


# --------------------------------------------------------------------------- #
#  Форма прихода / УПД (волна 3): строки-лоты, рождение +RECEIPT, мягкий замок
# --------------------------------------------------------------------------- #
def _lot_consumed_downstream(lot):
    """Потреблён ли лот ниже: расход/пайка/передача/списание/отпочкование/успех.

    Общий guard: до `PROTECT`-ошибки БД даём дружелюбный отказ на разрушающую
    правку (удаление строки прихода, переоткрытие комплектации).
    """
    return (lot.movements.filter(qty__lt=0).exists() or lot.successors.exists()
            or lot.stock_lines.exists())


def _consumed_lot_ids(lots):
    """Множество id партий набора, потреблённых ниже (`_lot_consumed_downstream`
    для формы целиком — три запроса на документ, а не на строку)."""
    ids = [lot.id for lot in lots]
    if not ids:
        return set()
    consumed = set(models.StockMovement.objects.filter(lot_id__in=ids, qty__lt=0)
                   .values_list('lot_id', flat=True))
    consumed.update(models.Lot.objects.filter(predecessor_id__in=ids)
                    .values_list('predecessor_id', flat=True))
    consumed.update(models.StockLine.objects.filter(lot_id__in=ids)
                    .values_list('lot_id', flat=True))
    return consumed


def create_receipt(project, user, number='', date=None, contractor=None):
    """Создать поставку (УПД) — рождение переехало из вьюхи в движок (Ф12e).

    Раньше `views.receipts` строила `Receipt` сырым `objects.create` и требовала
    `contractor_id` + непустой `number`: артефакт формы создания. Оба поля теперь
    обязательны к ФИКСАЦИИ (`REQUIRED_HEADER_BY_KIND` + CHECK
    `doc_locked_receipt_has_contractor`), а не к рождению."""
    return _born_order(models.Receipt, project, user, number, date,
                       contractor=contractor)


def receipt_form(receipt):
    """Проекция формы прихода: шапка УПД + строки-лоты (каждая строка = Lot).

    В модели отдельной `ReceiptLine` нет — строки прихода это его лоты. Каждый лот
    показывает рождённое кол-во, живой остаток (просел ли под пайку), цену и
    название из УПД. Ничего не хранит — чистая проекция.
    """
    lots = []
    total = ZERO
    receipt_lots = list(receipt.lots.select_related('item', 'item__category').order_by('id'))
    live_by_lot = lots_live_qty(receipt_lots)
    consumed = _consumed_lot_ids(receipt_lots)
    by_order, matched = None, ZERO
    shares = _purchase_shares(receipt.purchase, receipt_lots) if receipt.purchase_id else {}
    for lot in receipt_lots:
        total += lot.cost
        # Волна 26: сверка с заказом — что эти позиции стоят по его счёту (доля цены
        # строки, тем же правилом, что рождение партии из заказа). Позиции вне заказа в
        # сверку не входят: сравнивать их не с чем.
        if lot.id in shares:
            by_order = (by_order or ZERO) + shares[lot.id]
            matched += lot.cost
        lots.append({
            'id': lot.id, 'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'item_category': category_code(lot.item),   # фильтр колонки
            'qty': lot.qty, 'live_qty': live_by_lot[lot.id],
            # Волна 26: стоимость строки УПД — первична; цена штуки — производная.
            'cost': lot.cost, 'unit_cost': lot.unit_cost, 'lot_name': lot.lot_name,
            'part_number': lot.part_number,
            'consumed': lot.id in consumed,
        })
    return {
        'id': receipt.id, **_author(receipt), 'number': receipt.number, 'date': receipt.date,
        'code': receipt.code, 'description': receipt.description,
        # Ф14: колонка стала nullable (обязательность — на фиксации, не на рождении),
        # поэтому проекция больше не опирается на прежний NOT NULL.
        **_contractor_view(receipt.contractor),
        # Ф17: «кто привёз» ≠ «у кого купили» — расхождение с контрагентом заказа
        # считает движок, форма только рисует оранжевый глиф (не гейт).
        'contractor_mismatch': _contractor_mismatch(receipt.contractor_id,
                                                    receipt.purchase),
        'project_id': receipt.project_id, 'project_code': receipt.project.code,
        'project_name': receipt.project.description,
        'purchase_id': receipt.purchase_id,   # связанный заказ (закрытие строк)
        'locked': receipt.locked, 'total_cost': total,
        # Волна 26: «по заказу на эти позиции» и расхождение УПД со счётом (`None` — не из
        # заказа или сравнивать нечего).
        'by_order': by_order,
        'order_gap': (matched - by_order) if by_order is not None else None,
        'lots': lots,
    }


def add_receipt_lot(receipt, item, qty, cost=ZERO, lot_name='',
                    part_number=''):
    """Добавить строку УПД: рождается партия (`+RECEIPT`) в проекте прихода.
    `cost` — стоимость строки УПД целиком (волна 26), а не цена штуки."""
    _require_unlocked(receipt)
    if qty is None or qty <= 0:
        raise ValidationError('Количество прихода должно быть положительным.')
    if cost is not None and cost < 0:
        raise ValidationError('Стоимость не может быть отрицательной.')
    lot = models.Lot.objects.create(
        item=item, project=receipt.project, origin=receipt, qty=qty,
        cost=cost or ZERO, lot_name=lot_name or '',
        part_number=part_number or '',
    )
    rebuild_movements(lot)
    return lot


def _rescaled_cost(lot, qty):
    """Стоимость партии после правки количества без явной стоимости (волна 26).

    Цена штуки сохраняется: стоимость масштабируется долей. Партия поставки из заказа,
    которую не правили руками (стоимость = её доля цены строки), пересчитывается ТОЧНО
    от цены строки — так поставка частями сходится со счётом до копейки."""
    share = _purchase_share(lot)
    if share is not None and share[0] == lot.cost:
        line, before = share[1], share[2]
        return _share(line.price, line.qty, before + qty) - _share(line.price, line.qty, before)
    return _share(lot.cost, lot.qty, qty)


def _purchase_share(lot):
    """Доля цены строки заказа, положенная партии поставки из заказа: `(доля, строка,
    поступило до неё)`; `None` — партия не из заказа или у строки нет цены.

    «Поступило до» — по зафиксированным поставкам этого заказа, рождённым РАНЬШЕ партии
    (тот же гейт, что `_line_received`: черновая накладная заказ не гасит; порядок по `id`,
    как у очереди расходов) — так доля зафиксированной партии не зависит от поставок,
    пришедших после неё."""
    origin = lot.origin
    if origin.kind != models.DocumentKind.RECEIPT or not origin.purchase_id:
        return None
    line = origin.purchase.lines.filter(item_id=lot.item_id).first()
    if line is None or line.price is None or not line.qty:
        return None
    before = models.Lot.objects.filter(
        origin__purchase_id=origin.purchase_id, origin__locked=True, item_id=lot.item_id,
        pk__lt=lot.pk,
    ).aggregate(s=Sum('qty'))['s'] or ZERO
    return (_share(line.price, line.qty, before + lot.qty)
            - _share(line.price, line.qty, before), line, before)


def _purchase_shares(purchase, lots):
    """`{lot.id: доля цены строки}` для партий одной поставки из заказа — пакетом (тем же
    правилом, что `_purchase_share`: до партии — зафиксированные поставки заказа, рождённые
    раньше неё). Партии без строки заказа или без цены в словарь не попадают."""
    lines = {ln.item_id: ln for ln in purchase.lines.all()
             if ln.price is not None and ln.qty}
    earlier = list(models.Lot.objects.filter(origin__purchase=purchase, origin__locked=True)
                   .values_list('id', 'item_id', 'qty'))
    out = {}
    for lot in lots:
        line = lines.get(lot.item_id)
        if line is None:
            continue
        before = sum((q for i, item_id, q in earlier
                      if item_id == lot.item_id and i < lot.id), ZERO)
        out[lot.id] = (_share(line.price, line.qty, before + lot.qty)
                       - _share(line.price, line.qty, before))
    return out


def update_receipt_lot(lot, qty=None, cost=None, lot_name=None,
                       part_number=None):
    """Автосейв строки УПД (кол-во/стоимость/название/PN). Правка до замка.

    Кол-во не клампим по потреблению: уронить ниже списанного можно — живой остаток
    уйдёт в минус (недостача информативнее, в духе мутабельной ДНК). Правка количества
    без стоимости сохраняет цену штуки (`_rescaled_cost`); явная стоимость — главнее.
    """
    _require_unlocked(lot.origin)
    fields = []
    if qty is not None:
        if qty <= 0:
            raise ValidationError('Количество прихода должно быть положительным.')
        if cost is None and qty != lot.qty:
            lot.cost = _rescaled_cost(lot, qty)
            fields.append('cost')
        lot.qty = qty
        fields.append('qty')
    if cost is not None:
        if cost < 0:
            raise ValidationError('Стоимость не может быть отрицательной.')
        lot.cost = cost
        if 'cost' not in fields:
            fields.append('cost')
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
    _require_unlocked(lot.origin)
    if _lot_consumed_downstream(lot):
        raise ValidationError(
            'Партия уже потреблена ниже (пайка/передача) — удаление заблокировано.')
    lot.movements.all().delete()
    lot.delete()


def lock_receipt(receipt):
    """Поставить замок «сверено со сканом» — форма прихода read-only, партии УПД
    ложатся на склад (Ф15). Ф15 заодно сняла рукописную копию `lock_document`:
    поставка ходит общей дорогой, как остальные пять ордеров."""
    return lock_document(receipt, receipt.lots,
                         'Нельзя сверить пустой приход — добавьте строку.')


def unlock_receipt(receipt):
    """Снять замок — снова разрешить правку (партии УПД уходят со склада, Ф15).
    Ничего не разрушает (в отличие от переоткрытия комплектации), поэтому guard по
    потомкам не нужен."""
    return unlock_document(receipt)


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


PURCHASE_DRAFT_NO_RECEIPT = (
    'УПД создаётся по зафиксированному заказу — сперва зафиксируйте заказ.')
PURCHASE_CLOSED_NO_RECEIPT = (
    'Заказ закрыт полностью — по нему нечего принимать.')


def create_receipt_from_purchase(purchase, user, number='', date=None):
    """Родить черновик УПД по заказу: строки — ОСТАТКОМ заказа (волна 19, Ф6).

    В 98% случаев накладная повторяет заказ 1:1, и набивать строки заново незачем.
    Остаток (`qty − уже получено`, тот же `_line_received`, что красит форму заказа)
    вместо полного количества даёт «поставку частями» бесплатно: повторный вызов на
    частично закрытом заказе рождает вторую накладную ровно на недостающее.

    Поставщик — `purchase.contractor` (волна 19, Ф17): «кто привёз» наследуется от «у
    кого купили», копией при рождении. До Ф17 он читался сквозь цепочку
    `purchase.procurement.contractor` (Р3, отменена), и заказ без плана поставщика не
    знал вовсе. Заказ проставляется сразу (`purchase`), поэтому руками связывать в форме
    УПД больше не нужно.

    **Цена — из строки заказа, по счёту** (волна 24, решение Ивана 2026-10-16): партия
    получает долю цены строки (волна 26: стоимость, не цену штуки — `_share`). Заказ —
    объективный источник правды о цене, и в 99,9% случаев УПД её повторяет, так что
    вбивать её заново незачем. Копия при рождении, жёстко не связываем — расхождение по
    УПД правится в поставке («ручка для крайних случаев»). Оценку изделия в лот
    по-прежнему не кладём никогда (решение 2026-07-29: оценка, забытая при фиксации, молча
    стала бы фактом бюджета); строка без цены (заказ зафиксирован до волны 24) едет нулём —
    ноль виден глазом.
    Имя лота преднабиваем описанием изделия — его пользователь и правит по УПД.

    Всё рождённое — черновик: до фиксации на складе ничего не лежит (Ф15).
    """
    if not purchase.locked:
        raise ValidationError(PURCHASE_DRAFT_NO_RECEIPT)
    # Черновая накладная заказ не гасит (Ф6-правка `_line_received`), поэтому повторный
    # клик молча плодил бы её близнеца. Отправляем в уже заведённую: «частями» — это
    # ЗАФИКСИРОВАТЬ первую, а потом жать снова на остаток.
    open_receipt = models.Receipt.objects.filter(purchase=purchase, locked=False).first()
    if open_receipt is not None:
        raise ValidationError(
            f'По заказу уже заведена черновая поставка {open_receipt.code or open_receipt.number}'
            ' — заполните и зафиксируйте её; за остатком вернётесь сюда.')
    remaining = [
        (line, line.qty - _line_received(line))
        for line in purchase.lines.select_related('item').order_by('id')
    ]
    remaining = [(line, rest) for line, rest in remaining if rest > 0]
    if not remaining:
        raise ValidationError(PURCHASE_CLOSED_NO_RECEIPT)

    receipt = _born_order(
        models.Receipt, purchase.project, user, number, date,
        contractor=purchase.contractor, purchase=purchase)
    for line, rest in remaining:
        # Волна 26: партия получает свою ДОЛЮ цены строки накопительным округлением —
        # поставки частями в сумме дают счёт до копейки (раньше цена штуки округлялась).
        received = line.qty - rest
        add_receipt_lot(receipt, line.item, rest,
                        cost=(_share(line.price, line.qty, line.qty)
                              - _share(line.price, line.qty, received)
                              if line.price is not None else ZERO),
                        lot_name=line.item.description)
    return receipt


# --------------------------------------------------------------------------- #
#  Форма заказа / Purchase (волна 4): строки-обязательства + гашение приходом
# --------------------------------------------------------------------------- #
def create_purchase(procurement, user, item_ids=(), date=None, code=None, description=''):
    """Родить черновой заказ из закупки (волна 24) — единственный путь рождения заказа.

    Заказ — следствие работы с закупкой, поэтому рождается только из неё: проект он
    выводит через закупку, контрагента копирует из неё (наследование копией, Ф17), а
    строки — выбранные позиции плана с количеством **остатка** (хотим − уже в заказах
    этой закупки, не меньше нуля). Отсюда «разъезд» на несколько счетов без особого
    режима: урезал первый заказ — у строки плана появился остаток — второй «Новый
    заказ» берёт ровно его. Пустой выбор законен: заказ набирают руками в его форме.
    Работает и на черновой закупке — фиксация плана не блок для заказа (решение Ивана).
    Пустой код — фолбэком «Заказ 12» (Ф12e).
    """
    require_unique_code(models.Purchase, code)
    plan = {ln.item_id: ln for ln in procurement.lines.order_by('id')}
    chosen = [iid for iid in plan if iid in set(item_ids)]
    if len(chosen) != len(set(item_ids)):
        raise ValidationError('Позиция не в плане закупки — заказ берёт только строки плана.')
    rest = procurement_remainders(procurement)
    p = models.Purchase.objects.create(
        procurement=procurement, user=user,
        locked=False, date=date, code=code, description=description or '')
    models.PurchaseLine.objects.bulk_create([
        models.PurchaseLine(purchase=p, item_id=iid, qty=max(ZERO, rest[iid]))
        for iid in chosen])
    return p if code else fallback_code(p, 'Заказ')


def procurement_remainders(procurement):
    """`{item_id: остаток}` строк плана: хотим − Σ строк ВСЕХ заказов закупки (волна 24).

    Черновые заказы тоже вычитаем: остаток отвечает «что ещё никуда не взято», а не
    «что не под обязательством» (это — `planned`). Знаковый: перебор заказов по строке
    даёт минус, и форма его покажет.
    """
    taken = {}
    for item_id, qty in models.PurchaseLine.objects.filter(
            purchase__procurement=procurement).values_list('item_id', 'qty'):
        taken[item_id] = taken.get(item_id, ZERO) + qty
    return {item_id: qty - taken.get(item_id, ZERO)
            for item_id, qty in procurement.lines.values_list('item_id', 'qty')}


def purchase_candidates(purchase):
    """Позиции плана, которые заказ может взять строкой-призраком (волна 24).

    Только строки его закупки с остатком > 0 и которых в заказе ещё нет: выпадашка
    убывает по мере того, как заказы закрывают план. Количество по умолчанию — остаток,
    то же правило, что у окна «Новый заказ».
    """
    rest = procurement_remainders(purchase.procurement)
    have = set(purchase.lines.values_list('item_id', flat=True))
    out = []
    for ln in (purchase.procurement.lines.select_related('item', 'item__category')
               .order_by('item__code')):
        if ln.item_id in have or rest[ln.item_id] <= 0:
            continue
        out.append({'item_id': ln.item_id, 'item_code': ln.item.code,
                    'item_description': ln.item.description, 'uom': ln.item.uom,
                    'remaining': rest[ln.item_id]})
    return out


def _purchase_closure(purchase):
    """`{item_id: [{receipt_id, number, date, qty}]}` — чем закрыта каждая строка (Ф6).

    Источник — лоты приходов заказа (`Lot.origin → Receipt.purchase`); сопоставление
    по изделию, отдельного FK «строка заказа ↔ лот» не заводим: `PurchaseLine` уникален
    по `(purchase, item)`, поэтому атрибуция однозначна. Несколько лотов одного изделия
    в одной накладной (разные партии одной позиции УПД) сворачиваются в одну строку —
    пользователь спрашивает «какой накладной закрыто», а не «сколькими партиями».

    Заодно это ИСТОЧНИК `received` для формы: та же выборка, что у `_line_received`
    (включая гейт `origin__locked` — закрывают заказ только зафиксированные накладные),
    но одним запросом на заказ вместо запроса на строку.
    """
    out = {}
    lots = (models.Lot.objects.filter(origin__purchase=purchase, origin__locked=True)
            .select_related('origin').order_by('origin__date', 'origin_id', 'id'))
    for lot in lots:
        rows = out.setdefault(lot.item_id, [])
        for r in rows:
            if r['receipt_id'] == lot.origin_id:
                r['qty'] += lot.qty
                break
        else:
            rows.append({'receipt_id': lot.origin_id, 'number': lot.origin.number,
                         'date': lot.origin.date, 'qty': lot.qty})
    return out


def _contractor_mismatch(own_contractor_id, parent):
    """Расхождение контрагента с уровнем НАД ним (волна 19, Ф17) — флаг для формы.

    Контрагент есть у всех трёх уровней контура (закупка = ЧТО купить, заказ = У КОГО,
    поставка = КТО привёз) и наследуется копией при рождении, после чего живёт своей
    жизнью. Расхождение — законная ситуация («одна закупка точно может пойти от разных
    поставщиков»), поэтому это **не гейт фиксации**, а оранжевый глиф-warning в форме:
    в случае ошибки она кричит и подсказывает, в редком законном случае не мешает.

    Считаем только когда **оба** контрагента заданы и различаются: пустой снизу — это
    «не выбран», а не расхождение. Флаг считает движок, знак выбирает вью
    ([[engine-view-seam]]) — иначе форма сравнивала бы два id сама.
    """
    parent_id = parent.contractor_id if parent is not None else None
    return bool(own_contractor_id and parent_id and own_contractor_id != parent_id)


def lines_estimate(lines):
    """Оценка документа-намерения: `Σ(qty × item.estimated_cost)` + позиции без оценки.

    Прямое перемножение по строкам, без разузлования: строка закупки/заказа — это то,
    что покупают КАК ЕСТЬ, и цена берётся с самого изделия (у производимого там лежит
    роллап его состава — тоже валидная оценка покупки узла на стороне).

    Считаем по тем, у кого оценка есть, а коды остальных возвращаем списком: молча
    сложить их как 0 значило бы выдать неполную сумму за полную. Тот же приём, что у
    `_project_estimate` (`unestimated`) — вью показывает счётчик, а коды кладёт в title.

    Это НЕ деньги документа: факт живёт в поставке (`Lot.cost`). Здесь — прогноз,
    «во сколько это обойдётся», и цена может ещё десять раз поменяться.
    """
    estimate = ZERO
    unestimated = []
    for line in lines:
        if line.item.estimated_cost is None:
            unestimated.append(line.item.code)
            continue
        estimate += line.qty * line.item.estimated_cost
    return estimate, unestimated


def demand_map(projects):
    """`{item_id: нужда по листьям}` через набор проектов — знаменатель денег намерения.

    Та же нужда, что в «Потребности» проекта и закупки (`project_leaf_demand`,
    разузлование насквозь), только сложенная по Item и **без покрытия**: панель бюджета
    отвечает «сколько деталей нужно по-настоящему», а не «сколько осталось докупить».
    Между проектами не перенеттим: нужда проекта — его собственная.
    """
    total = {}
    bom = BomIndex()
    for project in projects:
        leaves, _incomplete = project_leaf_demand(project, bom)
        for leaf, qty in leaves.items():
            total[leaf.id] = total.get(leaf.id, ZERO) + qty
    return total


def intent_money(lines, need_by_item):
    """Три числа денег документа-намерения (2026-08-07): нужда / сумма строк / разница.

    - `demand` — **потребность**: `Σ` по строкам `нужда_проекта(item) × estimated_cost`.
      Сколько денег на эти позиции нужно по-настоящему, без запаса. Количество берётся
      НЕ из строки, а из потребности проекта — строка задаёт только номенклатуру.
    - `estimate` — сумма самого документа (`lines_estimate`, «во сколько обойдётся»).
    - `overpay` — их разница со знаком: `+` переплата (взяли с запасом), `−` недозаказ
      (взяли меньше нужды). Знак считает движок, подпись и цвет выбирает вью
      ([[engine-view-seam]]).

    Цена у обоих чисел одна — `estimated_cost` изделия. Поэтому позиция без оценки
    выпадает из **обеих** сумм разом и знак разницы не врёт; её код — в `unestimated`.
    Деньги ЗАКАЗА считает `purchase_money` — там цена по счёту, а не оценка (волна 24).

    Числа — витрина, а не снимок: замок морозит строки, но не цену и не BOM, поэтому у
    зафиксированного документа они законно едут вслед за справочником.

    Потребность проекта не поделена между его заказами: два заказа на один Item покажут
    каждый полную нужду. Число отвечает «сколько из ЭТОГО документа оправдано нуждой», и
    по проекту не складывается.
    """
    estimate, unestimated = lines_estimate(lines)
    demand = ZERO
    for line in lines:
        if line.item.estimated_cost is None:
            continue                      # уже учтён в `unestimated` — молчим в обеих суммах
        demand += need_by_item.get(line.item_id, ZERO) * line.item.estimated_cost
    return {'demand': demand, 'estimate': estimate, 'overpay': estimate - demand,
            'unestimated': unestimated}


def _ratio(part, whole):
    """Отношение `part / whole − 1` (знаковая доля: +0,22 = «на 22% больше»); `None`, если
    знаменателя нет — процент от нуля не бывает, вью рисует прочерк."""
    if not whole:
        return None
    return part / whole - 1


def procurement_money(procurement, lines=None):
    """Деньги закупки (волна 26) — главное число и его поддержка.

    **Закупка** = обязательства по счёту там, где позиции закрыты заказами, + оценка
    остатка там, где ещё нет (то же правило, что «план» проекта: факт где есть, оценка где
    нет). Все позиции закрыты — число становится чистым фактом (`is_fact`): «во сколько
    обошлась электроника» до копейки.

    - `ordered` — Σ цен строк ЗАФИКСИРОВАННЫХ заказов этой закупки (обязательства);
    - `rest` — остаток плана сверх заказанного × оценка изделия (`max(0, план − заказано)`);
    - `total` = ordered + rest;
    - `invoice_gap` — счёт к оценке по заказанным позициям: `Σ счёт / Σ (кол-во × ТЕКУЩАЯ
      оценка) − 1`. Оценка текущая, без снимка (решение Ивана): в активном проекте держим
      около нуля (цены свежие), перед новым контрактом — замер «насколько подорожало».
      Позиции без оценки в сравнение не входят.
    Позиции остатка без оценки — в `rest_unestimated` (сумма неполна, не молчим нулём).
    """
    if lines is None:
        lines = list(procurement.lines.select_related('item'))
    ordered_qty, ordered = {}, ZERO
    invoice, invoice_est = ZERO, ZERO
    for pl in models.PurchaseLine.objects.filter(
            purchase__procurement=procurement, purchase__locked=True).select_related('item'):
        ordered_qty[pl.item_id] = ordered_qty.get(pl.item_id, ZERO) + pl.qty
        price = pl.price or ZERO
        ordered += price
        if pl.item.estimated_cost is not None and pl.price is not None:
            invoice += price
            invoice_est += pl.qty * pl.item.estimated_cost
    rest, rest_unestimated, open_left = ZERO, [], False
    for line in lines:
        left = max(ZERO, line.qty - ordered_qty.get(line.item_id, ZERO))
        if not left:
            continue
        open_left = True
        if line.item.estimated_cost is None:
            rest_unestimated.append(line.item.code)
        else:
            rest += left * line.item.estimated_cost
    return {
        'ordered': ordered, 'rest': rest, 'total': ordered + rest,
        'is_fact': not open_left,
        'rest_unestimated': rest_unestimated,
        'invoice_gap': _ratio(invoice, invoice_est),
    }


# Строка взята с перебором больше чем в ПОЛТОРА раза от нужды — красный член. Порог
# задан в деньгах («переплата больше половины потребности»), но цена в неравенстве
# сокращается: `(qty − need)·цена > ½·need·цена` ⇔ `qty > 1.5·need`. Поэтому правило
# работает и там, где `estimated_cost` нет вовсе (красить, впрочем, будет нечего).
OVERPAY_LIMIT = Decimal('1.5')
# Шкала округления порога (2026-08-07): до 5 → до 10 → до 50 → до 100, ступень выбирается
# по величине самого порога. Округляем ПОРОГ, а не потребность: иначе «нужно 13, беру
# круглые 20» ловилось красным (порог 19.5), хотя это ровно то решение, к которому
# приходят руками — некратные числа не заказывают.
ROUND_STEPS = ((Decimal(50), Decimal(5)), (Decimal(100), Decimal(10)),
               (Decimal(500), Decimal(50)))
ROUND_STEP_MAX = Decimal(100)
# «Дорогая» строка — по Парето (решение Ивана 2026-10-20, вместо «верхней четверти»
# 2026-08-07): самые дорогие строки, которые ВМЕСТЕ дают первые 80% стоимости набора.
# Строка, на которой накопленная сумма переходит порог, — тоже дорогая (иначе в наборе из
# одной большой строки и мелочи дорогих не было бы вовсе).
PARETO_SHARE = Decimal('0.8')


def line_cost(item, qty):
    """Стоимость строки: `qty × estimated_cost`. Без оценки — `None`, а не ноль.

    Тот же приём, что у `lines_estimate`/`intent_money`: неизвестную цену нельзя
    показывать нулём — вью рисует прочерк, и строка не участвует в ранжировании.
    """
    return None if item.estimated_cost is None else qty * item.estimated_cost


def purchase_unit_price(line):
    """Цена штуки строки заказа — ВЫВОДИТСЯ делением цены строки по счёту на количество
    (волна 24: источник правды — рубли и копейки за строку целиком). Нет цены или
    количество ноль — `None`."""
    if line.price is None or not line.qty:
        return None
    return line.price / line.qty


def purchase_money(lines):
    """Деньги заказа (волна 24): сухой факт по счёту — `estimate` («Заказ») = Σ цен строк,
    сходится со счётом до копейки; строки без цены не входят, их коды — в `unestimated`.

    Потребности и переплаты здесь нет (решение Ивана): заказ — онлайн-зеркало оффлайн-
    счёта, а сравнение с нуждой — язык оценки, он живёт в закупке (`intent_money`).
    """
    estimate = ZERO
    unpriced = []
    for line in lines:
        if line.price is None:
            unpriced.append(line.item.code)
        else:
            estimate += line.price
    return {'estimate': estimate, 'unestimated': unpriced}


def line_flow_money(price, qty, received):
    """Деньги строки заказа по ходу поставки (волна 26): `(получено, ждём)` — доли цены
    строки по счёту. «Получено» = доля поступившего (сверх заказанного не бывает больше
    цены), «ждём» = остаток цены, поэтому получено + ждём = цена строки до копейки.
    Нет цены или кол-ва — `(0, 0)`: деньги строки ещё неизвестны.

    Единственное правило «ждём» в движке: им же считаются обещанные деньги «Заказа» в
    потребности проекта (`ProjectSupply.ordered_cost`) и «ждём от него» контрагента."""
    if price is None or not qty:
        return ZERO, ZERO
    got = _share(price, qty, min(received, qty))
    return got, price - got


def overpay_threshold(need):
    """Сколько можно взять при нужде `need`, чтобы это ещё не считалось перебором:
    **полторы нормы, округлённые вверх до круглого числа**.

    Одна фраза — и её видно в подсказке строки («без перебора можно до 20»). Понятность
    правила тут важнее точности (решение Ивана 2026-08-07): закупщик держит его в голове
    и заранее знает, загорится строка или нет.

    Округление вверх убирает жёсткость на малых количествах, где процент режет по живому:
    нужно 13 → полторы нормы 19.5 → **20**, то есть ровно то круглое число, которым и
    закупают. На больших партиях ступень грубее (5 → 10 → 50 → 100), и процент снова
    берёт своё: 100 → 150, 333 → 500.

    `need = 0` даёт порог 0: позиции нет в составе проекта, любое количество — перебор.
    """
    raw = need * OVERPAY_LIMIT
    step = next((s for limit, s in ROUND_STEPS if raw < limit), ROUND_STEP_MAX)
    return (raw / step).to_integral_value(rounding=ROUND_CEILING) * step


def is_overpaid(qty, need):
    """Строка взята сверх порога (красный). Пустая ячейка (`qty = 0`) не горит."""
    return qty > overpay_threshold(need) and qty > ZERO


def mark_pareto(rows, key='cost'):
    """Проставить `cost_status = 'costly'` строкам набора по Парето (2026-10-20): по
    убыванию стоимости, пока накопленное ДО строки меньше `PARETO_SHARE` суммы набора.
    Одно правило «дорогая строка» на весь продукт — строки закупки и состав изделия.
    Строки без цены и нулевые в ранжировании не участвуют («самый дорогой ноль» не
    бывает). Ждёт в строках деньги под ключом `key` (может быть `None`; у заказа — цена
    строки по счёту, у «Потребности» — план позиции), правит строки на месте."""
    ranked = sorted((r for r in rows if r[key] is not None and r[key] > ZERO),
                    key=lambda r: r[key], reverse=True)
    bar = PARETO_SHARE * sum((r[key] for r in ranked), ZERO)
    acc = ZERO
    for row in ranked:
        row['cost_status'] = 'costly' if acc < bar else None
        acc += row[key]
    for row in rows:
        row.setdefault('cost_status', None)
    return rows


def mark_costs(rows):
    """Проставить `cost_status` строкам: `overpaid` (красный) > `costly` (оранжевый).

    Смысл считает движок, знак выбирает вью ([[engine-view-seam]]): здесь — «эта строка
    дорогая» и «эта взята с перебором», а не «оранжевая»/«красная».

    «Дорогая» — по Парето внутри НАБОРА (`mark_pareto`; ранжирование внутри одного
    списка, поэтому считается тут, а не построчно): в разных документах дорого разное.

    Красное сильнее оранжевого (worst-of, как везде в продукте): перебор — повод
    вмешаться, дороговизна — повод посмотреть.

    Ждёт в строках `cost` (может быть `None`), `qty` и `need`; правит их на месте.
    """
    mark_pareto(rows)
    for row in rows:
        # Порог едет в строку: им вью объясняет цвет («без перебора можно до 20»).
        # Правило, которое видно, закупщик держит в голове — а держа, не спорит с ним.
        row['overpay_at'] = overpay_threshold(row['need'])
        if row['cost'] is not None and row['qty'] > row['overpay_at'] and row['qty'] > ZERO:
            row['cost_status'] = 'overpaid'
    return rows


def purchase_form(purchase):
    """Проекция формы заказа: шапка + строки (заказано/поступило/остаток) + приходы.

    Закрытость строки красится тем же словарём ✓/●/▲, что дефицит/формы:
    получено полностью → ✓ (available), частично → ● (on_order), ничего → ▲ (to_order).
    Статусы `partial`/`received` не храним — это вычисляемая закрытость. Ничего не
    хранит (чистая проекция).

    Ф6: строка несёт ещё и **чем** она закрыта (`receipts`) — обратная связь потока
    «Заказ → УПД». Список приходов заказа целиком остаётся отдельным табом.

    Волна 24 (приёмка Ивана): строка несёт **цену всей строки по счёту** (`price`) —
    рубли и копейки, отданные за строку; сумма заказа считается по ним, оценки изделия в
    заказе нет. Баланс проекта и стоимость-по-оценке из строк заказа сняты: «Заказано ·
    Поступило · Остаток» отвечает на вопрос заказа, «сколько надо» — дело закупки.
    """
    editable = not purchase.locked
    closure = _purchase_closure(purchase)
    lines = list(purchase.lines.select_related('item', 'item__category').order_by('id'))
    rows = []
    statuses = []
    total_ordered = ZERO
    total_received = ZERO
    received_money = ZERO
    awaiting_money = ZERO
    for line in lines:
        closed_by = closure.get(line.item_id, [])
        received = sum((r['qty'] for r in closed_by), ZERO)
        remaining = max(ZERO, line.qty - received)
        total_ordered += line.qty
        total_received += received
        got, wait = line_flow_money(line.price, line.qty, received)
        received_money += got
        awaiting_money += wait
        if line.qty > 0 and received >= line.qty:
            st = 'available'      # ✓ получено полностью
        elif received > 0:
            st = 'on_order'       # ● частично получено
        else:
            st = 'to_order'       # ▲ ждём поставки
        statuses.append(st)
        rows.append({
            'id': line.id, 'item_id': line.item_id, 'item_code': line.item.code,
            'item_description': line.item.description, 'uom': line.item.uom,
            'item_category': category_code(line.item),   # фильтр колонки
            # Оси изделия — под глиф строки (§7a): форма = изделие/компонент,
            # цвет = закрытость строки. Так же устроена форма закупки-плана (Ф3a).
            'item_native': line.item.native, 'item_synced': line.item.synced,
            'item_locked': line.item.locked,
            'qty': line.qty, 'received': received, 'remaining': remaining,
            'status': st,
            # Цена всей строки по счёту (волна 24) и выведенная из неё цена штуки.
            'price': line.price, 'unit_price': purchase_unit_price(line),
            'receipts': closed_by,     # Ф6: какими накладными строка закрыта
        })
    receipts = [
        # Ф6: `code` — первичная идентичность накладной (у рождённой из заказа
        # `number` пуст до заполнения по бумаге, и ссылка на него рисовала пустоту).
        {'id': r.id, 'code': r.code, 'number': r.number, 'date': r.date,
         'locked': r.locked,
         **_contractor_view(r.contractor),
         'lines': r.lots.count()}
        for r in purchase.receipts.select_related('contractor').order_by('id')
    ]
    # 2026-10-20: Парето по цене строки — что в заказе «тяжёлое», а что важные мелочи.
    mark_pareto(rows, key='price')
    money = purchase_money(lines)        # волна 24: сумма по счёту — без нужды и оценки
    return {
        'id': purchase.id, **_author(purchase), 'locked': purchase.locked,
        'project_id': purchase.project_id, 'project_code': purchase.project.code,
        'project_name': purchase.project.description,
        # Волна 24: закупка обязательна — заказ рождается из неё; её код — подпись ссылки.
        'procurement_id': purchase.procurement_id,   # якорь #A (Ф2k)
        'procurement_code': purchase.procurement.code,
        **_contractor_view(purchase.contractor),      # Ф17: у кого купили
        'code': purchase.code, 'description': purchase.description,
        'date': purchase.date,
        'editable': editable,                       # строки правятся только пока не зафиксировано
        'worst_status': _worst_of(statuses),      # worst-of закрытости строк
        'total_ordered': total_ordered, 'total_received': total_received,
        **money,          # estimate (сумма по счёту) / unestimated — блок «Деньги»
        # Волна 26: ход поставки в деньгах по счёту; получено + ждём = сумма заказа.
        'received_money': received_money, 'awaiting_money': awaiting_money,
        'rows': rows, 'receipts': receipts,
    }


PURCHASE_LOCKED = 'Строки правятся только в черновике заказа — снимите замок (unlock).'


PURCHASE_QTY_NEGATIVE = 'Количество заказа не может быть отрицательным.'


def add_purchase_line(purchase, item, qty, price=None):
    """Добавить строку заказа (только в черновике). `(purchase, item)` уникальна.

    **Ноль разрешён** (2026-08-19, решение Ивана) — на тех же основаниях, что и в
    закупке: строка рождается кликом из витрины «Потребность» именно с нулём («позицию
    беру, количество ещё думаю»), а количество набирают следом в «Строках», глядя на
    баланс проекта по этому компоненту. Черновик заказа — рабочее состояние, а не
    обязательство: обязательством он становится на фиксации. Отрицательное невозможно.
    В бланк поставщику нулевые строки не идут (`purchase_xlsx`).
    """
    _require_unlocked(purchase, PURCHASE_LOCKED)
    if qty is None or qty < 0:
        raise ValidationError(PURCHASE_QTY_NEGATIVE)
    # Волна 24: строка заказа ⊆ план — иначе распределение закупки её не увидит, и
    # «закупка — источник правды» тихо перестанет быть правдой.
    if not purchase.procurement.lines.filter(item=item).exists():
        raise ValidationError(
            f'Изделия {item.code} нет в закупке — сперва добавьте его в закупку.')
    if purchase.lines.filter(item=item).exists():
        raise ValidationError(
            f'Изделие {item.code} уже в заказе — правьте существующую строку.')
    price = _check_price(price)
    return models.PurchaseLine.objects.create(purchase=purchase, item=item, qty=qty,
                                              price=price)


PURCHASE_PRICE_NEGATIVE = 'Цена не может быть отрицательной.'


def _check_price(price):
    """Цена строки — неотрицательные рубли и копейки; лишние знаки округляем до копейки
    (поле денег — два знака, и сумма заказа обязана сходиться со счётом)."""
    if price is None:
        return None
    if price < 0:
        raise ValidationError(PURCHASE_PRICE_NEGATIVE)
    return price.quantize(KOPECK, rounding=ROUND_HALF_UP)


def update_purchase_line(line, qty=_UNSET, price=_UNSET):
    """Автосейв строки заказа — количества и/или цены строки по счёту (только в черновике).

    Ноль количества допустим на тех же основаниях, что при рождении строки: вернуть
    позицию в состояние «беру, но сколько — ещё думаю» так же законно, как в него прийти.
    Убрать позицию совсем — корзиной строки, а не нулём. Цена — часовой (волна 24):
    `None` стирает её обратно в «ещё не знаем» (заказ тогда не зафиксировать).
    """
    _require_unlocked(line.purchase, PURCHASE_LOCKED)
    fields = []
    if qty is not _UNSET:
        if qty is None or qty < 0:
            raise ValidationError(PURCHASE_QTY_NEGATIVE)
        line.qty = qty
        fields.append('qty')
    if price is not _UNSET:
        line.price = _check_price(price)
        fields.append('price')
    if fields:
        line.save(update_fields=fields)
    return line


def remove_purchase_line(line):
    """Удалить строку заказа (только в черновике)."""
    _require_unlocked(line.purchase, PURCHASE_LOCKED)
    line.delete()


def lock_purchase(purchase):
    """Поставить замок заказа — теперь считается в «заказано»,
    строки становятся read-only. Снятие (`unpost`) ничего не разрушает.

    Волна 19 (Ф1): бывший `send_purchase`. Отмены больше нет — отмена = удаление
    (развилка Р1), поэтому проверять «отменённый нельзя отправить» стало нечего.

    Ф17: контрагент обязателен к ФИКСАЦИИ (CHECK `purchase_locked_has_contractor`).
    Прикладной гейт дублирует инвариант БД, чтобы пользователь получил внятный отказ,
    а не `IntegrityError 3819` (урок Ф12e: CHECK без гейта — это 500 в лицо).
    """
    if not purchase.lines.exists():
        raise ValidationError('Нельзя утвердить пустой заказ — добавьте строку.')
    if purchase.contractor_id is None:
        raise ValidationError(
            'Перед фиксацией выберите контрагента — у кого заказано.')
    # Волна 26: дата обязательна к фиксации (CHECK `purchase_locked_has_date`) — по ней
    # ищется «последняя цена по счёту» изделия; у счёта/договора она есть всегда.
    if purchase.date is None:
        raise ValidationError('Перед фиксацией укажите дату заказа — дату счёта или договора.')
    # Волна 24: обязательство без цены не бывает — счёт её называет (0 законен).
    unpriced = list(purchase.lines.filter(price__isnull=True)
                    .order_by('item__code').values_list('item__code', flat=True))
    if unpriced:
        more = f' и ещё {len(unpriced) - 3}' if len(unpriced) > 3 else ''
        raise ValidationError(
            'Перед фиксацией укажите цену по счёту у всех строк — нет у '
            + ', '.join(unpriced[:3]) + more + '.')
    purchase.locked = True
    purchase.save(update_fields=['locked'])
    return purchase


def unlock_purchase(purchase):
    """Снять замок заказа. Purchase лотов не рождает — снятие
    обязательства ничего не разрушает (связанные приходы остаются, заказ просто
    выходит из счёта «заказано»), guard по потомкам не нужен."""
    purchase.locked = False
    purchase.save(update_fields=['locked'])
    return purchase


def delete_purchase(purchase):
    """Удалить заказ (WAVE14 Ф2). Мягкий замок как у ордеров: утверждённый сперва
    вернуть в черновик (снять замок); привязанный приход (`Receipt.purchase`,
    SET_NULL) держит — иначе удаление молча обнулило бы ссылку у поставок. Строки
    заказа (`PurchaseLine`) — каскад."""
    if purchase.locked:
        raise ValidationError(
            'Заказ утверждён — сперва верните его в черновик (снимите замок), затем удаляйте.')
    if purchase.receipts.exists():
        raise ValidationError('К заказу привязаны поставки (приход) — удаление заблокировано.')
    for att in purchase.attachments.all():         # физические файлы (каскад их сиротит)
        delete_attachment(att)
    try:
        purchase.delete()                          # каскад: строки заказа
    except ProtectedError:
        raise ValidationError('Заказ связан с другими записями — удаление заблокировано.')


# --------------------------------------------------------------------------- #
#  Форма передачи / Transfer (волна 5): отдаём партию заказчику (−ISSUE)
# --------------------------------------------------------------------------- #
def project_available_lots(project):
    """Лоты проекта с живым остатком > 0 — кандидаты на отгрузку заказчику.

    Пикер строки передачи: любой лот проекта, где ещё что-то лежит (обычно
    готовое железо — приборы из комплектации, но модель не ограничивает).
    """
    result = []
    lots = list(models.Lot.objects.filter(project=project)
                .select_related('item', 'origin').order_by('item__code', 'id'))
    live_by_lot = lots_live_qty(lots)
    for lot in lots:
        live = live_by_lot[lot.id]
        if live > 0:
            result.append({
                'lot_id': lot.id, 'item_id': lot.item_id,
                'item_code': lot.item.code, 'item_description': lot.item.description,
                'uom': lot.item.uom, 'live_qty': live, 'origin': lot.origin_kind,
                'part_number': lot.part_number,
                'lot_name': lot.lot_name,
            })
    return result


def _lot_label(lot):
    """Человекочитаемая метка лота для накладной/строки (название / PN / артикул)."""
    tail = lot.lot_name or lot.part_number or lot.item.code
    return f'#{lot.id} {tail}'


def _author(doc):
    """Автор документа для проекции формы (Ф2j): id + человеческое имя (для
    пикера авторства в шапке формы). `user` NOT NULL на всех ордерах/закупках."""
    u = doc.user
    if u is None:                        # страховка на легаси-строки
        return {'user_id': None, 'user_name': ''}
    return {'user_id': u.id, 'user_name': u.get_full_name() or u.get_username()}


def transfer_form(transfer):
    """Проекция формы передачи: шапка накладной + строки-лоты + итог.

    Каждая строка отдаёт партию заказчику (`−ISSUE`); показываем живой остаток
    источника (просел ли под передачу, не ушёл ли в минус). Ничего не хранит.
    """
    lines = []
    total_qty = ZERO
    doc_lines = list(transfer.lines.select_related('lot__item', 'lot__origin').order_by('id'))
    live_by_lot = lots_live_qty([line.lot for line in doc_lines])
    for line in doc_lines:
        lot = line.lot
        mag = -line.qty                       # знаковая строка (− расход) → магнитуда
        total_qty += mag
        lines.append({
            'id': line.id, 'lot_id': lot.id,
            'lot_label': _lot_label(lot),
            'origin': lot.origin_kind,        # глиф партии (§7a): форма = откуда родилась
            'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'qty': mag, 'display_name': line.display_name,
            'lot_live_qty': live_by_lot[lot.id],   # остаток источника после отгрузки
            'lot_name': lot.lot_name,
        })
    return {
        'id': transfer.id, **_author(transfer), 'number': transfer.number, 'date': transfer.date,
        'code': transfer.code, 'description': transfer.description,
        **_contractor_view(transfer.contractor),
        'project_id': transfer.project_id, 'project_code': transfer.project.code,
        'project_name': transfer.project.description, 'locked': transfer.locked,
        'total_qty': total_qty, 'lines': lines,
        'total_cost': outflow_money(doc_lines),    # волна 26: ★ блока «Деньги»
    }


def _movement_row(document, lot, qty, event):
    """Одна строка ленты движений: ордер + партия + знаковое кол-во."""
    return {
        'event': event,                 # 'born' — партия родилась | 'move' — движение
        'kind': document.kind, 'document_id': document.id,
        'code': document.code, 'number': document.number, 'date': document.date,
        'locked': document.locked, 'project_code': document.project.code,
        'lot_id': lot.id, 'lot_name': lot.lot_name, 'qty': qty,
    }


def item_movements(item):
    """Все ордера, коснувшиеся изделия, одной лентой — для его экрана (волна 19, Ф12a).

    Заменила узкую `item_shipments` (только передачи): изделие живёт не одними
    отгрузками, и «куда делось» читается лишь по всей ленте. Два источника, ровно
    как в модели:

    * **рождение партии** (born-direct) — `Lot.origin` (поставка / комплектация /
      инвентаризация / требование), знак `+`;
    * **движение существующей партии** — `StockLine` (пайка в комплектацию, передача,
      списание, требование, перемещение), знак уже в `qty` (− расход).

    `StockMovement` намеренно НЕ читаем: это проекция-остаток, её `source_type`/
    `source_id` пришлось бы резолвить обратно в документы. Порядок — свежие сверху;
    дата у ордера nullable (черновик комплектации), такие уходят в конец.
    """
    rows = [
        _movement_row(lot.origin, lot, lot.qty, 'born')
        for lot in (models.Lot.objects.filter(item=item)
                    .select_related('origin', 'origin__project'))
    ]
    rows += [
        _movement_row(line.document, line.lot, line.qty, 'move')
        for line in (models.StockLine.objects.filter(lot__item=item)
                     .select_related('document', 'document__project', 'lot'))
    ]
    rows.sort(key=lambda r: (r['date'] is not None, r['date'], r['document_id']),
              reverse=True)
    return rows


def create_transfer(project, user, number='', date=None, contractor=None):
    """Создать передачу (накладную) проекта. Строки добавляются в форме.

    `contractor` — контрагент-заказчик (опционален: получатель может быть проставлен
    позже в форме). Ф12e: номер тоже опционален — он обязателен к ФИКСАЦИИ
    (`REQUIRED_HEADER_BY_KIND`), а не к рождению."""
    return _born_order(models.Transfer, project, user, number, date,
                       contractor=contractor)


def add_transfer_line(transfer, lot, qty, display_name=''):
    """Отгрузить партию заказчику: строка передачи (`−ISSUE` на лоте).

    Лот — того же проекта (передаём своё, чужое — через требование). Кол-во не
    клампим по остатку: переотдать можно, лот уйдёт в минус (недостача информативна,
    в духе мутабельной ДНК).
    """
    _require_unlocked(transfer)
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
    _require_unlocked(line.document)
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
    _require_unlocked(line.document)
    lot = line.lot
    line.delete()
    rebuild_movements(lot)


def lock_transfer(transfer):
    """Поставить замок «отгружено»: накладная read-only, партии уходят со склада
    (`−ISSUE` материализуется, Ф15). Сюда позже ляжет подписанная накладная
    (Attachment). Ф15 сняла рукописную копию `lock_document` — общая дорога."""
    return lock_document(transfer, transfer.lines,
                         'Нельзя отгрузить пустую накладную — добавьте строку.')


def unlock_transfer(transfer):
    """Снять замок — снова разрешить правку (`−ISSUE` отпускается, партии
    возвращаются на склад, Ф15). Строки остаются, guard по потомкам не нужен."""
    return unlock_document(transfer)


# --------------------------------------------------------------------------- #
#  Закрытие проекта (волна 6): списание / требование + панель + мягкий замок
# --------------------------------------------------------------------------- #
def default_document_project():
    """Проект-якорь для ордера, рождённого по клику (Ф12e).

    `StockDocument.project` — NOT NULL (якорь Ф2k), фолбэк нужен обязательно.
    Берём белый «Собственный склад»: он всегда существует (синглтон сида), и это
    не ложные данные — документ и правда пока ничей, а не приписан чужому НИР.
    Меняется в шапке, пока ордер пуст (`_set_project`)."""
    return _internal_project(models.Project.Kind.INTERNAL_STOCK)


def _internal_project(kind):
    """Найти-или-создать внутренний проект-склад (белый/серый) — синглтон.

    Целевая «куча» для постановки на баланс (белый «Собственный склад») —
    `INTERNAL_KINDS` синглтоны (см. `Project.clean`), сид их заводит; здесь мягко
    добираем, чтобы движок был робастен и в голой БД/тестах.
    """
    proj = models.Project.objects.filter(kind=kind).first()
    if proj is not None:
        return proj
    code, description = {
        models.Project.Kind.INTERNAL_STOCK: ('WHITE', 'Собственный склад'),
        models.Project.Kind.INTERNAL_WRITEOFF: ('GREY', 'Свободные неучтённые'),
    }[kind]
    return models.Project.objects.create(
        code=code, description=description, kind=kind)


def _auto_number(prefix, project):
    """Авто-№ документа для мостов панели (акт списания/требование одним кликом)."""
    return f'{prefix}-{project.code}-{timezone.localdate():%Y%m%d}'


def all_available_lots():
    """Лоты всех проектов с живым остатком > 0 — пикер источника требования.

    Требование тянет из любого проекта (постановка своего на баланс, заём у
    соседнего активного) — поэтому пикер сквозной, с кодом проекта-источника.
    """
    result = []
    lots = list(models.Lot.objects.select_related('item', 'project', 'origin')
                .order_by('project__code', 'item__code', 'id'))
    live_by_lot = lots_live_qty(lots)
    for lot in lots:
        live = live_by_lot[lot.id]
        if live > 0:
            result.append({
                'lot_id': lot.id, 'item_id': lot.item_id,
                'item_code': lot.item.code, 'item_description': lot.item.description,
                'uom': lot.item.uom, 'live_qty': live, 'origin': lot.origin_kind,
                'project_id': lot.project_id, 'project_code': lot.project.code,
                'part_number': lot.part_number,
                'lot_name': lot.lot_name,
            })
    return result


# ── Списание / Writeoff (серый путь: чистый −ISSUE, лот покидает учёт) ──
def writeoff_form(writeoff):
    """Проекция формы списания: шапка акта + строки-лоты (`−ISSUE`) + итог.

    Списание — чистое выбытие из проекта (born-лота нет, `Writeoff` не origin);
    «в серый склад» — конвенция учёта, ре-материализация серых остатков — актом
    `Inventory` (следующая волна). Живой остаток источника показываем — просел ли.
    """
    lines = []
    total_qty = ZERO
    doc_lines = list(writeoff.lines.select_related('lot__item', 'lot__origin').order_by('id'))
    live_by_lot = lots_live_qty([line.lot for line in doc_lines])
    for line in doc_lines:
        lot = line.lot
        mag = -line.qty                       # знаковая строка (− расход) → магнитуда
        total_qty += mag
        lines.append({
            'id': line.id, 'lot_id': lot.id, 'lot_label': _lot_label(lot),
            'origin': lot.origin_kind,        # глиф партии (§7a): форма = откуда родилась
            'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'qty': mag, 'lot_live_qty': live_by_lot[lot.id],
            'lot_name': lot.lot_name,
        })
    return {
        'id': writeoff.id, **_author(writeoff), 'number': writeoff.number, 'date': writeoff.date,
        'code': writeoff.code, 'description': writeoff.description,
        'reason': writeoff.reason,
        'project_id': writeoff.project_id, 'project_code': writeoff.project.code,
        'project_name': writeoff.project.description, 'locked': writeoff.locked,
        'total_qty': total_qty, 'lines': lines,
        'total_cost': outflow_money(doc_lines),    # волна 26: ★ блока «Деньги»
    }


def create_writeoff(project, user, number='', date=None, reason=''):
    """Создать акт списания проекта. Строки добавляются в форме."""
    return _born_order(models.Writeoff, project, user, number, date,
                       reason=(reason or '').strip())


def add_writeoff_line(writeoff, lot, qty, location=None):
    """Списать партию из проекта: строка списания (`−ISSUE` на лоте).

    Списываем только своё (`lot.project == writeoff.project`). Кол-во не клампим по
    остатку (как приход/передача): пересписать можно, лот уйдёт в минус — недостача
    информативнее нуля (мутабельная ДНК).
    """
    _require_unlocked(writeoff)
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
    _require_unlocked(line.document)
    if qty is None or qty <= 0:
        raise ValidationError('Количество списания должно быть положительным.')
    line.qty = -qty                      # знаковая строка (− расход)
    line.save(update_fields=['qty'])
    rebuild_movements(line.lot)
    return line


def remove_writeoff_line(line):
    """Убрать строку списания (коррекция) — источник возвращает остаток."""
    _require_unlocked(line.document)
    lot = line.lot
    line.delete()
    rebuild_movements(lot)


def lock_writeoff(writeoff):
    """Провести списание (замок «списано», форма read-only)."""
    return lock_document(writeoff, writeoff.lines,
                         'Нельзя провести пустой акт списания — добавьте строку.')


def unlock_writeoff(writeoff):
    """Снять замок списания — снова разрешить правку."""
    return unlock_document(writeoff)


# ── Требование / Requisition (белый путь: −ISSUE источника + рождение потомка) ──
def _requisition_born_lot(requisition, source_lot):
    """Порождённый требованием лот-потомок источника (пара строки).

    Один источник = одна строка (guard в `add_requisition_line`), поэтому пара
    `(requisition, predecessor)` однозначна.
    """
    return requisition.lots.filter(predecessor=source_lot,
                                   item=source_lot.item).first()


def requisition_form(requisition):
    """Проекция формы требования: шапка (проект-получатель) + строки + итог.

    Каждая строка тянет из лота-источника (`−ISSUE`) и рождает лот-потомок в
    проекте-получателе (`+RECEIPT`, наследует item/цену/провенанс через
    `predecessor`). Показываем живой остаток источника (просел ли).
    """
    lines = []
    total_qty = ZERO
    doc_lines = list(requisition.lines
                     .select_related('lot__item', 'lot__project', 'lot__origin')
                     .order_by('id'))
    live_by_lot = lots_live_qty([line.lot for line in doc_lines])
    for line in doc_lines:
        src = line.lot                        # StockLine.lot = лот-источник расхода
        mag = -line.qty                       # знаковая строка (− расход) → магнитуда
        total_qty += mag
        born = _requisition_born_lot(requisition, src)
        lines.append({
            'id': line.id, 'source_lot_id': src.id, 'lot_label': _lot_label(src),
            'origin': src.origin_kind,        # глиф партии (§7a): форма = откуда родилась
            'source_project_code': src.project.code,
            'item_id': src.item_id, 'item_code': src.item.code,
            'item_description': src.item.description, 'uom': src.item.uom,
            'qty': mag, 'source_live_qty': live_by_lot[src.id],
            'born_lot_id': born.id if born else None,
            'lot_name': src.lot_name,
        })
    return {
        'id': requisition.id, **_author(requisition), 'number': requisition.number, 'date': requisition.date,
        'code': requisition.code, 'description': requisition.description,
        'project_id': requisition.project_id, 'project_code': requisition.project.code,
        'project_name': requisition.project.description, 'locked': requisition.locked,
        'total_qty': total_qty, 'lines': lines,
        'total_cost': outflow_money(doc_lines),    # волна 26: ★ блока «Деньги»
    }


def create_requisition(project, user, number='', date=None):
    """Создать требование в проект-получатель (`project` = куда кладём потомков)."""
    return _born_order(models.Requisition, project, user, number, date)


def add_requisition_line(requisition, source_lot, qty, location=None):
    """Отпочкование: `−ISSUE` от источника + рождение лота-потомка у получателя.

    Источник — из любого проекта (постановка своего на баланс → белый, заём у
    соседнего активного B→A). Потомок наследует item/цену/название/PN источника,
    `predecessor` → источник (генеалогия/провенанс для kitting из остатков). Один
    источник = одна строка (пара строки↔потомок однозначна). Кол-во не клампим.
    """
    _require_unlocked(requisition)
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
        predecessor=source_lot, qty=qty, cost=ZERO,
        lot_name=source_lot.lot_name, part_number=source_lot.part_number)
    _sync_born_cost(requisition)    # волна 26: потомок стоит долю, ушедшую из источника
    born.refresh_from_db(fields=['cost'])
    rebuild_movements(source_lot)   # −ISSUE у источника
    rebuild_movements(born)         # +RECEIPT у потомка
    return line


def update_requisition_line(line, qty):
    """Автосейв количества: правит и строку-источник (`−ISSUE`), и потомок (`+RECEIPT`).
    Только черновик (замок)."""
    _require_unlocked(line.document)
    if qty is None or qty <= 0:
        raise ValidationError('Количество требования должно быть положительным.')
    line.qty = -qty                      # знаковая строка (− расход) у источника
    line.save(update_fields=['qty'])
    born = _requisition_born_lot(line.document, line.lot)
    if born is not None:
        born.qty = qty                   # рождённый лот-потомок — положительное кол-во
        born.save(update_fields=['qty'])
        _sync_born_cost(line.document)   # волна 26: доля источника под новое кол-во
        born.refresh_from_db(fields=['cost'])
        rebuild_movements(born)
    rebuild_movements(line.lot)
    return line


def remove_requisition_line(line):
    """Убрать строку требования: снять потомок + вернуть остаток источнику.

    Guard: потомок не должен быть потреблён ниже (спаян/передан/списан из белого).
    """
    _require_unlocked(line.document)
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


def lock_requisition(requisition):
    """Провести требование (замок, форма read-only)."""
    return lock_document(requisition, requisition.lines,
                         'Нельзя провести пустое требование — добавьте строку.')


def unlock_requisition(requisition):
    """Снять замок требования — снова разрешить правку."""
    return unlock_document(requisition)


# ── Перемещение / Relocation (мультисклад: лот между локациями внутри проекта) ──
def _relocation_pair(relocation, lot):
    """Пара знаковых строк одного хода: (источник `−q`, приёмник `+q`). Один лот =
    один ход в перемещении (guard в `add_relocation_line`), поэтому пара однозначна."""
    lines = list(relocation.lines.filter(lot=lot).select_related('location'))
    src = next((l for l in lines if l.qty < 0), None)
    dst = next((l for l in lines if l.qty > 0), None)
    return src, dst


def relocation_form(relocation):
    """Проекция формы перемещения: шапка + ходы (лот, откуда→куда, кол-во) + итог.

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
            'origin': lot.origin_kind,        # глиф партии (§7a): форма = откуда родилась
            'item_id': lot.item_id, 'item_code': lot.item.code,
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
        'code': relocation.code, 'description': relocation.description,
        'project_id': relocation.project_id, 'project_code': relocation.project.code,
        'project_name': relocation.project.description, 'locked': relocation.locked,
        'total_qty': total_qty, 'moves': moves,
        'total_cost': outflow_money(relocation.lines.select_related('lot')),   # волна 26
    }


def create_relocation(project, user, number='', date=None):
    """Создать перемещение внутри проекта (`project` — где двигаем лоты по местам)."""
    return _born_order(models.Relocation, project, user, number, date)


def add_relocation_line(relocation, lot, qty, from_location, to_location):
    """Ход перемещения: пара знаковых строк (`−q` на источнике, `+q` на приёмнике).

    Двигаем только свой лот (`lot.project == relocation.project`) между двумя РАЗНЫМИ
    местами хранения. Один лот = один ход (правьте существующий). Кол-во не клампим по
    остатку источника (как передача/списание): пересместить можно, источник уйдёт в
    минус — недостача информативнее нуля (мутабельная ДНК). Тотал лота сохранён
    (`−q+q=0`) — двигаем распределение, не остаток.
    """
    _require_unlocked(relocation)
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
    _require_unlocked(relocation)
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
    _require_unlocked(relocation)
    relocation.lines.filter(lot=lot).delete()
    rebuild_movements(lot)


def lock_relocation(relocation):
    """Провести перемещение (замок, форма read-only)."""
    return lock_document(relocation, relocation.lines,
                         'Нельзя провести пустое перемещение — добавьте ход.')


def unlock_relocation(relocation):
    """Снять замок перемещения — снова разрешить правку."""
    return unlock_document(relocation)


def relocation_source_lots(project):
    """Лоты проекта с живым остатком > 0 — кандидаты на перемещение, с разбивкой по
    местам хранения (`lot_locations`): пикер видит, где лот лежит и сколько."""
    result = []
    lots = list(models.Lot.objects.filter(project=project)
                .select_related('item', 'origin').order_by('item__code', 'id'))
    live_by_lot = lots_live_qty(lots)
    for lot in lots:
        live = live_by_lot[lot.id]
        if live > 0:
            result.append({
                'lot_id': lot.id, 'item_id': lot.item_id,
                'item_code': lot.item.code, 'item_description': lot.item.description,
                'uom': lot.item.uom, 'live_qty': live,
                'part_number': lot.part_number,
                'lot_name': lot.lot_name,
                'by_location': lot_locations(lot),
            })
    return result


# ── Закупочный контур проекта: заказы и поставки одной проекцией ──
def project_supply(project):
    """Ленты снабжения проекта: его заказы и его поставки (табы формы проекта).

    Обе ленты — теми же строками, что отдаёт форма контрагента (`_purchase_rows` /
    `_receipt_rows` берут queryset именно для этого): разрез другой («что приехало В
    ЭТОТ проект» вместо «что привёз ЭТОТ контрагент»), а строка одна, и второго словаря
    под тот же смысл заводить незачем.

    Одной проекцией, а не двумя эндпойнтами: заказ и поставка — соседние уровни одного
    контура, форма показывает их рядом и спрашивает всегда вместе.

    Проект-склад (внутренний) отвечает тем же — пустыми лентами: закупочного контура у
    него обычно нет, но запрет на поставку прямо в склад из модели не следует.
    """
    return {
        'procurements': _procurement_rows(project.procurements),     # волна 24
        'purchases': _purchase_rows(
            models.Purchase.objects.filter(procurement__project=project)),
        'receipts': _receipt_rows(models.Receipt.objects.filter(project=project)),
    }


# ── Панель закрытия проекта + мягкий замок статуса ──
def project_closure(project):
    """Панель сведения остатков проекта к 0 + готовность к закрытию.

    Остаточные лоты (live≠0) — то, что мешает закрытию: положительные сводим в 0
    выходами (передача/списание/на баланс), отрицательные — аномалия «подбей лоты»
    (недостача, чинится правкой документа-потребителя). Закрыть можно **внешний**
    проект, когда остатков нет (внутренние склады постоянны — не закрываются).

    Волна 19, Ф15: раз черновик склад не двигает, мост «списать/на баланс» больше не
    уводит остаток мгновенно — он кладёт его в **черновой** закрывающий документ.
    Чтобы панель не выглядела «кнопка не сработала», отдаём `closing_drafts` —
    расфиксированные документы, уже разобравшие остатки этого проекта (в т.ч. чужого
    проекта-получателя, как требование в «Собственный склад»): их видно строкой
    «ждут фиксации», и они же становятся причиной отказа в `blocker`.
    """
    residuals = []
    positive = ZERO
    anomaly_count = 0
    lots = list(project.lots.select_related('item', 'origin').order_by('item__code', 'id'))
    live_by_lot = lots_live_qty(lots)
    for lot in lots:
        live = live_by_lot[lot.id]
        if live == 0:
            continue
        residuals.append({
            'lot_id': lot.id, 'lot_label': _lot_label(lot),
            'origin': lot.origin_kind,          # глиф партии (§7a): форма = откуда родилась
            'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'live_qty': live, 'anomaly': live < 0,
        })
        if live > 0:
            positive += live
        else:
            anomaly_count += 1
    drafts = _closing_drafts(project)
    # Аудит-1, Б2б-5: при смеси показываем ОБЕ половины работы. Черновики разобрали
    # часть остатка, но `live` до фиксации не гаснет — «зафиксируйте черновики» в
    # одиночку врало бы, что дальше делать нечего. Разбор считаем от магнитуды
    # расхода черновиков (`_closing_drafts.qty`), нижний зажим — от возможной
    # пере-разборки (два черновика на один лот).
    in_drafts = sum((row['qty'] for row in drafts), ZERO)
    unsorted = max(positive - in_drafts, ZERO)
    is_external = project.kind == models.Project.Kind.EXTERNAL
    is_closed = project.locked
    can_close = is_external and not is_closed and not residuals
    if not is_external:
        blocker = 'Внутренний склад постоянный — не закрывается.'
    elif is_closed:
        blocker = ''
    elif residuals and drafts and unsorted:
        blocker = (f'В черновиках {_num(in_drafts)}, не разобрано {_num(unsorted)} — '
                   'зафиксируйте черновики и сведите остаток в 0.')
    elif residuals and drafts:
        blocker = 'Закрывающие документы ещё черновики — зафиксируйте их.'
    elif residuals:
        blocker = 'Есть остаточные лоты — сведите их в 0.'
    else:
        blocker = ''
    return {
        'project_id': project.id, 'project_code': project.code,
        'project_name': project.description, 'kind': project.kind,
        'locked': project.locked, 'closed': project.closed,
        'is_external': is_external,
        'residuals': residuals, 'residual_positive': positive,
        'residual_in_drafts': in_drafts, 'residual_unsorted': unsorted,
        'anomaly_count': anomaly_count, 'closing_drafts': drafts,
        'can_close': can_close, 'blocker': blocker,
    }


def _closing_drafts(project):
    """Расфиксированные документы, уже разобравшие остатки проекта (Ф15).

    Ищем по строкам: любой `locked=False` документ, чья `StockLine` ссылается на лот
    этого проекта. Документ может жить в другом проекте (требование в «Собственный
    склад» тянет наш лот) — поэтому фильтр по строкам, а не по `document.project`.
    `qty` — сколько остатка ждёт фиксации (магнитуда расхода по нашим лотам).
    """
    rows = []
    docs = (models.StockDocument.objects
            .filter(locked=False, lines__lot__project=project)
            .distinct().order_by('id'))
    for doc in docs:
        qty = -(doc.lines.filter(lot__project=project, qty__lt=0)
                .aggregate(s=Sum('qty'))['s'] or ZERO)
        rows.append({
            'document_id': doc.id, 'kind': doc.kind,
            'code': doc.code or '', 'number': doc.number, 'qty': qty,
        })
    return rows


def lock_project(project):
    """Зафиксировать проект — мягкий замок-веха.

    Gate: внешний проект без остаточных лотов (всё сведено в 0). Ничего не
    разрушает — веха «проект отработан», реюз/расфиксация свободны.

    Волна 19, Ф1c: дату `closed` здесь больше НЕ штампуем — она информационная,
    Иван проставляет реальный срок руками (сколько работа заняла на самом деле,
    независимо от формальностей закрытия).
    """
    if project.kind != models.Project.Kind.EXTERNAL:
        raise ValidationError('Фиксировать можно только внешний проект (НИР/контракт).')
    if project.locked:
        raise ValidationError('Проект уже зафиксирован.')
    if project_closure(project)['residuals']:
        raise ValidationError(
            'Нельзя зафиксировать: есть остаточные лоты — сведите их в 0.')
    project.locked = True
    project.save(update_fields=['locked'])
    return project


def unlock_project(project):
    """Расфиксировать проект. Замок ничего не разрушал."""
    if not project.locked:
        raise ValidationError('Расфиксировать можно только зафиксированный проект.')
    project.locked = False
    project.save(update_fields=['locked'])
    return project


# ── Мосты панели закрытия (один клик = свести остаточный лот в 0) ──
def _require_no_closing_draft(lot):
    """Отказать, если остаток лота уже разобран черновым закрывающим актом (Ф15).

    Мосты панели «найти-или-создать»: лот, уже лежащий в черновике, раньше уводил
    их в ветку «создать новый акт» — и повторный клик плодил ВТОРОЙ документ на тот
    же остаток (после фиксации обоих лот ушёл бы в минус). Спровоцировать это легко:
    после Ф15 остаток на панели не гаснет до фиксации, и клик выглядит «не
    сработавшим». Правильный ответ — не второй документ, а напоминание, где лежит
    первый: работа уже сделана, осталось её зафиксировать.
    """
    kinds = (models.StockDocument.Kind.WRITEOFF, models.StockDocument.Kind.REQUISITION)
    doc = (models.StockDocument.objects
           .filter(locked=False, kind__in=kinds, lines__lot=lot, lines__qty__lt=0)
           .distinct().order_by('id').first())
    if doc is not None:
        raise ValidationError(
            f'Остаток лота уже разобран черновиком «{doc.code}» — '
            f'зафиксируйте его.')


def writeoff_lot(project, lot, qty, user):
    """Мост «списать остаток»: найти-или-создать акт списания проекта + строка.

    Оживляет действие панели: один клик кладёт остаток лота в акт списания. Ф15:
    остаток уйдёт в 0 не сейчас, а на фиксации акта — панель показывает лот
    остаточным, пока акт черновик (это и есть «ответственно нажал Зафиксировать»).
    Переиспользует последний **черновой** акт проекта; зафиксированный не трогаем —
    правка под замком запрещена.
    """
    if lot.project_id != project.id:
        raise ValidationError('Лот из другого проекта.')
    _require_no_closing_draft(lot)
    # Ф2c: `project` поднят в StockDocument (реверс — `project.documents`); типизированный
    # доступ через дочерний менеджер (прозрачно фильтрует по родительскому полю).
    writeoff = (models.Writeoff.objects.filter(project=project, locked=False)
                .order_by('-id').first())
    if writeoff is None:
        writeoff = create_writeoff(
            project, user, _auto_number('СПИС', project), reason='закрытие проекта')
    add_writeoff_line(writeoff, lot, qty)
    return writeoff


def requisition_lot(project, lot, qty, user, dest_kind=None):
    """Мост «на баланс»: отпочковать остаток проекта в белый «Собственный склад».

    Один клик панели кладёт остаток в требование: на фиксации он уйдёт в 0 у проекта
    (`−ISSUE`) и появится лотом-потомком на балансе (`+RECEIPT`) — до неё склад не
    двигается (Ф15). Переиспользует последнее **черновое** требование в целевой склад;
    зафиксированное не трогаем.
    """
    if lot.project_id != project.id:
        raise ValidationError('Лот из другого проекта.')
    _require_no_closing_draft(lot)
    dest = _internal_project(dest_kind or models.Project.Kind.INTERNAL_STOCK)
    requisition = (models.Requisition.objects.filter(project=dest, locked=False)
                   .order_by('-id').first())
    if requisition is None:
        requisition = create_requisition(dest, user, _auto_number('ТРБ', dest))
    add_requisition_line(requisition, lot, qty)
    return requisition


# --------------------------------------------------------------------------- #
#  Правка шапки форм (сквозная, все документы): номер/дата/мягкие поля
# --------------------------------------------------------------------------- #
# Инлайн-правка несруктурных полей шапки прямо в форме (автосейв по полю,
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


# Номер и дата шапки очищаются в черновике свободно (аудит-1, Б2б-4). Прежние
# `_require_number`/`_require_date` отклоняли пустую строку в PATCH — «заполнить можно,
# передумать нельзя», что расходилось с Ф12e: черновик имеет право быть неполным.
# Авторитетная per-kind политика обязательности живёт на модели
# (`StockDocument.REQUIRED_HEADER_BY_KIND`/`clean`, волна 13, Ф2d) и гейтится на
# ФИКСАЦИИ (`_require_header`) — там ошибиться документом уже поздно, а в черновике
# «стереть чужой номер» — обычный ход.


# --------------------------------------------------------------------------- #
#  Гигиена текстовых полей (2026-10-15, запрос Ивана)
# --------------------------------------------------------------------------- #
# Правило ОДНО и живёт здесь: поле формы спрашивает его через `/api/hygiene/` до
# сохранения (всплывашка «Принять / Перепишу сам»), а запись в БД чистится им же
# молча (`views._clean_payload`, синк библиотеки) — грязь не проходит никаким путём.
_HYGIENE_SPACE = str.maketrans({c: ' ' for c in
                                '\t\n\r\v\f   　'
                                + ''.join(map(chr, range(0x2000, 0x200b)))})
_HYGIENE_DROP = str.maketrans({c: None for c in '​‌‍⁠﻿­'})
# Двойники дефиса — только в КОДЕ: код ищут набором с клавиатуры, а `−` (минус) в
# `AR0144…−CPBR` поиск по `-` не находит. В описании минус и тире — законная
# типографика («−34…+14 дБм», «2.2–5.5 В»), их не трогаем.
_HYGIENE_DASH = str.maketrans({c: '-' for c in '−‐‑‒'})


def clean_text(value, code=False):
    """Очищенный текст: пробельные двойники (табуляция, переводы строк, неразрывный и
    прочие юникод-пробелы) → пробел, невидимые символы нулевой ширины → прочь, серии
    пробелов → один, края обрезаны; у кода (`code=True`) ещё и двойники дефиса → `-`.
    Не строка → как есть (числа/None/списки чистить нечего)."""
    if not isinstance(value, str):
        return value
    text = value.translate(_HYGIENE_SPACE).translate(_HYGIENE_DROP)
    if code:
        text = text.translate(_HYGIENE_DASH)
    return ' '.join(part for part in text.split(' ') if part)


def text_hygiene(value, code=False):
    """Вердикт для всплывашки поля: `{cleaned, dirty}`. `dirty` — очистка изменила
    больше, чем края: пробелы по краям обрезаем молча (решение Ивана — иначе вопрос
    выскакивал бы на каждый случайный пробел), остальное показываем на выбор."""
    raw = value if isinstance(value, str) else ''
    cleaned = clean_text(raw, code=code)
    return {'cleaned': cleaned, 'dirty': cleaned != raw.strip()}


def require_unique_code(model, code, pk=None):
    """Мягкая уникальность `code` (волна 19, Ф10, правило Ивана): плохой/занятый код
    ловим дружелюбно ДО IntegrityError, чтобы трение не уходило команде в оффлайн.

    `code` — уникальный короткий жаргон; занят в пределах своей сущности → отказ с
    внятным текстом (не 500). Пустой/`None` пропускаем (несколько NULL легальны). Для
    документов `model` = `StockDocument` (единое пространство кода на все ордера)."""
    code = (code or '').strip()
    if code and model.objects.filter(code=code).exclude(pk=pk).exists():
        raise ValidationError(f'Код «{code}» уже занят — выберите уникальный.')


def fallback_code(instance, label):
    """Проставить код-фолбэк «Поставка 12» только что рождённой сущности (Ф12e).

    «＋ Новый» больше не открывает форму создания — сущность рождается по клику, а
    `code` у половины сущностей `unique NOT NULL`: пустым его оставить нельзя.
    Решение Ивана 2026-07-28 — **единый шаблон везде** (`«{вид} {id}»`), включая
    ордера, где колонка допустила бы NULL: правило одно на всех, и титул формы
    (`code`, Ф11) нигде не вычисляется в обход данных.

    Код заведомо временный — человек перебьёт его своим жаргоном
    ([[code-identity-principle]]), поэтому уникальность добираем суффиксом, а не
    ошибкой: `id` уникален внутри сущности, но человек мог руками занять ровно
    «Изделие 12» раньше. Зовётся ПОСЛЕ `create` — до вставки `id` не существует.
    """
    base = f'{label} {instance.pk}'
    code, n = base, 1
    # Через `concrete_model` — у ордера это `StockDocument` (единое пространство
    # кода на семь видов); `Receipt.objects` фильтрует по `kind` и «Списание 12»
    # не увидел бы. У остальных сущностей proxy нет, и это тот же класс.
    model = instance._meta.concrete_model
    while model._default_manager.filter(code=code).exclude(pk=instance.pk).exists():
        n += 1
        code = f'{base}-{n}'
    instance.code = code
    instance.save(update_fields=['code'])
    return instance


def create_with_fallback_code(model, label, **fields):
    """Родить сущность, чей `code` — `unique NOT NULL`, без кода от человека (Ф12e).

    Шаблон фолбэка опирается на `id`, а `id` появляется только после вставки —
    отсюда два шага. Временный код — случайный: транзакция не даёт ему стать
    видимым снаружи, но защищает от коллизии двух одновременных рождений (пустая
    строка на этом месте оставила бы дыру шириной в один `INSERT`).
    """
    with transaction.atomic():
        obj = model.objects.create(code=uuid4().hex, **fields)
        return fallback_code(obj, label)


def _born_order(model, project, user, number='', date=None, **specifics):
    """Родить ордер любого вида (Ф12e) — одна точка на семь `create_*`.

    Что раньше отличало семь рождений — только вид и своя строка «Нужен № акта».
    Ф12e эти проверки снимает (номер обязателен к ФИКСАЦИИ, `REQUIRED_HEADER_BY_KIND`,
    а не к рождению), и различий не остаётся вовсе. `date` — не фолбэк-ложь, а факт:
    сегодня документ и правда заводят; к фиксации человек поправит его на дату УПД.
    Код — общий шаблон («Поставка 12»), пространство кода одно на все виды.
    """
    doc = model.objects.create(
        project=project, user=user, number=(number or '').strip(),
        date=date or timezone.localdate(), **specifics)
    return fallback_code(doc, models.DocumentKind(doc.kind).label)


def _set_code(instance, code):
    """Выставить `code` документа/сущности (волна 19, Ф10) под замком формы.

    `code` — часовой: `_UNSET` → не трогаем; иначе пустой → `NULL` (в MySQL несколько
    NULL не конфликтуют по unique, так очистка кода не ловит IntegrityError), непустой
    → строка. Уникальность — мягко (`require_unique_code`) на `StockDocument` (единое
    пространство кода ордеров). Отдельным `save` (как контрагент у передачи) — вне
    `_apply`, который пропускает None и не дал бы очистить код в NULL."""
    if code is not _UNSET:
        require_unique_code(models.StockDocument, code, instance.pk)
        instance.code = (code or '').strip() or None
        instance.save(update_fields=['code'])


def _set_author(doc, user):
    """Сменить автора документа (Ф2j) — сквозная правка шапки под замком.

    `user` — часовой: `_UNSET` → не трогаем; `User` → выставить. Автор обязателен
    (FK `StockDocument.user` NOT NULL), поэтому `None` отклоняем. Замок проверяет
    вызывающий (`update_*` уже гейтит `_require_unlocked`)."""
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
    ноль-оп. Замок проверяет вызывающий (`update_*` уже гейтит `_require_unlocked`)."""
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
    _require_native_target(item)
    if item.pk == kitting.target_item_id:
        return
    if kitting.lines.exists() or kitting.lots.exists():
        raise ValidationError(
            'Целевое изделие определяет состав — сначала удалите строки пайки '
            'и рождённый прибор.')
    kitting.target_item = item
    fields = ['target_item']
    # Цель появилась → появилась и потребность: без кол-ва образцов состав считать не
    # из чего. Ставим 1, ровно как рождение СРАЗУ с целью (`kittings` POST:
    # `qty=… or (1 if target else None)`) — там это правило уже жило, а путь «родил по
    # клику, цель выбрал в форме» его не проходил и оставлял `qty` пустым.
    if kitting.qty is None:
        kitting.qty = Decimal('1')
        fields.append('qty')
    kitting.save(update_fields=fields)


def update_document(doc, number=None, date=None, code=_UNSET, description=None,
                    user=_UNSET, project=_UNSET, contractor=_UNSET, reason=None):
    """**Единая** правка шапки ордера (волна 19, Ф14).

    До Ф14 шесть видов несли шесть одинаковых `update_*`, различавшихся ровно двумя
    строками специфики (`contractor` у передачи, `reason` у списания) — различие было
    структурным (у каждого своя таблица), а не поведенческим. MTI снят, специфика
    живёт колонками одной таблицы — вместе с ним схлопывается и эта шестерня.
    Per-kind имена остаются тонкими делегатами ниже: на них завязан словарь вызова
    (`update_writeoff(w, reason=…)` читается лучше общего), но реализация одна.

    `contractor` — часовой: не передан → не трогаем; `Counterparty` → выставить;
    `None` → снять. Применим только к своим видам (`CONTRACTOR_KINDS`) — то же, что
    стережёт CHECK `doc_contractor_only_own_kinds`, но дружелюбной ошибкой вместо
    `IntegrityError`.

    `number`/`date` — не переданы (`None`) → не трогаем; пустая строка → **очистка**
    (`''` / `NULL`): в черновике можно передумать, обязательность стережёт фиксация
    (аудит-1, Б2б-4). Дата идёт мимо `_apply` — там `None` занят под «не передано».
    """
    _require_unlocked(doc)
    _set_author(doc, user)
    _set_project(doc, project)
    _set_code(doc, code)
    if contractor is not _UNSET:
        if doc.kind not in models.CONTRACTOR_KINDS:
            raise ValidationError(
                'Контрагент есть только у поставки (поставщик) и передачи (заказчик).')
        doc.contractor = contractor
        doc.save(update_fields=['contractor'])
    if date is not None:
        doc.date = date or None         # '' → NULL (как у заказа, `update_purchase`)
        doc.save(update_fields=['date'])
    return _apply(doc, {
        'number': None if number is None else str(number).strip(),
        'reason': None if reason is None else reason.strip(),
        'description': None if description is None else description.strip(),
    })


def update_receipt(receipt, **kw):
    """Шапка поставки: № УПД / дата / код / описание / автор / проект-якорь."""
    return update_document(receipt, **kw)


def update_purchase(purchase, date=None, code=_UNSET, description=None, user=_UNSET,
                    contractor=_UNSET):
    """Правка шапки заказа (дата / код / описание / автор / контрагент). Только в
    черновике.

    Дата заказа nullable — пустая строка очищает её в NULL (в отличие от
    документов с обязательной датой). `code` — часовой `_UNSET` (пустой → NULL, чтобы
    несколько заказов без кода не конфликтовали по unique).

    Волна 24: ни проекта, ни закупки здесь нет — закупка задаётся при рождении и не
    меняется, проект выводится через неё. `contractor` — часовой (Ф17): не передан → не
    трогаем, сущность → выставить, `None` → снять; обязателен к ФИКСАЦИИ, а не к правке.
    """
    _require_unlocked(purchase, PURCHASE_LOCKED)
    _set_author(purchase, user)
    fields = []
    if contractor is not _UNSET:
        purchase.contractor = contractor
        fields.append('contractor')
    if date is not None:
        purchase.date = date or None
        fields.append('date')
    if code is not _UNSET:
        require_unique_code(models.Purchase, code, purchase.pk)
        purchase.code = (code or '').strip() or None
        fields.append('code')
    if description is not None:
        purchase.description = description.strip()
        fields.append('description')
    if fields:
        purchase.save(update_fields=fields)
    return purchase


def update_transfer(transfer, **kw):
    """Шапка передачи: № накладной / дата / код / описание / **заказчик** / автор / проект."""
    return update_document(transfer, **kw)


def update_writeoff(writeoff, **kw):
    """Шапка списания: № акта / дата / **причина** / код / описание / автор / проект."""
    return update_document(writeoff, **kw)


def update_requisition(requisition, **kw):
    """Шапка требования: № / дата / код / описание / автор / проект-получатель."""
    return update_document(requisition, **kw)


def update_relocation(relocation, **kw):
    """Шапка перемещения: № / дата / код / описание / автор / проект-якорь.

    Проект — якорь (`_set_project`): у перемещения строки-ходы ссылаются на лоты того
    же проекта, поэтому сменить его можно лишь у пустого ордера."""
    return update_document(relocation, **kw)


def update_kitting(kitting, qty=None, date=None, code=_UNSET, description=None,
                   user=_UNSET, project=_UNSET, target_item=_UNSET):
    """Правка шапки комплектации (кол-во образцов / дата / код / описание / автор / проект / цель).
    Только «в работе».

    Кол-во образцов пересчитывает потребности BOM — правится, пока `wip`. `project`/
    `target_item` — якоря #A (Ф2k): меняются только у пустой комплектации.
    """
    _require_unlocked(kitting)
    _set_author(kitting, user)
    _set_project(kitting, project)
    _set_target_item(kitting, target_item)
    _set_code(kitting, code)
    if qty is not None and qty <= 0:
        raise ValidationError('Количество образцов должно быть положительным.')
    fields = []
    if qty is not None:
        kitting.qty = qty
        fields.append('qty')
    if date is not None:                 # дата комплектации nullable
        kitting.date = date or None
        fields.append('date')
    if description is not None:
        kitting.description = description.strip()
        fields.append('description')
    if fields:
        kitting.save(update_fields=fields)
    return kitting


# --------------------------------------------------------------------------- #
#  Волна 7 — планирование закупок: командный свод + записываемый Procurement
# --------------------------------------------------------------------------- #
def counts_in_scope(project):
    """Проект участвует в арифметике охвата: **активный внешний**.

    Внутренние склады — источник покрытия, а не потребитель; закрытый проект не
    закупают. Правило одно на весь охват (витрина «Потребность» и деньги закупки считают
    один и тот же набор — иначе панель и витрина разошлись бы молча).
    """
    return project.kind == models.Project.Kind.EXTERNAL and not project.locked


def scope_demand(projects, active_only=True):
    """Потребность по **охвату**: свод покупных листьев через заданный набор проектов.

    Пришла 2026-08-11 на смену `scope_deficit` (витрина «К закупке») вместе с пересборкой
    формы закупки. Считает то же самое разузлование, но говорит на языке **баланса**, а не
    клампленного «Закупить»: колонки те же, что в «Потребности» проекта (`_leaf_row`), —
    Потр. · Компл. · Склад · Заказ · Баланс. Одна витрина потребности на продукт.

    Волна 24: закупка однопроектная, и единственный вызывающий (`procurement_demand`)
    передаёт ровно её проект с `active_only=False` — проект назван в шапке документа,
    выбирать не из чего. Отсев `counts_in_scope` (только активные внешние) остался
    правилом выбора набора на случай многопроектного свода.

    **Члены складываются через проекты, и баланс — их сумма** (решение Ивана 2026-08-11,
    сознательная смена семантики). Прежний свод не перенеттивал: `to_order` каждого
    проекта клампился в ноль, поэтому профицит проекта A не гасил нужду проекта B. Баланс
    знаковый, и в сумме гасит — но это НЕ ложь продукта: остаток соседнего проекта в
    контуре доступен, просто через документ (`Requisition`, заём B→A — штатный путь
    домена). Витрина отвечает «хватает ли по закупке в целом»; вопрос «хватает ли ИМЕННО
    в этом проекте» задают форме проекта, где перенеттивать нечего.
    """
    acc = {}  # item_id → агрегат по Item через проекты
    outside = ZERO  # траты вне потребности (2026-10-19) — для сверки с планом бюджета
    bom = BomIndex()
    for project in projects:
        if active_only and not counts_in_scope(project):
            continue
        supply = ProjectSupply(project)
        need_by_item, _incomplete = project_leaf_demand(project, bom)
        outside += supply.spent_outside({item.id for item in need_by_item})
        for item, need in need_by_item.items():
            row = acc.setdefault(item.id, {
                'item': item,
                'need': ZERO, 'kitted': ZERO, 'in_stock': ZERO, 'on_order': ZERO,
                'planned': ZERO, 'wip': ZERO,
                'kitted_cost': ZERO, 'in_stock_cost': ZERO, 'ordered_cost': ZERO,
                'spent_cost': ZERO, 'ahead': ZERO,
                'anomaly': False,
            })
            bal = supply.balance(item, need)
            for key in ('need', 'kitted', 'in_stock', 'on_order', 'planned', 'wip'):
                row[key] += bal[key]
            row['kitted_cost'] += supply.kitted_cost(item)
            row['in_stock_cost'] += supply.available_cost(item)
            row['ordered_cost'] += supply.ordered_cost(item)
            row['spent_cost'] += supply.spent(item)
            # Деньги впереди — по каждому проекту отдельно, как и бюджет: между проектами
            # не перенеттим (запас одного не закрывает нужду другого без документа).
            row['ahead'] += supply.plan_ahead(item, need)
            # Аномалия — свойство лота, а не суммы: хватает одного минусового лота в
            # одном проекте охвата, чтобы строка просила разбирательства.
            row['anomaly'] = row['anomaly'] or supply.has_negative_lot(item)
    rows = []
    for agg in acc.values():
        item = agg['item']
        row = _balance(agg['need'], agg['kitted'], agg['in_stock'], agg['on_order'])
        row.update({
            'planned': agg['planned'], 'wip': agg['wip'],   # доля «от нас» (волна 24)
            'component_id': item.id,
            'component_code': item.code,
            'component_description': item.description,
            'component_native': item.native,
            'component_synced': item.synced,
            'component_locked': item.locked,
            'component_category': category_code(item),   # фильтр колонки «Компонент»
            'uom': item.uom,
            'supply': _supply_status(row),
            'anomaly': agg['anomaly'],
            **_money_fields(item, agg['kitted_cost'], agg['in_stock_cost'],
                            agg['ordered_cost'], agg['spent_cost'], agg['ahead'],
                            agg['need']),
        })
        rows.append(row)
    mark_pareto(rows, key='plan_cost')      # 2026-10-20: что определяет стоимость
    # Тот же порядок, что в «Потребности» проекта: горит вперёд, внутри — по коду.
    rows.sort(key=lambda r: (-_WORST_RANK[r['status']], r['component_code']))
    return {'rows': rows, 'outside_spent': outside}


def _mark_taken(data, lines):
    """Отметить в своде позиции, уже взятые в строки документа (`in_lines`).

    Одна отметка на обе витрины контура — закупки и заказа (2026-08-19). Смысл ровно
    один: «строка по этому Item в документе уже есть». Булево вместо числа принципиально
    — количество живёт в табе «Строки», и дублировать его в витрине значило бы завести
    второе место правды.
    """
    taken = set(lines.values_list('item_id', flat=True))
    for row in data['rows']:
        row['in_lines'] = row['component_id'] in taken
    return data


def procurement_demand(procurement):
    """Витрина «Потребность» формы закупки: свод по её проекту + отметка «уже в строках».

    Телескоп закупки (2026-08-11): состояние складов и заказов проекта, помогает выбрать
    позицию — больше ничего; количество набирают в «Строках». Волна 24: закупка
    однопроектная и витрина живёт только здесь — у заказа её сняли, чтобы планировали в
    закупке, а не в заказе. Отсев `counts_in_scope` не применяется (`active_only=False`):
    проект назван в шапке, выбирать не из чего.
    """
    return _mark_taken(scope_demand([procurement.project], active_only=False),
                       procurement.lines)


def procurement_form(procurement):
    """Проекция формы закупки: шапка + проект + строки (`item`, `qty`) + итог.

    Волна 24: закупка однопроектная и источник правды контура; заказы рождаются из неё
    (`create_purchase`). Мягкий замок: строки правятся только пока не зафиксировано.
    Чистая проекция.
    """
    editable = not procurement.locked
    lines = list(procurement.lines.select_related('item', 'item__category').order_by('id'))
    rows = []
    total_qty = ZERO
    for line in lines:
        total_qty += line.qty
        rows.append({
            'id': line.id, 'item_id': line.item_id, 'item_code': line.item.code,
            'item_description': line.item.description, 'uom': line.item.uom, 'qty': line.qty,
            'item_category': category_code(line.item),   # фильтр колонки
            'item_native': line.item.native, 'item_synced': line.item.synced,
            'item_locked': line.item.locked,   # глиф строки по режиму (Ф3a)
        })
    # Деньги намерения (2026-08-07): потребность / закупка / переплата. Знаменатель —
    # нужда её проекта (волна 24: проект один и назван в шапке — отсева нет).
    project = procurement.project
    money = intent_money(lines, demand_map([project]))
    money.update(procurement_money(procurement, lines))
    return {
        'id': procurement.id, **_author(procurement), 'locked': procurement.locked,
        'code': procurement.code, 'description': procurement.description,
        'date': procurement.date,
        'project_id': project.id, 'project_code': project.code,
        'project_name': project.description,
        # Проект меняется, только пока заказов нет: у заказов он выводится отсюда, и
        # смена увела бы их (и их поставки) в чужой проект.
        'project_editable': not procurement.purchases.exists(),
        'editable': editable,                       # строки правятся только пока не зафиксировано
        'total_qty': total_qty,
        **money,          # demand / estimate / overpay / unestimated — панель бюджета
        'lines': rows,
    }


def create_procurement(project, user, date=None, code=None, description=''):
    """Создать закупку (черновик) под проект. Пустой код — фолбэком «Закупка 12» (Ф12e).
    Рождение по «＋ Новый» несёт проект-фолбэк (`default_document_project`), как ордера."""
    require_unique_code(models.Procurement, code)
    p = models.Procurement.objects.create(
        project=project, user=user, locked=False,
        date=date, code=code, description=(description or '').strip())
    return p if code else fallback_code(p, 'Закупка')


PROCUREMENT_LOCKED = (
    'Строки правятся только в черновике закупки — снимите замок (unlock).')


PROCUREMENT_QTY_NEGATIVE = 'Количество закупки не может быть отрицательным.'


def add_procurement_line(procurement, item, qty):
    """Добавить строку закупки-плана (только в черновике). `(procurement, item)` — одна строка.

    **Ноль разрешён** (2026-08-11, решение Ивана): строка рождается кликом из витрины
    «Потребность» именно с нулём — «позицию беру, количество ещё думаю». Это рабочее
    состояние плана, а не брак: количество набирают следом, в «Строках», глядя на баланс
    конкретного компонента. Отрицательное по-прежнему невозможно. В бланк поставщику
    нулевые строки не попадают (`procurement_xlsx`).
    """
    _require_unlocked(procurement, PROCUREMENT_LOCKED)
    if qty is None or qty < 0:
        raise ValidationError(PROCUREMENT_QTY_NEGATIVE)
    if procurement.lines.filter(item=item).exists():
        raise ValidationError(
            f'Изделие {item.code} уже в закупке — правьте существующую строку.')
    return models.ProcurementLine.objects.create(
        procurement=procurement, item=item, qty=qty)


def update_procurement_line(line, qty):
    """Автосейв количества строки закупки-плана (только в черновике).

    Ноль допустим на тех же основаниях, что и при рождении строки: план — черновик, и
    вернуть позицию в состояние «беру, но сколько — ещё думаю» так же законно, как в него
    прийти. Убрать позицию совсем — корзиной строки, а не нулём.
    """
    _require_unlocked(line.procurement, PROCUREMENT_LOCKED)
    if qty is None or qty < 0:
        raise ValidationError(PROCUREMENT_QTY_NEGATIVE)
    line.qty = qty
    line.save(update_fields=['qty'])
    return line


def remove_procurement_line(line):
    """Удалить строку закупки-плана (только в черновике).

    Волна 24: строку, которую разбирают заказы, не удаляем — иначе их строки повисли
    бы вне плана (инвариант «строка заказа ⊆ план»).
    """
    _require_unlocked(line.procurement, PROCUREMENT_LOCKED)
    if models.PurchaseLine.objects.filter(purchase__procurement=line.procurement,
                                          item=line.item_id).exists():
        raise ValidationError(
            f'Позицию {line.item.code} уже взяли заказы — сперва уберите её из заказов.')
    line.delete()


def lock_procurement(procurement):
    """Поставить замок закупки-плана — строки read-only.

    Волна 19 (Ф1): бывший `send_procurement`; отмена = удаление (Р1).
    """
    if not procurement.lines.exists():
        raise ValidationError('Нельзя утвердить пустую закупку — добавьте строку.')
    procurement.locked = True
    procurement.save(update_fields=['locked'])
    return procurement


def unlock_procurement(procurement):
    """Снять замок закупки-плана — ничего не разрушает."""
    procurement.locked = False
    procurement.save(update_fields=['locked'])
    return procurement


def update_procurement(procurement, date=None, code=_UNSET, description=None, user=_UNSET,
                       project=_UNSET):
    """Правка шапки закупки-плана (дата / код / описание / автор / контрагент). Только в черновике.

    Дата закупки nullable — пустая строка очищает её в NULL (как заказ). `code` —
    часовой `_UNSET` (пустой → NULL, чтобы несколько закупок без кода не конфликтовали
    по unique). `contractor` — часовой (волна 19, Ф4): не передан → не трогаем;
    `Counterparty` → выставить; `None` → снять (nullable).

    `project` (волна 24) — обязателен; меняется, только пока у закупки нет заказов:
    их проект выводится отсюда, и смена молча увела бы их вместе с поставками.
    """
    _require_unlocked(procurement, PROCUREMENT_LOCKED)
    _set_author(procurement, user)
    fields = []
    if project is not _UNSET:
        if project is None:
            raise ValidationError('Проект закупки обязателен.')
        if project.pk != procurement.project_id and procurement.purchases.exists():
            raise ValidationError(
                'У закупки есть заказы — их проект выводится из закупки; '
                'сменить проект можно, пока заказов нет.')
        procurement.project = project
        fields.append('project')
    if date is not None:
        procurement.date = date or None
        fields.append('date')
    if code is not _UNSET:
        require_unique_code(models.Procurement, code, procurement.pk)
        procurement.code = (code or '').strip() or None
        fields.append('code')
    if description is not None:
        procurement.description = description.strip()
        fields.append('description')
    if fields:
        procurement.save(update_fields=fields)
    return procurement


def delete_procurement(procurement):
    """Удалить закупку-план (WAVE14 Ф2). Мягкий замок: утверждённую сперва вернуть в
    черновик (снять замок); привязанные заказы (`Purchase.procurement`, PROTECT)
    держат — их сперва открепить/удалить. Строки плана (`ProcurementLine`) — каскад."""
    if procurement.locked:
        raise ValidationError(
            'Закупка утверждена — сперва верните её в черновик (снимите замок), затем удаляйте.')
    if procurement.purchases.exists():
        raise ValidationError('К закупке привязаны заказы — удаление заблокировано.')
    for att in procurement.attachments.all():      # физические файлы (каскад их сиротит)
        delete_attachment(att)
    try:
        procurement.delete()                       # каскад: строки закупки
    except ProtectedError:
        raise ValidationError('Закупка связана с другими записями — удаление заблокировано.')


# Волна 19, Ф17: `_plan_procurements` удалён — список закупок = ВСЕ закупки.
# Эвристика «есть заказы, но нет строк плана» существовала ровно затем, чтобы прятать
# закупки-пустышки, которые `_solo_procurement` плодил на каждый одиночный заказ (плата
# за NOT NULL у `Purchase.procurement`). Стал nullable — пустышек не бывает, и прятать
# нечего: фильтр и заглушка умерли одной правкой.


# Мост «витрина → строки плана» (`add_to_procurement`, топ-ап до наводки) снят
# 2026-08-11 вместе с витриной «К закупке». Новая «Потребность» кладёт позицию в план
# НУЛЁМ и ничего не досчитывает: витрина выбирает СТРОКУ, количество выбирают в
# «Строках», глядя на баланс одного компонента. Топ-ап был мостом между двумя числами,
# из которых одно (наводка) больше не показывается как решение.


def our_organization():
    """Наша сторона — **обычный контрагент**, чей ID знает окружение (волна 19, Ф4b).

    Решение Ивана 2026-07-30: не константа в коде и не отдельная таблица настроек, а
    запись `Counterparty`. Тогда себя правят той же формой, что всех, у нас те же
    `description`/`inn` и та же «карточка предприятия» во вложениях — а окружение лишь
    знает, кто из справочника «мы» (`settings.ORG_COUNTERPARTY_ID`). Название
    организации в репозиторий не попадает, оно живёт в данных и в `.env`.

    `None` — настройка не задана или указывает на удалённую запись. Это не ошибка:
    выгрузка обязана работать и без неё (см. `procurement_xlsx`).
    """
    oid = getattr(settings, 'ORG_COUNTERPARTY_ID', None)
    return models.Counterparty.objects.filter(pk=oid).first() if oid else None


def _author_line(user):
    """Автор запроса для бланка: имя · почта · телефон, через запятую.

    Бланк уходит поставщику, и графа «Автор» отвечает на один вопрос — **кому отвечать
    по этому файлу**. Одного имени для этого мало, поэтому рядом едут контакты (правка
    Ивана 2026-08-10); незаполненные просто не рисуются, как и пустые строки шапки.
    Телефон берём из приставки (`UserProfile.phone`) уже в готовом виде.
    """
    parts = [user.get_full_name() or user.get_username(), user.email,
             profile_of(user).phone]
    return ', '.join(p for p in parts if p)


def _doc_date(value):
    """Дата для документа НАРУЖУ — `дд.мм.гггг` (тот же формат, что в просмотре формы).

    Принимает и `date`, и ISO-строку: сущность, только что созданная или поправленная в
    этом же запросе, держит в памяти ровно то, что пришло из JSON (`'2026-07-30'`), пока
    её не перечитали из БД. Нераспознанное значение даёт пустую строку — сырой ISO или
    мусор в бланке у поставщика хуже отсутствующей графы.
    """
    if isinstance(value, str):
        try:
            value = dt_date.fromisoformat(value)
        except ValueError:
            return ''
    return value.strftime('%d.%m.%Y') if value else ''


def _xlsx_sheet(ws, title, head, headers, rows, widths, alerts=None, foot=None,
                money=(), center=()):
    """Один лист выгрузки: шапка (B/C) → пустая строка → нумерованная таблица.

    Форма листа поднята из `procurement_xlsx` (2026-07-30, выгрузка изделия): бланк
    закупки и выгрузка изделия рисуют одно и то же — подписи шапки в колонке **B**,
    значения в **C** (колонка A узкая, она под «№», подпись в ней Excel обрезал бы по
    занятой соседке), жирные заголовки таблицы и сквозная нумерация строк.

    `head` — пары `(подпись, значение)` или тройки `(подпись, значение, формат)`, где
    формат — числовой формат ячейки значения (деньги в шапке пишутся так же, как в
    таблице, иначе одно и то же число выглядит двумя разными вещами). Значение с
    форматом выключается ВЛЕВО — под текст соседних строк шапки, а не по правому краю,
    куда Excel сам уводит одинокое число;
    **пустые строки шапки не рисуются вовсе**:
    пустая графа во внешнем документе читается как брак, а не как «не задано» (внутри
    продукта правило обратное, §13 — там прочерк честнее). `rows` идут БЕЗ номера —
    его проставляет лист.

    `alerts` — параллельный `rows` список флагов «к строке есть вопрос» (2026-09-15,
    план закупок): движок отдаёт смысл, лист выбирает знак — КРАСНЫЙ шрифт всей строки
    ([[engine-view-seam]]). `foot` — итоговая строка после таблицы: жирная и БЕЗ
    номера (её ячейки раскладывает вызывающий — итог стоит в своей колонке).

    `money` / `center` — НОМЕРА колонок (с единицы, «№» тоже считается): денежный формат
    и выключка по центру на всю колонку, заголовок включительно. Выключка колонки
    подпись итога не перебивает — та всегда прижата к своему числу (см. `foot`). Оформление задаётся
    колонкой, а не ячейкой: колонка — это одна графа документа, и разнобой внутри неё
    читается как ошибка.
    """
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    bold = Font(bold=True)
    alert = Font(color='FFC00000')      # тот же красный, каким горит строка на экране
    middle = Alignment(horizontal='center')
    to_number = Alignment(horizontal='right')
    ws.title = title
    for label, value, *fmt in head:
        if value is None or value == '':
            continue
        ws.append([None, label, value])
        ws.cell(row=ws.max_row, column=2).font = bold
        if fmt:
            value_cell = ws.cell(row=ws.max_row, column=3)
            value_cell.number_format = fmt[0]
            # Значение шапки выключено ВЛЕВО, под текст соседних строк (правка Ивана
            # 2026-09-15): число само по себе Excel прижал бы к правому краю, и шапка
            # разъехалась бы на две колонки значений вместо одной.
            value_cell.alignment = Alignment(horizontal='left')
    if head:
        ws.append([])                  # пустая строка отбивает шапку от таблицы
    ws.append(headers)
    table_top = ws.max_row                 # заголовки таблицы: с них начинается графа
    for cell in ws[ws.max_row]:
        cell.font = bold
    for n, row in enumerate(rows, start=1):
        ws.append([n, *row])
        if alerts and alerts[n - 1]:
            for cell in ws[ws.max_row]:
                cell.font = alert
    if foot:
        ws.append(foot)
        for cell in ws[ws.max_row]:
            cell.font = bold
            # Подпись итога стоит СЛЕВА от своего числа и прижимается к нему: у левого
            # края широкой графы она снова оказалась бы «через весь лист» от суммы.
            if isinstance(cell.value, str):
                cell.alignment = to_number
    for column in ws.iter_cols(min_row=table_top, max_row=ws.max_row):
        n = column[0].column
        for cell in column:
            if n in money:
                cell.number_format = MONEY_FORMAT
            if n in center:
                cell.alignment = middle
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    return ws


def _blank_head(contractor, date, user):
    """Шапка бланка наружу — ОДНА на закупку и заказ (2026-08-10).

    Порядок и подписи заданы Иваном по образцу реального файла: **Поставщик** (у кого
    просим/покупаем) → **Заказчик** (мы, `our_organization`) → **Дата запроса** →
    **Автор запроса** с контактами. Сторона идёт одним наименованием: ИНН из бланка
    снят — реквизиты живут в договоре и в карточке предприятия, а в запросе цен они
    только шумят.

    Незаданные строки не рисуются вовсе (`_xlsx_sheet`): пустая графа во внешнем
    документе читается как брак, а не как «значение не задано».
    """
    us = our_organization()
    return [
        ('Поставщик', contractor.description if contractor else ''),
        ('Заказчик', us.description if us else ''),
        ('Дата запроса', _doc_date(date)),
        ('Автор запроса', _author_line(user)),
    ]


def procurement_xlsx(procurement):
    """Сгенерировать xlsx-бланк закупки-плана (bytes) — файл поставщику.

    **Документ наружу** (с 2026-07-20 уходит реальным контрагентам), поэтому состав
    меняется осознанно и разом, а не побочным эффектом правки формы. Волна 19, Ф4b —
    первое такое изменение: над таблицей появилась шапка запроса (кто просит, у кого,
    когда, кто автор), а у позиций — порядковый номер.

    Шапка — общая с бланком заказа (`_blank_head`): поставщик (`Procurement.contractor`
    — намерение плана, у кого собираемся купить) · заказчик (мы) · дата запроса · автор
    с контактами. Незаданные строки **не рисуются вовсе**: пустая графа во внешнем
    документе читается как брак, а не как «значение не задано» (внутри продукта правило
    обратное, §13 — там прочерк честнее).

    **Порядок позиций = порядок на экране** (`order_by('id')`, тот же, что у
    `procurement_form`): нумерация в файле обязана совпадать с тем, что видит человек,
    иначе «позиция 3» в переписке означает разное у нас и у поставщика.

    **Нулевые строки в бланк не идут** (2026-08-11, решение Ивана). Ноль внутри продукта
    — рабочее состояние черновика («позицию беру, количество думаю»), но спрашивать у
    поставщика цену на «0 шт» бессмысленно: наружу уходит только то, что решено. Фиксация
    нулей при этом не запрещает — план вправе быть зафиксирован с недодуманной строкой,
    просто она не покидает контур.

    Синхронно в запросе (файл небольшой, тяжёлых рантаймов нет). openpyxl — импорт
    ленивый (зависимость только ради экспорта).
    """
    from openpyxl import Workbook

    wb = Workbook()
    _xlsx_sheet(
        wb.active, 'Заказ',
        # Волна 24: у закупки контрагента нет — строка «Поставщик» в шапке не рисуется.
        head=_blank_head(None, procurement.date, procurement.user),
        headers=['№', 'Артикул', 'Наименование', 'Кол-во', 'Ед.'],
        rows=[(line.item.code, line.item.description, float(line.qty), line.item.uom)
              for line in procurement.lines.select_related('item').order_by('id')
              if line.qty > 0],
        widths=[5, 22, 48, 12, 8])       # «№» узкая; остальные — по содержимому
    return _xlsx_bytes(wb)


def purchase_xlsx(purchase):
    """Сгенерировать xlsx-бланк ЗАКАЗА (bytes) — тот же файл, что у закупки-плана.

    Решение Ивана 2026-08-10: закупка и заказ отдают наружу один и тот же документ —
    шапка запроса + нумерованные позиции. Разница только в источнике строк: у закупки
    это план (`ProcurementLine`), у заказа — обязательство перед конкретным поставщиком
    (`PurchaseLine`). Подписи шапки и имя листа НЕ разводим по видам (решение того же
    дня): получателю приходит бланк одной формы, чем бы он ни был у нас внутри.

    Порядок позиций — `order_by('id')`, тот же, что в табе «Строки»: нумерация в файле
    обязана совпадать с экраном, иначе «позиция 3» в переписке значит разное.

    **Нулевые строки в бланк не идут** — то же правило, что у закупки (2026-08-19, когда
    ноль стал законным и в заказе): ноль внутри продукта — состояние черновика, а наружу
    уходит только решённое.
    """
    from openpyxl import Workbook

    wb = Workbook()
    _xlsx_sheet(
        wb.active, 'Заказ',
        head=_blank_head(purchase.contractor if purchase.contractor_id else None,
                         purchase.date, purchase.user),
        headers=['№', 'Артикул', 'Наименование', 'Кол-во', 'Ед.'],
        rows=[(line.item.code, line.item.description, float(line.qty), line.item.uom)
              for line in purchase.lines.select_related('item').order_by('id')
              if line.qty > 0],
        widths=[5, 22, 48, 12, 8])
    return _xlsx_bytes(wb)


# Копейка (`KOPECK`, объявлена в шапке модуля) — шаг округления денег и в выгрузке.
# Округляем КАЖДУЮ строку, а потом складываем округлённое: «Всего» обязано сходиться со
# столбцом, который человек видит глазами, иначе первый же пересчёт калькулятором
# объявит файл кривым.
# «Финансовый» формат рубля (правка Ивана 2026-09-15) — тот же, что в Excel под этим
# именем: знак валюты прижат к правому краю графы, разряды отбиты, ноль рисуется
# прочерком. Деньги в таблице ЧИСЛА, а не строки: получатель считает по ним формулой.
MONEY_FORMAT = '_-* #,##0.00\\ "₽"_-;-* #,##0.00\\ "₽"_-;_-* "-"??\\ "₽"_-;_-@_-'
# Тот же рубль БЕЗ финансовой растяжки — для одиночного числа вне таблицы (шапка).
# «Финансовый» формат тем и живёт, что растягивает число к правому краю графы, и
# выключку ячейки при этом игнорирует (свойство Excel, не наша самодеятельность):
# прижать им значение влево нельзя. В шапке равнять не с чем — графы нет, значение
# стоит под текстом соседних строк, — поэтому берём тот же рубль, только без растяжки.
MONEY_PLAIN = '#,##0.00\\ "₽"'


def project_plan_xlsx(project):
    """План закупок проекта (bytes) — вкладка «Потребность», переведённая в деньги.

    Решения Ивана 2026-09-15 (эта выгрузка — документ, состав меняем осознанно):

    - **строки = весь таб**, как на экране, включая позиции, которых уже хватает: файл
      это снимок потребности проекта, а не остаток к оплате;
    - **порядок = порядок на экране** (`project_deficit` уже отсортировал: горит вперёд,
      внутри по коду) — «позиция 7» в разговоре значит одно и то же у файла и у формы;
    - **одна графа количества** вместо пяти чисел таба: `Заказ`, если он покрывает
      потребность (позицию взяли, и взяли с запасом — планируем тем числом, которым её
      реально берут), иначе `Потр.` (недозаказ не прячет остаток нужды);
    - **цена = оценка изделия** (`estimated_cost`), та же, из которой панель бюджета
      считает «План (прогноз)». Факт поставок сюда НЕ подмешиваем: цены в одной колонке
      должны быть одной природы;
    - **позиция без оценки едет в файл и горит красным** — молча сложить её как 0
      значило бы выдать неполный итог за полный (тот же приём, что `unestimated` в
      панели бюджета, только знаком строки, а не счётчиком);
    - **«Всего» = сумма столбца «Стоимость»**, а не число «План (прогноз)» из панели:
      итог обязан сходиться со строками файла. С панелью он законно расходится — план
      считает факт по поставкам и оценку ТОЛЬКО остатка «в пути / к заказу».

    Синхронно в запросе, openpyxl — ленивым импортом (как `procurement_xlsx`).
    """
    from openpyxl import Workbook

    components = project_deficit(project, with_tree=False)['components']
    prices = {i.id: i.estimated_cost for i in models.Item.objects.filter(
        id__in=[c['component_id'] for c in components]).only('id', 'estimated_cost')}
    rows, alerts, total = [], [], ZERO
    for c in components:
        qty = c['on_order'] if c['on_order'] >= c['need'] else c['need']
        price = prices.get(c['component_id'])
        cost = None if price is None else (qty * price).quantize(
            KOPECK, rounding=ROUND_HALF_UP)
        if cost is not None:
            total += cost
        rows.append((c['component_code'], c['component_description'], float(qty),
                     c['uom'], '' if price is None else float(price),
                     '' if cost is None else float(cost)))
        alerts.append(price is None)

    wb = Workbook()
    _xlsx_sheet(
        wb.active, 'План закупок',
        # Бюджет проекта — в шапке и теми же рублями, что в таблице: читатель сравнивает
        # его с «Всего» глазами, и два разных вида одного рубля мешают это делать.
        # Не задан — строки нет вовсе (общее правило шапки).
        head=[('Проект', project.code), ('Описание', project.description),
              ('Бюджет', None if project.budget is None else float(project.budget),
               MONEY_PLAIN)],
        headers=['№', 'Компонент', 'Описание', 'Кол-во', 'Ед.', 'Цена', 'Стоимость'],
        rows=rows, alerts=alerts,
        # Итог — в СВОЕЙ колонке (под «Стоимостью»), подпись — в СОСЕДНЕЙ слева
        # (правка Ивана 2026-09-15): подпись у самого числа, а не через весь лист.
        foot=[None, None, None, None, None, 'Всего', float(total)],
        money=(6, 7), center=(5,),
        widths=[5, 22, 48, 12, 8, 14, 16])
    return _xlsx_bytes(wb)


def _xlsx_bytes(wb):
    """Книга → bytes (в HTTP-ответ отдаём тело, файлов на диске не заводим)."""
    from io import BytesIO

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Листы выгрузки изделия = ВКЛАДКИ его формы (кроме «Файлов» — вложения в книгу не
# кладём). Порядок тот же, что на экране: состав → применение → склад → движения.
ITEM_XLSX_BOM = 'bom'          # «Только состав» — одна вкладка
ITEM_XLSX_ALL = 'all'          # «Все вкладки»


def item_xlsx(item, scope=ITEM_XLSX_BOM):
    """Сгенерировать xlsx-выгрузку изделия (bytes) — снимок его вкладок.

    Решение Ивана 2026-07-30. Файл повторяет ЭКРАН: колонки названы так же, как в
    табах формы, порядок листов — порядок вкладок. Два режима (пункты меню кнопки
    «Скачать»): `bom` — один лист «Состав»; `all` — все вкладки, кроме «Файлов».

    Лист «Состав» есть ВСЕГДА, даже у покупного компонента без BOM (у него и вкладки
    такой нет): пустой лист с заголовками честнее отказа скачать — человек видит, что
    состава нет, а не гадает, почему кнопка молчит. Он же первый — и потому несёт
    **шапку изделия** (код, описание, категория, единицы, оценка); остальные листы
    чистые таблицы, идентичность им даёт имя файла (= `code`).

    **Состав — один уровень**, ровно как на вкладке: разузлование до листьев — другой
    документ (сводная спецификация), и мешать их в одном файле нельзя.

    Синхронно в запросе, openpyxl — ленивым импортом (как `procurement_xlsx`).
    """
    from openpyxl import Workbook

    wb = Workbook()
    _xlsx_sheet(
        wb.active, 'Состав',
        head=[
            ('Код', item.code),
            ('Описание', item.description),
            ('Категория', item.category.code if item.category_id else ''),
            ('Единицы', item.uom),
            ('Оценка', float(item.estimated_cost)
                       if item.estimated_cost is not None else ''),
        ],
        headers=['№', 'Компонент', 'Описание', 'Кол-во', 'Ед.'],
        rows=[(bl.component.code, bl.component.description,
               float(bl.qty), bl.component.uom)
              for bl in item.bom_lines.select_related('component')],
        widths=[5, 22, 48, 12, 8])
    if scope != ITEM_XLSX_ALL:
        return _xlsx_bytes(wb)

    _xlsx_sheet(
        wb.create_sheet(), 'Применение',
        head=[],
        headers=['№', 'Изделие', 'Описание', 'Кол-во', 'Ед.'],
        # Кол-во — вхождение изделия в родителя, единица поэтому НАША (как в табе).
        rows=[(bl.parent.code, bl.parent.description, float(bl.qty), item.uom)
              for bl in item.used_in.select_related('parent')],
        widths=[5, 22, 48, 12, 8])
    item_lots = list(item.lots.select_related('project', 'origin'))
    live_by_lot = lots_live_qty(item_lots)
    _xlsx_sheet(
        wb.create_sheet(), 'Склад',
        head=[],
        headers=['№', 'Партия', 'Проект', 'Рожд.', 'Остаток', 'Ед.',
                 'Part number', 'Название'],
        # Остаток партии черновика — прочерк, а не 0 (Ф15: «едет, ещё не принято»).
        rows=[(f'#{lot.id}', lot.project.code, float(lot.qty),
               float(live_by_lot[lot.id]) if lot.origin.locked else '—',
               item.uom, lot.part_number, lot.lot_name)
              for lot in item_lots],
        widths=[5, 10, 16, 12, 12, 8, 22, 32])
    _xlsx_sheet(
        wb.create_sheet(), 'Движения',
        head=[],
        headers=['№', 'Ордер', 'Вид', 'Дата', 'Проект', 'Партия', 'Кол-во', 'Ед.'],
        rows=[(_movement_order_label(m), _movement_kind_label(m), _doc_date(m['date']),
               m['project_code'], _movement_lot_label(m), float(m['qty']), item.uom)
              for m in item_movements(item)],
        widths=[5, 22, 24, 12, 16, 28, 12, 8])
    return _xlsx_bytes(wb)


def _movement_order_label(m):
    """Ярлык ордера в ленте — тот же фолбэк, что на экране: код → номер → «Вид #id»."""
    return (m['code'] or m['number']
            or f'{models.DocumentKind(m["kind"]).label} #{m["document_id"]}')


def _movement_kind_label(m):
    """Вид ордера; у рождения партии — с пометкой (на экране она идёт подсказкой)."""
    label = models.DocumentKind(m['kind']).label
    return f'{label} · партия рождена' if m['event'] == 'born' else label


def _movement_lot_label(m):
    """Партия в ленте: `#id`, плюс имя из УПД, когда оно есть."""
    return f'#{m["lot_id"]} · {m["lot_name"]}' if m['lot_name'] else f'#{m["lot_id"]}'


# --------------------------------------------------------------------------- #
#  Волна 8 — pegging: нарезка плана (Procurement) на проектные заказы (Purchase)
# --------------------------------------------------------------------------- #
def _plan_allocations(procurement):
    """Разложенное под этой закупкой: `{(purchase_id, item_id): (qty, цена строки)}` —
    одним запросом.

    Ячейка распределения = строка заказа (`PurchaseLine`), пара `(purchase, item)`
    уникальна по схеме, поэтому ячейка ровно одна.
    """
    return {(pid, iid): (qty, price) for pid, iid, qty, price in (
        models.PurchaseLine.objects
        .filter(purchase__procurement=procurement)
        .values_list('purchase_id', 'item_id', 'qty', 'price'))}


def _allocation_status(planned, allocated):
    """Глиф строки плана: разложена ли она (правило Ивана 2026-08-05).

    Ровно в ноль → зелёный check. Не тронута (0) → красный warning. Перепег (разложено
    больше плана — движок его разрешает) → тоже красный: это расхождение, а не прогресс.
    Всё между → оранжевый warning: тронуто, но не подбито.
    """
    if allocated == 0:
        return 'to_order'
    if allocated == planned:
        return 'available'
    if allocated > planned:
        return 'to_order'
    return 'on_order'


def procurement_allocation(procurement):
    """Проекция таба «Строки» закупки: строка плана → её распределение по заказам.

    **Волна 24 — только чтение.** В закупке одно поле ввода — «сколько хотим»; сколько
    взял каждый заказ, правится в форме заказа, а заказ рождается из закупки кнопкой
    «Новый заказ» (остатком). Матрица с полями в ячейках (`set_allocation`, 2026-08-05)
    снята: форма, пиленная под нарезку, вышла сложной. Ячейка = `PurchaseLine`, пара
    `(purchase, item)` уникальна.

    Проект у закупки один, поэтому строка плана наконец несёт **честный баланс проекта**
    (до волны его нельзя было сложить через проекты охвата). Это тот же `_balance`, что в
    «Потребности» проекта: считает только зафиксированное и план зафиксированных закупок.

    `cost` есть на обоих уровнях — `qty × estimated_cost` того документа, чья строка.
    """
    allocations = _plan_allocations(procurement)
    orders = list(procurement.purchases.select_related('contractor').order_by('id'))
    project = procurement.project
    need_by_item, _incomplete = project_leaf_demand(project, BomIndex())
    need_by_item = {leaf.id: qty for leaf, qty in need_by_item.items()}
    supply = ProjectSupply(project)

    rows = []
    for line in procurement.lines.select_related('item', 'item__category').order_by('id'):
        cells = []
        allocated = ZERO
        for pu in orders:
            cell = allocations.get((pu.id, line.item_id))
            if cell is None:
                continue                       # в этот заказ позиция не входит
            qty, price = cell
            allocated += qty
            cells.append({
                'purchase_id': pu.id, 'purchase_code': pu.code or f'Заказ {pu.id}',
                'locked': pu.locked, **_contractor_view(pu.contractor),
                'qty': qty, 'price': price,
                # стоимость в заказе — его цена строки по счёту, пока её нет — оценка
                'cost': price if price is not None else line_cost(line.item, qty),
            })
        need = need_by_item.get(line.item_id, ZERO)
        bal = supply.balance(line.item, need)
        rows.append({
            'line_id': line.id, 'item_id': line.item_id,
            'item_code': line.item.code, 'item_description': line.item.description,
            'item_category': category_code(line.item),   # фильтр колонки
            'uom': line.item.uom, 'qty': line.qty,
            'allocated': allocated, 'remaining': line.qty - allocated,
            'status': _allocation_status(line.qty, allocated),
            # Баланс проекта по изделию + слагаемые (расшифровка под курсором).
            **{k: v for k, v in bal.items() if k != 'status'},
            'balance_status': bal['status'],
            'cost': line_cost(line.item, line.qty),
            'overpay_at': overpay_threshold(need),
            'cost_status': ('overpaid' if line.item.estimated_cost is not None
                            and is_overpaid(line.qty, need) else None),
            'orders': cells,
        })
    mark_costs(rows)                   # `cost_status` строк плана: overpaid > costly
    fan = [{
        'purchase_id': pu.id, 'purchase_code': pu.code or f'Заказ {pu.id}',
        'locked': pu.locked, **_contractor_view(pu.contractor),
        'lines': pu.lines.count(),
        'total': pu.lines.aggregate(s=Sum('qty'))['s'] or ZERO,
    } for pu in orders]
    return {
        'id': procurement.id, 'locked': procurement.locked,
        'rows': rows, 'fan': fan,
    }


# --------------------------------------------------------------------------- #
#  Волна 20 — контрагент: справочник + витрина двух сторон документооборота
# --------------------------------------------------------------------------- #
# `Counterparty` — единая внешняя сторона документооборота, и витрина устроена по её
# оси: **две стороны**, а не одна лента. Закупочная сторона (мы платим, к нам едет) —
# закупки → заказы → поставки; передачная (мы отдаём) — передачи заказчику. Стороны не
# взаимоисключающие: одно юрлицо законно и привозит нам, и принимает от нас.
#
# Каждая сторона отдаётся как **интеграл или `None`** (решение Ивана 2026-07-30):
# «ноль движений — стороны нет». Тот же приём, что `project_health` (внутренний склад
# → `None`, глиф нейтрален): пустоту решает ДВИЖОК, вью только не рисует панель.
#
# **Ролей-флагов не существует** (снесены 2026-07-30, Ф3): сторона — не свойство
# справочника, а факт документооборота. Два bool были декларацией о намерениях,
# которую человек поддерживал руками, тогда как правда всегда лежала в документах;
# хуже того, пикер по ним ФИЛЬТРОВАЛ и прятал нужную запись. Свежезаведённый
# контрагент честно показывает пустую форму (ни панелей, ни табов контура) — он
# заводится ровно тогда, когда ему собираются оформить заказ, и пустым не живёт.


def counterparty_sides(queryset):
    """Аннотировать контрагентов их сторонами ПО ФАКТАМ: `has_supply` / `has_shipment`.

    Заменила пару флагов-ролей: «поставщик» = у него что-то покупали (закупка-план,
    заказ или поставка), «заказчик» = ему что-то передавали. Один запрос на весь
    список (`Exists`, не счёт), потому что это ось СПИСКА режима — глиф строки
    (`fold-*`) и порядок в пикере («свои» для этого вида ордера — наверх).
    """
    receipts = models.StockDocument.objects.filter(
        contractor=OuterRef('pk'), kind=models.StockDocument.Kind.RECEIPT)
    transfers = models.StockDocument.objects.filter(
        contractor=OuterRef('pk'), kind=models.StockDocument.Kind.TRANSFER)
    return queryset.annotate(
        has_supply=(Exists(models.Purchase.objects.filter(contractor=OuterRef('pk')))
                    | Exists(receipts)),
        has_shipment=Exists(transfers))


def _qty_by_uom(pairs):
    """`[(uom, qty)]` → `[{uom, qty}]` со сложением внутри единицы (по алфавиту).

    Складывать штуки с метрами в одно число — ложь, поэтому «сколько привезли» это
    вектор по единицам, а не скаляр. Тот же приём, что в мете формы склада.
    """
    total = {}
    for uom, qty in pairs:
        total[uom] = total.get(uom, ZERO) + qty
    return [{'uom': uom, 'qty': total[uom]} for uom in sorted(total)]


def _counterparty_receipt_lots(counterparty):
    """Лоты, привезённые контрагентом: партии его **зафиксированных** поставок.

    Гейт `origin__locked=True` — та же граница, что у «потрачено» проекта
    (`_project_spent`, волна 19 Ф15): черновой УПД ещё не факт, и в интеграл он не
    идёт. Список поставок в табе при этом показывает и черновики — интеграл считает
    состоявшееся, таб показывает всё.
    """
    return (models.Lot.objects
            .filter(origin__kind=models.StockDocument.Kind.RECEIPT,
                    origin__contractor=counterparty, origin__locked=True)
            .select_related('item'))


def purchases_awaiting(purchases):
    """«Ждём» по набору ЗАФИКСИРОВАННЫХ заказов (волна 26): Σ по строкам `line_flow_money`
    — обязательства, ещё не закрытые УПД. Черновик — не обязательство, в сумму не входит.
    Тем же правилом считает «ждём» форма заказа, поэтому Σ форм = итог контрагента."""
    ids = [p.id for p in purchases if p.locked]
    if not ids:
        return ZERO
    received = _received_by(models.Lot.objects.filter(origin__purchase_id__in=ids))
    total = ZERO
    for pu, item_id, qty, price in models.PurchaseLine.objects.filter(
            purchase_id__in=ids).values_list('purchase_id', 'item_id', 'qty', 'price'):
        total += line_flow_money(price, qty, received.get((pu, item_id), ZERO))[1]
    return total


def _counterparty_supply(counterparty):
    """Интеграл закупочной стороны — «сколько у него куплено и что привёз».

    Два счёта контура (заказов / поставок; закупок у контрагента с волны 24 нет) +
    материальный итог
    (партий, штук по единицам, сумма). `open_purchases` — заказы, не закрытые
    поставками целиком (`purchase_coverage` ≠ ✓): единственное число панели, которое
    смотрит вперёд, а не назад. `None` — на этой стороне ни одного документа.
    """
    purchases = list(counterparty.purchases.all())
    receipts = models.Receipt.objects.filter(contractor=counterparty)
    receipt_count = receipts.count()
    if not (purchases or receipt_count):
        return None
    lots = list(_counterparty_receipt_lots(counterparty))
    return {
        'purchases': len(purchases),
        'open_purchases': sum(1 for status in purchases_coverage(purchases).values()
                              if status != 'available'),
        'receipts': receipt_count,
        # Расхождение «поставок 4, а привёз 0 партий» законно и требует объяснения:
        # черновые УПД считаются документами, но не фактом (Ф15). Отдаём их числом —
        # вью подписывает панель, вместо того чтобы пользователь читал это как баг.
        'draft_receipts': receipts.filter(locked=False).count(),
        'lots': len(lots),
        'qty_by_uom': _qty_by_uom((lot.item.uom, lot.qty) for lot in lots),
        'total': sum((lot.cost for lot in lots), ZERO),
        # Волна 26: ★ блока «Деньги» контрагента — обязательства, не закрытые УПД.
        'awaiting': purchases_awaiting(purchases),
    }


def _counterparty_shipment(counterparty):
    """Интеграл передачной стороны — «сколько ему отдано» (роль заказчика).

    Считается по строкам **зафиксированных** передач (тот же гейт Ф15, что у
    закупочной стороны). `qty` строки знаковая (− расход) → берём магнитуду; деньги —
    по цене лота-источника (единственная известная цена изделия: своей цены у передачи
    нет, документооборот с заказчиком живёт вне PLM). `None` — передач не было.
    """
    lines = list(models.StockLine.objects
                 .filter(document__kind=models.StockDocument.Kind.TRANSFER,
                         document__contractor=counterparty, document__locked=True)
                 .select_related('lot__item', 'document'))
    transfers = models.Transfer.objects.filter(contractor=counterparty)
    if not transfers.exists():
        return None
    return {
        'transfers': transfers.count(),
        'draft_transfers': transfers.filter(locked=False).count(),
        'lots': len({line.lot_id for line in lines}),
        'qty_by_uom': _qty_by_uom((line.lot.item.uom, -line.qty) for line in lines),
        'total': -sum(lines_values(lines).values(), ZERO),
    }


def _procurement_rows(queryset):
    """Строки ленты закупок-планов — таб «Закупки» ЛЮБОЙ формы, где эта лента нужна.

    Волна 21: функция берёт **queryset**, а не контрагента. У формы контрагента лента
    отвечает «у кого собираемся купить», у формы аккаунта — «что я планировал»; строка
    одна и та же, и второго словаря под тот же смысл заводить незачем.
    """
    rows = []
    for p in queryset.select_related('project').prefetch_related('lines').order_by('-id'):
        lines = list(p.lines.all())
        rows.append({
            'id': p.id, 'code': p.code, 'description': p.description,
            'date': p.date, 'locked': p.locked,
            'project_code': p.project.code,              # волна 24: закупка проектная
            'lines': len(lines), 'qty': sum((ln.qty for ln in lines), ZERO),
        })
    return rows


def _purchase_rows(queryset):
    """Строки ленты заказов — таб «Заказы» любой формы (контрагент, аккаунт).

    Закрытость строки красит тем же словарём ✓/●/▲, что список режима «Заказы»
    (`purchase_coverage`) — знак выбирает вью.
    """
    rows = []
    qs = list(queryset.select_related('procurement__project', 'contractor')
              .prefetch_related('lines__item').order_by('-id'))
    coverage = purchases_coverage(qs)
    for p in qs:
        lines = list(p.lines.all())
        money = purchase_money(lines)        # волна 24: сумма заказа — по счёту
        estimate, unestimated = money['estimate'], money['unestimated']
        rows.append({
            'id': p.id, 'code': p.code, 'description': p.description,
            'date': p.date, 'locked': p.locked,
            'project_code': p.project.code,
            # Обе стороны заказа сразу: в форме контрагента лента отвечает «в каком
            # проекте», в форме проекта — «у кого купили». Число одно и то же, меняется
            # только вопрос, поэтому обе колонки живут в строке, а какую показать —
            # решает вью ([[engine-view-seam]]).
            **_contractor_view(p.contractor),
            'lines': len(lines), 'qty': sum((ln.qty for ln in lines), ZERO),
            # Деньги заказа — по счёту (волна 24, `purchase_money`): Σ цен строк. Строки
            # без цены — кодами в `unestimated`, чтобы неполная сумма не выдавала себя
            # за полную.
            'estimate': estimate, 'unestimated': unestimated,
            'coverage': coverage[p.id],
        })
    return rows


def _receipt_rows(queryset):
    """Строки ленты поставок — таб «Поставки» любой формы (контрагент, проект).

    Берёт **queryset**, как `_purchase_rows`: у контрагента лента отвечает «что он
    привёз», у проекта — «что в проект приехало». Строка одна, и обе стороны (проект и
    поставщик) в ней есть — колонку выбирает вью.

    Деньги здесь — ФАКТ (`Lot.cost` из УПД), а не оценка: поставка тем и отличается
    от намерения, что цену уже знает.
    """
    rows = []
    qs = (queryset.select_related('project', 'contractor')
          .prefetch_related('lots__item').order_by('-id'))
    for r in qs:
        lots = list(r.lots.all())
        rows.append({
            'id': r.id, 'code': r.code, 'description': r.description,
            'number': r.number, 'date': r.date,
            'locked': r.locked, 'project_code': r.project.code,
            **_contractor_view(r.contractor),
            'purchase_id': r.purchase_id,
            'lots': len(lots),
            'total': sum((lot.cost for lot in lots), ZERO),
        })
    return rows


def _cp_transfer_rows(counterparty):
    """Таб «Передачи»: накладные, которыми ему отдавали (роль заказчика)."""
    rows = []
    qs = (models.Transfer.objects.filter(contractor=counterparty)
          .select_related('project').prefetch_related('lines__lot__item', 'lines__document')
          .order_by('-id'))
    for t in qs:
        lines = list(t.lines.all())
        rows.append({
            'id': t.id, 'code': t.code, 'number': t.number, 'date': t.date,
            'locked': t.locked, 'project_code': t.project.code,
            'lines': len(lines),
            'qty': sum((-ln.qty for ln in lines), ZERO),
            'total': -sum(lines_values(lines).values(), ZERO),
        })
    return rows


def counterparty_form(counterparty):
    """Проекция формы контрагента (волна 20): ДНК + два интеграла + четыре списка.

    Аккордеона «закупка → накладные» здесь нет (решение Ивана 2026-07-30, отмена
    формулировки семени): контрагент — не документ контура, а его сторона, и вложение
    уровней врало бы про путь. Заказ живёт без плана (Ф17), поставка — без заказа,
    поэтому уровни идут **тремя равными табами**, а связь «чем закрыто» остаётся там,
    где она однозначна — в форме заказа (Ф6).
    """
    return {
        'id': counterparty.id, 'code': counterparty.code,
        'description': counterparty.description, 'inn': counterparty.inn,
        # Стороны: интеграл или `None` («движений нет» решает движок, не вью). Отдельных
        # `has_*` здесь нет намеренно — «сторона есть» это и есть «интеграл не `None`»,
        # и два источника одной правды в одной проекции разошлись бы (Ф3).
        'supply': _counterparty_supply(counterparty),
        'shipment': _counterparty_shipment(counterparty),
        # Волна 24: закупок у контрагента нет — это внутреннее планирование; его лента —
        # обязательства (заказы) и движение (поставки, передачи).
        'purchases': _purchase_rows(counterparty.purchases),
        'receipts': _receipt_rows(models.Receipt.objects.filter(contractor=counterparty)),
        'transfers': _cp_transfer_rows(counterparty),
    }


def create_counterparty(code=None, description='', inn=''):
    """Завести контрагента. Пустой код — фолбэком «Контрагент 12» (Ф12e).

    Волна 19 (Ф10) оставила `code` контрагента без авто-фолбэка: заводили его только
    из пикера, где человек вводил имя. Волна 20 дала сущности форму, а форма рождается
    по клику (Ф12e) — титулу нужен код, и правило снова одно на всех.

    Роли при рождении больше нет (Ф3): контрагента заводят из пикера конкретного
    документа, и «кто он» этот документ и скажет — первым же фактом.
    """
    code = (code or '').strip() or None
    require_unique_code(models.Counterparty, code)
    fields = dict(description=(description or '').strip(), inn=(inn or '').strip())
    if code:
        return models.Counterparty.objects.create(code=code, **fields)
    return create_with_fallback_code(models.Counterparty, 'Контрагент', **fields)


def update_counterparty(counterparty, code=_UNSET, description=None, inn=None):
    """Правка ДНК контрагента под интерфейсным замком формы (волна 20).

    ДНК теперь ровно три поля — код, описание, ИНН (роль снесена, Ф3): всё остальное,
    что справочник «знает» о контрагенте, он знает из документов и правке не подлежит.

    `code` — часовой `_UNSET` (не прислали → не трогаем; пустой → NULL, как у
    документов: колонка nullable, и очистка кода не должна ловить IntegrityError).
    `description`/`inn` пустыми быть вправе (Ф12e: рождённое по клику незаполнено, и
    запрет очистки означал бы «заполнить можно, передумать нельзя»).
    """
    if code is not _UNSET:
        require_unique_code(models.Counterparty, code, counterparty.pk)
        counterparty.code = (code or '').strip() or None
    if description is not None:
        counterparty.description = description.strip()
    if inn is not None:
        counterparty.inn = inn.strip()
    counterparty.save()
    return counterparty


def delete_counterparty(counterparty):
    """Удалить контрагента (долг, приехавший вместе с формой; волна 20).

    До этой волны у контрагента не было пути удаления **вообще** — ни эндпойнта, ни
    функции движка, только админка. Друзья-guard'ы:
    — поставки/передачи (`StockDocument.contractor`, PROTECT) и заказы
      (`Purchase.contractor`, PROTECT) держат наглухо: документ без стороны не бывает;
    — вложения («карточка предприятия», Ф12b) сносим ЯВНО: каскад БД унёс бы строки и
      оставил файлы сиротами на диске (та же беда, что у `delete_project`).
    """
    if counterparty.documents.exists():
        raise ValidationError(
            'У контрагента есть поставки или передачи — удаление заблокировано.')
    if counterparty.purchases.exists():
        raise ValidationError('На контрагента оформлены заказы — удаление заблокировано.')
    for att in counterparty.attachments.all():   # физические файлы (каскад их сиротит)
        delete_attachment(att)
    try:
        counterparty.delete()
    except ProtectedError:
        raise ValidationError('Контрагент связан с документами — удаление заблокировано.')


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
def inventory_form(inventory):
    """Проекция формы инвентаризации: шапка акта + строки-лоты (`+RECEIPT`) + итог.

    Каждая строка — рождённый актом лот («найденная» партия): кол-во, живой остаток
    (просел ли под последующий расход), цена/название, зав.№ и провенанс
    (`predecessor` — из какого списанного лота ре-материализован). Чистая проекция.
    """
    lots = []
    total = ZERO
    inventory_lots = list(inventory.lots.select_related('item', 'predecessor__project')
                          .order_by('id'))
    live_by_lot = lots_live_qty(inventory_lots)
    consumed = _consumed_lot_ids(inventory_lots)
    for lot in inventory_lots:
        total += lot.cost
        pred = lot.predecessor
        lots.append({
            'id': lot.id, 'item_id': lot.item_id, 'item_code': lot.item.code,
            'item_description': lot.item.description, 'uom': lot.item.uom,
            'qty': lot.qty, 'live_qty': live_by_lot[lot.id],
            'cost': lot.cost, 'unit_cost': lot.unit_cost, 'lot_name': lot.lot_name,
            'part_number': lot.part_number,
            'predecessor_id': lot.predecessor_id,
            'predecessor_label': _lot_label(pred) if pred else '',
            'consumed': lot.id in consumed,
        })
    return {
        'id': inventory.id, **_author(inventory), 'number': inventory.number, 'date': inventory.date,
        'code': inventory.code, 'description': inventory.description,
        'project_id': inventory.project_id, 'project_code': inventory.project.code,
        'project_name': inventory.project.description, 'locked': inventory.locked,
        'total_cost': total, 'lots': lots,
    }


def create_inventory(project, user, number='', date=None):
    """Создать акт инвентаризации в проект-дом (куда рождаются найденные лоты).
    `description` (Ф10) заполняется в детальной форме под замком, не при создании."""
    return _born_order(models.Inventory, project, user, number, date)


def add_inventory_lot(inventory, item, qty, cost=None, lot_name='',
                      part_number='', predecessor=None):
    """Добавить строку акта: рождается «найденная» партия (`+RECEIPT`) в его проекте.

    `predecessor` (опц.) связывает найденный лот со списанным-источником
    (ре-материализация серого остатка — провенанс/генеалогия). Кол-во не клампим.
    `cost` — стоимость найденной партии; не задана — у потомка списанного это доля
    стоимости предшественника на найденное кол-во (волна 26), иначе ноль.
    """
    _require_unlocked(inventory)
    if qty is None or qty <= 0:
        raise ValidationError('Количество должно быть положительным.')
    if cost is not None and cost < 0:
        raise ValidationError('Стоимость не может быть отрицательной.')
    if cost is None:
        cost = (_share(predecessor.cost, predecessor.qty, qty)
                if predecessor is not None else ZERO)
    lot = models.Lot.objects.create(
        item=item, project=inventory.project, origin=inventory, qty=qty,
        cost=cost, lot_name=lot_name or '',
        part_number=part_number or '', predecessor=predecessor)
    rebuild_movements(lot)
    return lot


def update_inventory_lot(lot, qty=None, cost=None, lot_name=None,
                         part_number=None):
    """Автосейв строки акта (кол-во/стоимость/название/PN). Кол-во не клампим по
    расходу. Только черновик (замок). Правка количества без стоимости сохраняет цену
    штуки (стоимость масштабируется долей, волна 26)."""
    _require_unlocked(lot.origin)
    fields = []
    if qty is not None:
        if qty <= 0:
            raise ValidationError('Количество должно быть положительным.')
        if cost is None and qty != lot.qty:
            lot.cost = _share(lot.cost, lot.qty, qty)
            fields.append('cost')
        lot.qty = qty
        fields.append('qty')
    if cost is not None:
        if cost < 0:
            raise ValidationError('Стоимость не может быть отрицательной.')
        lot.cost = cost
        if 'cost' not in fields:
            fields.append('cost')
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
    _require_unlocked(lot.origin)
    if _lot_consumed_downstream(lot):
        raise ValidationError(
            'Найденная партия уже потреблена ниже — удаление заблокировано.')
    lot.movements.all().delete()
    lot.delete()


def lock_inventory(inventory):
    """Провести инвентаризацию (замок, форма read-only)."""
    return lock_document(inventory, inventory.lots,
                         'Нельзя провести пустой акт инвентаризации — добавьте строку.')


def unlock_inventory(inventory):
    """Снять замок инвентаризации — снова разрешить правку."""
    return unlock_document(inventory)


def update_inventory(inventory, **kw):
    """Шапка инвентаризации: № акта / дата / код / описание / автор / проект.

    Ф14: заодно приведена к общей дороге — своя рукописная обработка `code` (мимо
    `require_unique_code`, единственная такая среди шести) была недосмотром, а не
    решением; теперь код инвентаризации стережёт та же мягкая уникальность, что у
    остальных ордеров."""
    return update_document(inventory, **kw)


def written_off_lots():
    """Списанные лоты (серый путь) — кандидаты ре-материализации инвентаризацией.

    Списание — чистый `−ISSUE`: лот покинул учёт «в серый». Если серую партию нашли
    физически, инвентаризация возвращает её на баланс лотом-потомком (`predecessor` →
    списанный, наследование item/цены/названия/зав.№). Показываем суммарно списанное
    с лота (сколько «серого» доступно вернуть).

    Ф15: считаем только по **зафиксированным** актам — черновик списания это
    намерение, а не факт, и предлагать вернуть ещё не списанное значило бы делать
    склад из воздуха. Та же граница, что у остальных интегралов движка.
    """
    result = []
    wo = models.StockDocument.Kind.WRITEOFF
    for lot in (models.Lot.objects
                .filter(stock_lines__document__kind=wo,
                        stock_lines__document__locked=True).distinct()
                .select_related('item', 'project').order_by('project__code',
                                                            'item__code', 'id')):
        # qty знаковый (− расход) → магнитуда списанного = −Σ
        written = -(lot.stock_lines.filter(document__kind=wo, document__locked=True)
                    .aggregate(s=Sum('qty'))['s'] or ZERO)
        result.append({
            'lot_id': lot.id, 'item_id': lot.item_id,
            'item_code': lot.item.code, 'item_description': lot.item.description,
            'uom': lot.item.uom, 'written_qty': written,
            'project_code': lot.project.code, 'unit_cost': lot.unit_cost,
            'cost': lot.cost, 'qty': lot.qty,
            'lot_name': lot.lot_name, 'part_number': lot.part_number,
        })
    return result


# --------------------------------------------------------------------------- #
#  Справочники: создание изделий и проектов (канон «＋ Новая», 2026-07-03)
# --------------------------------------------------------------------------- #
def _resolve_category(category_id, native):
    """Категория изделия из справочника по PK (обязательна). Волна 15: `kind`-enum
    сменён FK-справочником `Category`. С 2026-10-15 — только своей стороны
    (`category.native == native`): чужая — дружелюбный отказ (страховка — `Item.clean`)."""
    if not category_id:
        raise ValidationError('Нужно выбрать категорию изделия.')
    try:
        category = models.Category.objects.get(pk=category_id)
    except (models.Category.DoesNotExist, ValueError, TypeError):
        raise ValidationError('Неизвестная категория изделия.')
    if category.native != bool(native):
        raise ValidationError(models.ITEM_CATEGORY_SIDE)
    return category


def item_is_used(item):
    """Изделие «используется» = есть хотя бы одна живая ссылка на него. Волна 15:
    заменяет снятое хранимое `active` вычисляемым признаком (спящий = 0 ссылок =
    кандидат на удаление). Зеркалит guard'ы `delete_item` (used ⇔ неудаляемо):
    вхождение в чужой BOM, лоты, строки заказа/закупки-плана, потребность проекта,
    цель комплектации. Дёшево — набор `Exists` с коротким замыканием на `or`."""
    return any(model.objects.filter(**{field: item}).exists()
               for model, field in _item_usage_refs())


def _item_usage_refs():
    """Живые ссылки на изделие `(модель, поле)` — одна опись для `item_is_used` и
    `used_item_ids`, чтобы поштучный и списочный признак не разошлись."""
    return ((models.BomLine, 'component'), (models.Lot, 'item'),
            (models.PurchaseLine, 'item'), (models.ProjectDemand, 'target_item'),
            (models.StockDocument, 'target_item'), (models.ProcurementLine, 'item'))


def used_item_ids():
    """Множество id изделий с живыми ссылками — `item_is_used` для всего справочника
    разом (запрос на вид ссылки, а не на изделие × вид)."""
    used = set()
    for model, field in _item_usage_refs():
        used.update(model.objects.exclude(**{f'{field}__isnull': True})
                    .values_list(f'{field}_id', flat=True).distinct())
    return used


def create_item(code=None, description='', category_id=None, uom='шт',
                native=False, estimated_cost=None, temperature=''):
    """Создать изделие справочника. `code` (заказной PN, канон библиотеки — колонка
    CSV «Design Item Id») уникален.

    Волна 19, Ф12e: рождается по клику «＋ Новое», поэтому пустым может быть всё —
    код добирается фолбэком «Изделие 12», описание остаётся пустым, категория
    остаётся `NULL` и требуется только к фиксации (`lock_item`). Ручное изделие
    рождается `synced=False` (руками, не из библиотеки)."""
    code = (code or '').strip()
    require_unique_code(models.Item, code)
    fields = dict(
        description=(description or '').strip(),
        category=_resolve_category(category_id, native) if category_id else None,
        uom=(uom or '').strip() or 'шт',
        temperature=(temperature or '').strip(),
        native=bool(native),
        estimated_cost=estimated_cost)
    if code:
        return models.Item.objects.create(code=code, **fields)
    return create_with_fallback_code(models.Item, 'Изделие', **fields)


def _require_item_unlocked(item):
    """Гейт фиксации (волна 17): мутации свойств/состава запрещены у зафиксированного
    изделия — сперва расфиксировать. Защищает библиотечные изделия от ручного
    дрейфа (библиотека = источник правды). Ловит и прямой запрос к API, не только
    UI. Синк библиотеки правит в обход (свои прямые ORM-операции)."""
    if item.locked:
        raise ValidationError(
            f'Изделие {item.code} зафиксировано — сперва расфиксируйте.')


def lock_item(item):
    """Зафиксировать изделие: форма становится read-only, мутации
    гейтятся. Идемпотентно.

    Ф12e: категория обязательна ЗДЕСЬ, а не при рождении (изделие заводится по
    клику пустым). Дружелюбный отказ до CHECK `item_locked_has_category` — тот
    остаётся страховкой от прямого ORM/админки."""
    if item.synced:
        # Ф5 (волна 23): фиксируется всё, кроме библиотечного — его защищает библиотека
        # (CHECK `item_synced_implies_not_locked`; здесь — человеческий отказ вместо 500).
        raise ValidationError('Библиотечный компонент не фиксируется — его защищает '
                              'библиотека: правится только цена.')
    if item.category_id is None:
        raise ValidationError('Перед фиксацией выберите категорию изделия.')
    if not item.locked:
        item.locked = True
        item.save(update_fields=['locked'])
    return item


def unlock_item(item):
    """Расфиксировать изделие: снова редактируемо. Идемпотентно.
    У библиотечного изделия следующий синк вернёт замок."""
    if item.locked:
        item.locked = False
        item.save(update_fields=['locked'])
    return item


def update_item(item, changes):
    """Правка свойств изделия под замком формы (§6). `changes` — только присланные
    поля (частичный PATCH). `code` уникален; категория из справочника
    (ключ `category_id`); описание непустое.

    Матрица `synced × locked` (Ф3a): зафиксированное (`locked`) — read-only целиком;
    библиотечное расфиксированное (`synced`) — правится ТОЛЬКО оценочная стоимость
    (остальные поля приходят из библиотеки, руками не трогаем); ручное расфиксированное
    — правится всё. `synced` руками не переключается (ставит только синк).

    Волна 23, Ф5 (решение Ивана): у ЗАФИКСИРОВАННОГО компонента (ручного — у
    библиотечного замка не бывает) цена остаётся правимой — синхронно с библиотечным:
    цена компонента живёт рынком, а не КД. Изделие (`native`) заперто целиком: его цена —
    роллап по составу («Переоценить»)."""
    if item.locked and (item.native or set(changes) - {'estimated_cost'}):
        _require_item_unlocked(item)
    if item.synced:
        illegal = set(changes) - {'estimated_cost'}
        if illegal:
            raise ValidationError(
                f'Изделие {item.code} — из библиотеки: правится только '
                f'оценочная стоимость (остальные поля берутся из библиотеки).')
    fields = []
    if 'code' in changes:
        v = (changes['code'] or '').strip()
        if not v:
            raise ValidationError('Нужен код изделия.')
        require_unique_code(models.Item, v, item.pk)
        item.code = v
        fields.append('code')
    if 'description' in changes:
        # Ф12e: пустое описание легально (см. `update_location`) — идентичность
        # держит `code`, а изделие рождается по клику незаполненным.
        item.description = (changes['description'] or '').strip()
        fields.append('description')
    if 'native' in changes:
        # Ось — раньше категории: категорию сверяем уже с новой стороной. Чужая
        # категория при смене оси СБРАСЫВАЕТСЯ (решение Ивана 2026-10-15: сброс
        # устойчив, черновику пустая законна, к фиксации выберут заново).
        item.native = bool(changes['native'])
        fields.append('native')
        if item.category_id and item.category.native != item.native:
            item.category = None
            fields.append('category')
    if 'category_id' in changes:
        # Пустая категория легальна в черновике; гейт — на фиксации (`lock_item`).
        item.category = (_resolve_category(changes['category_id'], item.native)
                         if changes['category_id'] else None)
        if 'category' not in fields:
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
    if fields:
        item.save(update_fields=fields)
    return item


def delete_item(item):
    """Удалить изделие из справочника (WAVE14 Ф2). Friendly-guard переводит `PROTECT`
    в человеческий отказ вместо 500: изделие держат партии, вхождение в чужой BOM,
    потребность проекта, строки заказа/закупки, цель комплектации. Свой состав (строки
    BOM, где изделие — parent) и вложения — каскад; файлы вложений сносим явно, иначе
    каскад БД осиротит их на диске (как в `delete_stock_document`).

    Гейт фиксации (волна 17): зафиксированное изделие руками не удаляют — сперва
    расфиксировать (UI прячет удаление у зафиксированного). Синк библиотеки удаляет
    ушедшие из библиотеки изделия в обход — расфиксирует их перед `delete_item`."""
    _require_item_unlocked(item)
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


# --------------------------------------------------------------------------- #
#  Синхронизация справочника с библиотекой компонентов Altium (волна 15)
# --------------------------------------------------------------------------- #
# Внешняя библиотека — источник правды по покупным изделиям. Форма грузит её
# CSV-таблицы (мульти-файл = вся библиотека за раз); движок парсит → диф против БД
# по ключу `code` → применение подтверждённых строк. Цену библиотека не
# хранит (`estimated_cost` — собственность Plume, синк её не трогает).
LIBRARY_ENCODING = 'cp1251'      # CP1251, разделитель ';' без экранирования, LF
LIBRARY_KEY_COL = 'Design Item Id'
LIBRARY_DESC_COL = 'Description'
LIBRARY_TEMP_COL = 'Temperature'


def parse_library_file(filename, raw):
    """Разобрать один CSV библиотеки → [row...]. `raw` — bytes (CP1251). Заголовок =
    эталон: нужные колонки ищем по имени (терпимо к порядку), отсутствие любой из трёх —
    ошибка. Строки нормализуем в `{code, description, temperature, category}`
    (категория — всегда `LIBRARY_CATEGORY`, имя файла классом больше не служит, решение
    2026-10-15); текст проходит гигиену (`clean_text`) молча — спросить тут некого.
    Дубль ключа в файле, пустой ключ или недобор колонок — человеческий отказ."""
    category = LIBRARY_CATEGORY[0]
    try:
        text = bytes(raw).decode(LIBRARY_ENCODING)
    except (UnicodeDecodeError, TypeError):
        raise ValidationError(f'{filename}: ожидалась кодировка CP1251.')
    reader = csv.reader(io.StringIO(text), delimiter=';')
    try:
        header = next(reader)
    except StopIteration:
        raise ValidationError(f'{filename}: пустой файл.')
    cols = {h.strip(): i for i, h in enumerate(header)}
    for col in (LIBRARY_KEY_COL, LIBRARY_DESC_COL, LIBRARY_TEMP_COL):
        if col not in cols:
            raise ValidationError(f'{filename}: нет колонки «{col}».')
    ki, di, ti = cols[LIBRARY_KEY_COL], cols[LIBRARY_DESC_COL], cols[LIBRARY_TEMP_COL]
    rows, seen = [], set()
    for lineno, rec in enumerate(reader, start=2):
        if not rec or all(not c.strip() for c in rec):
            continue                       # пустая строка (в т.ч. финальный LF)
        if len(rec) <= max(ki, di, ti):
            raise ValidationError(f'{filename}, строка {lineno}: мало колонок.')
        key = clean_text(rec[ki], code=True)
        if not key:
            raise ValidationError(f'{filename}, строка {lineno}: пустой Design Item Id.')
        if key in seen:
            raise ValidationError(f'{filename}: дубль Design Item Id «{key}».')
        seen.add(key)
        rows.append({'code': key, 'description': clean_text(rec[di]),
                     'temperature': clean_text(rec[ti]), 'category': category})
    return rows


def parse_library(files):
    """Разобрать мульти-файл загрузку. `files` — список `(filename, raw_bytes)`.
    Возвращает `{'rows': [row...]}`. Один файл дважды или один `code` в двух файлах —
    ошибка (в библиотеке ключ глобально уникален).

    Загрузка = **вся библиотека целиком** (решение Ивана 2026-10-15): «пропавшие»
    ищутся среди всех `synced`, а не в классах загруженных файлов — класса по имени
    файла больше нет. Частичная загрузка объявила бы остальное пропавшим."""
    if not files:
        raise ValidationError('Не выбрано ни одного файла.')
    names, rows, owner = set(), [], {}
    for filename, raw in files:
        if filename in names:
            raise ValidationError(f'Файл {filename} выбран дважды.')
        names.add(filename)
        for r in parse_library_file(filename, raw):
            key = r['code']
            if key in owner:
                raise ValidationError(
                    f'Design Item Id «{key}» есть в двух файлах ({owner[key]} и {filename}).')
            owner[key] = filename
            rows.append(r)
    return {'rows': rows}


# Порядок статусов в диф-вью: сперва требующие действия, потом флаги, потом «совпало».
_DIFF_ORDER = {'new': 0, 'changed': 1, 'mark': 2, 'gone': 3, 'orphan': 4, 'same': 5}


def _library_changes(item, row):
    """Что изменилось у существующего изделия против библиотеки: сравниваем только
    синкаемые поля (`description`/`category`/`temperature`). Категорию — по `code`
    (у синкаемого всегда `LIBRARY_CATEGORY`). `estimated_cost`/`uom`/`native` —
    собственность Plume, не сверяем."""
    changes = {}
    if item.description != row['description']:
        changes['description'] = {'old': item.description, 'new': row['description']}
    # Ф12e: у изделия-черновика категории может не быть — тогда это тоже
    # изменение («было пусто → станет `ЭК`»), а не падение.
    if category_code(item) != row['category']:
        changes['category'] = {'old': category_code(item), 'new': row['category']}
    if item.temperature != row['temperature']:
        changes['temperature'] = {'old': item.temperature, 'new': row['temperature']}
    return changes


def _diff_row(status, row, item, changes=None):
    out = {'status': status,
           'code': (row or {}).get('code') or item.code,
           'item_id': item.id if item else None}
    if row is not None:
        out['incoming'] = {'description': row['description'],
                           'temperature': row['temperature'], 'category': row['category']}
    if item is not None:
        out['current'] = {'description': item.description,
                          'temperature': item.temperature,
                          'category': category_code(item),
                          'native': item.native, 'synced': item.synced,
                          'locked': item.locked}
    if changes:
        out['changes'] = changes
    return out


def library_diff(parsed):
    """Полная сверка загруженной библиотеки против БД по ключу `code`.
    `parsed` — из `parse_library`. Возвращает список диф-строк со статусом:

    - `new`     — ключа нет в БД → создать (`native=false`, `synced=true`, `locked=false`);
    - `changed` — есть, отличается description/category/temperature → обновить
      (+ пометить `synced`, снять замок);
    - `mark`    — есть, содержимое совпадает, но ещё не помечено `synced` → пометить
      библиотечным (`synced=true`, замок снять). Путь бэкфилла после Ф3a: все
      существующие библиотечные приходят `synced=false` и помечаются первым же синком;
    - `same`    — есть, совпадает И уже `synced` → ничего;
    - `gone`    — библиотечное (`synced`) в БД, нет в загрузке, не используется →
      кандидат на удаление;
    - `orphan`  — то же, но используется (живые ссылки) → флаг «сирота, нет в
      библиотеке» (не действие: удалить нельзя, обновлять нечем).

    Замок синк снимает всюду, где метит `synced` — этого требует инвариант 0008
    (`synced ⟹ not locked`): библиотечное защищено матрицей «правь только цену», а
    не фиксацией, и стухший замок на нём был бы вторым, противоречащим словарём.
    (Раньше здесь стояло «`locked` не трогаем» — докстринг отстал от инварианта,
    аудит-1 Б1а-6.)

    «Пропавшие» — только среди библиотечных (`synced`): загрузка = вся библиотека
    (2026-10-15), ручное изделие библиотеке не принадлежит и пропасть из неё не может."""
    by_key = {r['code']: r for r in parsed['rows']}
    existing = {i.code: i
                for i in models.Item.objects.select_related('category')}
    result = []
    for key, row in by_key.items():
        item = existing.get(key)
        if item is None:
            result.append(_diff_row('new', row, None))
            continue
        changes = _library_changes(item, row)
        if changes:
            status = 'changed'
        elif not item.synced:
            status = 'mark'       # совпадает по содержимому, но ещё не помечено библиотечным
        else:
            status = 'same'
        result.append(_diff_row(status, row, item, changes))
    for key, item in existing.items():
        if key in by_key or not item.synced:
            continue
        result.append(_diff_row('orphan' if item_is_used(item) else 'gone', None, item))
    result.sort(key=lambda d: (_DIFF_ORDER[d['status']], d['code']))
    return result


def apply_library_diff(parsed, confirmed):
    """Применить подтверждённые строки дифа. `confirmed` — множество
    `code`, отмеченных галочкой. Диф пересчитываем здесь заново (не
    доверяем присланным клиентом значениям): действие берётся из свежего статуса,
    поля — из `parsed`. Всё в одной транзакции (bulk = всё-или-ничего).

    - `new`     → создать `Item` (`native=false`, `synced=true`, `locked=false`,
      категория `library_category`);
    - `changed` → обновить description/category/temperature (+ пометить `synced`,
      снять замок — инвариант 0008 `synced ⟹ not locked`);
    - `mark`    → пометить библиотечным (`synced=true`, замок снять);
    - `gone`    → удалить (`delete_item` — guard добьёт, если стало используемым);
    - `orphan`/`same` → no-op даже если ключ подтверждён.

    Возвращает сводку `{created, updated, marked, deleted}`."""
    confirmed = set(confirmed or [])
    by_key = {r['code']: r for r in parsed['rows']}
    summary = {'created': 0, 'updated': 0, 'marked': 0, 'deleted': 0}
    with transaction.atomic():
        for diff in library_diff(parsed):
            key = diff['code']
            if key not in confirmed:
                continue
            status = diff['status']
            if status == 'new':
                src = by_key[key]
                # Библиотека = источник правды → изделие рождается библиотечным
                # (`synced`), но НЕ запертым (`locked=false`) — готово под ввод цены
                # (Ф3a, решение Ивана 2026-07-24). Защита остального — матрицей `synced`.
                models.Item.objects.create(
                    code=key, description=src['description'],
                    category=library_category(),
                    temperature=src['temperature'], native=False,
                    synced=True, locked=False)
                summary['created'] += 1
            elif status == 'changed':
                src = by_key[key]
                item = models.Item.objects.get(code=key)
                item.description = src['description']
                item.category = library_category()
                item.temperature = src['temperature']
                # Синк подтверждает библиотечное происхождение → метим `synced` и
                # снимаем стухший замок (инвариант `synced ⟹ not locked`; библиотечное
                # защищено матрицей «правь только цену», а не фиксацией).
                item.synced = True
                item.locked = False
                item.save(update_fields=['description', 'category', 'temperature',
                                         'synced', 'locked'])
                summary['updated'] += 1
            elif status == 'mark':
                # Содержимое совпадает — метим библиотечным и снимаем стухший замок
                # (инвариант `synced ⟹ not locked`).
                item = models.Item.objects.get(code=key)
                item.synced = True
                item.locked = False
                item.save(update_fields=['synced', 'locked'])
                summary['marked'] += 1
            elif status == 'gone':
                item = models.Item.objects.get(code=key)
                unlock_item(item)          # расфиксировать перед удалением (гейт)
                delete_item(item)
                summary['deleted'] += 1
    return summary


# --------------------------------------------------------------------------- #
#  Роллап оценочной стоимости по BOM (волна 15)
# --------------------------------------------------------------------------- #
def _rollup_cost(item, cache, visiting, updated, incomplete, write=True):
    """Пост-order обход BOM: стоимость узла. Покупной лист → его `estimated_cost`
    (None → неполнота, вверх идёт как 0). Производимый узел → Σ(стоимость компонента
    × qty); результат пишем в `estimated_cost` ВСЕХ производимых узлов поддерева.
    `cache` мемоизирует общие поддеревья, `visiting` ловит циклы (страховка — их
    гасит уже `add_bom_line`). `write=False` — живой пересчёт без записи (волна 26:
    блок «Деньги» сравнивает его с сохранённой оценкой); `updated` тогда — узлы, чья
    сохранённая оценка разошлась с живой."""
    if item.id in cache:
        return cache[item.id]
    if not item.native:
        cost = item.estimated_cost
        if cost is None:
            incomplete.append(item.code)
        cache[item.id] = cost
        return cost
    if item.id in visiting:
        raise ValidationError(f'Цикл в составе: {item.code}.')
    visiting.add(item.id)
    lines = list(item.bom_lines.select_related('component'))
    if not lines:
        incomplete.append(item.code)   # производимый без состава — оценить нечем
    total = ZERO
    for bl in lines:
        c = _rollup_cost(bl.component, cache, visiting, updated, incomplete, write)
        total += (c if c is not None else ZERO) * bl.qty
    visiting.discard(item.id)
    if item.estimated_cost != total:
        if write:
            item.estimated_cost = total
            item.save(update_fields=['estimated_cost'])
        updated.append(item.code)
    cache[item.id] = total
    return total


def rollup_estimated_cost(item):
    """Пересчитать оценочную стоимость производимого изделия роллапом по BOM
    (рекурсивно до листьев). Пишет оценку во все производимые узлы поддерева, не
    только в вершину (сменили цену листа → обновились и промежуточные платы, и
    прибор). Возвращает `{estimated_cost, updated, incomplete}`: `updated` — какие
    узлы переоценены, `incomplete` — листья/узлы без известной стоимости (учтены
    как 0, но помечены). Только для `native` (у покупного оценка — ручная)."""
    if not item.native:
        raise ValidationError('Пересчёт стоимости — только для производимого изделия.')
    updated, incomplete = [], []
    with transaction.atomic():
        cost = _rollup_cost(item, {}, set(), updated, incomplete)
    return {'estimated_cost': cost, 'updated': updated, 'incomplete': incomplete}


# Расхождение оценки покупного с последней ценой, после которого блок «Деньги» изделия
# предупреждает и предлагает «Взять в оценку» (решение Ивана 2026-10-19: 10%).
ESTIMATE_DRIFT = Decimal('0.10')


def _price_facts(item):
    """Факты цены покупного изделия (волна 26): `[(дата, id-ключ, кол-во, деньги, док)]`.

    Два источника, оба — зафиксированный факт: строки ЗАФИКСИРОВАННЫХ заказов (цена строки
    по счёту, дата заказа — обязательна к фиксации) и партии ЗАФИКСИРОВАННЫХ поставок
    без заказа (стоимость по УПД, дата поставки). Поставка из заказа второй раз не
    считается — её цена уже в заказе (как у «потрачено»). **Нули пропускаем** (решение
    Ивана): образцы — исключения отношений с поставщиком, а не рынок."""
    facts = []
    for pl in (models.PurchaseLine.objects
               .filter(item=item, purchase__locked=True, price__gt=0, qty__gt=0)
               .select_related('purchase__contractor')):
        pu = pl.purchase
        facts.append((pu.date, ('purchase', pu.id), pl.qty, pl.price, {
            'kind': 'purchase', 'id': pu.id, 'code': pu.code, 'date': pu.date,
            **_contractor_view(pu.contractor)}))
    for lot in (models.Lot.objects
                .filter(item=item, origin__kind=models.DocumentKind.RECEIPT,
                        origin__locked=True, origin__purchase__isnull=True,
                        cost__gt=0, qty__gt=0)
                .select_related('origin__contractor')):
        r = lot.origin
        facts.append((r.date, ('receipt', lot.id), lot.qty, lot.cost, {
            'kind': 'receipt', 'id': r.id, 'code': r.code, 'date': r.date,
            **_contractor_view(r.contractor)}))
    return facts


def item_money(item):
    """Блок «Деньги» изделия (волна 26). Главное число — ФАКТ, где он есть.

    **Покупное:** ★ последняя цена по счёту (штука; последний по дате документа факт, без
    фолбэков — дата у зафиксированных заказа и поставки обязательна; при равных датах —
    позже заведённый), средняя (взвешенная по количеству: все деньги / все штуки),
    максимальная. Оценка разошлась с последней ценой больше `ESTIMATE_DRIFT` →
    `estimate_drift` (вью предупреждает и даёт «Взять в оценку»).

    **Производимое:** ★ живой роллап по составу (`_rollup_cost(write=False)`), рядом —
    позиции без цены и три самых дорогих компонента первого уровня по вкладу; живой
    роллап ≠ сохранённой оценке (до копейки — это арифметика) → `estimate_stale`.

    Обоим — **на складах на сумму**: Σ стоимостей движений всех партий изделия.
    """
    stock_value = (models.StockMovement.objects.filter(lot__item=item)
                   .aggregate(s=Sum('cost'))['s'] or ZERO)
    out = {'native': item.native, 'estimate': item.estimated_cost, 'stock_value': stock_value}
    if item.native:
        incomplete, stale = [], []
        cost = _rollup_cost(item, {}, set(), stale, incomplete, write=False)
        top = sorted((r for r in bom_line_costs(item) if r['cost']),
                     key=lambda r: -r['cost'])
        out.update({
            'rollup': cost, 'incomplete': incomplete, 'top': top[:3],
            'estimate_stale': item.estimated_cost != cost,
        })
        return out
    facts = _price_facts(item)
    if not facts:
        out.update({'last': None, 'avg': None, 'max': None, 'facts': 0,
                    'estimate_drift': None})
        return out
    date, _key, qty, money, doc = max(facts, key=lambda f: (f[0], f[1]))
    last = money / qty
    total_qty = sum((f[2] for f in facts), ZERO)
    drift = (_ratio(item.estimated_cost, last)
             if item.estimated_cost is not None else None)
    out.update({
        'last': last, 'last_doc': doc,
        'avg': sum((f[3] for f in facts), ZERO) / total_qty,
        'max': max(f[3] / f[2] for f in facts),
        'facts': len(facts),
        # Оценка против последней цены: `−0,23` = «оценка ниже на 23%». Сигнал — только
        # сверх порога; нет оценки — тоже сигнал (взять в оценку есть что).
        'estimate_drift': drift,
        'estimate_off': item.estimated_cost is None or abs(drift) > ESTIMATE_DRIFT,
    })
    return out


def _node_cost(component, qty, bom, cache):
    """Оценка `qty` штук компонента в составе: покупной без оценки — `None` (неизвестное ≠
    бесплатное), свой — живой роллап по индексу BOM (`_bom_unit_cost`)."""
    if not component.native and component.estimated_cost is None:
        return None
    return qty * _bom_unit_cost(component, bom, cache)


def _bom_subtree(component, qty, bom, cache, depth, visiting, out):
    """Поддерево своего компонента для аккордеона «Состава» (2026-10-20): pre-order с
    `depth`, кол-во — НАКОПЛЕННОЕ (штук на одно изделие формы), поэтому оценки детей в
    сумме дают оценку узла. Цикл — страховка `visiting` (его гасит `add_bom_line`)."""
    if component.id in visiting:
        return
    visiting.add(component.id)
    for bl in bom.children(component):
        c, n = bl.component, qty * bl.qty
        out.append({'component_id': c.id, 'component_code': c.code,
                    'component_description': c.description, 'uom': c.uom,
                    'component_native': c.native, 'component_synced': c.synced,
                    'component_locked': c.locked,
                    'qty': n, 'depth': depth, 'is_leaf': not c.native,
                    'cost': _node_cost(c, n, bom, cache)})
        if c.native:
            _bom_subtree(c, n, bom, cache, depth + 1, visiting, out)
    visiting.discard(component.id)


def bom_line_costs(item):
    """Оценка строк состава (2026-10-20, колонка «Оценка» таба «Состав»): `кол-во ×
    оценка компонента`, у своего компонента — живой роллап (то же число, что ★ блока
    «Деньги» и топ-3: одна функция). Без цены — `None` (неизвестное ≠ бесплатное).
    Подсветка — Парето (`mark_pareto`): строки, дающие первые 80% стоимости прибора.
    У своего компонента — `tree`: его поддерево для аккордеона (динамический Парето по
    фронту раскрытия считает вью). Индекс BOM — один на проекцию, без запроса на узел."""
    bom, cache, rows = BomIndex(), {}, []
    lines = list(item.bom_lines.select_related('component'))
    bom.preload(bl.component for bl in lines)
    for bl in lines:
        c = bl.component
        tree = []
        if c.native:
            _bom_subtree(c, bl.qty, bom, cache, 0, {item.id}, tree)
        rows.append({'id': bl.id, 'component_id': c.id, 'code': c.code, 'qty': bl.qty,
                     'cost': _node_cost(c, bl.qty, bom, cache), 'tree': tree})
    return mark_pareto(rows)


def adopt_last_price(item):
    """«Взять в оценку» (волна 26): оценка покупного ← последняя цена по счёту, до копейки.

    Оценка остаётся ручной (Иван перебивает её по КП), команда лишь освежает её в клик.
    Гейт — тот же, что у ручной правки оценки (`update_item`)."""
    if item.native:
        raise ValidationError('У изделия оценка — роллап по составу: «Переоценить».')
    money = item_money(item)
    if money['last'] is None:
        raise ValidationError('Цены по счёту ещё нет — брать в оценку нечего.')
    return update_item(item, {'estimated_cost': money['last'].quantize(
        KOPECK, rounding=ROUND_HALF_UP)})


def create_project(code=None, description='', budget=None, started=None):
    """Создать внешний проект (НИР/контракт). Код уникален; пустой — фолбэком
    «Проект 12» (Ф12e: сущность рождается по клику, а не из формы создания).

    Только `kind=external`: внутренние склады (WHITE/GREY) — синглтоны из сида
    (`Project.clean`), кнопкой «＋ Новый» не заводятся.
    """
    code = (code or '').strip()
    if code and models.Project.objects.filter(code=code).exists():
        raise ValidationError(f'Проект с кодом {code} уже есть.')
    fields = dict(description=(description or '').strip(),
                  kind=models.Project.Kind.EXTERNAL,
                  budget=budget, started=started or None)
    if code:
        return models.Project.objects.create(code=code, **fields)
    return create_with_fallback_code(models.Project, 'Проект', **fields)


def update_project(project, changes):
    """Правка реквизитов проекта под замком формы (§6): код, описание, бюджет, дата начала.
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
    if 'description' in changes:
        # Ф12e: пустое описание легально (см. `update_location`).
        project.description = (changes['description'] or '').strip()
        fields.append('description')
    if 'budget' in changes:
        project.budget = changes['budget']                 # Decimal или None (сброс)
        fields.append('budget')
    if 'started' in changes:
        project.started = changes['started'] or None
        fields.append('started')
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
    if project.procurements.exists():
        raise ValidationError('К проекту привязаны закупки — удаление заблокировано.')
    if project.demands.exists():
        raise ValidationError('В проекте есть потребности (приборы) — сперва уберите их.')
    for att in project.attachments.all():          # физические файлы (каскад их сиротит)
        delete_attachment(att)
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
    if project.locked:
        raise ValidationError('Проект закрыт — переоткройте, чтобы править потребность.')


def add_project_demand(project, item, qty):
    """Добавить прибор в потребность проекта. Пара (проект, изделие) уникальна."""
    _editable_project(project)
    if qty is None or qty <= ZERO:
        raise ValidationError('Кол-во приборов должно быть больше нуля.')
    if models.ProjectDemand.objects.filter(project=project, target_item=item).exists():
        raise ValidationError(f'Прибор {item.code} уже в потребности проекта.')
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


def add_bom_line(parent, component, qty):
    """Добавить компонент в состав изделия. Без самоссылки, циклов и дублей.
    Гейт фиксации: у зафиксированного изделия состав не правят (волна 17).

    Аудит-1 (Б1а-3): `position` (позиционное обозначение — C1, R12) снят. Поле
    приговорил ещё FIELD_MATRIX: год оно жило в схеме, движке и API, но форма
    изделия его не показывала — а состав приезжает из библиотеки Altium, где
    позиции живут в схемотехнике, а не в PLM. Хранить то, чего никто не вводит и
    не видит, — не «задел», а расхождение схемы и вью.
    """
    _require_item_unlocked(parent)
    if qty is None or qty <= ZERO:
        raise ValidationError('Кол-во должно быть больше нуля.')
    if component.id == parent.id:
        raise ValidationError('Изделие не может входить само в себя.')
    if models.BomLine.objects.filter(parent=parent, component=component).exists():
        raise ValidationError(f'Компонент {component.code} уже в составе.')
    if _bom_would_cycle(parent, component):
        raise ValidationError(f'Цикл в составе: {component.code} уже содержит {parent.code}.')
    return models.BomLine.objects.create(
        parent=parent, component=component, qty=qty)


def update_bom_line(line, qty=None):
    """Правка строки состава (кол-во, автосейв). Гейт фиксации у изделия-
    владельца (волна 17)."""
    _require_item_unlocked(line.parent)
    if qty is not None:
        if qty <= ZERO:
            raise ValidationError('Кол-во должно быть больше нуля.')
        line.qty = qty
        line.save(update_fields=['qty'])
    return line


def remove_bom_line(line):
    """Убрать строку из состава изделия. Гейт фиксации у изделия-владельца (волна 17)."""
    _require_item_unlocked(line.parent)
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
    # Волна 19, Ф12b: не-ордерные владельцы. Вид ордера остаётся именем в API
    # (`receipt`/`transfer`/…) и ложится в общее поле `document`; у этих —
    # своё поле, имя типа = имя поля.
    'project': models.Project, 'procurement': models.Procurement,
    'purchase': models.Purchase, 'counterparty': models.Counterparty,
}

# Имя типа в API → поле-владелец в `Attachment`. Совпадают у всех, кроме шести
# видов ордера: они схлопнуты в один FK `document` (волна 13, Ф2b).
_ATTACHMENT_OWNER_FIELD_BY_TYPE = {
    t: (t if t in models.ATTACHMENT_OWNER_FIELDS else 'document')
    for t in ATTACHMENT_OWNER_MODELS
}


def _attachment_owner_field(owner_type):
    """Поле-владелец под owner_type: 'project' → project; вид ордера → document."""
    return _ATTACHMENT_OWNER_FIELD_BY_TYPE[owner_type]


def resolve_attachment_owner(owner_type, owner_id):
    """Найти владельца по типу (имя из API) и id. Ошибка на неизвестный тип."""
    model = ATTACHMENT_OWNER_MODELS.get(owner_type)
    if model is None:
        raise ValidationError(f'Неизвестный тип владельца вложения: {owner_type}.')
    try:
        return model.objects.get(pk=owner_id)
    except model.DoesNotExist:
        raise ValidationError('Документ-владелец вложения не найден.')


# Файл на диске может разойтись с записью в БД — вручную удалили, перезалили мимо
# приложения, не доехал при переносе. Витрина показывает это ЦВЕТОМ глифа (волна 19,
# Ф12a): ok — совпадает, changed — на месте, но размер/время не те, missing — записи
# есть, файла нет. Допуск по времени: mtime записывается диском чуть позже, чем БД
# штампует `uploaded_at`.
_ATTACHMENT_MTIME_SLACK = timedelta(minutes=1)


def attachment_state(att):
    """Состояние файла на диске относительно записи в БД: ok | changed | missing."""
    try:
        path = att.file.path
        stat = os.stat(path)
    except (ValueError, OSError):
        return 'missing'
    if stat.st_size != att.size:
        return 'changed'
    if att.uploaded_at:
        touched = datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc)
        if touched > att.uploaded_at + _ATTACHMENT_MTIME_SLACK:
            return 'changed'
    return 'ok'


def attachment_row(att):
    """Проекция вложения для витрины (путь к файлу не отдаём — качаем эндпоинтом)."""
    return {
        'id': att.id, 'filename': att.filename or att.file.name,
        'size': att.size, 'content_type': att.content_type,
        'description': att.description, 'uploaded_at': att.uploaded_at,
        # Человеческое имя, а не логин: в списке «Загрузил» читают людей (Ф12a).
        # Тот же выбор, что у авторства документов (`_author`).
        'user': (att.user.get_full_name() or att.user.get_username()) if att.user_id else '',
        'state': attachment_state(att),
        'url': f'/api/attachments/{att.id}/download/',
    }


def attachments_for(owner_type, owner_id):
    """Список вложений владельца (свежие сверху)."""
    if owner_type not in ATTACHMENT_OWNER_MODELS:
        raise ValidationError(f'Неизвестный тип владельца вложения: {owner_type}.')
    field = _attachment_owner_field(owner_type)
    if field == 'document':
        # id ордеров глобально уникален (Ф2a) → document_id однозначен; фильтр по
        # kind сохраняет прежнюю строгость (несовпадение вида → пусто).
        flt = {'document_id': owner_id, 'document__kind': owner_type}
    else:
        flt = {f'{field}_id': owner_id}
    qs = (models.Attachment.objects.filter(**flt)
          .select_related('user').order_by('-id'))
    return [attachment_row(a) for a in qs]


def _fit(value, field_name):
    """Подрезать служебную строку вложения под длину её поля (лимит берём у модели)."""
    limit = models.Attachment._meta.get_field(field_name).max_length
    return (value or '')[:limit]


def add_attachment(owner_type, owner, upload, user, description=''):
    """Прикрепить файл к владельцу: файл на диск, метаданные из upload (не с клиента).

    filename/size/content_type заполняет сервер из загруженного файла. Владелец
    ровно один (exclusive arc item↔document) — поле задаётся по owner_type. Синхронно.

    Служебные строки (имя, MIME) приходят от браузера и подрезаются по длине поля:
    метаданные описывают файл, а не решают, приняли его или нет — длинный MIME не
    повод отказать в загрузке (грабля xlsx, 65 символов против прежних 64).
    """
    if owner_type not in ATTACHMENT_OWNER_MODELS:
        raise ValidationError(f'Неизвестный тип владельца вложения: {owner_type}.')
    if upload is None:
        raise ValidationError('Нужен файл вложения.')
    limit = settings.MAX_ATTACHMENT_SIZE
    if upload.size and upload.size > limit:
        raise ValidationError(f'Файл больше лимита ({limit // (1024 * 1024)} МБ).')
    att = models.Attachment(
        file=upload,
        filename=_fit(upload.name, 'filename'), size=upload.size or 0,
        content_type=_fit(getattr(upload, 'content_type', ''), 'content_type'),
        description=(description or '').strip(), user=user,
        **{_attachment_owner_field(owner_type): owner})
    att.full_clean(exclude=['file'])   # exclusive-arc + длины полей (file уже валиден)
    att.save()
    return att


def update_attachment(att, description=None):
    """Правка описания вложения. Метаданные файла неизменны."""
    if description is not None:
        att.description = (description or '').strip()
        att.save(update_fields=['description'])
    return att


def delete_attachment(att):
    """Удалить вложение: строку в БД и физический файл с диска."""
    att.file.delete(save=False)
    att.delete()


# --------------------------------------------------------------------------- #
#  Аккаунт: форма пользователя + тема интерфейса (волна 21)
# --------------------------------------------------------------------------- #
# Пользователь становится сущностью со своей каноничной формой. Три вещи, которые
# здесь важнее кода:
#
# 1. **Фиксации у пользователя нет.** `locked` в продукте значит «документ стал фактом,
#    движок дальше не даст его менять». Человек не документ — он не рождает факта,
#    который движок считает, и замораживать нечего. Остаётся личный замок ФОРМЫ
#    (интерфейсный, живёт во вью). Прецедент — контрагент (волна 20).
# 2. **Титул формы = `username`, и полем он не рисуется.** Пара `code`+`description`
#    не нарушена, а расщеплена по ДНК Django: идентичность — `username`, литературное
#    имя — `first_name`+`last_name` (`get_full_name` склеивает обратно). `username`
#    задаётся админкой, значит степенью свободы формы не является — и полем не бывает
#    (тот же приём, что снял `Item.native`).
# 3. **Про темы движок знает ровно слаг и список допустимых** (`models.THEMES`). Ярлык
#    («Тёмная»), палитра, набор CSS-файлов — знание ВЬЮ: `core/theme.ts` +
#    `themes/registry.ts`. Движок не знает даже, какая из тем светлая.


def profile_of(user):
    """Приставка настроек пользователя (`UserProfile`), рождаемая ЛЕНИВО.

    Сигнала на `post_save` пользователя намеренно нет: сигнал — магия на расстоянии
    ради экономии одной строки, и он ломает `loaddata` (снимки прода). Единственный
    вход к профилю — эта функция, поэтому «профиля ещё нет» состоянием продукта не
    является: первый же запрос его создаёт.
    """
    profile, _ = models.UserProfile.objects.get_or_create(user=user)
    return profile


def _document_rows(queryset):
    """Строки ленты ордеров — СМЕШАННЫЙ фид семи видов с колонкой типа.

    Один таб, а не семь (как список режима «Ордера»): вид ордера здесь колонка, а не
    раздел. Счётчиков в строке нет намеренно — общей меры у семи видов не существует
    (у поставки объём это партии, у передачи — строки), а счёт, который человеку нужен
    («сколько всего»), живёт в мете формы.
    """
    return [{
        'id': d.id, 'kind': d.kind, 'code': d.code, 'number': d.number,
        'description': d.description, 'date': d.date, 'locked': d.locked,
        'project_code': d.project.code,
    } for d in queryset.select_related('project').order_by('-id')]


def user_form(user):
    """Проекция формы аккаунта: ДНК Django + тема + три ленты «своих» документов.

    Ленты — теми же строками, что отдаёт форма контрагента (`_procurement_rows` /
    `_purchase_rows` берут queryset именно для этого). «Своих» — буквально: реверс
    `user.procurements` / `user.purchases` / `user.documents`, то есть авторство, а не
    права. Модели «кто чьи документы видит» в продукте нет и не нужно.

    Списка допустимых тем здесь нет: дропдаун наполняет `themes/registry.ts` (ярлыки —
    знание вью), а движок стережёт слаг в `set_theme`. Два источника одного словаря
    разошлись бы.
    """
    return {
        # ДНК Django. `username` идёт в титул формы и полем не рисуется (см. шапку).
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'full_name': user.get_full_name() or user.username,
        # Приставка: тема и телефон (обе — свойства ЧЕЛОВЕКА, а не ДНК Django).
        'theme': profile_of(user).theme,
        'phone': profile_of(user).phone,
        'procurements': _procurement_rows(user.procurements),
        'purchases': _purchase_rows(user.purchases),
        'documents': _document_rows(user.documents),
    }


def update_user(user, first_name=None, last_name=None, email=None):
    """Правка ДНК пользователя (имя / фамилия / почта) — под замком формы.

    Пустые значения законны (Django своё пустое имя и почту допускает), поэтому
    часового `_UNSET` здесь нет: `None` = «ключа в PATCH не было», пустая строка =
    «очистили», и запрет очистки означал бы «заполнить можно, передумать нельзя».
    """
    if first_name is not None:
        user.first_name = first_name.strip()
    if last_name is not None:
        user.last_name = last_name.strip()
    if email is not None:
        email = email.strip()
        if email:
            EmailValidator(message='Почта задана неверно.')(email)
        user.email = email
    user.save()
    return user


def set_theme(user, slug):
    """Единственный вход к теме интерфейса. Неизвестный слаг — отказ.

    Валидация живёт ЗДЕСЬ, а не `CheckConstraint`'ом в БД (единственное осознанное
    исключение из привычки продукта стеречь `choices` схемой): тема — это набор файлов
    вью, и требовать под новую тему миграцию значило бы вписать вью в схему.
    """
    slug = (slug or '').strip()
    if slug not in models.THEMES:
        raise ValidationError(f'Неизвестная тема интерфейса: «{slug}».')
    profile = profile_of(user)
    profile.theme = slug
    profile.save(update_fields=['theme'])
    return profile


# Российский номер: 11 цифр с ведущей 7/8 либо 10 цифр без кода страны. Другого
# формата продукт не принимает (решение Ивана 2026-08-10): телефон едет в бланк
# ПОСТАВЩИКУ, и «ровный вид наружу» дороже, чем возможность записать что угодно.
_PHONE_DIGITS = 10


def normalize_phone(raw):
    """Любой ввод → «+7 985 963 42 31» (или `''`, если стёрли).

    Один вид у одного факта: то, что лежит в колонке, — ровно то, что человек видит в
    форме и получатель видит в бланке. Поэтому нормализуем НА ВВОДЕ, а не на каждой
    выдаче. Разделители, скобки, `8` вместо `+7`, пробелы вразнобой — всё это способы
    записать один и тот же номер, и спорить с человеком о них незачем.

    Не сводится к российскому номеру (иностранный, внутренний короткий, опечатка) —
    отказ с человеческим текстом, как у почты: молча сохранить «как ввели» значит
    пустить в документ наружу что угодно.
    """
    raw = (raw or '').strip()
    if not raw:
        return ''
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if len(digits) == 11 and digits[0] in '78':
        digits = digits[1:]
    if len(digits) != _PHONE_DIGITS:
        raise ValidationError('Телефон задан неверно — нужен российский номер, '
                              'например +7 985 963 42 31.')
    return f'+7 {digits[:3]} {digits[3:6]} {digits[6:8]} {digits[8:]}'


def set_phone(user, raw):
    """Единственный вход к телефону — как `set_theme` к теме.

    Телефон живёт в приставке (`UserProfile`), а не в ДНК Django, поэтому и правится
    отдельно от `update_user`: разные таблицы — разные входы.
    """
    profile = profile_of(user)
    profile.phone = normalize_phone(raw)
    profile.save(update_fields=['phone'])
    return profile


def change_password(user, current, new, repeat):
    """Смена пароля: текущий → повтор → штатные валидаторы Django → запись.

    Своих правил стойкости не изобретаем — `AUTH_PASSWORD_VALIDATORS` уже настроены и
    те же, что у админки. Порядок проверок = порядок, в котором человек ошибается.
    Сессию после смены пароля поддерживает вьюха (`update_session_auth_hash`): это
    знание про HTTP-сессию, а не про пользователя.
    """
    if not user.check_password(current or ''):
        raise ValidationError('Текущий пароль неверен.')
    if not new:
        raise ValidationError('Новый пароль пуст.')
    if new != repeat:
        raise ValidationError('Новый пароль и повтор не совпадают.')
    validate_password(new, user)
    user.set_password(new)
    user.save(update_fields=['password'])
    return user


# --------------------------------------------------------------------------- #
#  Предпросмотр фиксации (волна 23, Ф1) — «осознанная шероховатость»
# --------------------------------------------------------------------------- #
# Фиксация — самое весомое действие формы, и решение Ивана — сделать его ощутимым:
# перед «Зафиксировать» / «Расфиксировать» окно говорит, к чему это приведёт, ЖИВЫМИ
# числами («41 позиция на 359 364 ₽ начнёт считаться в „Заказано“ ЛК-1»). Последствия —
# смысл, поэтому живут здесь; вью только рисует окно. Отказ (`refusal`) не
# пересказываем, а получаем честно: настоящая фиксация в транзакции с откатом — та же
# проверка, что у кнопки, без второй копии гейтов.

class _DryRun(Exception):
    """Откат пробной фиксации в `fixation_preview`."""


def _plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _count(n, one, few, many):
    return f'{n} {_plural(n, one, few, many)}'


def _agree(n, one, many):
    """Глагол при числительном: «41 позиция начнёт», «42/89 позиций начнут»."""
    n = abs(int(n))
    return one if n % 10 == 1 and n % 100 != 11 else many


def _rub(value):
    """Рубли для текста окна: разряды узким пробелом, копейки — только если есть."""
    value = Decimal(value or 0)
    text = f'{value:,.2f}' if value != value.to_integral() else f'{value:,.0f}'
    return text.replace(',', ' ').replace('.', ',') + ' ₽'


def _qty(value):
    value = Decimal(value or 0).normalize()
    return format(value, 'f').replace('.', ',')


def _estimate(lines):
    """Оценка строк `(item, qty)`: сумма по `estimated_cost` + число позиций без оценки."""
    total, missing = ZERO, 0
    for item, qty in lines:
        if item.estimated_cost is None:
            missing += 1
        else:
            total += qty * item.estimated_cost
    return total, missing


def _estimate_lines(n, total, missing, verb_phrase, basis='оценка'):
    """«41 позиция на 359 364 ₽ (оценка) …» + предупреждение о позициях без оценки.
    `verb_phrase` — `(при одной, при многих)`: глагол согласуется с числом позиций.
    `basis` — откуда сумма: «оценка» или «по счёту» (заказ с ценами строк, волна 24)."""
    head = _count(n, 'позиция', 'позиции', 'позиций') + (
        f' на {_rub(total)} ({basis})' if total or basis == 'по счёту' else ' без оценки')
    verb_phrase = _agree(n, *verb_phrase)
    out = [{'text': f'{head} {verb_phrase}'}]
    if missing and total:
        out.append({'text': f'у {_count(missing, "позиции", "позиций", "позиций")} нет '
                            f'оценки — в сумму они не вошли', 'warn': True})
    return out


def _lots_word(n):
    return _count(n, 'партия', 'партии', 'партий')


def _lots_cost(lots):
    return sum((lot.cost for lot in lots), ZERO)


def _doc_lines_lots(doc):
    """Строки расхода документа (`qty < 0`) → (число партий, сумма шт.)."""
    lines = [sl for sl in doc.lines.all() if sl.qty < 0]
    return len({sl.lot_id for sl in lines}), sum((-sl.qty for sl in lines), ZERO)


def _consequences(entity, obj, lock):
    """Строки последствий по виду. `lock` — фиксация (True) / расфиксация (False)."""
    if entity == 'purchases':
        plines = list(obj.lines.select_related('item'))
        lines = [(pl.item, pl.qty) for pl in plines]
        # Волна 24: заказ с ценами строк называет сумму ПО СЧЁТУ; без них — оценку.
        priced = bool(plines) and all(pl.price is not None for pl in plines)
        if priced:
            total, missing = sum((pl.price for pl in plines), ZERO), 0
        else:
            total, missing = _estimate(lines)
        p = obj.project.code
        out = _estimate_lines(
            len(lines), total, missing, basis='по счёту' if priced else 'оценка',
            verb_phrase=
            (f'станет обязательством проекта {p} — в «Потребности» позиция зеленеет',
             f'станут обязательством проекта {p} — в «Потребности» позиции зеленеют')
            if lock else
            (f'перестанет быть обязательством проекта {p}',
             f'перестанут быть обязательством проекта {p}'))
        receipts = models.StockDocument.objects.filter(purchase=obj).count()
        if not lock and receipts:
            out.append({'text': f'привязанные поставки ({receipts}) останутся привязанными'})
        return out
    if entity == 'procurements':
        lines = [(pl.item, pl.qty) for pl in obj.lines.select_related('item')]
        total, missing = _estimate(lines)
        p = obj.project.code
        # Волна 24: фиксация закупки ставит позиции «в план» проекта — они входят в
        # «Заказ» его «Потребности» оранжевыми, пока заказы не возьмут их обязательством.
        return _estimate_lines(len(lines), total, missing,
                               (f'встанет в план проекта {p} — оранжевой в «Заказе»',
                                f'встанут в план проекта {p} — оранжевыми в «Заказе»')
                               if lock else
                               (f'выйдет из плана проекта {p}',
                                f'выйдут из плана проекта {p}'))
    if entity == 'items':
        # На склад и балансы фиксация изделия не влияет — последствие у неё одно, и
        # оно же последняя строка (`_editability`), поэтому здесь пусто.
        return []
    if entity == 'projects':
        if lock:
            return [{'text': f'проект {obj.code} станет архивным — веха «работа завершена»'},
                    {'text': 'остатков нет: все партии проекта сведены в 0'}]
        return [{'text': f'проект {obj.code} снова станет активным'}]

    # Складские ордера: фиксация двигает склад (Ф15), расфиксация — откатывает.
    # Глагол везде согласуется с числом партий: «1 партия уйдёт», «3 партии уйдут».
    project = obj.project.code if obj.project_id else '—'
    if entity in ('receipts', 'inventories'):
        lots = list(obj.lots.all())
        n, cost = len(lots), _lots_cost(lots)
        head = (_count(n, 'найденная партия', 'найденные партии', 'найденных партий')
                if entity == 'inventories' else _lots_word(n))
        if cost:
            head += f' на {_rub(cost)}' + (' (по УПД)' if entity == 'receipts' else '')
        out = [{'text': f'{head} ' + (f'{_agree(n, "ляжет", "лягут")} на склад проекта {project}'
                                      if lock else
                                      f'{_agree(n, "уйдёт", "уйдут")} со склада проекта {project}')}]
        if entity == 'receipts' and obj.purchase_id:
            out.append({'text': f'строки заказа «{obj.purchase.code}» '
                                + ('будут закрыты поставкой' if lock
                                   else 'снова станут ожидаемыми')})
        if not lock:
            used = len(_consumed_lot_ids(lots))
            if used:
                out.append({'text': f'{_lots_word(used)} уже '
                                    f'{_agree(used, "израсходована", "израсходованы")} в '
                                    f'других документах — {_agree(used, "её", "их")} остаток '
                                    f'уйдёт в минус', 'warn': True})
        return out
    if entity == 'kittings':
        target = obj.target_item.code if obj.target_item_id else '—'
        n, _ = _doc_lines_lots(obj)
        n_items = len({sl.lot.item_id for sl in obj.lines.select_related('lot') if sl.qty < 0})
        if lock:
            return [{'text': f'родится партия-прибор {target} × {_qty(obj.qty)} в проекте '
                             f'{project}, себестоимость {_rub(kitting_cost(obj))}'},
                    {'text': f'со склада {_agree(n, "спишется", "спишутся")} {_lots_word(n)} '
                             f'компонентов ({_count(n_items, "позиция", "позиции", "позиций")})'}]
        return [{'text': f'партия-прибор {target} × {_qty(obj.qty)} будет удалена'},
                {'text': f'{_lots_word(n)} компонентов {_agree(n, "вернётся", "вернутся")} '
                         f'на склад'}]
    if entity in ('transfers', 'writeoffs'):
        n, units = _doc_lines_lots(obj)
        head = f'{_lots_word(n)} ({_qty(units)} шт.)'
        if not lock:
            return [{'text': f'{head} {_agree(n, "вернётся", "вернутся")} на склад проекта {project}'}]
        if entity == 'transfers':
            to = obj.contractor.description if obj.contractor_id else 'заказчику'
            return [{'text': f'{head} {_agree(n, "уйдёт", "уйдут")} со склада проекта '
                             f'{project} → {to}'}]
        return [{'text': f'{head} {_agree(n, "будет списана", "будут списаны")} со склада '
                         f'проекта {project}'}]
    if entity == 'requisitions':
        lines = [sl for sl in obj.lines.select_related('lot__project') if sl.qty < 0]
        sources = ', '.join(sorted({sl.lot.project.code for sl in lines})) or '—'
        n = len({sl.lot_id for sl in lines})
        return [{'text': f'{_lots_word(n)} {_agree(n, "перейдёт", "перейдут")}: {sources} → {project}'
                 if lock else
                 f'{_lots_word(n)} {_agree(n, "вернётся", "вернутся")}: {project} → {sources}'}]
    if entity == 'relocations':
        lines = list(obj.lines.select_related('location'))
        src = ', '.join(sorted({sl.location.code for sl in lines if sl.qty < 0})) or '—'
        dst = ', '.join(sorted({sl.location.code for sl in lines if sl.qty > 0})) or '—'
        n = len({sl.lot_id for sl in lines})
        return [{'text': f'{_lots_word(n)} {_agree(n, "переедет", "переедут")}: {src} → {dst}'
                 if lock else
                 f'{_lots_word(n)} {_agree(n, "вернётся", "вернутся")}: {dst} → {src}'}]
    return []


# Вид → (модель, винительный падеж) — заголовок окна. Ключ = сегмент URL
# сущности (`purchases/12/lock/`), тот же, по которому вью находит объект.
FIXATION_KINDS = {
    'items': (models.Item, 'изделие'),
    'projects': (models.Project, 'проект'),
    'purchases': (models.Purchase, 'заказ'),
    'procurements': (models.Procurement, 'закупку'),
    'receipts': (models.Receipt, 'поставку'),
    'kittings': (models.Kitting, 'комплектацию'),
    'transfers': (models.Transfer, 'передачу'),
    'writeoffs': (models.Writeoff, 'списание'),
    'requisitions': (models.Requisition, 'требование'),
    'inventories': (models.Inventory, 'инвентаризацию'),
    'relocations': (models.Relocation, 'перемещение'),
}


def _fixation_fns():
    return {
        'items': (lock_item, unlock_item), 'projects': (lock_project, unlock_project),
        'purchases': (lock_purchase, unlock_purchase),
        'procurements': (lock_procurement, unlock_procurement),
        'receipts': (lock_receipt, unlock_receipt), 'kittings': (lock_kitting, unlock_kitting),
        'transfers': (lock_transfer, unlock_transfer),
        'writeoffs': (lock_writeoff, unlock_writeoff),
        'requisitions': (lock_requisition, unlock_requisition),
        'inventories': (lock_inventory, unlock_inventory),
        'relocations': (lock_relocation, unlock_relocation),
    }


def _editability(entity, obj, lock):
    """Последняя строка окна — что станет с правкой формы. Расфиксация называет и
    кнопку (вариант Ивана): после неё форма остаётся в просмотре, правку открывает
    «Редактировать» — отдельным решением (UI_GUIDE §5)."""
    what = ('строки и шапка', 'строки и шапку')            # им. / вин. падеж
    if entity == 'items':
        n = obj.bom_lines.count()
        bom = f'состав ({_count(n, "строка", "строки", "строк")}) и свойства'
        what = (bom, bom) if n else ('свойства', 'свойства')
    if lock:
        if entity == 'items' and not obj.native:
            return {'text': f'{what[0]} станут только для чтения — кроме цены'}
        return {'text': f'{what[0]} станут только для чтения'}
    return {'text': f'{what[1]} снова можно будет редактировать — кнопкой «Редактировать»'}


def fixation_preview(entity, pk, lock):
    """Окно перед фиксацией (`lock=True`) / расфиксацией: `{title, verb, lines,
    refusal}`. `lines` — `[{text, warn?}]`, последней всегда строка про правимость
    (решение Ивана: «для человека, который знает, как оно работает», но оставить —
    удалить потом легко). `refusal` — текст отказа движка или `None`."""
    model, accusative = FIXATION_KINDS[entity]
    obj = model.objects.get(pk=pk)
    code = getattr(obj, 'code', '') or f'#{obj.pk}'
    verb = 'Зафиксировать' if lock else 'Расфиксировать'
    refusal = None
    try:
        with transaction.atomic():
            fn = _fixation_fns()[entity][0 if lock else 1]
            fn(model.objects.get(pk=pk))       # свежая копия: пробный прогон её портит
            raise _DryRun
    except _DryRun:
        pass
    except ValidationError as e:
        refusal = e.messages[0] if e.messages else str(e)
    # При отказе последствий не перечисляем: их не будет, а строка вроде «остатков нет»
    # рядом с отказом «есть остатки» соврала бы.
    lines = [] if refusal else _consequences(entity, obj, lock) + [_editability(entity, obj, lock)]
    return {'title': f'{verb} {accusative} «{code}»?', 'verb': verb,
            'lines': lines, 'refusal': refusal}
