# Аудит-1, Б1а-3 и Б1а-2: снос двух приговорённых мест схемы.
#
# `BomLine.position` — позиционное обозначение, год жившее в схеме, движке и API,
# но никогда не показанное формой изделия (приговор FIELD_MATRIX A1). Данных за ним
# нет: ввести их было неоткуда, состав приезжает синком из библиотеки Altium.
#
# `StockMovement.Type.RETURN` — значение enum, которого движок не писал никогда
# (`rebuild_movements` знает RECEIPT/ISSUE). Только choices → таблицу не трогает.
#
# Обратной заливки не пишем: терять нечего, а перед 1.0 история всё равно едет в
# сквош.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0017_user_profile'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='bomline',
            name='position',
        ),
        migrations.AlterField(
            model_name='stockmovement',
            name='type',
            field=models.CharField(choices=[('RECEIPT', 'Приход'), ('ISSUE', 'Расход')], max_length=16, verbose_name='тип'),
        ),
    ]
