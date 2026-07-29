"""Волна 19, Ф17 — развязка закупочного контура: контрагент у всех трёх уровней.

**Закупка = ЧТО купить · Заказ = У КОГО купить · Поставка = КТО привёз.** Контрагента
у среднего уровня не было, и «Заказ → УПД» читал его сквозь цепочку
`purchase.procurement.contractor` (развилка Р3 волны 19, отменена этой фазой). Заказ,
оформленный без закупки, своего поставщика не знал физически.

Схема:
- `Purchase.contractor` — FK на `Counterparty`, nullable, `PROTECT` (обязательство,
  как у поставки);
- `Purchase.procurement` → **nullable**: заказ бывает и без плана. До Ф17 колонка была
  NOT NULL, и одиночный заказ тихо рождал закупку-пустышку (`_solo_procurement`),
  которую список закупок прятал эвристикой (`_plan_procurements`) — обе конструкции
  снесены движком в этой же фазе;
- CHECK `purchase_locked_has_contractor` — обязательность на ФИКСАЦИИ, а не при
  рождении (канон Ф12e/Ф14): черновик имеет право быть неполным.

Данные — тот же «копией при рождении», применённый разово к истории:
1. `contractor` ← `procurement.contractor` (намерение плана становится фактом заказа);
2. фолбэк — контрагент **первой поставки** заказа: «кто привёз» — лучший известный
   ответ на «у кого купили», когда план молчал;
3. остаток: зафиксированный заказ, которому нечего унаследовать, **расфиксируется**.
   По новому правилу такой записи не существует, а снятие замка у заказа ничего не
   разрушает (лотов он не рождает, привязанные поставки остаются) — он лишь выходит
   из счёта «заказано», пока человек не выберет контрагента.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def inherit_contractor(apps, schema_editor):
    """Контрагент заказа: из плана, иначе из первой его поставки, иначе — расфиксировать."""
    Purchase = apps.get_model('plume', 'Purchase')
    StockDocument = apps.get_model('plume', 'StockDocument')
    unfixed = []
    for pu in Purchase.objects.select_related('procurement').all():
        cid = pu.procurement.contractor_id if pu.procurement_id else None
        if cid is None:
            cid = (StockDocument.objects
                   .filter(purchase_id=pu.pk, kind='receipt', contractor__isnull=False)
                   .order_by('date', 'id')
                   .values_list('contractor_id', flat=True).first())
        if cid is not None:
            pu.contractor_id = cid
            pu.save(update_fields=['contractor'])
        elif pu.locked:
            pu.locked = False
            pu.save(update_fields=['locked'])
            unfixed.append(pu.pk)
    if unfixed:
        print(f'\n  Ф17: расфиксированы заказы без известного контрагента: {unfixed}')


def forget_contractor(apps, schema_editor):
    """Реверс: наследование разовое, снимать нечего — колонку уносит `AddField`.

    Расфиксацию из forward обратно не накатываем: какие заказы были заперты, знает
    только вывод прогона, а угадывать замок задним числом — врать про документ.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0014_procurement_scope'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='purchase',
            name='contractor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='purchases', to='plume.counterparty', verbose_name='контрагент'),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='procurement',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='purchases', to='plume.procurement', verbose_name='закупка-план'),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='purchases', to='plume.project', verbose_name='проект'),
        ),
        # Перенос — строго между колонкой и констрейнтом: до него CHECK упал бы на
        # зафиксированных заказах, у которых контрагента ещё нет.
        migrations.RunPython(inherit_contractor, forget_contractor),
        migrations.AddConstraint(
            model_name='purchase',
            constraint=models.CheckConstraint(condition=models.Q(('locked', False), ('contractor__isnull', False), _connector='OR'), name='purchase_locked_has_contractor'),
        ),
    ]
