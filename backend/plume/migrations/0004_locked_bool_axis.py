# Волна 19, Ф1c: строковая ось статуса → `bool locked` на всех пяти сущностях.
#
# Порядок — классический трёхтакт: добавить поле → залить из старого → снять старое.
# Симметрично обратима (reverse заливает `status` обратно), поэтому откат с прода
# не страшен. Объём на снимке прода 2026-07-20: 172 изделия, 1 закупка, 3 заказа,
# 4 проекта, 0 ордеров — дроп БД не нужен, риск минимальный.
#
# Заодно у Проекта уходит суффикс `_at` у дат: они стали чисто информационными
# (`close_project` их больше не штампует), а коллизии `closed` с замком нет именно
# потому, что замок назван `locked`.

from django.db import migrations, models


# Прямой ход: что считается «заперто» в старой строковой оси.
LOCKED_FROM = {
    'Item': 'posted',
    'StockDocument': 'posted',
    'Procurement': 'posted',
    'Purchase': 'posted',
    'Project': 'closed',      # у проекта ось звалась active/closed
}
UNLOCKED_FROM = {
    'Item': 'draft',
    'StockDocument': 'draft',
    'Procurement': 'draft',
    'Purchase': 'draft',
    'Project': 'active',
}


def fill_locked(apps, schema_editor):
    for model_name, posted in LOCKED_FROM.items():
        model = apps.get_model('plume', model_name)
        n = model.objects.filter(status=posted).update(locked=True)
        total = model.objects.count()
        print(f'  {model_name}: {n} из {total} → locked=True')
        stuck = model.objects.exclude(
            status__in=(posted, UNLOCKED_FROM[model_name])).count()
        if stuck:
            print(f'  ! {model_name}: {stuck} строк с посторонним статусом — '
                  f'считаны как незапертые, проверь руками')


def fill_status(apps, schema_editor):
    """Обратный ход: bool → строка (значения те же, что были до миграции)."""
    for model_name, posted in LOCKED_FROM.items():
        model = apps.get_model('plume', model_name)
        model.objects.filter(locked=True).update(status=posted)
        model.objects.filter(locked=False).update(status=UNLOCKED_FROM[model_name])


class Migration(migrations.Migration):

    dependencies = [('plume', '0003_status_single_axis')]

    operations = [
        # 1. Поле рядом со старым.
        migrations.AddField(
            model_name='item',
            name='locked',
            field=models.BooleanField(default=False, verbose_name='зафиксировано'),
        ),
        migrations.AddField(
            model_name='stockdocument',
            name='locked',
            field=models.BooleanField(default=False, verbose_name='зафиксирован'),
        ),
        migrations.AddField(
            model_name='procurement',
            name='locked',
            field=models.BooleanField(default=False, verbose_name='зафиксирована'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='locked',
            field=models.BooleanField(default=False, verbose_name='зафиксирован'),
        ),
        migrations.AddField(
            model_name='project',
            name='locked',
            field=models.BooleanField(default=False, verbose_name='зафиксирован'),
        ),

        # 2. Данные.
        migrations.RunPython(fill_locked, fill_status),

        # 3. Старая ось снята.
        migrations.RemoveField(model_name='item', name='status'),
        migrations.RemoveField(model_name='stockdocument', name='status'),
        migrations.RemoveField(model_name='procurement', name='status'),
        migrations.RemoveField(model_name='purchase', name='status'),
        migrations.RemoveField(model_name='project', name='status'),

        # 4. Даты проекта — без суффикса связи.
        migrations.RenameField(model_name='project', old_name='started_at',
                               new_name='started'),
        migrations.RenameField(model_name='project', old_name='closed_at',
                               new_name='closed'),
    ]
