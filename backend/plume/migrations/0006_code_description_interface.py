"""Волна 19, Ф10 — единый интерфейс идентичности `code` + `description`.

Свёртка расползшихся «ручек» к одной паре у КАЖДОЙ сущности (кроме Item — он едет
своей миграцией в Ф3): `name`/`label` → `description`, добавлен `code` там, где его
не было (Counterparty/Procurement/Purchase/документы). Мёртвое `note` удалено везде.
`Category.icon` (коды Codicon) удалён — per-категорийный глиф отпал (режимы
Изделия/Компоненты), заодно снята протечка темы в API (Ф7).

`RenameField` сохраняет данные существующих строк (name/label не теряются). Новые
`code` — `null=True, unique=True`: в MySQL несколько NULL не конфликтуют, поэтому
существующие строки живут с пустым кодом, человек заполняет когда захочет; уникальность
стережёт только непустые. Симметрично обратима (кроме безвозвратно удалённых note/icon).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0005_procurement_contractor'),
    ]

    operations = [
        # --- Category: label → description, снос icon ---
        migrations.RenameField('category', 'label', 'description'),
        migrations.AlterField(
            'category', 'description',
            models.CharField(max_length=128, verbose_name='описание')),
        migrations.RemoveField('category', 'icon'),

        # --- Project: name → description ---
        migrations.RenameField('project', 'name', 'description'),
        migrations.AlterField(
            'project', 'description',
            models.CharField(max_length=255, verbose_name='описание')),

        # --- Location: name → description ---
        migrations.RenameField('location', 'name', 'description'),
        migrations.AlterField(
            'location', 'description',
            models.CharField(max_length=255, verbose_name='описание')),

        # --- Counterparty: name → description, + code, ordering ---
        migrations.RenameField('counterparty', 'name', 'description'),
        migrations.AlterField(
            'counterparty', 'description',
            models.CharField(max_length=255, verbose_name='описание')),
        migrations.AddField(
            'counterparty', 'code',
            models.CharField(blank=True, max_length=64, null=True, unique=True,
                             verbose_name='код')),
        migrations.AlterModelOptions(
            name='counterparty',
            options={'ordering': ['description'], 'verbose_name': 'контрагент',
                     'verbose_name_plural': 'контрагенты'}),

        # --- Procurement: + code, + description, снос note ---
        migrations.AddField(
            'procurement', 'code',
            models.CharField(blank=True, max_length=64, null=True, unique=True,
                             verbose_name='код')),
        migrations.AddField(
            'procurement', 'description',
            models.CharField(blank=True, default='', max_length=255,
                             verbose_name='описание')),
        migrations.RemoveField('procurement', 'note'),

        # --- Purchase: + code, + description, снос note ---
        migrations.AddField(
            'purchase', 'code',
            models.CharField(blank=True, max_length=64, null=True, unique=True,
                             verbose_name='код')),
        migrations.AddField(
            'purchase', 'description',
            models.CharField(blank=True, default='', max_length=255,
                             verbose_name='описание')),
        migrations.RemoveField('purchase', 'note'),

        # --- StockDocument (базовый MTI-родитель): + code, + description, снос note ---
        migrations.AddField(
            'stockdocument', 'code',
            models.CharField(blank=True, max_length=64, null=True, unique=True,
                             verbose_name='код')),
        migrations.AddField(
            'stockdocument', 'description',
            models.CharField(blank=True, default='', max_length=255,
                             verbose_name='описание')),
        migrations.RemoveField('stockdocument', 'note'),
    ]
