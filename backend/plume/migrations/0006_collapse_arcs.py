"""Волна 13, Ф2b — коллапс дуг в единый FK на MTI-родителя `StockDocument`.

Ф2a унифицировала id-пространство ордеров (PK ребёнка = id родителя), поэтому дуги
`Lot.origin` (4 FK) и `StockLine.document` (4 FK) схлопываются в ОДИН FK на
`StockDocument`, а `Attachment` из 7-путного владельца становится двухпутным
(Item ИЛИ ордер). Три exclusive-arc Check и три набора nullable-FK умирают.

**Бэкфилл тривиален:** старая FK-колонка (`receipt_id`/…) уже хранит id ребёнка,
который РАВЕН id родителя `StockDocument`, поэтому
`origin_id = COALESCE(receipt_id, kitting_id, inventory_id, requisition_id)` — это
прямое значение нового FK, без ремапа (в отличие от 0005).

**Порядок ↔ реверсивность.** `RemoveConstraint` идёт ПЕРВЫМ в forward → его реверс
(`AddConstraint`) выполняется ПОСЛЕДНИМ при откате, т.е. уже после того, как обратный
бэкфилл (`RunSQL.reverse_sql`) восстановил старые колонки из свёрнутого FK по `kind`.
Иначе Check «ровно один задан» упал бы на пустых восстановленных колонках.

Портируемо (MySQL + SQLite): бэкфилл — чистый `UPDATE ... COALESCE` / `UPDATE ...
WHERE id IN (SELECT ... FROM plume_stockdocument WHERE kind=...)`.
"""
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


def _exactly_one_q(fields):
    """Клон `models._exactly_one_q` (inline, чтобы историческая миграция не зависела
    от будущих правок модели) — даёт байт-идентичный `condition` для --check."""
    q = Q()
    for chosen in fields:
        term = Q(**{f'{chosen}__isnull': False})
        for other in fields:
            if other != chosen:
                term &= Q(**{f'{other}__isnull': True})
        q |= term
    return q


def _restore_by_kind(table, columns):
    """Обратный бэкфилл: раздать свёрнутый FK по старым nullable-колонкам согласно
    дискриминатору `kind` родителя. `columns` — {старая_колонка: значение kind}."""
    src = 'origin_id' if table == 'plume_lot' else 'document_id'
    return [
        f"UPDATE {table} SET {col}_id = {src} "
        f"WHERE {src} IN (SELECT id FROM plume_stockdocument WHERE kind = '{kind}')"
        for col, kind in columns.items()
    ]


LOT_KINDS = {'receipt': 'receipt', 'kitting': 'kitting',
             'inventory': 'inventory', 'requisition': 'requisition'}
STOCKLINE_KINDS = {'kitting': 'kitting', 'transfer': 'transfer',
                   'writeoff': 'writeoff', 'requisition': 'requisition'}
ATTACHMENT_KINDS = {'receipt': 'receipt', 'transfer': 'transfer',
                    'kitting': 'kitting', 'inventory': 'inventory',
                    'writeoff': 'writeoff', 'requisition': 'requisition'}


def _fk(related_name, null):
    return models.ForeignKey(
        blank=null, null=null, on_delete=django.db.models.deletion.CASCADE,
        related_name=related_name, to='plume.stockdocument',
        verbose_name='ордер-владелец')


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0005_stockdocument_mti'),
    ]

    operations = [
        # ---- Lot.origin: 4 FK + Check → один FK ---------------------------- #
        migrations.RemoveConstraint(model_name='lot', name='lot_exactly_one_origin'),
        migrations.AddField(
            model_name='lot', name='origin',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='lots', to='plume.stockdocument',
                verbose_name='ордер-origin'),
        ),
        migrations.RunSQL(
            sql="UPDATE plume_lot SET origin_id = "
                "COALESCE(receipt_id, kitting_id, inventory_id, requisition_id)",
            reverse_sql=_restore_by_kind('plume_lot', LOT_KINDS),
        ),
        migrations.AlterField(
            model_name='lot', name='origin',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name='lots',
                to='plume.stockdocument', verbose_name='ордер-origin'),
        ),
        migrations.RemoveField(model_name='lot', name='receipt'),
        migrations.RemoveField(model_name='lot', name='kitting'),
        migrations.RemoveField(model_name='lot', name='inventory'),
        migrations.RemoveField(model_name='lot', name='requisition'),

        # ---- StockLine.document: 4 FK + Check → один FK -------------------- #
        migrations.RemoveConstraint(model_name='stockline',
                                    name='stockline_exactly_one_document'),
        migrations.AddField(
            model_name='stockline', name='document', field=_fk('lines', null=True),
        ),
        migrations.RunSQL(
            sql="UPDATE plume_stockline SET document_id = "
                "COALESCE(kitting_id, transfer_id, writeoff_id, requisition_id)",
            reverse_sql=_restore_by_kind('plume_stockline', STOCKLINE_KINDS),
        ),
        migrations.AlterField(
            model_name='stockline', name='document', field=_fk('lines', null=False),
        ),
        migrations.RemoveField(model_name='stockline', name='kitting'),
        migrations.RemoveField(model_name='stockline', name='transfer'),
        migrations.RemoveField(model_name='stockline', name='writeoff'),
        migrations.RemoveField(model_name='stockline', name='requisition'),

        # ---- Attachment.owner: 7 FK → item + document (2-путная дуга) ------ #
        migrations.RemoveConstraint(model_name='attachment',
                                    name='attachment_exactly_one_owner'),
        migrations.AddField(
            model_name='attachment', name='document', field=_fk('attachments', null=True),
        ),
        migrations.RunSQL(
            sql="UPDATE plume_attachment SET document_id = COALESCE("
                "receipt_id, transfer_id, kitting_id, inventory_id, "
                "writeoff_id, requisition_id)",
            reverse_sql=_restore_by_kind('plume_attachment', ATTACHMENT_KINDS),
        ),
        migrations.RemoveField(model_name='attachment', name='receipt'),
        migrations.RemoveField(model_name='attachment', name='transfer'),
        migrations.RemoveField(model_name='attachment', name='kitting'),
        migrations.RemoveField(model_name='attachment', name='inventory'),
        migrations.RemoveField(model_name='attachment', name='writeoff'),
        migrations.RemoveField(model_name='attachment', name='requisition'),
        migrations.AddConstraint(
            model_name='attachment',
            constraint=models.CheckConstraint(
                condition=_exactly_one_q(('item', 'document')),
                name='attachment_exactly_one_owner'),
        ),
    ]
