# Волна 13, Ф2f — два идентификатора партии вместо `serial_number`/`received_name`:
#   `lot_name` (человеческий: имена из УПД + заводские №) и `part_number` (строгий
#   машинный: MPN / децимальный номер). НЕ простой rename — слияние с приоритетом:
#     lot_name    ← COALESCE(received_name, serial_number)   (received_name важнее)
#     part_number ← новое пустое поле
#     drop serial_number
# Реверс структурно-полный, значение сохранно (lot_name → received_name; serial → ''),
# но лоссовый по «в каком поле лежал зав.№»: forward после reverse значение-стабилен
# (coalesce(received_name,'') == received_name), т.е. round-trip остаток инвариантен.

from django.db import migrations, models
from django.db.models import F


def merge_serial_into_lot_name(apps, schema_editor):
    Lot = apps.get_model('plume', 'Lot')
    # received_name уже переименован в lot_name; забираем serial туда, где имя пусто.
    Lot.objects.filter(lot_name='').exclude(serial_number='').update(
        lot_name=F('serial_number'))


def noop(apps, schema_editor):
    # Реверс: значение уже в lot_name → received_name (RenameField ниже вернёт его);
    # serial_number воссоздаётся пустым (RemoveField reverse). Расщепить нельзя.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0008_relocation_child'),
    ]

    operations = [
        migrations.AddField(
            model_name='lot',
            name='part_number',
            field=models.CharField(blank=True, default='', max_length=128,
                                   verbose_name='part number'),
        ),
        migrations.RenameField(
            model_name='lot',
            old_name='received_name',
            new_name='lot_name',
        ),
        migrations.AlterField(
            model_name='lot',
            name='lot_name',
            field=models.CharField(blank=True, default='', max_length=255,
                                   verbose_name='название партии'),
        ),
        migrations.RunPython(merge_serial_into_lot_name, noop),
        migrations.RemoveField(
            model_name='lot',
            name='serial_number',
        ),
    ]
