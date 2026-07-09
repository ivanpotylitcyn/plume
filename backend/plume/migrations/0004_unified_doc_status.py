# Волна 13, Ф1 — единый мягкий замок складского документа `status {draft ⇄ posted}`.
#
# Сворачивает разнородные замки (`Receipt.approved`, `Transfer.posted`,
# `Kitting.status{wip/closed/cancelled}`) в одну ось на абстрактной шапке `StockDoc`
# и заводит `status` на Инвентаризации/Требовании/Списании (раньше — без замка).
#
# Порядок операций важен: сначала ДОБАВЛЯЕМ новые `status`-колонки (старые пока живы),
# КОПИРУЕМ данные (approved/posted → posted; kitting wip/cancelled → draft, closed →
# posted), и только потом СНОСИМ `approved`/`posted`. Реверсивна: обратная перезаливка
# читает `status` в заново поднятые булевы (cancelled на реверсе не восстановить —
# он был снят как канон «отмена = удаление», draft → wip).
from django.db import migrations, models


def status_forward(apps, schema_editor):
    """approved/posted → posted; kitting: closed → posted, wip/cancelled → draft."""
    Receipt = apps.get_model('plume', 'Receipt')
    Transfer = apps.get_model('plume', 'Transfer')
    Kitting = apps.get_model('plume', 'Kitting')
    Receipt.objects.filter(approved=True).update(status='posted')
    Transfer.objects.filter(posted=True).update(status='posted')
    Kitting.objects.filter(status='closed').update(status='posted')
    Kitting.objects.filter(status__in=('wip', 'cancelled')).update(status='draft')


def status_reverse(apps, schema_editor):
    """Обратно: posted → approved/posted True; kitting posted → closed, draft → wip."""
    Receipt = apps.get_model('plume', 'Receipt')
    Transfer = apps.get_model('plume', 'Transfer')
    Kitting = apps.get_model('plume', 'Kitting')
    Receipt.objects.filter(status='posted').update(approved=True)
    Transfer.objects.filter(status='posted').update(posted=True)
    Kitting.objects.filter(status='posted').update(status='closed')
    Kitting.objects.filter(status='draft').update(status='wip')


_STATUS_CHOICES = [('draft', 'Черновик'), ('posted', 'Проведён')]


def _status_field():
    return models.CharField('статус', max_length=16, choices=_STATUS_CHOICES,
                            default='draft')


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0003_stockline_consolidation'),
    ]

    operations = [
        # 1) новые status-колонки (старые approved/posted пока живы для копирования)
        migrations.AddField('receipt', 'status', _status_field()),
        migrations.AddField('transfer', 'status', _status_field()),
        migrations.AddField('inventory', 'status', _status_field()),
        migrations.AddField('requisition', 'status', _status_field()),
        migrations.AddField('writeoff', 'status', _status_field()),
        # 2) kitting: старая колонка status меняет choices/default (значения ещё старые)
        migrations.AlterField('kitting', 'status', _status_field()),
        # 3) перелив данных обоих направлений
        migrations.RunPython(status_forward, status_reverse),
        # 4) снос старых булевых замков
        migrations.RemoveField('receipt', 'approved'),
        migrations.RemoveField('transfer', 'posted'),
    ]
