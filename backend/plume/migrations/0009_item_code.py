# Волна 19, Ф3b: `Item.design_item_id → code` — последний пункт «зоопарка имён».
# Единый интерфейс идентичности (`code` + `description`) достаётся и Изделию;
# `unique=True` переезжает вместе с полем, данные не трогаются. Полностью обратима.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0008_item_synced_not_locked'),
    ]

    operations = [
        migrations.RenameField(
            model_name='item',
            old_name='design_item_id',
            new_name='code',
        ),
        migrations.AlterField(
            model_name='item',
            name='code',
            field=models.CharField(max_length=128, unique=True, verbose_name='код'),
        ),
        migrations.AlterModelOptions(
            name='item',
            options={'ordering': ['code'], 'verbose_name': 'изделие',
                     'verbose_name_plural': 'изделия'},
        ),
    ]
