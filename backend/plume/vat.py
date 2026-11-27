"""Денежные факты входящих документов; политика затрат сейчас — полная стоимость.

document_amount — буквально сумма строки в выбранном режиме ввода; vat_amount —
налог из документа (автоматический расчёт лишь подсказка). price/cost — совместимая
с движком проекция полной стоимости. Не восстанавливаем налог у старых данных.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

CENT = Decimal('0.01')
TERMS = ('vat_mode', 'vat_category', 'vat_rate')
FACTS = (*TERMS, 'document_amount', 'vat_amount')
FIELDS = (*FACTS, 'vat_amount_manual')
HEADER = (*TERMS, 'document_total', 'document_vat_total')


class VatTerms(models.Model):
    vat_mode = models.CharField('ввод сумм', max_length=8, default='included',
                               choices=[('included', 'С НДС'), ('excluded', 'Без НДС')])
    vat_category = models.CharField('НДС', max_length=8, default='unknown', choices=[
        ('unknown', 'Не указан'), ('exempt', 'Без НДС'), ('taxable', 'По ставке')])
    vat_rate = models.DecimalField('ставка НДС, %', max_digits=7, decimal_places=4,
                                   null=True, blank=True)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(condition=Q(vat_mode__in=['included', 'excluded']),
                                   name='%(class)s_vat_mode'),
            models.CheckConstraint(condition=(
                Q(vat_category__in=['unknown', 'exempt'], vat_rate__isnull=True)
                | Q(vat_category='taxable', vat_rate__isnull=False,
                    vat_rate__gte=0, vat_rate__lte=100)), name='%(class)s_vat_rate'),
        ]


class VatDocument(VatTerms):
    document_total = models.DecimalField('итого по документу', max_digits=14,
                                        decimal_places=2, null=True, blank=True)
    document_vat_total = models.DecimalField('НДС по документу', max_digits=14,
                                            decimal_places=2, null=True, blank=True)

    class Meta(VatTerms.Meta):
        abstract = True
        constraints = [*VatTerms.Meta.constraints,
            models.CheckConstraint(condition=Q(document_total__isnull=True)
                | Q(document_total__gte=0), name='%(class)s_document_total'),
            models.CheckConstraint(condition=Q(document_vat_total__isnull=True)
                | Q(document_vat_total__gte=0), name='%(class)s_document_vat_total'),
        ]


class VatFacts(VatTerms):
    document_amount = models.DecimalField('сумма строки из документа', max_digits=14,
                                         decimal_places=2, null=True, blank=True)
    vat_amount = models.DecimalField('НДС строки из документа', max_digits=14,
                                    decimal_places=2, null=True, blank=True)
    vat_amount_manual = models.BooleanField('НДС введён из документа', default=False)

    class Meta(VatTerms.Meta):
        abstract = True
        constraints = [*VatTerms.Meta.constraints,
            models.CheckConstraint(condition=Q(document_amount__isnull=True)
                | Q(document_amount__gte=0), name='%(class)s_document_amount'),
            models.CheckConstraint(condition=(
                Q(vat_category='unknown', vat_amount__isnull=True)
                | Q(vat_category='exempt', document_amount__isnull=True, vat_amount__isnull=True)
                | Q(vat_category='exempt', vat_amount=0)
                | Q(vat_category='taxable', document_amount__isnull=True, vat_amount__isnull=True)
                | Q(vat_category='taxable', vat_amount__gte=0)),
                name='%(class)s_vat_amount'),
        ]


def decimal(value, *, nullable=True, places=CENT):
    if value is None and nullable:
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result >= Decimal('1000000000000'):
            raise ValueError
        result = result.quantize(places, rounding=ROUND_HALF_UP)
        if result >= Decimal('1000000000000'):
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Ожидается неотрицательное конечное десятичное число.')


def terms(obj):
    return {key: getattr(obj, key) for key in TERMS}


def set_terms(obj, patch):
    for key in TERMS:
        if key in patch:
            setattr(obj, key, patch[key])
    if obj.vat_mode not in ('included', 'excluded'):
        raise ValidationError('Неизвестный режим ввода НДС.')
    if obj.vat_category not in ('unknown', 'exempt', 'taxable'):
        raise ValidationError('Неизвестная категория НДС.')
    if obj.vat_category == 'taxable':
        obj.vat_rate = decimal(obj.vat_rate, nullable=False, places=Decimal('0.0001'))
        if obj.vat_rate > 100:
            raise ValidationError('Ставка НДС должна быть от 0 до 100%.')
    else:
        obj.vat_rate = None
    if obj.vat_category == 'unknown' and obj.vat_mode != 'included':
        raise ValidationError('Для НДС сверху укажите ставку или «Без НДС».')


def automatic_tax(amount, obj):
    if amount is None or obj.vat_category == 'unknown':
        return None
    if obj.vat_category == 'exempt':
        return Decimal('0.00')
    divisor = 100 + obj.vat_rate if obj.vat_mode == 'included' else Decimal(100)
    return (amount * obj.vat_rate / divisor).quantize(CENT, rounding=ROUND_HALF_UP)


def apply_facts(obj, gross_field, patch, *, gross_changed=False):
    """Правка исходных фактов и совместимой проекции price/cost (без save).

    Старый API price/cost по-прежнему принимает полную стоимость. Новый ввод идёт
    через document_amount. Смена режима переинтерпретирует исходную сумму явно.
    """
    if set(patch) - set(FACTS):
        raise ValidationError('Неизвестные налоговые поля строки документа.')
    gross = getattr(obj, gross_field)
    source = obj.document_amount if obj.document_amount is not None else gross
    manual = obj.vat_amount_manual
    entered_tax = obj.vat_amount
    if 'vat_amount' in patch:
        manual = patch['vat_amount'] is not None
        entered_tax = decimal(patch['vat_amount'])
    set_terms(obj, patch)
    if 'document_amount' in patch:
        source = decimal(patch['document_amount'])
    elif gross_changed:
        source = gross
        if source is not None and obj.vat_mode == 'excluded' and obj.vat_category == 'taxable':
            extracted = (gross * obj.vat_rate / (100 + obj.vat_rate)).quantize(CENT, rounding=ROUND_HALF_UP)
            source = gross - extracted
            if 'vat_amount' not in patch:
                entered_tax, manual = extracted, False
                patch = {'vat_amount': extracted, **patch}
    if source is None and gross_field == 'cost':
        raise ValidationError('Укажите сумму строки УПД; для бесплатной поставки — 0.')
    obj.document_amount = source
    expected = automatic_tax(source, obj)
    if source is None or obj.vat_category != 'taxable':
        if 'vat_amount' not in patch:
            manual = False
    tax = entered_tax if manual or patch.get('vat_amount') is not None else expected
    if source is None:
        if tax is not None:
            raise ValidationError('Сначала укажите сумму строки.')
    elif obj.vat_category == 'unknown' and tax is not None:
        raise ValidationError('Для суммы НДС укажите налоговую категорию.')
    elif obj.vat_category == 'exempt' and tax != 0:
        raise ValidationError('У строки «Без НДС» налог равен нулю.')
    elif obj.vat_mode == 'included' and tax is not None and tax > source:
        raise ValidationError('НДС не может превышать сумму строки с НДС.')
    obj.vat_amount = tax
    obj.vat_amount_manual = manual
    result = source + (tax or 0) if source is not None and obj.vat_mode == 'excluded' else source
    setattr(obj, gross_field, decimal(result))


def facts(obj, gross_field):
    gross = getattr(obj, gross_field)
    source = obj.document_amount if obj.document_amount is not None else gross
    if obj.document_amount is not None:
        gross = source + (obj.vat_amount or 0) if obj.vat_mode == 'excluded' else source
    expected = automatic_tax(source, obj)
    return wire({**terms(obj), 'document_amount': source, 'vat_amount': obj.vat_amount,
            'vat_amount_manual': obj.vat_amount_manual,
            'net_amount': gross - obj.vat_amount
                if gross is not None and obj.vat_amount is not None else None,
            'gross_amount': gross,
            'vat_difference': obj.vat_amount - expected
                if obj.vat_amount is not None and expected is not None else None})


def summary(doc, rows, gross_field):
    rows = list(rows)
    known = [r for r in rows if getattr(r, gross_field) is not None and r.vat_amount is not None]
    complete = len(known) == len(rows)
    gross = sum((getattr(r, gross_field) or Decimal(0) for r in rows), Decimal(0))
    tax = sum((r.vat_amount for r in known), Decimal(0)) if complete else None
    return {**terms(doc), 'document_total': doc.document_total,
            'document_vat_total': doc.document_vat_total,
            'gross_amount': gross, 'vat_amount': tax,
            'net_amount': gross - tax if tax is not None else None,
            'unknown_rows': len(rows) - len(known),
            'total_gap': gross - doc.document_total if doc.document_total is not None else None,
            'vat_gap': tax - doc.document_vat_total
                if tax is not None and doc.document_vat_total is not None else None}


def check_totals(doc, rows, gross_field):
    totals = summary(doc, rows, gross_field)
    if totals['total_gap'] not in (None, 0) or totals['vat_gap'] not in (None, 0):
        raise ValidationError('Суммы строк не совпадают с итогами документа — проверьте сумму и НДС.')
    if doc.document_vat_total is not None and totals['unknown_rows']:
        raise ValidationError('Для сверки НДС укажите налоговые данные всех строк.')


def wire(values):
    """Денежные факты в JSON — десятичными строками, без промежуточного float."""
    return {key: str(value) if isinstance(value, Decimal) else value
            for key, value in values.items()}
