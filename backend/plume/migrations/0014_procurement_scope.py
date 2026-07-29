# Волна 19, Ф13: охват закупки — набор проектов, под которые она ведётся.
# Схема + перенос: «пусто = пусто», поэтому существующие закупки нельзя оставить с
# пустым охватом — они бы ослепли (наводка исчезла бы). Охват выводим из того, что
# уже сказано пеггингом: проекты заказов, рождённых под этим планом. Это честнее
# «всех активных внешних» — план уже показал, кого он на деле кормит.
from django.db import migrations, models


def scope_from_pegging(apps, schema_editor):
    """Охват = проекты заказов под планом (для планов, которые уже разложены)."""
    Procurement = apps.get_model('plume', 'Procurement')
    for p in Procurement.objects.all():
        ids = set(p.purchases.values_list('project_id', flat=True))
        if ids:
            p.projects.set(ids)


def drop_scope(apps, schema_editor):
    """Реверс: охват выводим обратно из пеггинга, отдельного хранилища у него не было."""
    Procurement = apps.get_model('plume', 'Procurement')
    for p in Procurement.objects.all():
        p.projects.clear()


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0013_draft_born_incomplete'),
    ]

    operations = [
        migrations.AddField(
            model_name='procurement',
            name='projects',
            field=models.ManyToManyField(blank=True, related_name='procurements', to='plume.project', verbose_name='охват (проекты)'),
        ),
        migrations.RunPython(scope_from_pegging, drop_scope),
    ]
