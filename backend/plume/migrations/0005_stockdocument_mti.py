# Волна 13, Ф2a — MTI-ядро: абстрактный миксин `StockDoc` схлопнут в конкретного
# родителя `StockDocument`; 6 складских документов стали MTI-наследниками (их PK =
# единый `id` этой таблицы, унификация id-пространства). Добавлен дискриминатор `kind`.
#
# Физику Django не сгенерит (обретение MTI-родителя на живых данных: RemoveField(id) с
# входящими FK на MySQL просто упадёт, а parent_link нельзя с дефолтом). Поэтому:
#   • CreateModel(StockDocument) — реальная операция (таблица-родитель);
#   • превращение детей — через SeparateDatabaseAndState: СОСТОЯНИЕ декларируем сами
#     (RemoveField status/id + AddField parent_link-ptr на каждого ребёнка), а ФИЗИКУ
#     делаем raw-SQL под FK_CHECKS=0 (MySQL) — см. mti_forward/mti_backward.
#
# Реверсивна по инварианту (как 0003/0004): обратный проход возвращает детям
# собственный AUTO-PK `id` + колонку `status`, перецепляет дуги и сносит родителя;
# ТОЧНЫЕ прежние id не восстанавливаются (не важно — инвариант остатка/движений держим).
import django.db.models.deletion
from django.db import migrations, models


# (таблица ребёнка, вид ордера) — порядок фиксирован (id родителя раздаём подряд)
CHILDREN = [
    ('plume_receipt', 'receipt'),
    ('plume_kitting', 'kitting'),
    ('plume_inventory', 'inventory'),
    ('plume_requisition', 'requisition'),
    ('plume_transfer', 'transfer'),
    ('plume_writeoff', 'writeoff'),
]

# входящие дуги: (таблица, колонка-FK, таблица-ребёнок) — их значения-id надо перецепить
# на новые id родителя, а FK-констрейнты переуказать на child.stockdocument_ptr_id.
INBOUND = [
    ('plume_lot', 'receipt_id', 'plume_receipt'),
    ('plume_lot', 'kitting_id', 'plume_kitting'),
    ('plume_lot', 'inventory_id', 'plume_inventory'),
    ('plume_lot', 'requisition_id', 'plume_requisition'),
    ('plume_attachment', 'receipt_id', 'plume_receipt'),
    ('plume_attachment', 'transfer_id', 'plume_transfer'),
    ('plume_attachment', 'kitting_id', 'plume_kitting'),
    ('plume_attachment', 'inventory_id', 'plume_inventory'),
    ('plume_attachment', 'writeoff_id', 'plume_writeoff'),
    ('plume_attachment', 'requisition_id', 'plume_requisition'),
    ('plume_stockline', 'kitting_id', 'plume_kitting'),
    ('plume_stockline', 'transfer_id', 'plume_transfer'),
    ('plume_stockline', 'writeoff_id', 'plume_writeoff'),
    ('plume_stockline', 'requisition_id', 'plume_requisition'),
]


def _require_mysql(schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        raise RuntimeError(
            'Миграция 0005 (MTI-конверсия) написана под MySQL (боевой рантайм).'
        )


def _inbound_fk_names(cur, introspection, table, column):
    """Имена FK-констрейнтов на (table.column) — Django-хеши, берём интроспекцией."""
    names = []
    for name, meta in introspection.get_constraints(cur, table).items():
        if meta.get('foreign_key') and meta['columns'] == [column]:
            names.append(name)
    return names


def mti_forward(apps, schema_editor):
    """Физика: раздать детям parent-id, перецепить дуги, PK ребёнка → ptr, снять status."""
    _require_mysql(schema_editor)
    conn = schema_editor.connection
    cur = conn.cursor()
    intro = conn.introspection
    cur.execute('SET FOREIGN_KEY_CHECKS=0')
    try:
        # 1. Родительская строка на каждого ребёнка (kind+status) + временный ptr.
        for tbl, kind in CHILDREN:
            cur.execute(f'ALTER TABLE {tbl} ADD COLUMN stockdocument_ptr_id BIGINT NULL')
            cur.execute(f'SELECT id, status FROM {tbl} ORDER BY id')
            for old_id, status in cur.fetchall():
                cur.execute(
                    'INSERT INTO plume_stockdocument (kind, status) VALUES (%s, %s)',
                    [kind, status])
                cur.execute('SELECT LAST_INSERT_ID()')
                new_id = cur.fetchone()[0]
                cur.execute(f'UPDATE {tbl} SET stockdocument_ptr_id=%s WHERE id=%s',
                            [new_id, old_id])
        # 2. Перецепить значения входящих дуг (old child.id → new parent.id).
        for tbl, col, child in INBOUND:
            cur.execute(
                f'UPDATE {tbl} t JOIN {child} c ON t.{col}=c.id '
                f'SET t.{col}=c.stockdocument_ptr_id WHERE t.{col} IS NOT NULL')
        # 3. Снять входящие FK-констрейнты (указывают на исчезающий child.id).
        for tbl, col, child in INBOUND:
            for name in _inbound_fk_names(cur, intro, tbl, col):
                cur.execute(f'ALTER TABLE {tbl} DROP FOREIGN KEY {name}')
        # 4. Ребёнок: снять status, снять AUTO+PK+id, ptr → PK + FK на родителя.
        for tbl, kind in CHILDREN:
            cur.execute(f'ALTER TABLE {tbl} DROP COLUMN status')
            cur.execute(f'ALTER TABLE {tbl} MODIFY id BIGINT NOT NULL')  # снять AUTO_INCREMENT
            cur.execute(f'ALTER TABLE {tbl} DROP PRIMARY KEY')
            cur.execute(f'ALTER TABLE {tbl} DROP COLUMN id')
            cur.execute(f'ALTER TABLE {tbl} MODIFY stockdocument_ptr_id BIGINT NOT NULL')
            cur.execute(f'ALTER TABLE {tbl} ADD PRIMARY KEY (stockdocument_ptr_id)')
            cur.execute(
                f'ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_sdptr_fk '
                f'FOREIGN KEY (stockdocument_ptr_id) REFERENCES plume_stockdocument (id)')
        # 5. Вернуть входящие FK, теперь на child.stockdocument_ptr_id.
        for i, (tbl, col, child) in enumerate(INBOUND):
            cur.execute(
                f'ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_{col}_sd_{i}_fk '
                f'FOREIGN KEY ({col}) REFERENCES {child} (stockdocument_ptr_id)')
    finally:
        cur.execute('SET FOREIGN_KEY_CHECKS=1')


def mti_backward(apps, schema_editor):
    """Обратно: детям — свой AUTO-PK id + status; дуги назад на child.id; снести родителя."""
    _require_mysql(schema_editor)
    conn = schema_editor.connection
    cur = conn.cursor()
    intro = conn.introspection
    cur.execute('SET FOREIGN_KEY_CHECKS=0')
    try:
        # 1. Снять входящие FK (указывают на child.stockdocument_ptr_id).
        for tbl, col, child in INBOUND:
            for name in _inbound_fk_names(cur, intro, tbl, col):
                cur.execute(f'ALTER TABLE {tbl} DROP FOREIGN KEY {name}')
        # 2. Ребёнок: вернуть собственный AUTO-PK id, статус из родителя; ptr пока держим.
        for tbl, kind in CHILDREN:
            for name in _inbound_fk_names(cur, intro, tbl, 'stockdocument_ptr_id'):
                cur.execute(f'ALTER TABLE {tbl} DROP FOREIGN KEY {name}')
            cur.execute(f'ALTER TABLE {tbl} DROP PRIMARY KEY')
            cur.execute(
                f'ALTER TABLE {tbl} ADD COLUMN id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY '
                f'FIRST')
            cur.execute(
                f'ALTER TABLE {tbl} ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT %s',
                ['draft'])
            cur.execute(
                f'UPDATE {tbl} t JOIN plume_stockdocument s '
                f'ON t.stockdocument_ptr_id=s.id SET t.status=s.status')
        # 3. Перецепить входящие дуги назад: parent-id → новый child.id.
        for tbl, col, child in INBOUND:
            cur.execute(
                f'UPDATE {tbl} t JOIN {child} c ON t.{col}=c.stockdocument_ptr_id '
                f'SET t.{col}=c.id WHERE t.{col} IS NOT NULL')
        # 4. Снять ptr-колонку у детей и удалить строки родителя.
        for tbl, kind in CHILDREN:
            cur.execute(f'ALTER TABLE {tbl} DROP COLUMN stockdocument_ptr_id')
        cur.execute('DELETE FROM plume_stockdocument')
        # 5. Вернуть входящие FK на child.id.
        for i, (tbl, col, child) in enumerate(INBOUND):
            cur.execute(
                f'ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_{col}_id_{i}_fk '
                f'FOREIGN KEY ({col}) REFERENCES {child} (id)')
    finally:
        cur.execute('SET FOREIGN_KEY_CHECKS=1')


def _child_state_ops(model, extra=()):
    """State-операции превращения ребёнка в MTI-наследника StockDocument."""
    return [
        migrations.RemoveField(model_name=model, name='status'),
        migrations.RemoveField(model_name=model, name='id'),
        migrations.AddField(
            model_name=model,
            name='stockdocument_ptr',
            field=models.OneToOneField(
                auto_created=True, on_delete=django.db.models.deletion.CASCADE,
                parent_link=True, primary_key=True, serialize=False,
                to='plume.stockdocument'),
        ),
    ]


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0004_unified_doc_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='StockDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('kind', models.CharField(
                    blank=True, default='', max_length=16, verbose_name='вид ордера',
                    choices=[('receipt', 'Приход (УПД)'), ('kitting', 'Комплектация'),
                             ('inventory', 'Инвентаризация'), ('requisition', 'Требование'),
                             ('transfer', 'Передача'), ('writeoff', 'Списание'),
                             ('relocation', 'Перемещение')])),
                ('status', models.CharField(
                    default='draft', max_length=16, verbose_name='статус',
                    choices=[('draft', 'Черновик'), ('posted', 'Проведён')])),
            ],
            options={'verbose_name': 'ордер', 'verbose_name_plural': 'ордера'},
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=(
                _child_state_ops('receipt') + _child_state_ops('kitting')
                + _child_state_ops('inventory') + _child_state_ops('requisition')
                + _child_state_ops('transfer') + _child_state_ops('writeoff')
            ),
            database_operations=[
                migrations.RunPython(mti_forward, mti_backward),
            ],
        ),
    ]
