"""Волна 19, Ф12a: `Attachment.label` → `description`.

Последний `label`-как-подпись в схеме: Ф10 свела все сущности к паре
«идентичность + описание», вложение осталось в стороне. Идентичность файла —
`filename` (своего `code` у него нет), поэтому описание встаёт сразу за ним.
Данные едут вместе с полем (RenameField), потерь нет.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0009_item_code'),
    ]

    operations = [
        migrations.RenameField(
            model_name='attachment',
            old_name='label',
            new_name='description',
        ),
        migrations.AlterField(
            model_name='attachment',
            name='description',
            field=models.CharField(blank=True, default='', max_length=255,
                                   verbose_name='описание'),
        ),
    ]
