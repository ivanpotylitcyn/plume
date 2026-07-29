"""Волна 19, Ф12e — черновик имеет право родиться неполным.

«＋ Новый» больше не открывает форму создания, а СРАЗУ рождает сущность: значит
обязательные поля обязаны пережить момент рождения пустыми. Приём тот же, что
Ф14 применила к специфике ордера (`contractor`/`target_item`): колонка nullable,
а обязательность переезжает на ФИКСАЦИЮ (CHECK по `locked` + гейт в движке).

Здесь остаётся ровно одно поле — `Item.category`: `Receipt.contractor` и
`Kitting.target_item` уже стали nullable в `0012` вместе со сносом MTI (план
волны говорил про три FK, но два из них закрылись предыдущей фазой).

Попутно (долг Ф8): ярлык вида `receipt` «Приход (УПД)» → «Поставка» — глоссарий
переехал на «Поставку» ещё в волне 14, а `choices` отстали. Теперь этот ярлык не
только подпись в админке, но и источник фолбэк-кода («Поставка 12»), поэтому
расхождение с фронтом стало бы видно пользователю. DDL не трогает.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0012_collapse_mti_stockdocument'),
    ]

    operations = [
        migrations.AlterField(
            model_name='item',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='items', to='plume.category', verbose_name='категория'),
        ),
        migrations.AlterField(
            model_name='stockdocument',
            name='kind',
            field=models.CharField(blank=True, choices=[('receipt', 'Поставка'), ('kitting', 'Комплектация'), ('inventory', 'Инвентаризация'), ('requisition', 'Требование'), ('transfer', 'Передача'), ('writeoff', 'Списание'), ('relocation', 'Перемещение')], default='', max_length=16, verbose_name='вид ордера'),
        ),
        migrations.AddConstraint(
            model_name='item',
            constraint=models.CheckConstraint(condition=models.Q(('locked', False), ('category__isnull', False), _connector='OR'), name='item_locked_has_category'),
        ),
    ]
