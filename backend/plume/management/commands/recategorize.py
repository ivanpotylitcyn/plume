"""Разложить изделия по категориям из CSV-таблицы (уборка справочника, 2026-10-15).

    manage.py recategorize ТАБЛИЦА.csv            # сухой прогон: отчёт, БД не трогаем
    manage.py recategorize ТАБЛИЦА.csv --apply    # записать (одна транзакция)
    manage.py recategorize ТАБЛИЦА.csv --apply --prune   # + снести пустые не-канонные

Таблица — UTF-8 CSV с колонками `code` (код изделия) и `category` (код категории),
прочие колонки игнорируются. **Таблица живёт ВНЕ репозитория**: проект открытый, а
это перечень наших изделий. Логика — `engine.recategorize_items`.
"""
import csv

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from plume import engine


class _DryRun(Exception):
    """Откат сухого прогона: отчёт посчитан на настоящей БД и выброшен."""


class Command(BaseCommand):
    help = 'Разложить изделия по категориям из CSV (code, category).'

    def add_arguments(self, parser):
        parser.add_argument('table', help='CSV с колонками code, category')
        parser.add_argument('--apply', action='store_true', help='записать (иначе сухой прогон)')
        parser.add_argument('--prune', action='store_true',
                            help='удалить пустые категории вне канона')

    def handle(self, table, apply, prune, **opts):
        mapping = {}
        with open(table, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                code, cat = (row.get('code') or '').strip(), (row.get('category') or '').strip()
                if code and cat:
                    mapping[code] = cat
        if not mapping:
            raise CommandError('В таблице нет строк с code и category.')
        try:
            with transaction.atomic():
                report = engine.recategorize_items(mapping, prune=prune)
                if not apply:
                    raise _DryRun
        except _DryRun:
            pass
        except ValidationError as e:
            raise CommandError(e.messages[0] if e.messages else str(e))

        self.stdout.write(f'Строк в таблице: {len(mapping)}')
        self.stdout.write(f'  сменят категорию: {report["changed"]}')
        self.stdout.write(f'  уже на месте:     {report["same"]}')
        if report['missing_items']:
            self.stdout.write(f'  нет в БД (пропущены): {", ".join(report["missing_items"])}')
        if report['untouched']:
            self.stdout.write(f'  в БД, но не в таблице: {len(report["untouched"])} — '
                              f'{", ".join(report["untouched"][:20])}'
                              + (' …' if len(report['untouched']) > 20 else ''))
        if prune:
            self.stdout.write(f'  пустые категории вне канона: {", ".join(report["pruned"]) or "—"}')
        self.stdout.write(self.style.SUCCESS('Записано.') if apply
                          else self.style.WARNING('Сухой прогон — БД не изменена (--apply).'))
