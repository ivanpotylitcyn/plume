# Волна 24 (решение Ивана 2026-10-16): контрагент — только у заказа. Закупка — инструмент
# внутреннего планирования и к контрагенту не относится; у контрагента остаются его
# обязательства (заказы) и то, что он привёз или принял (поставки, передачи).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0007_unlock_unpriced_purchases'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='procurement',
            name='contractor',
        ),
    ]
