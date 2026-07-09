# Волна 13, Ф0 — консолидация четырёх таблиц строк-расхода
# (KittingLine/TransferLine/WriteoffLine/RequisitionLine) в единую знаковую `StockLine`.
#
# Порядок операций важен: сначала создаём StockLine, КОПИРУЕМ данные (со сменой знака
# на отрицательный — расход), и только потом сносим старые таблицы. На время
# сосуществования новые FK-владельцы держат временный related_name='+' (иначе конфликт
# обратного акцессора `lines` со старыми *Line-моделями), после сноса — переводим на
# 'lines' (правка только состояния, без SQL).
import django.db.models.deletion
from django.db import migrations, models


def copy_lines_to_stockline(apps, schema_editor):
    """Перелить строки 4 старых таблиц в StockLine (qty → −qty, расход)."""
    KittingLine = apps.get_model('plume', 'KittingLine')
    TransferLine = apps.get_model('plume', 'TransferLine')
    WriteoffLine = apps.get_model('plume', 'WriteoffLine')
    RequisitionLine = apps.get_model('plume', 'RequisitionLine')
    Location = apps.get_model('plume', 'Location')
    StockLine = apps.get_model('plume', 'StockLine')

    main = Location.objects.filter(code='MAIN').first() or Location.objects.order_by('id').first()
    main_id = main.id if main else None

    rows = []
    for kl in KittingLine.objects.all():
        rows.append(StockLine(kitting_id=kl.kitting_id, lot_id=kl.lot_id,
                              location_id=kl.location_id, qty=-kl.qty, date=kl.date))
    for tl in TransferLine.objects.all():
        # у передачи не было своей локации — приземляем на основной склад (как движок)
        rows.append(StockLine(transfer_id=tl.transfer_id, lot_id=tl.lot_id,
                              location_id=main_id, qty=-tl.qty,
                              display_name=tl.display_name))
    for wl in WriteoffLine.objects.all():
        rows.append(StockLine(writeoff_id=wl.writeoff_id, lot_id=wl.lot_id,
                              location_id=wl.location_id, qty=-wl.qty))
    for rl in RequisitionLine.objects.all():
        rows.append(StockLine(requisition_id=rl.requisition_id, lot_id=rl.source_lot_id,
                              location_id=rl.location_id, qty=-rl.qty))
    StockLine.objects.bulk_create(rows)


def copy_stockline_back(apps, schema_editor):
    """Обратная миграция: разлить StockLine по 4 воссозданным таблицам (−qty → qty)."""
    KittingLine = apps.get_model('plume', 'KittingLine')
    TransferLine = apps.get_model('plume', 'TransferLine')
    WriteoffLine = apps.get_model('plume', 'WriteoffLine')
    RequisitionLine = apps.get_model('plume', 'RequisitionLine')
    Lot = apps.get_model('plume', 'Lot')
    StockLine = apps.get_model('plume', 'StockLine')

    item_by_lot = dict(Lot.objects.values_list('id', 'item_id'))
    for sl in StockLine.objects.all():
        mag = -sl.qty
        if sl.kitting_id:
            KittingLine.objects.create(
                kitting_id=sl.kitting_id, component_id=item_by_lot[sl.lot_id],
                lot_id=sl.lot_id, location_id=sl.location_id, qty=mag, date=sl.date)
        elif sl.transfer_id:
            TransferLine.objects.create(
                transfer_id=sl.transfer_id, lot_id=sl.lot_id, qty=mag,
                display_name=sl.display_name)
        elif sl.writeoff_id:
            WriteoffLine.objects.create(
                writeoff_id=sl.writeoff_id, lot_id=sl.lot_id,
                location_id=sl.location_id, qty=mag)
        elif sl.requisition_id:
            RequisitionLine.objects.create(
                requisition_id=sl.requisition_id, source_lot_id=sl.lot_id,
                location_id=sl.location_id, qty=mag)


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0002_transfer_posted'),
    ]

    operations = [
        # 1. Создаём StockLine (временный related_name='+' на владельцах — без конфликта
        #    обратного акцессора со старыми *Line, пока те живы).
        migrations.CreateModel(
            name='StockLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('qty', models.DecimalField(decimal_places=4, max_digits=14, verbose_name='кол-во (со знаком: − расход)')),
                ('date', models.DateField(blank=True, null=True, verbose_name='дата (пайка)')),
                ('display_name', models.CharField(blank=True, default='', max_length=255, verbose_name='отображаемое имя (накладная)')),
                ('kitting', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='plume.kitting')),
                ('transfer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='plume.transfer')),
                ('writeoff', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='plume.writeoff')),
                ('requisition', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='plume.requisition')),
                ('location', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='plume.location')),
                ('lot', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stock_lines', to='plume.lot', verbose_name='лот (расходуемый источник)')),
            ],
            options={
                'verbose_name': 'строка движения',
                'verbose_name_plural': 'строки движения',
            },
        ),
        # 2. Копируем данные (со сменой знака) до сноса старых таблиц.
        migrations.RunPython(copy_lines_to_stockline, copy_stockline_back),
        # 3. Инвариант «ровно один документ-владелец» (данные ему уже удовлетворяют).
        migrations.AddConstraint(
            model_name='stockline',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kitting__isnull', False), ('transfer__isnull', True), ('writeoff__isnull', True), ('requisition__isnull', True)), models.Q(('transfer__isnull', False), ('kitting__isnull', True), ('writeoff__isnull', True), ('requisition__isnull', True)), models.Q(('writeoff__isnull', False), ('kitting__isnull', True), ('transfer__isnull', True), ('requisition__isnull', True)), models.Q(('requisition__isnull', False), ('kitting__isnull', True), ('transfer__isnull', True), ('writeoff__isnull', True)), _connector='OR'), name='stockline_exactly_one_document'),
        ),
        # 4. Сносим старые таблицы строк-расхода.
        migrations.DeleteModel(name='KittingLine'),
        migrations.DeleteModel(name='TransferLine'),
        migrations.DeleteModel(name='WriteoffLine'),
        migrations.DeleteModel(name='RequisitionLine'),
        # 5. Теперь конфликт снят — переводим владельцев на конечный related_name='lines'
        #    (правка состояния, без SQL).
        migrations.AlterField(
            model_name='stockline',
            name='kitting',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='plume.kitting'),
        ),
        migrations.AlterField(
            model_name='stockline',
            name='transfer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='plume.transfer'),
        ),
        migrations.AlterField(
            model_name='stockline',
            name='writeoff',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='plume.writeoff'),
        ),
        migrations.AlterField(
            model_name='stockline',
            name='requisition',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='plume.requisition'),
        ),
    ]
