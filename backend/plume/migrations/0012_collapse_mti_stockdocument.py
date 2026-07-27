"""Волна 19, Ф14 — снос MTI: семь таблиц ордера схлопываются в одну.

Семь детских таблиц держали **шесть** колонок специфики на все виды, причём три из
них (inventory / requisition / relocation) не содержали ничего, кроме своего PK.
Специфика переезжает nullable-колонками в `plume_stockdocument`, дети становятся
`proxy`-моделями с kind-фильтрующим менеджером — код продолжает писать
`Receipt.objects.filter(...)`, исчезают таблицы, а не API.

Перевязывать ссылки не требуется: `Lot.origin`, `StockLine.document` и
`Attachment.document` указывают на родителя с волны 13 (Ф2b).

**Порядок операций важен и отличается от автосгенерированного.** Автодетектор ставит
снос детских колонок ПЕРЕД созданием родительских — данные погибли бы до переноса.
Здесь: развести имена → создать колонки → перенести → снести детей → CHECK последними
(данные к этому моменту уже обязаны констрейнтам соответствовать).

Первый шаг — **развод имён** (`contractor` → `mti_contractor` и т.д.): пока ребёнок
ещё MTI, одноимённое поле в родителе даёт `FieldError: Local field 'contractor' in
class 'Receipt' clashes with field of the same name from base class`. `RenameField`
переименовывает колонку вместе с данными, поэтому перенос ничего не теряет.

**Контрагент — одна колонка** (решение Ивана 2026-07-27): `Receipt.contractor`
(поставщик) и `Transfer.contractor` (заказчик) сливаются в общий `contractor`,
направление читается из `kind`.

**CHECK черновико-терпимые:** обязательность стережёт ФИКСАЦИЯ, не рождение
(решение Ф12e от 2026-07-27) — `locked` документ обязан быть полным, черновик имеет
право быть пустым.

Симметрично обратима: назад воссоздаются детские таблицы и наполняются из родителя.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Специфика: вид → {поле родителя: поле разведённого ребёнка}. Контрагент приходит
# из ДВУХ видов (поставщик у поставки, заказчик у передачи) в одну общую колонку.
_SPECIFIC = {
    'receipt': ('Receipt', {'contractor_id': 'mti_contractor_id',
                            'purchase_id': 'mti_purchase_id'}),
    'transfer': ('Transfer', {'contractor_id': 'mti_contractor_id'}),
    'kitting': ('Kitting', {'target_item_id': 'mti_target_item_id',
                            'qty': 'mti_qty'}),
    'writeoff': ('Writeoff', {'reason': 'mti_reason'}),
}
_ALL_KINDS = {
    'receipt': 'Receipt', 'kitting': 'Kitting', 'inventory': 'Inventory',
    'requisition': 'Requisition', 'transfer': 'Transfer',
    'writeoff': 'Writeoff', 'relocation': 'Relocation',
}


def collapse(apps, schema_editor):
    """Дети → родитель: перелить специфику в поднятые колонки."""
    StockDocument = apps.get_model('plume', 'StockDocument')
    for child_name, mapping in _SPECIFIC.values():
        Child = apps.get_model('plume', child_name)
        for row in Child.objects.all():
            StockDocument.objects.filter(pk=row.pk).update(
                **{parent: getattr(row, child) for parent, child in mapping.items()})


def explode(apps, schema_editor):
    """Родитель → дети: воссоздать строки детских таблиц из общей.

    К моменту вызова таблицы детей уже воссозданы (реверс `DeleteModel`) и пусты.
    Имена полей здесь ещё разведённые (`mti_*`): обратный `RenameField` идёт последним.

    Пишем **сырым `INSERT … SELECT`, а не ORM**: у MTI-ребёнка `objects.create()`
    вставляет строку И в родительскую таблицу тоже (это и есть MTI), из-за чего
    попытка «долить только детскую часть» падает на `user_id cannot be null` —
    родитель-то уже существует. Прямой INSERT в детскую таблицу обходит эту
    семантику и ровно этого мы и хотим.
    """
    StockDocument = apps.get_model('plume', 'StockDocument')
    parent_table = StockDocument._meta.db_table
    connection = schema_editor.connection
    quote = schema_editor.quote_name

    # Через обычный курсор, не `schema_editor.execute`: последний считает всё DDL и на
    # MySQL (без транзакционного DDL) падает с `TransactionManagementError`.
    with connection.cursor() as cursor:
        for kind, child_name in _ALL_KINDS.items():
            Child = apps.get_model('plume', child_name)
            mapping = _SPECIFIC.get(kind, (None, {}))[1]
            # ptr + специфика; имена колонок берём из исторической модели, не из головы
            cols = {'stockdocument_ptr_id': 'id'}
            for parent_field, child_field in mapping.items():
                cols[Child._meta.get_field(child_field.removesuffix('_id')).column] = \
                    StockDocument._meta.get_field(parent_field.removesuffix('_id')).column
            cursor.execute(
                f'INSERT INTO {quote(Child._meta.db_table)} '
                f'({", ".join(quote(c) for c in cols)}) '
                f'SELECT {", ".join(quote(c) for c in cols.values())} '
                f'FROM {quote(parent_table)} WHERE {quote("kind")} = %s',
                [kind],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0011_attachment_owners'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- 0. Развод имён: пока ребёнок MTI, одноимённое поле в родителе — FieldError ---
        migrations.RenameField(model_name='receipt', old_name='contractor', new_name='mti_contractor'),
        migrations.RenameField(model_name='receipt', old_name='purchase', new_name='mti_purchase'),
        migrations.RenameField(model_name='transfer', old_name='contractor', new_name='mti_contractor'),
        migrations.RenameField(model_name='kitting', old_name='target_item', new_name='mti_target_item'),
        migrations.RenameField(model_name='kitting', old_name='qty', new_name='mti_qty'),
        migrations.RenameField(model_name='writeoff', old_name='reason', new_name='mti_reason'),

        # --- 1. Колонки специфики в родителе (все nullable) ---
        migrations.AddField(
            model_name='stockdocument',
            name='contractor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='documents', to='plume.counterparty', verbose_name='контрагент'),
        ),
        migrations.AddField(
            model_name='stockdocument',
            name='purchase',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='receipts', to='plume.purchase'),
        ),
        migrations.AddField(
            model_name='stockdocument',
            name='target_item',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='kittings', to='plume.item', verbose_name='прибор-цель'),
        ),
        migrations.AddField(
            model_name='stockdocument',
            name='qty',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True, verbose_name='кол-во образцов'),
        ),
        migrations.AddField(
            model_name='stockdocument',
            name='reason',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='причина'),
        ),

        # --- 2. Перенос данных (до сноса детей!) ---
        migrations.RunPython(collapse, explode),

        # --- 3. Снос детских таблиц целиком ---
        # Колонки поштучно НЕ снимаем: у трёх видов таблица и так состояла из одного
        # PK, а MySQL отвечает на снос последней колонки «You can't delete all columns
        # with ALTER TABLE; use DROP TABLE instead» (1090). `DeleteModel` роняет
        # таблицу целиком, а в реверсе воссоздаёт её сразу со всеми колонками —
        # отдельные `RemoveField` не нужны ни туда, ни обратно.
        migrations.DeleteModel(name='Receipt'),
        migrations.DeleteModel(name='Kitting'),
        migrations.DeleteModel(name='Inventory'),
        migrations.DeleteModel(name='Requisition'),
        migrations.DeleteModel(name='Transfer'),
        migrations.DeleteModel(name='Writeoff'),
        migrations.DeleteModel(name='Relocation'),

        # --- 4. Те же имена — теперь proxy над родителем ---
        migrations.CreateModel(
            name='Receipt',
            fields=[],
            options={'verbose_name': 'поставка', 'verbose_name_plural': 'поставки',
                     'proxy': True, 'indexes': [], 'constraints': []},
            bases=('plume.stockdocument',),
        ),
        migrations.CreateModel(
            name='Kitting',
            fields=[],
            options={'verbose_name': 'комплектация', 'verbose_name_plural': 'комплектации',
                     'proxy': True, 'indexes': [], 'constraints': []},
            bases=('plume.stockdocument',),
        ),
        migrations.CreateModel(
            name='Inventory',
            fields=[],
            options={'verbose_name': 'инвентаризация', 'verbose_name_plural': 'инвентаризации',
                     'proxy': True, 'indexes': [], 'constraints': []},
            bases=('plume.stockdocument',),
        ),
        migrations.CreateModel(
            name='Requisition',
            fields=[],
            options={'verbose_name': 'требование', 'verbose_name_plural': 'требования',
                     'proxy': True, 'indexes': [], 'constraints': []},
            bases=('plume.stockdocument',),
        ),
        migrations.CreateModel(
            name='Transfer',
            fields=[],
            options={'verbose_name': 'передача', 'verbose_name_plural': 'передачи',
                     'proxy': True, 'indexes': [], 'constraints': []},
            bases=('plume.stockdocument',),
        ),
        migrations.CreateModel(
            name='Writeoff',
            fields=[],
            options={'verbose_name': 'списание', 'verbose_name_plural': 'списания',
                     'proxy': True, 'indexes': [], 'constraints': []},
            bases=('plume.stockdocument',),
        ),
        migrations.CreateModel(
            name='Relocation',
            fields=[],
            options={'verbose_name': 'перемещение', 'verbose_name_plural': 'перемещения',
                     'proxy': True, 'indexes': [], 'constraints': []},
            bases=('plume.stockdocument',),
        ),

        # --- 5. CHECK последними: данные уже обязаны им соответствовать ---
        migrations.AddConstraint(
            model_name='stockdocument',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kind', 'receipt'), _negated=True), ('locked', False), ('contractor__isnull', False), _connector='OR'), name='doc_locked_receipt_has_contractor'),
        ),
        migrations.AddConstraint(
            model_name='stockdocument',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kind', 'kitting'), _negated=True), ('locked', False), models.Q(('target_item__isnull', False), ('qty__isnull', False)), _connector='OR'), name='doc_locked_kitting_has_target'),
        ),
        migrations.AddConstraint(
            model_name='stockdocument',
            constraint=models.CheckConstraint(condition=models.Q(('kind__in', ('receipt', 'transfer')), ('contractor__isnull', True), _connector='OR'), name='doc_contractor_only_own_kinds'),
        ),
        migrations.AddConstraint(
            model_name='stockdocument',
            constraint=models.CheckConstraint(condition=models.Q(('kind', 'receipt'), ('purchase__isnull', True), _connector='OR'), name='doc_purchase_only_receipt'),
        ),
        migrations.AddConstraint(
            model_name='stockdocument',
            constraint=models.CheckConstraint(condition=models.Q(('kind', 'kitting'), models.Q(('target_item__isnull', True), ('qty__isnull', True)), _connector='OR'), name='doc_target_only_kitting'),
        ),
    ]
