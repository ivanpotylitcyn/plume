# Волна 27, Ф0 (решения Ивана 2026-10-21): переименования, освобождающие имена под
# складской контур, — механика не меняется.
#
# 1. Вид `requisition` (отпочкование между проектами) → `reassignment` «Перевод». Имя
#    «Требование» уходит новому официальному виду (Ф2: Центральный → наша локация).
#    `kind` хранится строкой и в ордере, и в проекции (`StockMovement.source_type`) —
#    правим оба. На проде таких ордеров 0 (снимок 2026-10-21), переносятся dev и тесты.
# 2. Идентичность партии — пара `code` + `description`, как у всех сущностей:
#    `part_number` → `code` (неуникальный — факт с коробки), `lot_name` → `description`.

from django.db import migrations, models


KINDS = [('receipt', 'Поставка'), ('kitting', 'Комплектация'),
         ('inventory', 'Инвентаризация'), ('reassignment', 'Перевод'),
         ('transfer', 'Передача'), ('writeoff', 'Списание'),
         ('relocation', 'Перемещение')]


def rename_kind(old, new):
    def run(apps, schema_editor):
        StockDocument = apps.get_model('plume', 'StockDocument')
        StockMovement = apps.get_model('plume', 'StockMovement')
        StockDocument.objects.filter(kind=old).update(kind=new)
        StockMovement.objects.filter(source_type=old).update(source_type=new)
    return run


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0010_procurement_locked_has_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stockdocument', name='kind',
            field=models.CharField(blank=True, choices=KINDS + [('requisition', 'Требование')],
                                   default='', max_length=16, verbose_name='вид ордера'),
        ),
        migrations.RunPython(rename_kind('requisition', 'reassignment'),
                             rename_kind('reassignment', 'requisition')),
        migrations.AlterField(
            model_name='stockdocument', name='kind',
            field=models.CharField(blank=True, choices=KINDS, default='', max_length=16,
                                   verbose_name='вид ордера'),
        ),
        migrations.DeleteModel(name='Requisition'),
        migrations.CreateModel(
            name='Reassignment',
            fields=[],
            options={
                'verbose_name': 'перевод',
                'verbose_name_plural': 'переводы',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('plume.stockdocument',),
        ),
        migrations.RenameField(model_name='lot', old_name='part_number', new_name='code'),
        migrations.RenameField(model_name='lot', old_name='lot_name', new_name='description'),
        migrations.AlterField(
            model_name='lot', name='code',
            field=models.CharField(blank=True, default='', max_length=128,
                                   verbose_name='код (PN)'),
        ),
        migrations.AlterField(
            model_name='lot', name='description',
            field=models.CharField(blank=True, default='', max_length=255,
                                   verbose_name='описание (наименование)'),
        ),
    ]
