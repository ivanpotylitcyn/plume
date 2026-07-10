# Волна 13, Ф2f+ — `Supplier → Counterparty` (единая сущность контрагента с ролями)
# + структурный контрагент на приходе и передаче:
#   RenameModel Supplier → Counterparty  (переносит таблицу + перецепляет FK в состоянии)
#   +is_supplier (default=True — исторические поставщики), +is_customer (default=False)
#   Receipt.supplier → contractor        (RenameField, FK на Counterparty цел)
#   +Transfer.contractor                 (nullable — старые передачи получателя не имели)
# Реверсивна и без потерь: обе роли/FK структурно-полны, значение сохранно
# (все прежние Supplier == is_supplier поставщики; contractor приходов цел). Схема-only.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0009_lot_identifiers'),
    ]

    operations = [
        migrations.RenameModel(old_name='Supplier', new_name='Counterparty'),
        migrations.AlterModelOptions(
            name='counterparty',
            options={'ordering': ['name'], 'verbose_name': 'контрагент',
                     'verbose_name_plural': 'контрагенты'},
        ),
        migrations.AddField(
            model_name='counterparty',
            name='is_supplier',
            field=models.BooleanField(default=True, verbose_name='поставщик'),
        ),
        migrations.AddField(
            model_name='counterparty',
            name='is_customer',
            field=models.BooleanField(default=False, verbose_name='заказчик'),
        ),
        migrations.RenameField(
            model_name='receipt', old_name='supplier', new_name='contractor',
        ),
        migrations.AlterField(
            model_name='receipt',
            name='contractor',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='receipts', to='plume.counterparty',
                verbose_name='поставщик'),
        ),
        migrations.AddField(
            model_name='transfer',
            name='contractor',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='transfers', to='plume.counterparty',
                verbose_name='заказчик'),
        ),
    ]
