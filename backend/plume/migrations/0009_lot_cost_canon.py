# Волна 26, Ф0 — учётный канон партии «стоимость + количество, последний забирает
# остаток» (решение Ивана 2026-10-19, сверено с SAP/Odoo/1С: первична сумма, цена —
# производная) и обязательная дата зафиксированного заказа.
#
# 1. Заказы, зафиксированные без даты, расфиксируем (прецедент `0007`: инвариант
#    «обязательство без X не бывает» — дату набивают по счёту и фиксируют заново).
# 2. `Lot.unit_cost` (цена штуки до копейки) → `Lot.cost` (стоимость партии):
#    - партия поставки из заказа, цену которой не правили руками (= округлённой доле
#      строки), получает ТОЧНУЮ долю цены строки накопительным округлением — сумма долей
#      по строке сходится со счётом до копейки;
#    - остальные — `qty × unit_cost` до копейки (цену правили по УПД — это факт).
# 3. `StockMovement.cost` — пересборка проекции тем же правилом, что
#    `engine.rebuild_movements` (копия алгоритма: миграция не зовёт живой движок).

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import migrations, models

ZERO = Decimal('0')
KOPECK = Decimal('0.01')
RELOCATION = 'relocation'
RECEIPT = 'receipt'


def _kop(x):
    return x.quantize(KOPECK, rounding=ROUND_HALF_UP)


def _share(cost, qty, part):
    return _kop(cost * part / qty) if qty else ZERO


def unlock_undated_purchases(apps, schema_editor):
    Purchase = apps.get_model('plume', 'Purchase')
    Purchase.objects.filter(locked=True, date__isnull=True).update(locked=False)


def fill_lot_cost(apps, schema_editor):
    Lot = apps.get_model('plume', 'Lot')
    PurchaseLine = apps.get_model('plume', 'PurchaseLine')
    drained = {}                      # (purchase_id, item_id) → кол-во уже разнесённых партий
    for lot in Lot.objects.select_related('origin').order_by('id'):
        cost = _kop(lot.qty * lot.unit_cost)
        origin = lot.origin
        if origin.kind == RECEIPT and origin.purchase_id:
            line = PurchaseLine.objects.filter(purchase_id=origin.purchase_id,
                                               item_id=lot.item_id).first()
            if line is not None and line.price is not None and line.qty:
                key = (origin.purchase_id, lot.item_id)
                before = drained.get(key, ZERO)
                drained[key] = before + lot.qty
                if lot.unit_cost == _kop(line.price / line.qty):
                    cost = (_share(line.price, line.qty, before + lot.qty)
                            - _share(line.price, line.qty, before))
        lot.cost = cost
        lot.save(update_fields=['cost'])


def rebuild_movements(apps, schema_editor):
    Lot = apps.get_model('plume', 'Lot')
    Location = apps.get_model('plume', 'Location')
    StockMovement = apps.get_model('plume', 'StockMovement')
    main = Location.objects.filter(code='MAIN').first() or Location.objects.order_by('id').first()
    for lot in Lot.objects.select_related('origin').order_by('id'):
        StockMovement.objects.filter(lot=lot).delete()
        rows = []
        if lot.qty and lot.origin.locked:
            rows.append(StockMovement(
                lot=lot, location=main, type='RECEIPT', qty=lot.qty, cost=lot.cost,
                source_type=lot.origin.kind, source_id=lot.origin_id))
        drained = ZERO
        for sl in lot.stock_lines.select_related('document').order_by('id'):
            if not sl.document.locked:
                continue
            if sl.qty < 0 and sl.document.kind != RELOCATION:
                before = _share(lot.cost, lot.qty, drained)
                drained -= sl.qty
                value = -(_share(lot.cost, lot.qty, drained) - before)
            else:
                value = _share(lot.cost, lot.qty, abs(sl.qty))
                value = value if sl.qty > 0 else -value
            rows.append(StockMovement(
                lot=lot, location_id=sl.location_id,
                type='RECEIPT' if sl.qty > 0 else 'ISSUE', qty=sl.qty, cost=value,
                source_type=sl.document.kind, source_id=sl.document_id))
        StockMovement.objects.bulk_create(rows)


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0008_remove_procurement_contractor'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(unlock_undated_purchases, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='purchase',
            constraint=models.CheckConstraint(condition=models.Q(('locked', False), ('date__isnull', False), _connector='OR'), name='purchase_locked_has_date'),
        ),
        migrations.AddField(
            model_name='lot',
            name='cost',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name='стоимость партии'),
        ),
        migrations.AddField(
            model_name='stockmovement',
            name='cost',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name='стоимость (со знаком)'),
        ),
        migrations.RunPython(fill_lot_cost, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='lot',
            name='unit_cost',
        ),
        migrations.RunPython(rebuild_movements, migrations.RunPython.noop),
    ]
