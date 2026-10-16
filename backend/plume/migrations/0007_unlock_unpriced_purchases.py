# Волна 24 (решение Ивана 2026-10-16): зафиксированный заказ — это обязательство, и
# обязательства без цены не бывает. Заказы, зафиксированные до того, как у строки
# появилась цена (`PurchaseLine.price`, `0006`), инвариант нарушают: их расфиксируем —
# «нет цены, значит не оплачено». Цены набивают по счетам и фиксируют заново; костылей
# вида «потрачено по оценке» движок не держит. Правило общее, без хардкода id.

from django.db import migrations


def forward(apps, schema_editor):
    Purchase = apps.get_model('plume', 'Purchase')
    Purchase.objects.filter(locked=True, lines__price__isnull=True).distinct() \
        .update(locked=False)


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0006_procurement_source_of_truth'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
