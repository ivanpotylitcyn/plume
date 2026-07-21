# Волна 19, Ф1: свод всех статусов к одной оси `DocStatus {draft, posted}`.
#
# Схема + данные одной миграцией. На проде (снимок 2026-07-20) затронутых строк НОЛЬ:
# все закупки/заказы в `draft`, все проекты в `active` — конвертация здесь de facto
# no-op. Написана защитной осознанно: dev-базы и прод могут разойтись, а стоит это
# три запроса. Счётчики печатаются, чтобы на проде было видно, что реально тронули.

from django.db import migrations, models
from django.db.migrations.recorder import MigrationRecorder


# Старые значения → новая ось. `cancelled` НЕ удаляем автоматически (развилка Р1:
# отмена = удаление, но решение об удалении конкретной записи — за человеком):
# возвращаем в черновик, дальше Иван разбирает через UI.
STATUS_MAP = {
    'sent': 'posted',
    'partial': 'posted',      # мёртвый статус: «получено» стало вычисляемым
    'received': 'posted',     # то же
    'cancelled': 'draft',
}


def to_single_axis(apps, schema_editor):
    was_cancelled = 0
    for model_name in ('Procurement', 'Purchase'):
        model = apps.get_model('plume', model_name)
        for old, new in STATUS_MAP.items():
            n = model.objects.filter(status=old).update(status=new)
            if n:
                print(f'  {model_name}: {old} → {new} — {n} шт.')
                if old == 'cancelled':
                    was_cancelled += n
        stuck = model.objects.exclude(status__in=('draft', 'posted')).count()
        if stuck:
            print(f'  ! {model_name}: {stuck} строк с неизвестным статусом — проверь руками')

    project = apps.get_model('plume', 'Project')
    n = project.objects.filter(status='draft').update(status='active')
    if n:
        print(f'  Project: draft → active — {n} шт.')

    # Подсказку печатаем ТОЛЬКО если отменённые реально были: иначе на чистой базе
    # она пугает пустым «разбери руками».
    if was_cancelled:
        print(f'  ({was_cancelled} бывших отменённых вернулись в черновики — разбери '
              f'через UI: удалить или вернуть в работу)')


def drop_ghost_migration(apps, schema_editor):
    """Убрать миграцию-призрак `plume/0002_transfer_posted` из `django_migrations`.

    Файл снесён при сквоше истории, а запись в БД осталась (обнаружено первым же
    снимком прода 2026-07-20). Django такие записи игнорирует, поэтому вреда не было,
    но `showmigrations` врал, и в проде сосуществовали две разные `0002`.
    """
    qs = MigrationRecorder(schema_editor.connection).migration_qs.filter(
        app='plume', name='0002_transfer_posted')
    n = qs.count()
    if n:
        qs.delete()
        print(f'  призрак 0002_transfer_posted удалён из django_migrations ({n} зап.)')


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0002_item_status'),
    ]

    operations = [
        # Данные — до смены choices (choices на уровне БД не живут, но так честнее
        # читается: сперва привели значения, потом сузили словарь).
        migrations.RunPython(to_single_axis, migrations.RunPython.noop),
        # Необратимо по существу: `cancelled → draft` теряет исходное значение,
        # разворот вернул бы неверное. Обратный ход — noop.
        migrations.RunPython(drop_ghost_migration, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='procurement',
            name='status',
            field=models.CharField(choices=[('draft', 'Черновик'), ('posted', 'Проведён')], default='draft', max_length=16, verbose_name='статус'),
        ),
        migrations.AlterField(
            model_name='project',
            name='status',
            field=models.CharField(choices=[('active', 'Активен'), ('closed', 'Закрыт')], default='active', max_length=16, verbose_name='статус'),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='status',
            field=models.CharField(choices=[('draft', 'Черновик'), ('posted', 'Проведён')], default='draft', max_length=16, verbose_name='статус'),
        ),
    ]
