# 2026-10-20 (решение Ивана): дата закупки обязательна к фиксации — как у заказа
# (`purchase_locked_has_date`, `0009`). В отличие от `0009`, данные миграция НЕ правит:
# зафиксированные закупки без даты Иван датирует руками (расфиксировать → указать дату →
# зафиксировать), автоматическая расфиксация молча сдвинула бы «в плане» потребности.
# Поэтому перед CHECK — проверка: осталась такая закупка — стоп с понятным списком,
# а не голый `IntegrityError 3819` посреди выката.

from django.conf import settings
from django.db import migrations, models


def require_dated_locked(apps, schema_editor):
    Procurement = apps.get_model('plume', 'Procurement')
    left = [p.code or f'#{p.pk}'
            for p in Procurement.objects.filter(locked=True, date__isnull=True).order_by('pk')]
    if left:
        raise RuntimeError(
            'Зафиксированные закупки без даты — сперва датируйте их '
            '(расфиксировать → дата → зафиксировать): ' + ', '.join(left))


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0009_lot_cost_canon'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(require_dated_locked, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='procurement',
            constraint=models.CheckConstraint(condition=models.Q(('locked', False), ('date__isnull', False), _connector='OR'), name='procurement_locked_has_date'),
        ),
    ]
