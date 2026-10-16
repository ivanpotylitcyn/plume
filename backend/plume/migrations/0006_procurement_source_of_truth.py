# Волна 24 (2026-10-16): Закупка — источник правды закупочного контура.
# Плюс `PurchaseLine.price` — цена всей строки заказа по счёту (приёмка волны).
#
# Закупка становится однопроектной (`Procurement.project`), заказ рождается только из
# неё (`Purchase.procurement` NOT NULL) и выводит проект через неё (`Purchase.project`
# снят). Плюс unique `(procurement, item)` у строки плана — на неё опирается инвариант
# «строка заказа ⊆ план». Решения — JOURNAL 2026-10-16, план — docs/WAVE24.md.
#
# Данные переносятся общим правилом, без хардкода id (на проде — по свежему снимку):
# 1. проект закупки = проект её заказов; заказы разных проектов → отказ с перечнем;
#    закупка без заказов → «Собственный склад» (фолбэк, как у ордеров по клику);
# 2. каждому заказу без закупки — своя закупка (честный слепок истории: каждый такой
#    заказ планировался сам по себе), строки «хотим» = заказано;
# 3. каждой закупке — недостающие строки плана из строк её заказов (Σ кол-в), чтобы
#    инвариант «строка заказа ⊆ план» держался с первого дня.

from collections import defaultdict
from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def _internal_stock(Project):
    proj = Project.objects.filter(kind='internal_stock').first()
    if proj is None:
        proj = Project.objects.create(code='WHITE', description='Собственный склад',
                                      kind='internal_stock')
    return proj


def _free_code(Procurement, code):
    """Код закупки, свободный среди закупок: коллизия → суффикс « (заказ)», « (заказ 2)»…"""
    if not code or not Procurement.objects.filter(code=code).exists():
        return code
    n = 1
    while True:
        candidate = f'{code} (заказ)' if n == 1 else f'{code} (заказ {n})'
        if not Procurement.objects.filter(code=candidate).exists():
            return candidate
        n += 1


def forward(apps, schema_editor):
    Project = apps.get_model('plume', 'Project')
    Procurement = apps.get_model('plume', 'Procurement')
    ProcurementLine = apps.get_model('plume', 'ProcurementLine')
    Purchase = apps.get_model('plume', 'Purchase')
    PurchaseLine = apps.get_model('plume', 'PurchaseLine')

    # 1. Проект существующих закупок — из их заказов.
    mixed = []
    fallback = None
    for proc in Procurement.objects.order_by('id'):
        projects = set(Purchase.objects.filter(procurement=proc)
                       .values_list('project_id', flat=True))
        if len(projects) > 1:
            codes = sorted(Project.objects.filter(pk__in=projects)
                           .values_list('code', flat=True))
            mixed.append(f'{proc.code or proc.pk}: {", ".join(codes)}')
            continue
        if projects:
            proc.project_id = projects.pop()
        else:
            fallback = fallback or _internal_stock(Project)
            proc.project_id = fallback.pk
        proc.save(update_fields=['project'])
    if mixed:
        raise RuntimeError(
            'Закупки с заказами нескольких проектов — разведите их до миграции: '
            + '; '.join(mixed))

    # 2. Своя закупка каждому одиночному заказу.
    for pu in Purchase.objects.filter(procurement__isnull=True).order_by('id'):
        proc = Procurement.objects.create(
            code=_free_code(Procurement, pu.code), description=pu.description,
            locked=pu.locked, project_id=pu.project_id,
            contractor_id=pu.contractor_id, date=pu.date, user_id=pu.user_id)
        if not proc.code:
            proc.code = _free_code(Procurement, f'Закупка {proc.pk}')
            proc.save(update_fields=['code'])
        pu.procurement = proc
        pu.save(update_fields=['procurement'])

    # 3. Строки плана ⊇ строки заказов.
    for proc in Procurement.objects.order_by('id'):
        ordered = defaultdict(Decimal)
        for item_id, qty in PurchaseLine.objects.filter(
                purchase__procurement=proc).values_list('item_id', 'qty'):
            ordered[item_id] += qty
        planned = set(ProcurementLine.objects.filter(procurement=proc)
                      .values_list('item_id', flat=True))
        ProcurementLine.objects.bulk_create([
            ProcurementLine(procurement=proc, item_id=item_id, qty=qty)
            for item_id, qty in ordered.items() if item_id not in planned])


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0005_category_native'),
    ]

    operations = [
        migrations.AddField(
            model_name='procurement',
            name='project',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='procurements', to='plume.project',
                                    verbose_name='проект'),
        ),
        migrations.RunPython(forward, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='procurement',
            name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='procurements', to='plume.project',
                                    verbose_name='проект'),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='procurement',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='purchases', to='plume.procurement',
                                    verbose_name='закупка'),
        ),
        migrations.RemoveField(
            model_name='purchase',
            name='project',
        ),
        # Цена ВСЕЙ строки заказа по счёту (решения Ивана при приёмке волны, 2026-10-16).
        migrations.AddField(
            model_name='purchaseline',
            name='price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14,
                                      null=True, verbose_name='цена строки (по счёту)'),
        ),
        migrations.AddConstraint(
            model_name='procurementline',
            constraint=models.UniqueConstraint(fields=('procurement', 'item'),
                                               name='procurementline_uniq_procurement_item'),
        ),
    ]
