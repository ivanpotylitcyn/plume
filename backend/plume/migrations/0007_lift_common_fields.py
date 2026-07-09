"""Волна 13, Ф2c — подъём общих полей ордера с 6 детей в MTI-родителя `StockDocument`.

`project`/`user`/`date`/`number`/`note` жили копиями на каждом из 6 складских
документов (`Receipt`/`Kitting`/`Inventory`/`Requisition`/`Transfer`/`Writeoff`).
Ф2a унифицировала id-пространство (PK ребёнка = `stockdocument_ptr_id` = id родителя),
поэтому поля переезжают в родителя по прямому равенству id — без ремапа.

**Почему `SeparateDatabaseAndState` (как 0005), а не обычные AddField/RemoveField:**
в MTI поле родителя и одноимённое поле ребёнка НЕ могут сосуществовать в состоянии —
Django падает на клэше имён. Автодетектор это обходит порядком (сперва все RemoveField
детей, потом AddField родителя), поэтому СОСТОЯНИЕ берём его же операциями (`--check`
чист), а ФИЗИКУ пишем raw-SQL под `FK_CHECKS=0` (на DB-уровне колонки на разных
таблицах не конфликтуют, и мы полностью контролируем nullability + порядок бэкфилла).

Реверсивно и полностью: forward копит родителя из детей и роняет дочерние колонки;
reverse воссоздаёт дочерние колонки (nullable → fill → NOT NULL → FK) и роняет
родительские. MySQL-only (как вся MTI-цепочка с 0005; боевой рантайм — MySQL).
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


# Дочерняя таблица → её поднимаемые колонки (в порядке бэкфилла). Child PK =
# stockdocument_ptr_id (== id родителя). Kitting — без number/note; note — только у
# инвентаризации; date у Kitting был nullable, у остальных пяти — NOT NULL.
CHILD_COLS = {
    'plume_receipt':     ['project_id', 'user_id', 'date', 'number'],
    'plume_kitting':     ['project_id', 'user_id', 'date'],
    'plume_inventory':   ['project_id', 'user_id', 'date', 'number', 'note'],
    'plume_requisition': ['project_id', 'user_id', 'date', 'number'],
    'plume_transfer':    ['project_id', 'user_id', 'date', 'number'],
    'plume_writeoff':    ['project_id', 'user_id', 'date', 'number'],
}
CHILD_DATE_NOTNULL = {'plume_receipt', 'plume_inventory', 'plume_requisition',
                      'plume_transfer', 'plume_writeoff'}

# DDL для (пере)создания одной колонки — nullable/temp вариант (FK-колонки временно
# NULL, ужесточаются после заполнения; строковые — сразу NOT NULL DEFAULT '').
COL_DDL = {
    'project_id': 'BIGINT NULL',
    'user_id':    'INT NULL',            # auth.User.id = AutoField → INT
    'date':       'DATE NULL',
    'number':     "VARCHAR(64) NOT NULL DEFAULT ''",
    'note':       "VARCHAR(255) NOT NULL DEFAULT ''",
}


def _require_mysql(schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        raise RuntimeError(
            'Миграция 0007 (подъём полей MTI) написана под MySQL (боевой рантайм).')


def _fk_names(cur, intro, table, column):
    """Имена FK-констрейнтов на (table.column) — Django-хеши, берём интроспекцией."""
    return [name for name, meta in intro.get_constraints(cur, table).items()
            if meta.get('foreign_key') and meta['columns'] == [column]]


def lift_forward(apps, schema_editor):
    """Физика: добавить поля в родителя, залить из детей, снять с детей."""
    _require_mysql(schema_editor)
    conn = schema_editor.connection
    cur = conn.cursor()
    intro = conn.introspection
    cur.execute('SET FOREIGN_KEY_CHECKS=0')
    try:
        # 1. Родительские колонки (project/user временно NULL — заполним ниже).
        cur.execute(
            "ALTER TABLE plume_stockdocument "
            "ADD COLUMN project_id BIGINT NULL, "
            "ADD COLUMN user_id INT NULL, "
            "ADD COLUMN date DATE NULL, "
            "ADD COLUMN number VARCHAR(64) NOT NULL DEFAULT '', "
            "ADD COLUMN note VARCHAR(255) NOT NULL DEFAULT ''")
        # 2. Бэкфилл родителя из каждого ребёнка (id == stockdocument_ptr_id).
        for tbl, cols in CHILD_COLS.items():
            setexpr = ', '.join(f'p.{c} = ch.{c}' for c in cols)
            cur.execute(f'UPDATE plume_stockdocument p JOIN {tbl} ch '
                        f'ON p.id = ch.stockdocument_ptr_id SET {setexpr}')
        # 3. Ужесточить project/user до NOT NULL (данные уже есть).
        cur.execute('ALTER TABLE plume_stockdocument '
                    'MODIFY project_id BIGINT NOT NULL, MODIFY user_id INT NOT NULL')
        # 4. FK родителя на справочники.
        cur.execute('ALTER TABLE plume_stockdocument ADD CONSTRAINT sd_project_fk '
                    'FOREIGN KEY (project_id) REFERENCES plume_project (id)')
        cur.execute('ALTER TABLE plume_stockdocument ADD CONSTRAINT sd_user_fk '
                    'FOREIGN KEY (user_id) REFERENCES auth_user (id)')
        # 5. Снять с детей FK (project/user), затем сами колонки.
        for tbl, cols in CHILD_COLS.items():
            for col in ('project_id', 'user_id'):
                for name in _fk_names(cur, intro, tbl, col):
                    cur.execute(f'ALTER TABLE {tbl} DROP FOREIGN KEY {name}')
            drops = ', '.join(f'DROP COLUMN {c}' for c in cols)
            cur.execute(f'ALTER TABLE {tbl} {drops}')
    finally:
        cur.execute('SET FOREIGN_KEY_CHECKS=1')


def lift_backward(apps, schema_editor):
    """Обратно: воссоздать дочерние колонки, залить из родителя, снять с родителя."""
    _require_mysql(schema_editor)
    conn = schema_editor.connection
    cur = conn.cursor()
    cur.execute('SET FOREIGN_KEY_CHECKS=0')
    try:
        # 1. Дочерние колонки заново (FK — временно NULL).
        for tbl, cols in CHILD_COLS.items():
            adds = ', '.join(f'ADD COLUMN {c} {COL_DDL[c]}' for c in cols)
            cur.execute(f'ALTER TABLE {tbl} {adds}')
        # 2. Залить детей из родителя.
        for tbl, cols in CHILD_COLS.items():
            setexpr = ', '.join(f'ch.{c} = p.{c}' for c in cols)
            cur.execute(f'UPDATE {tbl} ch JOIN plume_stockdocument p '
                        f'ON ch.stockdocument_ptr_id = p.id SET {setexpr}')
        # 3. Ужесточить NOT NULL (project/user везде; date — кроме kitting).
        for tbl, cols in CHILD_COLS.items():
            mods = ['MODIFY project_id BIGINT NOT NULL', 'MODIFY user_id INT NOT NULL']
            if tbl in CHILD_DATE_NOTNULL:
                mods.append('MODIFY date DATE NOT NULL')
            cur.execute(f'ALTER TABLE {tbl} ' + ', '.join(mods))
        # 4. Вернуть дочерние FK.
        for tbl in CHILD_COLS:
            cur.execute(f'ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_project_fk '
                        f'FOREIGN KEY (project_id) REFERENCES plume_project (id)')
            cur.execute(f'ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_user_fk '
                        f'FOREIGN KEY (user_id) REFERENCES auth_user (id)')
        # 5. Снять родительские FK + колонки.
        cur.execute('ALTER TABLE plume_stockdocument DROP FOREIGN KEY sd_project_fk')
        cur.execute('ALTER TABLE plume_stockdocument DROP FOREIGN KEY sd_user_fk')
        cur.execute('ALTER TABLE plume_stockdocument '
                    'DROP COLUMN project_id, DROP COLUMN user_id, '
                    'DROP COLUMN date, DROP COLUMN number, DROP COLUMN note')
    finally:
        cur.execute('SET FOREIGN_KEY_CHECKS=1')


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('plume', '0006_collapse_arcs'),
    ]

    # СОСТОЯНИЕ (как автодетектор: сперва все RemoveField детей, потом AddField
    # родителя — так одноимённые поля родителя/ребёнка не сосуществуют, нет клэша).
    state_operations = [
        migrations.RemoveField(model_name='inventory', name='date'),
        migrations.RemoveField(model_name='inventory', name='note'),
        migrations.RemoveField(model_name='inventory', name='number'),
        migrations.RemoveField(model_name='inventory', name='project'),
        migrations.RemoveField(model_name='inventory', name='user'),
        migrations.RemoveField(model_name='kitting', name='date'),
        migrations.RemoveField(model_name='kitting', name='project'),
        migrations.RemoveField(model_name='kitting', name='user'),
        migrations.RemoveField(model_name='receipt', name='date'),
        migrations.RemoveField(model_name='receipt', name='number'),
        migrations.RemoveField(model_name='receipt', name='project'),
        migrations.RemoveField(model_name='receipt', name='user'),
        migrations.RemoveField(model_name='requisition', name='date'),
        migrations.RemoveField(model_name='requisition', name='number'),
        migrations.RemoveField(model_name='requisition', name='project'),
        migrations.RemoveField(model_name='requisition', name='user'),
        migrations.RemoveField(model_name='transfer', name='date'),
        migrations.RemoveField(model_name='transfer', name='number'),
        migrations.RemoveField(model_name='transfer', name='project'),
        migrations.RemoveField(model_name='transfer', name='user'),
        migrations.RemoveField(model_name='writeoff', name='date'),
        migrations.RemoveField(model_name='writeoff', name='number'),
        migrations.RemoveField(model_name='writeoff', name='project'),
        migrations.RemoveField(model_name='writeoff', name='user'),
        migrations.AddField(
            model_name='stockdocument', name='project',
            field=models.ForeignKey(
                default=1, on_delete=django.db.models.deletion.PROTECT,
                related_name='documents', to='plume.project',
                verbose_name='проект'),
            preserve_default=False),
        migrations.AddField(
            model_name='stockdocument', name='user',
            field=models.ForeignKey(
                default=1, on_delete=django.db.models.deletion.PROTECT,
                related_name='documents', to=settings.AUTH_USER_MODEL,
                verbose_name='автор'),
            preserve_default=False),
        migrations.AddField(
            model_name='stockdocument', name='date',
            field=models.DateField(blank=True, null=True, verbose_name='дата')),
        migrations.AddField(
            model_name='stockdocument', name='number',
            field=models.CharField(blank=True, default='', max_length=64,
                                   verbose_name='номер')),
        migrations.AddField(
            model_name='stockdocument', name='note',
            field=models.CharField(blank=True, default='', max_length=255,
                                   verbose_name='примечание')),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=state_operations,
            database_operations=[
                migrations.RunPython(lift_forward, lift_backward),
            ],
        ),
    ]
