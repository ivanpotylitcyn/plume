# Волна 27, Ф1–Ф2 (решения Ивана 2026-10-21): Центральный склад, локация «Куда» в шапке
# рождающих ордеров и новый официальный вид «Требование».
#
# Данные: в БД с данными заводим «Центральный склад» и кладём на него поставки — их лоты
# встают в очередь «ждут Требования» (на проде две поставки, снимок 2026-10-21). Прежняя
# «главная» локация (`MAIN` или первая по id) остаётся нашей: туда — комплектации и
# инвентаризации. Всё, что лоты поставок делали на прежней главной, переносим на
# Центральный (строки и проекция) — иначе приход уехал бы, а расход остался, и главная
# ушла бы в минус. Пустую БД (тесты, первый сид) не трогаем: Центральный лениво заводит
# движок (`engine.central_location`).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_central(apps, schema_editor):
    Location = apps.get_model('plume', 'Location')
    Doc = apps.get_model('plume', 'StockDocument')
    Lot = apps.get_model('plume', 'Lot')
    StockLine = apps.get_model('plume', 'StockLine')
    StockMovement = apps.get_model('plume', 'StockMovement')
    if not (Location.objects.exists() or Doc.objects.exists()):
        return
    old_main = (Location.objects.filter(code='MAIN').first()
                or Location.objects.order_by('id').first())
    code, n = 'Центральный', 2
    while Location.objects.filter(code=code).exists():
        code, n = f'Центральный-{n}', n + 1
    central = Location.objects.create(code=code, description='Центральный склад',
                                      central=True)
    Doc.objects.filter(kind='receipt').update(location=central)
    own_docs = Doc.objects.filter(kind__in=['kitting', 'inventory'])
    if own_docs.exists():
        own = old_main or Location.objects.create(code='Склад', description='Наш склад')
        own_docs.update(location=own)
    if old_main is not None:
        lot_ids = list(Lot.objects.filter(origin__kind='receipt').values_list('id', flat=True))
        StockLine.objects.filter(lot_id__in=lot_ids, location=old_main).update(location=central)
        StockMovement.objects.filter(lot_id__in=lot_ids,
                                     location=old_main).update(location=central)


def unseed_central(apps, schema_editor):
    Location = apps.get_model('plume', 'Location')
    StockLine = apps.get_model('plume', 'StockLine')
    StockMovement = apps.get_model('plume', 'StockMovement')
    Doc = apps.get_model('plume', 'StockDocument')
    central = Location.objects.filter(central=True).first()
    Doc.objects.update(location=None)
    if central is None:
        return
    main = Location.objects.exclude(pk=central.pk).order_by('id').first()
    if main is not None:
        StockLine.objects.filter(location=central).update(location=main)
        StockMovement.objects.filter(location=central).update(location=main)
    if not (StockLine.objects.filter(location=central).exists()
            or StockMovement.objects.filter(location=central).exists()):
        central.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0011_wave27_renames'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Requisition',
            fields=[
            ],
            options={
                'verbose_name': 'требование',
                'verbose_name_plural': 'требования',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('plume.stockdocument',),
        ),
        migrations.AlterModelOptions(
            name='location',
            options={'ordering': ['code'], 'verbose_name': 'локация', 'verbose_name_plural': 'локации'},
        ),
        migrations.RemoveField(
            model_name='location',
            name='kind',
        ),
        migrations.AddField(
            model_name='location',
            name='central',
            field=models.BooleanField(blank=True, default=None, null=True, unique=True, verbose_name='центральный склад'),
        ),
        migrations.AddField(
            model_name='stockdocument',
            name='location',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='documents', to='plume.location', verbose_name='куда'),
        ),
        migrations.AlterField(
            model_name='stockdocument',
            name='kind',
            field=models.CharField(blank=True, choices=[('receipt', 'Поставка'), ('kitting', 'Комплектация'), ('inventory', 'Инвентаризация'), ('reassignment', 'Перевод'), ('requisition', 'Требование'), ('transfer', 'Передача'), ('writeoff', 'Списание'), ('relocation', 'Перемещение')], default='', max_length=16, verbose_name='вид ордера'),
        ),
        migrations.RunPython(seed_central, unseed_central),
        migrations.AddConstraint(
            model_name='location',
            constraint=models.CheckConstraint(condition=models.Q(('central__isnull', True), ('central', True), _connector='OR'), name='location_central_true_or_null'),
        ),
        migrations.AddConstraint(
            model_name='stockdocument',
            constraint=models.CheckConstraint(condition=models.Q(('kind__in', ('receipt', 'kitting', 'inventory', 'requisition')), ('location__isnull', True), _connector='OR'), name='doc_location_only_own_kinds'),
        ),
        migrations.AddConstraint(
            model_name='stockdocument',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kind__in', ('receipt', 'kitting', 'inventory', 'requisition')), _negated=True), ('locked', False), ('location__isnull', False), _connector='OR'), name='doc_locked_has_location'),
        ),
    ]
