"""Волна 19, Ф12b: владельцы вложений — +project, +procurement, +purchase, +counterparty.

Файлы нужны не только изделию и ордеру: проекту — ТЗ и договор, закупке/заказу —
бланк запроса, счёт, КП, контрагенту — «карточка предприятия» (сегодня болтается по
чатам). `Location`/`Category` владельцами намеренно НЕ становятся — заведём, когда
заболит. Дуга остаётся exclusive-arc: CHECK пересобирается на шесть полей (данных
не касается — старые вложения уже лежат ровно на одном владельце), поэтому
миграция симметрично обратима.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0010_attachment_description'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='attachment',
            name='attachment_exactly_one_owner',
        ),
        migrations.AddField(
            model_name='attachment',
            name='counterparty',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='plume.counterparty'),
        ),
        migrations.AddField(
            model_name='attachment',
            name='procurement',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='plume.procurement'),
        ),
        migrations.AddField(
            model_name='attachment',
            name='project',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='plume.project'),
        ),
        migrations.AddField(
            model_name='attachment',
            name='purchase',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='plume.purchase'),
        ),
        migrations.AddConstraint(
            model_name='attachment',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('item__isnull', False), ('document__isnull', True), ('project__isnull', True), ('procurement__isnull', True), ('purchase__isnull', True), ('counterparty__isnull', True)), models.Q(('document__isnull', False), ('item__isnull', True), ('project__isnull', True), ('procurement__isnull', True), ('purchase__isnull', True), ('counterparty__isnull', True)), models.Q(('project__isnull', False), ('item__isnull', True), ('document__isnull', True), ('procurement__isnull', True), ('purchase__isnull', True), ('counterparty__isnull', True)), models.Q(('procurement__isnull', False), ('item__isnull', True), ('document__isnull', True), ('project__isnull', True), ('purchase__isnull', True), ('counterparty__isnull', True)), models.Q(('purchase__isnull', False), ('item__isnull', True), ('document__isnull', True), ('project__isnull', True), ('procurement__isnull', True), ('counterparty__isnull', True)), models.Q(('counterparty__isnull', False), ('item__isnull', True), ('document__isnull', True), ('project__isnull', True), ('procurement__isnull', True), ('purchase__isnull', True)), _connector='OR'), name='attachment_exactly_one_owner'),
        ),
    ]
