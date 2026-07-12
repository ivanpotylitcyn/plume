"""Юнит-тесты движка волны 1 — гарантия корректности формул (вместо прод-обкатки).

Каждый тест строит минимальный сценарий и проверяет одну формулу.
"""
import os
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from plume import models
from plume import engine


def D(x):
    return Decimal(str(x))


def _cat(code='test', label='Тест'):
    """Категория-заглушка для тестов (волна 15: `Item.category` — обязательный FK).
    Класс изделия в движке логику не ветвит, поэтому одной общей категории хватает."""
    c, _ = models.Category.objects.get_or_create(code=code, defaults={'label': label})
    return c


# Изолированный MEDIA_ROOT для тестов вложений (волна 11): загрузки не пачкают
# рабочий backend/media; чистим на выходе модуля.
_TEST_MEDIA = tempfile.mkdtemp(prefix='plume-test-media-')


def tearDownModule():
    shutil.rmtree(_TEST_MEDIA, ignore_errors=True)


class EngineTestBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='t')
        self.main = models.Location.objects.create(code='MAIN', name='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', name='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.supplier = models.Counterparty.objects.create(name='Поставщик')

    def make_item(self, code, manufactured=False, kind=None):
        # `kind` — исторический хинт (движок по классу не ветвит); категория —
        # общая заглушка `_cat()`. `manufactured` → ось `produced` (волна 15).
        return models.Item.objects.create(
            design_item_id=code, description=code, category=_cat(),
            produced=manufactured)

    def receipt_lot(self, item, project, qty, purchase=None):
        r = models.Receipt.objects.create(
            number=f'UPD-{item.design_item_id}-{qty}', date='2026-05-01', contractor=self.supplier,
            project=project, user=self.user, purchase=purchase)
        lot = models.Lot.objects.create(item=item, project=project, origin=r, qty=D(qty))
        engine.rebuild_movements(lot)
        return lot


class RebuildAndStockTests(EngineTestBase):
    def test_receipt_lot_live_qty(self):
        lot = self.receipt_lot(self.make_item('A'), self.prj, 10)
        self.assertEqual(engine.lot_live_qty(lot), D(10))
        self.assertEqual(lot.movements.count(), 1)

    def test_kitting_issue_reduces_qty(self):
        comp = self.make_item('R')
        lot = self.receipt_lot(comp, self.prj, 100)
        dev = self.make_item('DEV', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1),
                                          status=models.DocStatus.DRAFT)
        models.StockLine.objects.create(document=k, lot=lot,
                                        location=self.main, qty=D(-30))
        engine.rebuild_movements(lot)
        self.assertEqual(engine.lot_live_qty(lot), D(70))

    def test_available_can_be_negative(self):
        comp = self.make_item('R')
        lot = self.receipt_lot(comp, self.prj, 5)
        dev = self.make_item('DEV', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1),
                                          status=models.DocStatus.DRAFT)
        models.StockLine.objects.create(document=k, lot=lot,
                                        location=self.main, qty=D(-8))
        engine.rebuild_movements(lot)
        self.assertEqual(engine.item_available(comp, self.prj), D(-3))
        self.assertTrue(engine.item_has_negative_lot(comp, self.prj))

    def test_reopen_then_delete_leaves_no_phantom(self):
        """Волна 13 Ф1: отмена = удаление (`cancelled` снят), но проведённую
        комплектацию с born-лотом сперва расфиксируют. Расфиксация чисто сносит
        лот-прибор (не фантом), удаление черновика освобождает компоненты.

        (Историческая грабля Ф1: прямое `posted.delete()` на MySQL упиралось в CHECK
        `exactly_one_origin`. В Ф2b дуга схлопнута в один CASCADE-FK `Lot.origin` — CHECK
        умер; замок «сперва расфиксировать» держит прикладной guard `delete_stock_document`.
        Тут проверяем корректный путь reopen→delete. См. JOURNAL 2026-07-09 Ф1/Ф2b.)"""
        comp = self.make_item('R')
        lot = self.receipt_lot(comp, self.prj, 10)
        dev = self.make_item('DEV', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1))
        engine.add_kitting_line(k, comp, lot, D(4))
        born = engine.close_kitting(k)              # posted + рождается лот-прибор
        self.assertTrue(models.Lot.objects.filter(pk=born.pk).exists())
        engine.reopen_kitting(k)                    # расфиксировать: born-лот снят
        self.assertFalse(models.Lot.objects.filter(pk=born.pk).exists())  # не фантом
        self.assertEqual(k.status, models.DocStatus.DRAFT)
        k.delete()                                  # черновик удаляется свободно
        engine.rebuild_movements(lot)               # компонент освобождён (нет −ISSUE)
        self.assertEqual(engine.lot_live_qty(lot), D(10))

    def test_stockline_rebuild_invariant_across_docs(self):
        """Волна 13 Ф0: единая `StockLine` покрывает 4 бывших таблицы строк-расхода.

        Один лот, тронутый разными документами-владельцами (комплектация/списание/
        передача) через знаковые `StockLine`, даёт те же остаток и движения, что и
        прежние раздельные строки — инвариант остатка при консолидации.
        """
        comp = self.make_item('R')
        lot = self.receipt_lot(comp, self.prj, 100)
        dev = self.make_item('DEV', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1),
                                          status=models.DocStatus.DRAFT)
        w = models.Writeoff.objects.create(project=self.prj, user=self.user,
                                           number='W-1', date='2026-06-01')
        cust = models.Project.objects.create(
            code='P2', name='Проект 2', kind=models.Project.Kind.EXTERNAL)
        t = models.Transfer.objects.create(project=self.prj, user=self.user,
                                            number='T-1', date='2026-06-01')
        # знаковые строки (− расход) трёх разных документов на один лот
        models.StockLine.objects.create(document=k, lot=lot, location=self.main, qty=D(-30))
        models.StockLine.objects.create(document=w, lot=lot, location=self.main, qty=D(-10))
        models.StockLine.objects.create(document=t, lot=lot, location=self.main, qty=D(-5))
        engine.rebuild_movements(lot)
        # 100 − 30 − 10 − 5 = 55; born-приход + три расхода = 4 движения
        self.assertEqual(engine.lot_live_qty(lot), D(55))
        self.assertEqual(lot.movements.count(), 4)
        srcs = set(lot.movements.values_list('source_type', flat=True))
        self.assertEqual(srcs, {'receipt', 'kitting', 'writeoff', 'transfer'})
        # exclusive-arc: строка ссылается ровно на один документ
        sl = models.StockLine.objects.filter(document=k).get()
        self.assertEqual(sl.doc_kind, 'kitting')
        self.assertLess(sl.qty, D(0))            # хранится со знаком (− расход)


class CoverageTests(EngineTestBase):
    def test_triple_split_segments(self):
        cov = engine._coverage(need=D(10), available=D(4), on_order=D(3))
        self.assertEqual(cov['have'], D(4))
        self.assertEqual(cov['on_order'], D(3))
        self.assertEqual(cov['to_order'], D(3))
        self.assertEqual(cov['status'], 'to_order')

    def test_fully_covered_is_available(self):
        cov = engine._coverage(need=D(10), available=D(12), on_order=D(0))
        self.assertEqual(cov['have'], D(10))
        self.assertEqual(cov['to_order'], D(0))
        self.assertEqual(cov['status'], 'available')

    def test_only_ordered_is_on_order(self):
        cov = engine._coverage(need=D(10), available=D(0), on_order=D(10))
        self.assertEqual(cov['status'], 'on_order')

    def test_negative_available_does_not_credit(self):
        cov = engine._coverage(need=D(10), available=D(-5), on_order=D(0))
        self.assertEqual(cov['have'], D(0))
        self.assertEqual(cov['to_order'], D(10))

    def test_worst_and_best_of(self):
        self.assertEqual(engine._worst_of(['available', 'to_order', 'on_order']),
                         'to_order')
        self.assertEqual(engine._best_of(['to_order', 'on_order']), 'on_order')


class OnOrderTests(EngineTestBase):
    def test_purchased_open_order_minus_received(self):
        item = self.make_item('SCR', kind='material')
        proc = models.Procurement.objects.create(user=self.user,
                                                 status=models.Procurement.Status.SENT)
        purchase = models.Purchase.objects.create(
            procurement=proc, project=self.prj, user=self.user,
            status=models.Purchase.Status.SENT)
        models.PurchaseLine.objects.create(purchase=purchase, item=item, qty=D(40))
        # поступило 15 по этому заказу
        self.receipt_lot(item, self.prj, 15, purchase=purchase)
        self.assertEqual(engine.item_on_order(item, self.prj), D(25))

    def test_draft_purchase_not_counted(self):
        item = self.make_item('SCR', kind='material')
        proc = models.Procurement.objects.create(user=self.user)
        purchase = models.Purchase.objects.create(
            procurement=proc, project=self.prj, user=self.user,
            status=models.Purchase.Status.DRAFT)
        models.PurchaseLine.objects.create(purchase=purchase, item=item, qty=D(40))
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))

    def test_manufactured_wip_is_on_order(self):
        board = self.make_item('BRD', manufactured=True)
        models.Kitting.objects.create(project=self.prj, target_item=board,
                                      user=self.user, qty=D(4),
                                      status=models.DocStatus.DRAFT)
        self.assertEqual(engine.item_on_order(board, self.prj), D(4))


class DeficitTests(EngineTestBase):
    def test_full_deficit_scenario(self):
        device = self.make_item('DEV', manufactured=True, kind='device')
        case = self.make_item('CASE')
        screw = self.make_item('SCR', kind='material')
        models.BomLine.objects.create(parent=device, component=case, qty=D(1))
        models.BomLine.objects.create(parent=device, component=screw, qty=D(4))
        models.ProjectDemand.objects.create(project=self.prj, target_item=device, qty=D(10))

        # CASE: на складе 12 → ✓
        self.receipt_lot(case, self.prj, 12)
        # SCR: заказано 25 (sent), склада нет → ●25 ▲15
        proc = models.Procurement.objects.create(user=self.user,
                                                 status=models.Procurement.Status.SENT)
        purchase = models.Purchase.objects.create(
            procurement=proc, project=self.prj, user=self.user,
            status=models.Purchase.Status.SENT)
        models.PurchaseLine.objects.create(purchase=purchase, item=screw, qty=D(25))

        d = engine.project_deficit(self.prj)
        dm = d['demands'][0]
        self.assertEqual(dm['status'], 'to_order')   # worst-of (SCR ▲)
        lines = {ln['component_design_item_id']: ln for ln in dm['lines']}
        self.assertEqual(lines['CASE']['status'], 'available')
        self.assertEqual(lines['CASE']['have'], D(10))
        self.assertEqual(lines['SCR']['need'], D(40))
        self.assertEqual(lines['SCR']['on_order'], D(25))
        self.assertEqual(lines['SCR']['to_order'], D(15))


class StockMapTests(EngineTestBase):
    def test_map_across_projects_sorted(self):
        white = models.Project.objects.create(
            code='WHITE', name='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        item = self.make_item('CASE')
        self.receipt_lot(item, self.prj, 12)
        inv = models.Inventory.objects.create(project=white, user=self.user,
                                              number='INV-1', date='2026-06-01')
        lot = models.Lot.objects.create(item=item, project=white, origin=inv, qty=D(5))
        engine.rebuild_movements(lot)

        m = engine.stock_map(item)
        self.assertEqual(len(m['rows']), 2)
        # белый склад идёт первым (мягкая сортировка)
        self.assertEqual(m['rows'][0]['project_code'], 'WHITE')
        self.assertEqual(m['rows'][0]['available'], D(5))
        self.assertEqual(m['rows'][1]['available'], D(12))

    def test_zero_available_excluded(self):
        item = self.make_item('CASE')
        lot = self.receipt_lot(item, self.prj, 0)
        m = engine.stock_map(item)
        self.assertEqual(m['rows'], [])


class KittingCockpitTests(EngineTestBase):
    """Волна 2: кокпит комплектации — призрачные строки, пайка, закрытие."""

    def setUp(self):
        super().setUp()
        self.device = self.make_item('DEV', manufactured=True,
                                     kind='device')
        self.case = self.make_item('CASE')
        self.res = self.make_item('RES')
        # прибор из 1 корпуса и 2 резисторов
        models.BomLine.objects.create(parent=self.device, component=self.case, qty=D(1))
        models.BomLine.objects.create(parent=self.device, component=self.res, qty=D(2))

    def make_kitting(self, qty=2):
        return models.Kitting.objects.create(
            project=self.prj, target_item=self.device, user=self.user,
            qty=D(qty), status=models.DocStatus.DRAFT)

    def test_ghost_rows_before_piercing(self):
        # склад пуст → обе призрачные строки красные (▲ to_order)
        k = self.make_kitting(qty=2)
        c = engine.kitting_cockpit(k)
        rows = {r['component_design_item_id']: r for r in c['rows']}
        self.assertEqual(rows['CASE']['need'], D(2))     # 1×2
        self.assertEqual(rows['RES']['need'], D(4))      # 2×2
        self.assertEqual(rows['CASE']['pierced'], D(0))
        self.assertEqual(rows['CASE']['ghost']['status'], 'to_order')
        self.assertEqual(c['cockpit_status'], 'to_order')

    def test_ghost_available_when_stock_exists(self):
        # есть лот корпуса → призрачная строка зелёная + лот-кандидат
        self.receipt_lot(self.case, self.prj, 10)
        k = self.make_kitting(qty=2)
        c = engine.kitting_cockpit(k)
        row = {r['component_design_item_id']: r for r in c['rows']}['CASE']
        self.assertEqual(row['ghost']['status'], 'available')
        self.assertEqual(len(row['ghost']['candidate_lots']), 1)
        self.assertEqual(row['ghost']['candidate_lots'][0]['live_qty'], D(10))

    def test_pierce_creates_line_and_issue(self):
        lot = self.receipt_lot(self.case, self.prj, 10)
        k = self.make_kitting(qty=2)
        engine.add_kitting_line(k, self.case, lot, D(2))
        # лот просел на 2 (ISSUE), строка BOM закрыта
        self.assertEqual(engine.lot_live_qty(lot), D(8))
        c = engine.kitting_cockpit(k)
        row = {r['component_design_item_id']: r for r in c['rows']}['CASE']
        self.assertEqual(row['pierced'], D(2))
        self.assertEqual(row['remaining'], D(0))
        self.assertIsNone(row['ghost'])          # покрыто — призрака нет
        self.assertEqual(len(row['real_lines']), 1)

    def test_pierce_rejects_foreign_project_lot(self):
        other = models.Project.objects.create(code='P2', name='Другой')
        lot = self.receipt_lot(self.case, other, 10)
        k = self.make_kitting(qty=1)
        with self.assertRaises(ValidationError):
            engine.add_kitting_line(k, self.case, lot, D(1))

    def test_pierce_rejects_wrong_component_lot(self):
        lot = self.receipt_lot(self.res, self.prj, 10)   # лот резистора
        k = self.make_kitting(qty=1)
        with self.assertRaises(ValidationError):
            engine.add_kitting_line(k, self.case, lot, D(1))   # ждём корпус

    def test_update_line_qty_rebuilds(self):
        lot = self.receipt_lot(self.case, self.prj, 10)
        k = self.make_kitting(qty=2)
        line = engine.add_kitting_line(k, self.case, lot, D(2))
        engine.update_kitting_line(line, D(5))
        self.assertEqual(engine.lot_live_qty(lot), D(5))

    def test_remove_line_restores_qty(self):
        lot = self.receipt_lot(self.case, self.prj, 10)
        k = self.make_kitting(qty=2)
        line = engine.add_kitting_line(k, self.case, lot, D(3))
        self.assertEqual(engine.lot_live_qty(lot), D(7))
        engine.remove_kitting_line(line)
        self.assertEqual(engine.lot_live_qty(lot), D(10))

    def test_close_births_device_lot_with_cost_snapshot(self):
        case_lot = self.receipt_lot(self.case, self.prj, 10)
        case_lot.unit_cost = D(800); case_lot.save()
        res_lot = self.receipt_lot(self.res, self.prj, 100)
        res_lot.unit_cost = D(1); res_lot.save()
        k = self.make_kitting(qty=2)
        engine.add_kitting_line(k, self.case, case_lot, D(2))   # 2×800
        engine.add_kitting_line(k, self.res, res_lot, D(4))     # 4×1
        lot = engine.close_kitting(k)
        k.refresh_from_db()
        self.assertEqual(k.status, models.DocStatus.POSTED)
        self.assertEqual(lot.qty, D(2))
        # (2×800 + 4×1) / 2 = 802
        self.assertEqual(lot.unit_cost, D('802.00'))
        self.assertEqual(engine.lot_live_qty(lot), D(2))

    def test_close_only_wip(self):
        k = self.make_kitting(qty=1)
        engine.close_kitting(k)
        with self.assertRaises(ValidationError):
            engine.close_kitting(k)

    def test_pierce_blocked_after_close(self):
        lot = self.receipt_lot(self.case, self.prj, 10)
        k = self.make_kitting(qty=1)
        engine.close_kitting(k)
        with self.assertRaises(ValidationError):
            engine.add_kitting_line(k, self.case, lot, D(1))

    def test_reopen_restores_wip_and_removes_lot(self):
        k = self.make_kitting(qty=1)
        lot = engine.close_kitting(k)
        engine.reopen_kitting(k)
        k.refresh_from_db()
        self.assertEqual(k.status, models.DocStatus.DRAFT)
        self.assertFalse(models.Lot.objects.filter(pk=lot.pk).exists())

    def test_reopen_blocked_when_device_consumed(self):
        k = self.make_kitting(qty=1)
        device_lot = engine.close_kitting(k)
        # прибор передан заказчику → потомок вниз, переоткрытие запрещено
        transfer = models.Transfer.objects.create(
            project=self.prj, user=self.user, date='2026-06-01', number='TN-1')
        models.StockLine.objects.create(document=transfer, lot=device_lot,
                                        location=self.main, qty=D(-1))
        engine.rebuild_movements(device_lot)
        with self.assertRaises(ValidationError):
            engine.reopen_kitting(k)


class ReceiptCockpitTests(EngineTestBase):
    """Волна 3: кокпит прихода — строки-лоты УПД, рождение +RECEIPT, замок."""

    def make_receipt(self, approved=False):
        return models.Receipt.objects.create(
            number='УПД-Т', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user,
            status=models.DocStatus.POSTED if approved else models.DocStatus.DRAFT)

    def test_add_lot_births_receipt_movement(self):
        r = self.make_receipt()
        case = self.make_item('CASE')
        lot = engine.add_receipt_lot(r, case, D(12), unit_cost=D(800),
                                     lot_name='Корпус Al')
        self.assertEqual(lot.project_id, r.project_id)   # проект наследован
        self.assertEqual(engine.lot_live_qty(lot), D(12))
        mv = lot.movements.get()
        self.assertEqual(mv.type, models.StockMovement.Type.RECEIPT)
        self.assertEqual(mv.qty, D(12))

    def test_cockpit_shows_lines_and_total(self):
        r = self.make_receipt()
        engine.add_receipt_lot(r, self.make_item('A'), D(2), unit_cost=D(100))
        engine.add_receipt_lot(r, self.make_item('B'), D(3), unit_cost=D(10))
        c = engine.receipt_cockpit(r)
        self.assertEqual(len(c['lots']), 2)
        self.assertEqual(c['total_cost'], D(230))        # 2×100 + 3×10
        self.assertFalse(c['approved'])

    def test_add_lot_rejects_nonpositive_qty(self):
        r = self.make_receipt()
        with self.assertRaises(ValidationError):
            engine.add_receipt_lot(r, self.make_item('A'), D(0))

    def test_update_lot_qty_rebuilds(self):
        r = self.make_receipt()
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(10))
        engine.update_receipt_lot(lot, qty=D(7))
        self.assertEqual(engine.lot_live_qty(lot), D(7))

    def test_update_lot_cost_and_name(self):
        r = self.make_receipt()
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.update_receipt_lot(lot, unit_cost=D(42), lot_name='Ы',
                                  part_number='PN-1')
        lot.refresh_from_db()
        self.assertEqual(lot.unit_cost, D(42))
        self.assertEqual(lot.lot_name, 'Ы')
        self.assertEqual(lot.part_number, 'PN-1')

    def test_remove_lot(self):
        r = self.make_receipt()
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.remove_receipt_lot(lot)
        self.assertFalse(models.Lot.objects.filter(pk=lot.pk).exists())

    def test_remove_blocked_when_consumed(self):
        r = self.make_receipt()
        comp = self.make_item('R')
        lot = engine.add_receipt_lot(r, comp, D(100))
        dev = self.make_item('DEV', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1),
                                          status=models.DocStatus.DRAFT)
        engine.add_kitting_line(k, comp, lot, D(30))   # спаяли — потреблён ниже
        with self.assertRaises(ValidationError):
            engine.remove_receipt_lot(lot)

    def test_approve_locks_edits(self):
        r = self.make_receipt()
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.approve_receipt(r)
        r.refresh_from_db()
        self.assertTrue(r.is_posted)
        with self.assertRaises(ValidationError):
            engine.update_receipt_lot(lot, qty=D(9))
        with self.assertRaises(ValidationError):
            engine.add_receipt_lot(r, self.make_item('B'), D(1))

    def test_approve_rejects_empty(self):
        r = self.make_receipt()
        with self.assertRaises(ValidationError):
            engine.approve_receipt(r)

    def test_unapprove_reenables_edits(self):
        r = self.make_receipt()
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.approve_receipt(r)
        engine.unapprove_receipt(r)
        r.refresh_from_db()
        self.assertFalse(r.is_posted)
        engine.update_receipt_lot(lot, qty=D(9))       # снова можно
        self.assertEqual(engine.lot_live_qty(lot), D(9))

    def test_received_lot_feeds_kitting_cockpit(self):
        # приход РЕЗ → лот сразу виден кокпиту комплектации как кандидат
        r = self.make_receipt()
        comp = self.make_item('R')
        engine.add_receipt_lot(r, comp, D(50))
        dev = self.make_item('DEV', manufactured=True)
        models.BomLine.objects.create(parent=dev, component=comp, qty=D(2))
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1),
                                          status=models.DocStatus.DRAFT)
        c = engine.kitting_cockpit(k)
        row = {r['component_design_item_id']: r for r in c['rows']}['R']
        self.assertEqual(row['ghost']['status'], 'available')
        self.assertEqual(len(row['ghost']['candidate_lots']), 1)


class PurchaseCockpitTests(EngineTestBase):
    """Волна 4: кокпит заказа — строки-обязательства, замок отправки, гашение
    приходом, мост «дефицит → заказ»."""

    def test_create_purchase_autocreates_procurement(self):
        p = engine.create_purchase(self.prj, self.user)
        self.assertEqual(p.status, models.Purchase.Status.DRAFT)
        self.assertIsNotNone(p.procurement_id)          # авто-родитель
        self.assertEqual(p.project_id, self.prj.id)

    def test_add_line_and_cockpit_totals(self):
        p = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(p, self.make_item('A'), D(10))
        engine.add_purchase_line(p, self.make_item('B'), D(5))
        c = engine.purchase_cockpit(p)
        self.assertEqual(len(c['rows']), 2)
        self.assertEqual(c['total_ordered'], D(15))
        self.assertEqual(c['total_received'], D(0))
        self.assertTrue(c['editable'])
        self.assertEqual(c['rows'][0]['status'], 'to_order')   # ждём поставки

    def test_add_line_rejects_duplicate_item(self):
        p = engine.create_purchase(self.prj, self.user)
        item = self.make_item('A')
        engine.add_purchase_line(p, item, D(10))
        with self.assertRaises(ValidationError):
            engine.add_purchase_line(p, item, D(3))

    def test_add_line_rejects_nonpositive(self):
        p = engine.create_purchase(self.prj, self.user)
        with self.assertRaises(ValidationError):
            engine.add_purchase_line(p, self.make_item('A'), D(0))

    def test_update_and_remove_line(self):
        p = engine.create_purchase(self.prj, self.user)
        line = engine.add_purchase_line(p, self.make_item('A'), D(10))
        engine.update_purchase_line(line, D(7))
        line.refresh_from_db()
        self.assertEqual(line.qty, D(7))
        engine.remove_purchase_line(line)
        self.assertFalse(models.PurchaseLine.objects.filter(pk=line.pk).exists())

    def test_send_counts_in_on_order(self):
        item = self.make_item('SCR', kind='material')
        p = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(p, item, D(40))
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))  # draft не в счёте
        engine.send_purchase(p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(40))

    def test_send_rejects_empty(self):
        p = engine.create_purchase(self.prj, self.user)
        with self.assertRaises(ValidationError):
            engine.send_purchase(p)

    def test_lines_locked_after_send(self):
        p = engine.create_purchase(self.prj, self.user)
        line = engine.add_purchase_line(p, self.make_item('A'), D(10))
        engine.send_purchase(p)
        with self.assertRaises(ValidationError):
            engine.update_purchase_line(line, D(5))
        with self.assertRaises(ValidationError):
            engine.add_purchase_line(p, self.make_item('B'), D(1))

    def test_unsend_reenables_and_drops_from_on_order(self):
        item = self.make_item('SCR', kind='material')
        p = engine.create_purchase(self.prj, self.user)
        line = engine.add_purchase_line(p, item, D(40))
        engine.send_purchase(p)
        engine.unsend_purchase(p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))
        engine.update_purchase_line(line, D(30))       # снова можно
        self.assertEqual(line.qty, D(30))

    def test_cancel_drops_from_on_order(self):
        item = self.make_item('SCR', kind='material')
        p = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(p, item, D(40))
        engine.send_purchase(p)
        engine.cancel_purchase(p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))
        with self.assertRaises(ValidationError):        # отменённый не отправить
            engine.send_purchase(p)
        engine.restore_purchase(p)
        self.assertEqual(p.status, models.Purchase.Status.DRAFT)

    def test_linked_receipt_reduces_on_order_and_closes_line(self):
        item = self.make_item('SCR', kind='material')
        p = engine.create_purchase(self.prj, self.user)
        line = engine.add_purchase_line(p, item, D(40))
        engine.send_purchase(p)
        # приход 15, связанный с заказом → поступило 15, «заказано» 25
        self.receipt_lot(item, self.prj, 15, purchase=p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(25))
        c = engine.purchase_cockpit(p)
        row = c['rows'][0]
        self.assertEqual(row['received'], D(15))
        self.assertEqual(row['remaining'], D(25))
        self.assertEqual(row['status'], 'on_order')     # ● частично
        self.assertEqual(len(c['receipts']), 1)
        # добираем остаток → строка закрыта (✓), «заказано» 0
        self.receipt_lot(item, self.prj, 25, purchase=p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))
        row = engine.purchase_cockpit(p)['rows'][0]
        self.assertEqual(row['status'], 'available')

    def test_set_receipt_purchase_rejects_foreign_project(self):
        other = models.Project.objects.create(
            code='P2', name='Проект 2', kind=models.Project.Kind.EXTERNAL)
        p = engine.create_purchase(other, self.user)
        r = models.Receipt.objects.create(
            number='УПД-Х', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        with self.assertRaises(ValidationError):
            engine.set_receipt_purchase(r, p)           # заказ чужого проекта

    def test_deficit_bridge_creates_and_increments_line(self):
        item = self.make_item('SCR', kind='material')
        p1 = engine.add_to_project_order(self.prj, item, D(15), self.user)
        self.assertEqual(p1.lines.get(item=item).qty, D(15))
        # повтор той же позиции — инкремент в том же черновике
        p2 = engine.add_to_project_order(self.prj, item, D(10), self.user)
        self.assertEqual(p1.id, p2.id)
        self.assertEqual(p2.lines.get(item=item).qty, D(25))


class TransferCockpitTests(EngineTestBase):
    """Волна 5: кокпит передачи — отгрузка партии заказчику (`−ISSUE`), пикер
    отдаваемых лотов, guard чужого проекта, коррекция строк."""

    def setUp(self):
        super().setUp()
        self.device = self.make_item('DEV', manufactured=True,
                                      kind='device')
        # готовое железо на складе проекта: лот 5 (как из комплектации/прихода)
        self.lot = self.receipt_lot(self.device, self.prj, 5)

    def test_add_line_issues_from_lot(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.add_transfer_line(t, self.lot, D(2))
        self.assertEqual(engine.lot_live_qty(self.lot), D(3))   # 5 − 2
        self.assertTrue(self.lot.movements.filter(type='ISSUE', qty=D(-2)).exists())

    def test_cockpit_totals_and_live(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.add_transfer_line(t, self.lot, D(2), display_name='Прибор зав.№7')
        c = engine.transfer_cockpit(t)
        self.assertEqual(c['number'], 'Н-1')
        self.assertEqual(c['total_qty'], D(2))
        self.assertEqual(len(c['lines']), 1)
        row = c['lines'][0]
        self.assertEqual(row['qty'], D(2))
        self.assertEqual(row['lot_live_qty'], D(3))
        self.assertEqual(row['display_name'], 'Прибор зав.№7')

    def test_default_display_name_from_lot(self):
        self.lot.lot_name = 'ЗН-42'
        self.lot.save(update_fields=['lot_name'])
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        line = engine.add_transfer_line(t, self.lot, D(1))
        self.assertIn('ЗН-42', line.display_name)               # авто-метка лота

    def test_create_rejects_empty_number(self):
        with self.assertRaises(ValidationError):
            engine.create_transfer(self.prj, self.user, '   ')

    def test_add_line_rejects_foreign_project_lot(self):
        other = models.Project.objects.create(
            code='P2', name='Проект 2', kind=models.Project.Kind.EXTERNAL)
        t = engine.create_transfer(other, self.user, 'Н-2')
        with self.assertRaises(ValidationError):
            engine.add_transfer_line(t, self.lot, D(1))         # лот чужого проекта

    def test_add_line_rejects_nonpositive(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        with self.assertRaises(ValidationError):
            engine.add_transfer_line(t, self.lot, D(0))

    def test_over_issue_drives_negative_not_clamped(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.add_transfer_line(t, self.lot, D(8))             # больше остатка 5
        self.assertEqual(engine.lot_live_qty(self.lot), D(-3))  # недостача информативна

    def test_update_qty_rebuilds_and_remove_restores(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        line = engine.add_transfer_line(t, self.lot, D(2))
        engine.update_transfer_line(line, qty=D(4))
        self.assertEqual(engine.lot_live_qty(self.lot), D(1))   # 5 − 4
        engine.update_transfer_line(line, display_name='новое имя')
        line.refresh_from_db()
        self.assertEqual(line.display_name, 'новое имя')
        engine.remove_transfer_line(line)
        self.assertEqual(engine.lot_live_qty(self.lot), D(5))   # источник восстановлен

    def test_available_lots_picker(self):
        # ещё один лот проекта + чужой проект + нулевой остаток → в пикере только живой свой
        other = models.Project.objects.create(
            code='P2', name='Проект 2', kind=models.Project.Kind.EXTERNAL)
        self.receipt_lot(self.device, other, 3)                 # чужой проект
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.add_transfer_line(t, self.lot, D(5))             # свой лот в ноль
        picker = engine.project_available_lots(self.prj)
        self.assertEqual(picker, [])                            # живых своих лотов нет
        self.assertEqual(len(engine.project_available_lots(other)), 1)

    def test_post_locks_edits(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        line = engine.add_transfer_line(t, self.lot, D(2))
        engine.post_transfer(t)
        self.assertTrue(engine.transfer_cockpit(t)['posted'])
        with self.assertRaises(ValidationError):
            engine.update_transfer_line(line, qty=D(1))
        with self.assertRaises(ValidationError):
            engine.add_transfer_line(t, self.lot, D(1))
        with self.assertRaises(ValidationError):
            engine.remove_transfer_line(line)

    def test_post_rejects_empty(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        with self.assertRaises(ValidationError):
            engine.post_transfer(t)

    def test_unpost_reenables_edits(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        line = engine.add_transfer_line(t, self.lot, D(2))
        engine.post_transfer(t)
        engine.unpost_transfer(t)
        self.assertFalse(engine.transfer_cockpit(t)['posted'])
        engine.update_transfer_line(line, qty=D(3))            # снова можно
        self.assertEqual(engine.lot_live_qty(self.lot), D(2))

    def test_item_shipments_projection(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-7')
        engine.add_transfer_line(t, self.lot, D(2), display_name='Прибор №7')
        rows = engine.item_shipments(self.device)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['number'], 'Н-7')
        self.assertEqual(rows[0]['qty'], D(2))
        self.assertEqual(rows[0]['display_name'], 'Прибор №7')
        self.assertFalse(rows[0]['posted'])


class WriteoffCockpitTests(EngineTestBase):
    """Волна 6: списание — чистый `−ISSUE` из проекта (серый путь), guard чужого
    проекта, коррекция строк, пересписание в минус (не клампим)."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')
        self.lot = self.receipt_lot(self.item, self.prj, 10)

    def test_add_line_issues_from_lot(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1', reason='брак')
        engine.add_writeoff_line(w, self.lot, D(4))
        self.assertEqual(engine.lot_live_qty(self.lot), D(6))
        self.assertTrue(self.lot.movements.filter(type='ISSUE', qty=D(-4)).exists())

    def test_cockpit_totals(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1', reason='брак')
        engine.add_writeoff_line(w, self.lot, D(4))
        c = engine.writeoff_cockpit(w)
        self.assertEqual(c['number'], 'СП-1')
        self.assertEqual(c['reason'], 'брак')
        self.assertEqual(c['total_qty'], D(4))
        self.assertEqual(c['lines'][0]['lot_live_qty'], D(6))

    def test_create_rejects_empty_number(self):
        with self.assertRaises(ValidationError):
            engine.create_writeoff(self.prj, self.user, '  ')

    def test_add_line_rejects_foreign_project(self):
        other = models.Project.objects.create(
            code='P2', name='Проект 2', kind=models.Project.Kind.EXTERNAL)
        w = engine.create_writeoff(other, self.user, 'СП-2')
        with self.assertRaises(ValidationError):
            engine.add_writeoff_line(w, self.lot, D(1))

    def test_add_line_rejects_nonpositive(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1')
        with self.assertRaises(ValidationError):
            engine.add_writeoff_line(w, self.lot, D(0))

    def test_over_writeoff_negative_not_clamped(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1')
        engine.add_writeoff_line(w, self.lot, D(14))
        self.assertEqual(engine.lot_live_qty(self.lot), D(-4))

    def test_update_and_remove_restores(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1')
        line = engine.add_writeoff_line(w, self.lot, D(4))
        engine.update_writeoff_line(line, D(7))
        self.assertEqual(engine.lot_live_qty(self.lot), D(3))
        engine.remove_writeoff_line(line)
        self.assertEqual(engine.lot_live_qty(self.lot), D(10))


class RequisitionCockpitTests(EngineTestBase):
    """Волна 6: требование/отпочкование — `−ISSUE` источника + рождение
    лота-потомка (`+RECEIPT`) у получателя с наследованием цены/провенанса."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')
        self.src = self.receipt_lot(self.item, self.prj, 10)
        self.src.unit_cost = D('2.50')
        self.src.part_number = 'ЗН-9'
        self.src.save(update_fields=['unit_cost', 'part_number'])
        self.white = models.Project.objects.create(
            code='WHITE', name='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)

    def test_add_line_issues_source_and_births_child(self):
        req = engine.create_requisition(self.white, self.user, 'ТР-1')
        engine.add_requisition_line(req, self.src, D(4))
        self.assertEqual(engine.lot_live_qty(self.src), D(6))    # источник просел
        born = engine._requisition_born_lot(req, self.src)
        self.assertIsNotNone(born)
        self.assertEqual(born.project_id, self.white.id)
        self.assertEqual(born.qty, D(4))
        self.assertEqual(born.unit_cost, D('2.50'))              # цена унаследована
        self.assertEqual(born.predecessor_id, self.src.id)      # генеалогия
        self.assertEqual(engine.lot_live_qty(born), D(4))       # +RECEIPT у потомка

    def test_cockpit_shows_source_and_born(self):
        req = engine.create_requisition(self.white, self.user, 'ТР-1')
        engine.add_requisition_line(req, self.src, D(4))
        c = engine.requisition_cockpit(req)
        self.assertEqual(c['total_qty'], D(4))
        row = c['lines'][0]
        self.assertEqual(row['source_project_code'], self.prj.code)
        self.assertEqual(row['source_live_qty'], D(6))
        self.assertIsNotNone(row['born_lot_id'])

    def test_same_project_rejected(self):
        req = engine.create_requisition(self.prj, self.user, 'ТР-1')
        with self.assertRaises(ValidationError):
            engine.add_requisition_line(req, self.src, D(1))    # источник = получатель

    def test_duplicate_source_rejected(self):
        req = engine.create_requisition(self.white, self.user, 'ТР-1')
        engine.add_requisition_line(req, self.src, D(2))
        with self.assertRaises(ValidationError):
            engine.add_requisition_line(req, self.src, D(1))

    def test_update_syncs_source_and_child(self):
        req = engine.create_requisition(self.white, self.user, 'ТР-1')
        line = engine.add_requisition_line(req, self.src, D(4))
        engine.update_requisition_line(line, D(7))
        born = engine._requisition_born_lot(req, self.src)
        self.assertEqual(engine.lot_live_qty(self.src), D(3))
        self.assertEqual(engine.lot_live_qty(born), D(7))

    def test_remove_restores_source_and_deletes_child(self):
        req = engine.create_requisition(self.white, self.user, 'ТР-1')
        line = engine.add_requisition_line(req, self.src, D(4))
        engine.remove_requisition_line(line)
        self.assertEqual(engine.lot_live_qty(self.src), D(10))
        self.assertIsNone(engine._requisition_born_lot(req, self.src))

    def test_all_available_lots_picker(self):
        rows = engine.all_available_lots()
        self.assertTrue(any(r['lot_id'] == self.src.id and
                            r['project_code'] == self.prj.code for r in rows))


class ProjectClosureTests(EngineTestBase):
    """Волна 6: панель закрытия (остаточные лоты → 0) + мягкий замок статуса +
    мосты «списать»/«на баланс»."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')
        self.lot = self.receipt_lot(self.item, self.prj, 10)

    def test_closure_lists_residuals_and_blocks(self):
        c = engine.project_closure(self.prj)
        self.assertEqual(len(c['residuals']), 1)
        self.assertEqual(c['residual_positive'], D(10))
        self.assertFalse(c['can_close'])
        with self.assertRaises(ValidationError):
            engine.close_project(self.prj)

    def test_writeoff_bridge_then_close(self):
        engine.writeoff_lot(self.prj, self.lot, D(10), self.user)
        c = engine.project_closure(self.prj)
        self.assertEqual(c['residuals'], [])
        self.assertTrue(c['can_close'])
        engine.close_project(self.prj)
        self.prj.refresh_from_db()
        self.assertEqual(self.prj.status, models.Project.Status.CLOSED)
        self.assertIsNotNone(self.prj.closed_at)

    def test_requisition_bridge_moves_to_white(self):
        engine.requisition_lot(self.prj, self.lot, D(10), self.user)
        self.assertEqual(engine.lot_live_qty(self.lot), D(0))
        white = engine._internal_project(models.Project.Kind.INTERNAL_STOCK)
        moved = engine.item_available(self.item, white)
        self.assertEqual(moved, D(10))                          # оказалось на балансе
        self.assertTrue(engine.project_closure(self.prj)['can_close'])

    def test_negative_residual_is_anomaly_and_blocks(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1')
        engine.add_writeoff_line(w, self.lot, D(14))            # пересписали → −4
        c = engine.project_closure(self.prj)
        self.assertEqual(c['anomaly_count'], 1)
        self.assertTrue(c['residuals'][0]['anomaly'])
        self.assertFalse(c['can_close'])

    def test_internal_project_not_closable(self):
        white = models.Project.objects.create(
            code='WHITE', name='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        c = engine.project_closure(white)
        self.assertFalse(c['is_external'])
        self.assertFalse(c['can_close'])
        with self.assertRaises(ValidationError):
            engine.close_project(white)

    def test_reopen_restores_active(self):
        engine.writeoff_lot(self.prj, self.lot, D(10), self.user)
        engine.close_project(self.prj)
        engine.reopen_project(self.prj)
        self.prj.refresh_from_db()
        self.assertEqual(self.prj.status, models.Project.Status.ACTIVE)
        self.assertIsNone(self.prj.closed_at)


class HeaderEditTests(EngineTestBase):
    """Волна 6 (докрутка): правка шапки кокпитов — номер/дата/мягкие поля,
    read-only под замком, nullable-дата очищается."""

    def test_transfer_header_edit_and_lock(self):
        dev = self.make_item('DEV', manufactured=True, kind='device')
        lot = self.receipt_lot(dev, self.prj, 5)
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.update_transfer(t, number='Н-99', date='2026-06-15')
        t.refresh_from_db()
        self.assertEqual(t.number, 'Н-99')
        self.assertEqual(str(t.date), '2026-06-15')
        with self.assertRaises(ValidationError):
            engine.update_transfer(t, number='   ')          # пустой номер
        engine.add_transfer_line(t, lot, D(1))
        engine.post_transfer(t)
        with self.assertRaises(ValidationError):
            engine.update_transfer(t, number='Н-100')        # под замком нельзя

    def test_receipt_header_locked(self):
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01',
            contractor=self.supplier, project=self.prj, user=self.user)
        engine.add_receipt_lot(r, self.make_item('A'), D(2))
        engine.update_receipt(r, number='U-2')
        r.refresh_from_db()
        self.assertEqual(r.number, 'U-2')
        engine.approve_receipt(r)
        with self.assertRaises(ValidationError):
            engine.update_receipt(r, number='U-3')

    def test_purchase_note_and_clear_date(self):
        p = engine.create_purchase(self.prj, self.user, date='2026-05-01', note='x')
        engine.update_purchase(p, note='новое', date='')     # '' → NULL (nullable)
        p.refresh_from_db()
        self.assertEqual(p.note, 'новое')
        self.assertIsNone(p.date)

    def test_kitting_qty_rescales_needs(self):
        comp = self.make_item('R')
        self.receipt_lot(comp, self.prj, 100)
        dev = self.make_item('DEV', manufactured=True)
        models.BomLine.objects.create(parent=dev, component=comp, qty=D(2))
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
            user=self.user, qty=D(1), status=models.DocStatus.DRAFT)
        self.assertEqual(engine.kitting_cockpit(k)['rows'][0]['need'], D(2))
        engine.update_kitting(k, qty=D(3))
        self.assertEqual(engine.kitting_cockpit(k)['rows'][0]['need'], D(6))
        engine.close_kitting(k)
        with self.assertRaises(ValidationError):
            engine.update_kitting(k, qty=D(4))               # не wip — нельзя

    def test_writeoff_and_requisition_header(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1')
        engine.update_writeoff(w, number='СП-2', reason='брак')
        w.refresh_from_db()
        self.assertEqual((w.number, w.reason), ('СП-2', 'брак'))
        white = models.Project.objects.create(code='WHITE', name='Склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        req = engine.create_requisition(white, self.user, 'ТР-1')
        engine.update_requisition(req, number='ТР-2', date='2026-06-01')
        req.refresh_from_db()
        self.assertEqual(req.number, 'ТР-2')


class CommandDeficitTests(EngineTestBase):
    """Волна 7: командный свод — Σ проектных дефицитов по Item, без перенеттинга."""

    def _device_with_screw(self, screw, qty_per, suffix=''):
        dev = self.make_item(f'DEV{screw.design_item_id}{suffix}', manufactured=True,
                             kind='device')
        models.BomLine.objects.create(parent=dev, component=screw, qty=D(qty_per))
        return dev

    def test_rolls_up_by_item_across_projects(self):
        scr = self.make_item('SCR', kind='material')
        dev = self._device_with_screw(scr, 4)
        prj2 = models.Project.objects.create(code='P2', name='Проект 2',
                                             kind=models.Project.Kind.EXTERNAL)
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=prj2, target_item=dev, qty=D(5))

        rows = {r['item_design_item_id']: r for r in engine.command_deficit()['rows']}
        row = rows['SCR']
        self.assertEqual(row['need'], D(60))         # 40 + 20
        self.assertEqual(row['to_order'], D(60))     # склада/заказов нет
        self.assertEqual(row['status'], 'to_order')
        self.assertEqual(len(row['by_project']), 2)

    def test_stock_and_order_no_cross_project_netting(self):
        scr = self.make_item('SCR', kind='material')
        dev = self._device_with_screw(scr, 4)
        prj2 = models.Project.objects.create(code='P2', name='Проект 2',
                                             kind=models.Project.Kind.EXTERNAL)
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=prj2, target_item=dev, qty=D(5))
        # склад лежит только в P1 (10 шт) — НЕ должен гасить нужду P2
        self.receipt_lot(scr, self.prj, 10)

        row = {r['item_design_item_id']: r for r in engine.command_deficit()['rows']}['SCR']
        self.assertEqual(row['have'], D(10))          # только P1 покрыт
        self.assertEqual(row['to_order'], D(50))      # 30 (P1) + 20 (P2), не 40
        self.assertEqual(row['need'], D(60))

    def test_closed_and_internal_projects_excluded(self):
        scr = self.make_item('SCR', kind='material')
        dev = self._device_with_screw(scr, 2)
        closed = models.Project.objects.create(code='PC', name='Закрытый',
            kind=models.Project.Kind.EXTERNAL, status=models.Project.Status.CLOSED)
        white = models.Project.objects.create(code='WHITE', name='Склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        models.ProjectDemand.objects.create(project=closed, target_item=dev, qty=D(3))
        models.ProjectDemand.objects.create(project=white, target_item=dev, qty=D(3))
        self.assertEqual(engine.command_deficit()['rows'], [])

    def test_intra_project_need_aggregated_across_demands(self):
        # два прибора в одном проекте делят компонент → потребность суммируется,
        # покрытие считается один раз (одна by_project-строка на проект)
        scr = self.make_item('SCR', kind='material')
        dev_a = self._device_with_screw(scr, 4, suffix='A')
        dev_b = self._device_with_screw(scr, 3, suffix='B')
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev_a, qty=D(2))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev_b, qty=D(2))

        row = {r['item_design_item_id']: r for r in engine.command_deficit()['rows']}['SCR']
        self.assertEqual(row['need'], D(14))          # 2×4 + 2×3
        self.assertEqual(len(row['by_project']), 1)   # агрегат по проекту

    def test_sorted_worst_first(self):
        red = self.make_item('RED', kind='material')
        green = self.make_item('GRN', kind='material')
        dev = self.make_item('DEVX', manufactured=True, kind='device')
        models.BomLine.objects.create(parent=dev, component=red, qty=D(1))
        models.BomLine.objects.create(parent=dev, component=green, qty=D(1))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(5))
        self.receipt_lot(green, self.prj, 100)        # GRN покрыт ✓, RED красный ▲

        codes = [r['item_design_item_id'] for r in engine.command_deficit()['rows']]
        self.assertEqual(codes, ['RED', 'GRN'])       # красное наверх


class ProcurementCockpitTests(EngineTestBase):
    """Волна 7: записываемый план закупки — строки, замок отправки, мост, xlsx."""

    def test_create_and_cockpit_totals(self):
        p = engine.create_procurement(self.user, note='весна')
        engine.add_procurement_line(p, self.make_item('A'), D(10))
        engine.add_procurement_line(p, self.make_item('B'), D(5))
        c = engine.procurement_cockpit(p)
        self.assertEqual(len(c['lines']), 2)
        self.assertEqual(c['total_qty'], D(15))
        self.assertTrue(c['editable'])
        self.assertEqual(c['status'], models.Procurement.Status.DRAFT)
        self.assertEqual(c['note'], 'весна')

    def test_add_line_rejects_duplicate_and_nonpositive(self):
        p = engine.create_procurement(self.user)
        item = self.make_item('A')
        engine.add_procurement_line(p, item, D(10))
        with self.assertRaises(ValidationError):
            engine.add_procurement_line(p, item, D(3))
        with self.assertRaises(ValidationError):
            engine.add_procurement_line(p, self.make_item('B'), D(0))

    def test_update_and_remove_line(self):
        p = engine.create_procurement(self.user)
        line = engine.add_procurement_line(p, self.make_item('A'), D(10))
        engine.update_procurement_line(line, D(7))
        line.refresh_from_db()
        self.assertEqual(line.qty, D(7))
        engine.remove_procurement_line(line)
        self.assertFalse(models.ProcurementLine.objects.filter(pk=line.pk).exists())

    def test_send_locks_and_rejects_empty(self):
        p = engine.create_procurement(self.user)
        with self.assertRaises(ValidationError):
            engine.send_procurement(p)                 # пустую нельзя
        line = engine.add_procurement_line(p, self.make_item('A'), D(10))
        engine.send_procurement(p)
        self.assertEqual(p.status, models.Procurement.Status.SENT)
        with self.assertRaises(ValidationError):
            engine.update_procurement_line(line, D(5))  # строки под замком
        with self.assertRaises(ValidationError):
            engine.add_procurement_line(p, self.make_item('B'), D(1))

    def test_unsend_cancel_restore(self):
        p = engine.create_procurement(self.user)
        line = engine.add_procurement_line(p, self.make_item('A'), D(10))
        engine.send_procurement(p)
        engine.unsend_procurement(p)
        engine.update_procurement_line(line, D(30))    # снова можно
        self.assertEqual(line.qty, D(30))
        engine.send_procurement(p)
        engine.cancel_procurement(p)
        with self.assertRaises(ValidationError):
            engine.send_procurement(p)                 # отменённую не отправить
        engine.restore_procurement(p)
        self.assertEqual(p.status, models.Procurement.Status.DRAFT)

    def test_bridge_add_to_procurement_creates_and_increments(self):
        item = self.make_item('SCR', kind='material')
        p1 = engine.add_to_procurement(item, D(15), self.user)
        self.assertEqual(p1.lines.get(item=item).qty, D(15))
        p2 = engine.add_to_procurement(item, D(10), self.user)
        self.assertEqual(p1.id, p2.id)                 # тот же черновик
        self.assertEqual(p2.lines.get(item=item).qty, D(25))

    def test_bridge_ignores_solo_purchase_stub(self):
        # заказ волны 4 плодит 1:1-заглушку Procurement — мост её не должен трогать
        engine.create_purchase(self.prj, self.user)      # заглушка (draft, с purchase)
        item = self.make_item('SCR', kind='material')
        p = engine.add_to_procurement(item, D(5), self.user)
        self.assertFalse(p.purchases.exists())           # это чистый план, не заглушка
        self.assertEqual(list(engine._plan_procurements()), [p])  # заглушки нет в списке

    def test_update_header(self):
        p = engine.create_procurement(self.user)
        engine.update_procurement(p, date='2026-07-10', note='осень')
        p.refresh_from_db()
        self.assertEqual(str(p.date), '2026-07-10')
        self.assertEqual(p.note, 'осень')
        engine.update_procurement(p, date='')          # пустая строка → NULL
        p.refresh_from_db()
        self.assertIsNone(p.date)

    def test_xlsx_bytes_have_header_and_rows(self):
        from io import BytesIO

        from openpyxl import load_workbook
        p = engine.create_procurement(self.user)
        engine.add_procurement_line(p, self.make_item('R100'), D(12))
        data = engine.procurement_xlsx(p)
        self.assertTrue(data)                          # непустой байт-поток
        ws = load_workbook(BytesIO(data)).active
        self.assertEqual(ws['A1'].value, 'Артикул')
        self.assertEqual(ws['A2'].value, 'R100')
        self.assertEqual(ws['C2'].value, 12)


class PeggingTests(EngineTestBase):
    """Волна 8: нарезка плана (Procurement) на проектные заказы (Purchase)."""

    def setUp(self):
        super().setUp()
        self.prj2 = models.Project.objects.create(
            code='P2', name='Проект 2', kind=models.Project.Kind.EXTERNAL)
        self.scr = self.make_item('SCR', kind='material')
        dev = self.make_item('DEV', manufactured=True, kind='device')
        models.BomLine.objects.create(parent=dev, component=self.scr, qty=D(4))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=self.prj2, target_item=dev, qty=D(5))
        self.plan = engine.create_procurement(self.user, note='свод')      # need 40 + 20
        engine.add_procurement_line(self.plan, self.scr, D(60))

    def test_peg_creates_project_purchase_under_plan(self):
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(40), self.user)
        pu = self.plan.purchases.get(project=self.prj)
        self.assertEqual(pu.procurement_id, self.plan.id)   # под планом, не solo-заглушка
        self.assertEqual(pu.status, models.Purchase.Status.DRAFT)
        self.assertEqual(pu.lines.get(item=self.scr).qty, D(40))
        # повторный пег — инкремент в тот же заказ
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(10), self.user)
        self.assertEqual(self.plan.purchases.count(), 1)
        self.assertEqual(pu.lines.get(item=self.scr).qty, D(50))

    def test_autopeg_distributes_and_idempotent(self):
        engine.autopeg_procurement(self.plan, self.user)
        p1 = self.plan.purchases.get(project=self.prj)
        p2 = self.plan.purchases.get(project=self.prj2)
        self.assertEqual(p1.lines.get(item=self.scr).qty, D(40))     # по наводке свода
        self.assertEqual(p2.lines.get(item=self.scr).qty, D(20))
        row = engine.procurement_pegging(self.plan)['rows'][0]
        self.assertEqual(row['pegged'], D(60))
        self.assertEqual(row['remaining'], D(0))
        self.assertEqual(row['status'], 'available')
        # идемпотентность — повтор ничего не добавляет
        engine.autopeg_procurement(self.plan, self.user)
        self.assertEqual(p1.lines.get(item=self.scr).qty, D(40))
        self.assertEqual(self.plan.purchases.count(), 2)

    def test_peg_guards(self):
        with self.assertRaises(ValidationError):            # item не в плане
            engine.peg_procurement_line(self.plan, self.make_item('OTH'),
                                        self.prj, D(1), self.user)
        with self.assertRaises(ValidationError):            # неположительное кол-во
            engine.peg_procurement_line(self.plan, self.scr, self.prj, D(0), self.user)
        white = models.Project.objects.create(code='WHITE', name='Свой склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        with self.assertRaises(ValidationError):            # не внешний проект
            engine.peg_procurement_line(self.plan, self.scr, white, D(1), self.user)
        closed = models.Project.objects.create(code='CL', name='Закрыт',
            kind=models.Project.Kind.EXTERNAL, status=models.Project.Status.CLOSED)
        with self.assertRaises(ValidationError):            # не активный проект
            engine.peg_procurement_line(self.plan, self.scr, closed, D(1), self.user)

    def test_unpeg_removes_and_blocks_sent(self):
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(40), self.user)
        engine.unpeg_procurement_line(self.plan, self.scr, self.prj)
        pu = self.plan.purchases.get(project=self.prj)
        self.assertFalse(pu.lines.exists())                 # пег снят
        # пег в отправленном заказе — снять нельзя, пока не снят send
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(40), self.user)
        engine.send_purchase(pu)
        with self.assertRaises(ValidationError):
            engine.unpeg_procurement_line(self.plan, self.scr, self.prj)

    def test_plan_list_includes_pegged_excludes_solo(self):
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(10), self.user)
        engine.create_purchase(self.prj, self.user)         # solo-заглушка (purchases, без строк)
        ids = {p.id for p in engine._plan_procurements()}
        self.assertEqual(ids, {self.plan.id})               # пегнутый план виден, заглушка — нет


class ClosureHttpTests(TestCase):
    """Волна 6: HTTP-путь через test Client — провязка urls/views + мапинг ошибок."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.main = models.Location.objects.create(code='MAIN', name='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', name='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.item = models.Item.objects.create(design_item_id='R100', description='R100', category=_cat())
        self.sup = models.Counterparty.objects.create(name='П')
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01',
            contractor=self.sup, project=self.prj,
            user=get_user_model().objects.first())
        self.lot = models.Lot.objects.create(item=self.item, project=self.prj,
            origin=r, qty=D(10))
        engine.rebuild_movements(self.lot)
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_writeoff_flow(self):
        r = self.c.post('/api/writeoffs/', {'project_id': self.prj.id,
            'number': 'СП-1', 'reason': 'брак'}, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        wid = r.json()['id']
        r = self.c.post(f'/api/writeoffs/{wid}/lines/',
            {'lot_id': self.lot.id, 'qty': 4}, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(float(r.json()['total_qty']), 4.0)
        # чужой проект → 400
        other = models.Project.objects.create(code='P2', name='П2',
            kind=models.Project.Kind.EXTERNAL)
        r2 = self.c.post('/api/writeoffs/', {'project_id': other.id, 'number': 'СП-2'},
            content_type='application/json')
        w2 = r2.json()['id']
        bad = self.c.post(f'/api/writeoffs/{w2}/lines/',
            {'lot_id': self.lot.id, 'qty': 1}, content_type='application/json')
        self.assertEqual(bad.status_code, 400)

    def test_closure_bridges_and_lock(self):
        panel = self.c.get(f'/api/projects/{self.prj.id}/closure/').json()
        self.assertFalse(panel['can_close'])
        self.assertEqual(len(panel['residuals']), 1)
        # мост «на баланс» → белый, остаток в 0, можно закрыть
        r = self.c.post(f'/api/projects/{self.prj.id}/stock-lot/',
            {'lot_id': self.lot.id, 'qty': 10}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['can_close'])
        # закрытие 200 + повторное закрытие → 400
        c1 = self.c.post(f'/api/projects/{self.prj.id}/close/')
        self.assertEqual(c1.status_code, 200)
        self.assertEqual(c1.json()['status'], 'closed')
        c2 = self.c.post(f'/api/projects/{self.prj.id}/close/')
        self.assertEqual(c2.status_code, 400)
        # переоткрытие
        ro = self.c.post(f'/api/projects/{self.prj.id}/reopen/')
        self.assertEqual(ro.json()['status'], 'active')

    def test_requisition_flow(self):
        white = models.Project.objects.create(code='WHITE', name='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        r = self.c.post('/api/requisitions/', {'project_id': white.id, 'number': 'ТР-1'},
            content_type='application/json')
        self.assertEqual(r.status_code, 201)
        rid = r.json()['id']
        line = self.c.post(f'/api/requisitions/{rid}/lines/',
            {'source_lot_id': self.lot.id, 'qty': 3}, content_type='application/json')
        self.assertEqual(line.status_code, 201)
        self.assertIsNotNone(line.json()['lines'][0]['born_lot_id'])
        picker = self.c.get('/api/available-lots/')
        self.assertEqual(picker.status_code, 200)


class ProcurementHttpTests(TestCase):
    """Волна 7: HTTP-путь — свод, записываемый Procurement, мост, order.xlsx."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.prj = models.Project.objects.create(
            code='P1', name='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.scr = models.Item.objects.create(design_item_id='SCR', description='Винт',
            category=_cat())
        self.dev = models.Item.objects.create(design_item_id='DEV', description='Прибор',
            category=_cat(), produced=True)
        models.BomLine.objects.create(parent=self.dev, component=self.scr, qty=D(4))
        models.ProjectDemand.objects.create(project=self.prj, target_item=self.dev,
            qty=D(10))
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_command_deficit_and_bridge(self):
        svod = self.c.get('/api/command-deficit/')
        self.assertEqual(svod.status_code, 200)
        rows = {r['item_design_item_id']: r for r in svod.json()['rows']}
        self.assertEqual(float(rows['SCR']['to_order']), 40.0)
        # мост «свод → закупка» создаёт черновик
        add = self.c.post('/api/command-deficit/add-to-procurement/',
            {'item_id': self.scr.id, 'qty': 40}, content_type='application/json')
        self.assertEqual(add.status_code, 201)
        pid = add.json()['procurement_id']
        cockpit = self.c.get(f'/api/procurements/{pid}/').json()
        self.assertEqual(float(cockpit['total_qty']), 40.0)

    def test_procurement_crud_lock_and_xlsx(self):
        r = self.c.post('/api/procurements/', {'note': 'весна'},
            content_type='application/json')
        self.assertEqual(r.status_code, 201)
        pid = r.json()['id']
        line = self.c.post(f'/api/procurements/{pid}/lines/',
            {'item_id': self.scr.id, 'qty': 12}, content_type='application/json')
        self.assertEqual(line.status_code, 201)
        # дубль item → 400
        dup = self.c.post(f'/api/procurements/{pid}/lines/',
            {'item_id': self.scr.id, 'qty': 1}, content_type='application/json')
        self.assertEqual(dup.status_code, 400)
        # отправка → строки под замком
        sent = self.c.post(f'/api/procurements/{pid}/send/')
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.json()['status'], 'sent')
        locked = self.c.post(f'/api/procurements/{pid}/lines/',
            {'item_id': self.dev.id, 'qty': 1}, content_type='application/json')
        self.assertEqual(locked.status_code, 400)
        # выгрузка xlsx — бинарное тело, xlsx content-type
        xlsx = self.c.get(f'/api/procurements/{pid}/order.xlsx')
        self.assertEqual(xlsx.status_code, 200)
        self.assertIn('spreadsheetml', xlsx['Content-Type'])
        self.assertTrue(xlsx['Content-Disposition'].startswith('attachment'))
        self.assertTrue(xlsx.content[:2] == b'PK')      # zip-сигнатура xlsx


class PeggingHttpTests(TestCase):
    """Волна 8: HTTP-путь pegging — проекция, peg/unpeg/autopeg, гварды."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.prj = models.Project.objects.create(code='P1', name='Проект 1',
            kind=models.Project.Kind.EXTERNAL)
        self.prj2 = models.Project.objects.create(code='P2', name='Проект 2',
            kind=models.Project.Kind.EXTERNAL)
        self.scr = models.Item.objects.create(design_item_id='SCR', description='Винт',
            category=_cat())
        dev = models.Item.objects.create(design_item_id='DEV', description='Прибор',
            category=_cat(), produced=True)
        models.BomLine.objects.create(parent=dev, component=self.scr, qty=D(4))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=self.prj2, target_item=dev, qty=D(5))
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))
        add = self.c.post('/api/command-deficit/add-to-procurement/',
            {'item_id': self.scr.id, 'qty': 60}, content_type='application/json')
        self.pid = add.json()['procurement_id']

    def test_pegging_projection_and_autopeg(self):
        peg = self.c.get(f'/api/procurements/{self.pid}/pegging/')
        self.assertEqual(peg.status_code, 200)
        row = peg.json()['rows'][0]
        self.assertEqual(row['item_design_item_id'], 'SCR')
        self.assertEqual(float(row['pegged']), 0.0)
        self.assertEqual(len(row['by_project']), 2)             # наводка по двум проектам
        auto = self.c.post(f'/api/procurements/{self.pid}/autopeg/')
        self.assertEqual(auto.status_code, 200)
        body = auto.json()
        self.assertEqual(len(body['fan']), 2)                  # веер из двух заказов
        self.assertEqual(float(body['rows'][0]['pegged']), 60.0)
        self.assertEqual(body['rows'][0]['status'], 'available')

    def test_manual_peg_unpeg_and_guard(self):
        peg = self.c.post(f'/api/procurements/{self.pid}/peg/',
            {'item_id': self.scr.id, 'project_id': self.prj.id, 'qty': 25},
            content_type='application/json')
        self.assertEqual(peg.status_code, 200)
        self.assertEqual(float(peg.json()['rows'][0]['pegged']), 25.0)
        # item не в плане → 400
        x = models.Item.objects.create(design_item_id='X', description='X', category=_cat())
        bad = self.c.post(f'/api/procurements/{self.pid}/peg/',
            {'item_id': x.id, 'project_id': self.prj.id, 'qty': 1},
            content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        # unpeg → 0
        un = self.c.post(f'/api/procurements/{self.pid}/unpeg/',
            {'item_id': self.scr.id, 'project_id': self.prj.id},
            content_type='application/json')
        self.assertEqual(un.status_code, 200)
        self.assertEqual(float(un.json()['rows'][0]['pegged']), 0.0)


class ReferenceCreateTests(EngineTestBase):
    """Канон «＋ Новая» (2026-07-03): создание изделий и проектов из справочников."""

    def test_create_item_defaults_and_fields(self):
        cat = _cat('mcu', 'Микроконтроллеры')
        i = engine.create_item('R100', 'Резистор', category_id=cat.id,
                               uom='шт', produced=False, estimated_cost=D('1.50'),
                               temperature='-40-125°C')
        self.assertEqual(i.design_item_id, 'R100')
        self.assertEqual(i.category_id, cat.id)
        self.assertEqual(i.temperature, '-40-125°C')
        self.assertEqual(i.estimated_cost, D('1.50'))
        # обрезка пробелов; дефолты uom=шт, produced=False
        j = engine.create_item(' B1 ', ' Плата ', category_id=cat.id)
        self.assertEqual(j.design_item_id, 'B1')
        self.assertEqual(j.uom, 'шт')
        self.assertFalse(j.produced)

    def test_create_item_rejects_dup_empty_and_bad_category(self):
        cat = _cat()
        engine.create_item('R100', 'Резистор', category_id=cat.id)
        with self.assertRaises(ValidationError):
            engine.create_item('R100', 'Дубль', category_id=cat.id)   # дубль ключа
        with self.assertRaises(ValidationError):
            engine.create_item('', 'Без ключа', category_id=cat.id)
        with self.assertRaises(ValidationError):
            engine.create_item('X1', '', category_id=cat.id)          # без описания
        with self.assertRaises(ValidationError):
            engine.create_item('X2', 'Без категории')                 # категория обязательна
        with self.assertRaises(ValidationError):
            engine.create_item('X3', 'Плохая', category_id=999999)    # неизвестная категория

    def test_create_project_is_external_active(self):
        p = engine.create_project('НИР-1', 'Тема', budget=D('100000'))
        self.assertEqual(p.kind, models.Project.Kind.EXTERNAL)
        self.assertEqual(p.status, models.Project.Status.ACTIVE)
        self.assertEqual(p.budget, D('100000'))

    def test_create_project_rejects_dup_and_empty(self):
        engine.create_project('НИР-1', 'Тема')
        with self.assertRaises(ValidationError):
            engine.create_project('НИР-1', 'Дубль')    # дубль кода
        with self.assertRaises(ValidationError):
            engine.create_project('', 'Без кода')
        with self.assertRaises(ValidationError):
            engine.create_project('НИР-2', '')         # без названия


class ReferenceCreateHttpTests(TestCase):
    """Канон «＋ Новая»: HTTP-путь создания изделия/проекта."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_create_item_http(self):
        cat = _cat()
        r = self.c.post('/api/items/', {'design_item_id': 'R100', 'description': 'Резистор',
            'category_id': cat.id, 'produced': False},
            content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['design_item_id'], 'R100')
        # появляется в списке
        lst = self.c.get('/api/items/').json()
        self.assertTrue(any(i['design_item_id'] == 'R100' for i in lst))
        # дубль → 400
        dup = self.c.post('/api/items/', {'design_item_id': 'R100', 'description': 'Дубль',
            'category_id': cat.id}, content_type='application/json')
        self.assertEqual(dup.status_code, 400)

    def test_create_project_http(self):
        r = self.c.post('/api/projects/', {'code': 'НИР-1', 'name': 'Тема',
            'budget': '100000'}, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body['kind'], 'external')
        self.assertEqual(body['status'], 'active')
        bad = self.c.post('/api/projects/', {'code': '', 'name': 'X'},
            content_type='application/json')
        self.assertEqual(bad.status_code, 400)


class InventoryCockpitTests(EngineTestBase):
    """Волна 9: инвентаризация — рождение «найденных» партий (`+RECEIPT`, 4-й
    origin) + серая ре-материализация списанного лота с наследованием провенанса."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')
        self.grey = models.Project.objects.create(
            code='GREY', name='Свободные неучтённые',
            kind=models.Project.Kind.INTERNAL_WRITEOFF)

    def test_add_lot_births_receipt_movement(self):
        inv = engine.create_inventory(self.prj, self.user, 'ИНВ-1', note='пересчёт')
        lot = engine.add_inventory_lot(inv, self.item, D(7), unit_cost=D('1.50'),
                                       lot_name='Резистор')
        self.assertEqual(lot.origin_kind, 'inventory')
        self.assertEqual(lot.project_id, self.prj.id)
        self.assertEqual(engine.lot_live_qty(lot), D(7))       # +RECEIPT
        self.assertTrue(lot.movements.filter(type='RECEIPT', qty=D(7)).exists())

    def test_cockpit_totals_and_note(self):
        inv = engine.create_inventory(self.prj, self.user, 'ИНВ-1', note='пересчёт')
        engine.add_inventory_lot(inv, self.item, D(4), unit_cost=D('2'))
        c = engine.inventory_cockpit(inv)
        self.assertEqual(c['number'], 'ИНВ-1')
        self.assertEqual(c['note'], 'пересчёт')
        self.assertEqual(c['total_cost'], D(8))                # 4 × 2
        self.assertEqual(c['lots'][0]['live_qty'], D(4))

    def test_create_rejects_empty_number(self):
        with self.assertRaises(ValidationError):
            engine.create_inventory(self.prj, self.user, '  ')

    def test_add_lot_rejects_nonpositive_and_negative_cost(self):
        inv = engine.create_inventory(self.prj, self.user, 'ИНВ-1')
        with self.assertRaises(ValidationError):
            engine.add_inventory_lot(inv, self.item, D(0))
        with self.assertRaises(ValidationError):
            engine.add_inventory_lot(inv, self.item, D(1), unit_cost=D(-1))

    def test_update_and_remove_lot(self):
        inv = engine.create_inventory(self.prj, self.user, 'ИНВ-1')
        lot = engine.add_inventory_lot(inv, self.item, D(4))
        engine.update_inventory_lot(lot, qty=D(9), unit_cost=D('3'))
        self.assertEqual(engine.lot_live_qty(lot), D(9))
        engine.remove_inventory_lot(lot)
        self.assertFalse(models.Lot.objects.filter(pk=lot.id).exists())

    def test_remove_blocked_when_consumed(self):
        inv = engine.create_inventory(self.prj, self.user, 'ИНВ-1')
        lot = engine.add_inventory_lot(inv, self.item, D(10))
        # потребим найденный лот передачей → удаление заблокировано
        tr = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.add_transfer_line(tr, lot, D(3))
        with self.assertRaises(ValidationError):
            engine.remove_inventory_lot(lot)

    def test_rematerialize_written_off_lot_inherits_provenance(self):
        # списываем партию из проекта (серый путь), затем находим и ре-материализуем в GREY
        src = self.receipt_lot(self.item, self.prj, 10)
        src.unit_cost = D('2.50'); src.lot_name = 'Резистор'; src.part_number = 'ЗН-9'
        src.save(update_fields=['unit_cost', 'lot_name', 'part_number'])
        w = engine.create_writeoff(self.prj, self.user, 'СП-1', reason='на серый')
        engine.add_writeoff_line(w, src, D(6))
        self.assertEqual(engine.lot_live_qty(src), D(4))
        # пикер показывает списанный лот с суммой списания
        picker = {r['lot_id']: r for r in engine.written_off_lots()}
        self.assertIn(src.id, picker)
        self.assertEqual(picker[src.id]['written_qty'], D(6))
        # ре-материализация: born-лот в GREY с predecessor и унаследованными полями
        inv = engine.create_inventory(self.grey, self.user, 'ИНВ-G1')
        born = engine.add_inventory_lot(inv, src.item, D(6), unit_cost=src.unit_cost,
                                        lot_name=src.lot_name,
                                        part_number=src.part_number, predecessor=src)
        self.assertEqual(born.project_id, self.grey.id)
        self.assertEqual(born.predecessor_id, src.id)
        self.assertEqual(born.unit_cost, D('2.50'))
        self.assertEqual(engine.lot_live_qty(born), D(6))
        c = engine.inventory_cockpit(inv)
        self.assertEqual(c['lots'][0]['predecessor_id'], src.id)
        self.assertTrue(c['lots'][0]['predecessor_label'])


class InventoryHttpTests(TestCase):
    """Волна 9: HTTP-путь инвентаризации — create/строка/правка/пикер/ре-материализация."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.main = models.Location.objects.create(code='MAIN', name='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', name='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.grey = models.Project.objects.create(
            code='GREY', name='Свободные неучтённые',
            kind=models.Project.Kind.INTERNAL_WRITEOFF)
        self.item = models.Item.objects.create(design_item_id='R100', description='R100', category=_cat())
        self.sup = models.Counterparty.objects.create(name='П')
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01',
            contractor=self.sup, project=self.prj, user=get_user_model().objects.first())
        self.lot = models.Lot.objects.create(item=self.item, project=self.prj,
            origin=r, qty=D(10), unit_cost=D('2.50'), part_number='ЗН-9')
        engine.rebuild_movements(self.lot)
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_inventory_crud_flow(self):
        r = self.c.post('/api/inventories/', {'project_id': self.prj.id,
            'number': 'ИНВ-1', 'note': 'пересчёт'}, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        iid = r.json()['id']
        # строка = найденная партия (+RECEIPT)
        line = self.c.post(f'/api/inventories/{iid}/lots/',
            {'item_id': self.item.id, 'qty': 7, 'unit_cost': '1.5',
             'lot_name': 'Резистор'}, content_type='application/json')
        self.assertEqual(line.status_code, 201)
        body = line.json()
        self.assertEqual(float(body['total_cost']), 10.5)
        self.assertEqual(float(body['lots'][0]['live_qty']), 7.0)
        # нонпозитив qty → 400
        bad = self.c.post(f'/api/inventories/{iid}/lots/',
            {'item_id': self.item.id, 'qty': 0}, content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        # правка шапки
        patch = self.c.patch(f'/api/inventories/{iid}/', {'note': 'обновлено'},
            content_type='application/json')
        self.assertEqual(patch.json()['note'], 'обновлено')

    def test_rematerialize_via_picker(self):
        # списываем часть лота → появляется в пикере ре-материализации
        w = self.c.post('/api/writeoffs/', {'project_id': self.prj.id, 'number': 'СП-1'},
            content_type='application/json').json()
        self.c.post(f"/api/writeoffs/{w['id']}/lines/",
            {'lot_id': self.lot.id, 'qty': 6}, content_type='application/json')
        picker = self.c.get('/api/written-off-lots/')
        self.assertEqual(picker.status_code, 200)
        self.assertTrue(any(x['lot_id'] == self.lot.id and float(x['written_qty']) == 6.0
                            for x in picker.json()))
        # ре-материализация в GREY: predecessor → списанный, поля унаследованы
        inv = self.c.post('/api/inventories/', {'project_id': self.grey.id,
            'number': 'ИНВ-G1'}, content_type='application/json').json()
        line = self.c.post(f"/api/inventories/{inv['id']}/lots/",
            {'predecessor_id': self.lot.id, 'qty': 6}, content_type='application/json')
        self.assertEqual(line.status_code, 201)
        row = line.json()['lots'][0]
        self.assertEqual(row['predecessor_id'], self.lot.id)
        self.assertEqual(float(row['unit_cost']), 2.50)       # цена унаследована
        self.assertEqual(row['part_number'], 'ЗН-9')          # PN унаследован


class OrderDeleteHttpTests(TestCase):
    """Волна 13 Ф1b: HTTP-путь post/unpost + DELETE ордеров (friendly-guard)."""

    def setUp(self):
        self.user = get_user_model().objects.create(username='admin', is_superuser=True)
        self.main = models.Location.objects.create(code='MAIN', name='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', name='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.item = models.Item.objects.create(design_item_id='R100', description='R100', category=_cat())
        self.sup = models.Counterparty.objects.create(name='П')
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01',
            contractor=self.sup, project=self.prj, user=self.user)
        self.lot = models.Lot.objects.create(item=self.item, project=self.prj,
            origin=r, qty=D(10))
        engine.rebuild_movements(self.lot)
        self.c = Client()
        self.c.force_login(self.user)

    def test_writeoff_post_unpost_delete_flow(self):
        w = self.c.post('/api/writeoffs/', {'project_id': self.prj.id, 'number': 'СП-1'},
            content_type='application/json').json()
        wid = w['id']
        self.c.post(f'/api/writeoffs/{wid}/lines/', {'lot_id': self.lot.id, 'qty': 4},
            content_type='application/json')
        # провести
        posted = self.c.post(f'/api/writeoffs/{wid}/post/')
        self.assertEqual(posted.status_code, 200)
        self.assertTrue(posted.json()['posted'])
        # posted — удаление отклонено (сперва расфиксировать)
        blocked = self.c.delete(f'/api/writeoffs/{wid}/')
        self.assertEqual(blocked.status_code, 400)
        # расфиксировать → удалить
        self.assertEqual(self.c.post(f'/api/writeoffs/{wid}/unpost/').status_code, 200)
        gone = self.c.delete(f'/api/writeoffs/{wid}/')
        self.assertEqual(gone.status_code, 204)
        self.assertFalse(models.Writeoff.objects.filter(pk=wid).exists())
        # источник освобождён (нет −ISSUE)
        self.assertEqual(engine.lot_live_qty(self.lot), D(10))

    def test_receipt_delete_draft(self):
        r = models.Receipt.objects.create(number='U-2', date='2026-05-01',
            contractor=self.sup, project=self.prj, user=self.user)
        lot = engine.add_receipt_lot(r, self.item, D(5))
        resp = self.c.delete(f'/api/receipts/{r.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(models.Lot.objects.filter(pk=lot.pk).exists())


class ProjectBudgetTests(EngineTestBase):
    """Волна 10: бюджет проекта — потрачено/план/компас + себестоимость/экономия."""

    def make_demand(self, device, qty):
        models.ProjectDemand.objects.create(project=self.prj, target_item=device, qty=D(qty))

    def test_spent_counts_only_receipt_lots(self):
        # приходной лот считается по (цена×кол-во); заём (requisition) — бесплатен
        case = self.make_item('CASE')
        self.receipt_lot(case, self.prj, 1)  # добавит default unit_cost=0
        r = models.Receipt.objects.create(number='U-2', date='2026-05-02',
            contractor=self.supplier, project=self.prj, user=self.user)
        paid = models.Lot.objects.create(item=case, project=self.prj, origin=r,
            qty=D(3), unit_cost=D(800))
        engine.rebuild_movements(paid)
        # заём из белого склада → born-лот в prj (origin requisition), цена наследуется
        white = models.Project.objects.create(code='WHT', name='Склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        src = models.Lot.objects.create(item=case, project=white,
            origin=models.Inventory.objects.create(project=white, user=self.user,
                number='INV-W', date='2026-05-01'), qty=D(5), unit_cost=D(700))
        engine.rebuild_movements(src)
        req = engine.create_requisition(self.prj, self.user, 'ТРБ-1')
        engine.add_requisition_line(req, src, D(2))

        b = engine.project_budget(self.prj)
        self.assertEqual(b['spent'], D(2400))   # только 3×800; заём не в счёт

    def test_plan_estimate_then_replaced_by_fact(self):
        device = self.make_item('DEV', manufactured=True, kind='device')
        screw = self.make_item('SCR', kind='material')
        screw.estimated_cost = D(50)
        screw.save()
        models.BomLine.objects.create(parent=device, component=screw, qty=D(4))
        self.make_demand(device, 10)  # need SCR 40
        self.prj.budget = D(3000)
        self.prj.save()

        # склада/заказа нет → план = оценка 40×50 = 2000, компас = 3000−2000
        b = engine.project_budget(self.prj)
        self.assertEqual(b['spent'], D(0))
        self.assertEqual(b['plan'], D(2000))
        self.assertEqual(b['compass'], D(1000))
        self.assertEqual(b['unestimated'], [])

        # пришёл УПД на все 40 по реальной цене 45 → оценка сменилась фактом
        r = models.Receipt.objects.create(number='U-3', date='2026-05-03',
            contractor=self.supplier, project=self.prj, user=self.user)
        lot = models.Lot.objects.create(item=screw, project=self.prj, origin=r,
            qty=D(40), unit_cost=D(45))
        engine.rebuild_movements(lot)
        b = engine.project_budget(self.prj)
        self.assertEqual(b['spent'], D(1800))
        self.assertEqual(b['plan'], D(1800))      # факт заместил оценку → сошлось
        self.assertEqual(b['compass'], D(1200))

    def test_unestimated_flagged_not_silently_zero(self):
        device = self.make_item('DEV', manufactured=True, kind='device')
        screw = self.make_item('SCR', kind='material')  # без estimated_cost
        models.BomLine.objects.create(parent=device, component=screw, qty=D(4))
        self.make_demand(device, 10)

        b = engine.project_budget(self.prj)
        self.assertEqual(b['unestimated'], ['SCR'])
        self.assertEqual(b['plan'], D(0))   # неполон — но флаг поднят

    def test_economy_equals_borrow_value(self):
        # прибор из купленного CASE (спот) + заёмного RES (бесплатно в бюджете,
        # но по реальной цене в себестоимости) → экономия = стоимость заёма
        device = self.make_item('DEV', manufactured=True, kind='device')
        case = self.make_item('CASE')
        res = self.make_item('RES')
        models.BomLine.objects.create(parent=device, component=case, qty=D(1))
        models.BomLine.objects.create(parent=device, component=res, qty=D(2))
        self.make_demand(device, 1)

        # CASE: куплен ровно 1 @ 800
        r = models.Receipt.objects.create(number='U-4', date='2026-05-04',
            contractor=self.supplier, project=self.prj, user=self.user)
        case_lot = models.Lot.objects.create(item=case, project=self.prj, origin=r,
            qty=D(1), unit_cost=D(800))
        engine.rebuild_movements(case_lot)
        # RES: заём 2 @ 10 из белого склада
        white = models.Project.objects.create(code='WHT', name='Склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        src = models.Lot.objects.create(item=res, project=white,
            origin=models.Inventory.objects.create(project=white, user=self.user,
                number='INV-W2', date='2026-05-01'), qty=D(2), unit_cost=D(10))
        engine.rebuild_movements(src)
        req = engine.create_requisition(self.prj, self.user, 'ТРБ-2')
        engine.add_requisition_line(req, src, D(2))
        res_lot = req.lots.first()

        # собираем прибор
        k = models.Kitting.objects.create(project=self.prj, target_item=device,
            user=self.user, qty=D(1), status=models.DocStatus.DRAFT)
        engine.add_kitting_line(k, case, case_lot, D(1))
        engine.add_kitting_line(k, res, res_lot, D(2))
        engine.close_kitting(k)

        b = engine.project_budget(self.prj)
        self.assertEqual(b['spent'], D(800))    # только CASE
        self.assertEqual(b['cost'], D(820))     # снимок: 800 + 2×10 (заём по реальной цене)
        self.assertEqual(b['economy'], D(20))   # польза заёма = 2×10

    def test_compass_none_without_budget(self):
        b = engine.project_budget(self.prj)
        self.assertIsNone(b['budget'])
        self.assertIsNone(b['compass'])


class ProjectBudgetHttpTests(TestCase):
    """Волна 10: HTTP-путь бюджета проекта."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.main = models.Location.objects.create(code='MAIN', name='Основной склад')
        self.prj = models.Project.objects.create(code='P1', name='Проект 1',
            kind=models.Project.Kind.EXTERNAL, budget=D(5000))
        self.sup = models.Counterparty.objects.create(name='П')
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_budget_projection(self):
        device = models.Item.objects.create(design_item_id='DEV', description='DEV',
            category=_cat(), produced=True)
        scr = models.Item.objects.create(design_item_id='SCR', description='SCR',
            category=_cat(), estimated_cost=D(50))
        models.BomLine.objects.create(parent=device, component=scr, qty=D(2))
        models.ProjectDemand.objects.create(project=self.prj, target_item=device, qty=D(10))
        r = self.c.get(f'/api/projects/{self.prj.id}/budget/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(float(body['plan']), 1000.0)     # 20×50
        self.assertEqual(float(body['compass']), 4000.0)  # 5000−1000
        self.assertEqual(float(body['spent']), 0.0)


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class AttachmentTests(EngineTestBase):
    """Волна 11: вложения — файл на диск, exclusive-arc владелец, метаданные с сервера."""

    def setUp(self):
        super().setUp()
        self.receipt = models.Receipt.objects.create(
            number='УПД-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)

    def _file(self, name='scan.pdf', body=b'%PDF-1.4 test', ctype='application/pdf'):
        return SimpleUploadedFile(name, body, content_type=ctype)

    def test_add_fills_metadata_and_owner(self):
        att = engine.add_attachment('receipt', self.receipt, self._file(),
                                    self.user, label='  скан УПД ')
        self.assertEqual(att.document_id, self.receipt.id)
        self.assertEqual(att.filename, 'scan.pdf')
        self.assertEqual(att.size, len(b'%PDF-1.4 test'))
        self.assertEqual(att.content_type, 'application/pdf')
        self.assertEqual(att.label, 'скан УПД')            # подрезано
        self.assertEqual(att.user_id, self.user.id)
        self.assertIsNone(att.item_id)                     # ровно один владелец (item↔document)

    def test_attachments_for_lists_newest_first(self):
        a1 = engine.add_attachment('receipt', self.receipt, self._file('a.pdf'), self.user)
        a2 = engine.add_attachment('receipt', self.receipt, self._file('b.pdf'), self.user)
        rows = engine.attachments_for('receipt', self.receipt.id)
        self.assertEqual([r['id'] for r in rows], [a2.id, a1.id])
        self.assertEqual(rows[0]['url'], f'/api/attachments/{a2.id}/download/')

    def test_unknown_owner_type_rejected(self):
        # purchase/procurement НЕ владельцы вложений (нет FK в модели)
        with self.assertRaises(ValidationError):
            engine.resolve_attachment_owner('purchase', 1)
        with self.assertRaises(ValidationError):
            engine.attachments_for('bogus', 1)

    def test_oversize_rejected(self):
        big = SimpleUploadedFile('big.bin', b'x' * 10, content_type='application/octet-stream')
        with override_settings(MAX_ATTACHMENT_SIZE=5):
            with self.assertRaises(ValidationError):
                engine.add_attachment('receipt', self.receipt, big, self.user)

    def test_update_and_delete_removes_file(self):
        att = engine.add_attachment('receipt', self.receipt, self._file(), self.user)
        path = att.file.path
        self.assertTrue(os.path.exists(path))
        engine.update_attachment(att, label='новая подпись')
        att.refresh_from_db()
        self.assertEqual(att.label, 'новая подпись')
        engine.delete_attachment(att)
        self.assertFalse(models.Attachment.objects.filter(pk=att.id).exists())
        self.assertFalse(os.path.exists(path))             # файл удалён с диска


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class AttachmentHttpTests(TestCase):
    """Волна 11: HTTP-путь вложений — multipart upload → list → patch → download → delete."""

    def setUp(self):
        self.user = get_user_model().objects.create(username='admin', is_superuser=True)
        self.supplier = models.Counterparty.objects.create(name='П')
        self.prj = models.Project.objects.create(
            code='P1', name='Проект', kind=models.Project.Kind.EXTERNAL)
        self.receipt = models.Receipt.objects.create(
            number='УПД-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_full_cycle(self):
        up = SimpleUploadedFile('scan.pdf', b'%PDF data', content_type='application/pdf')
        r = self.c.post(f'/api/attachments/receipt/{self.receipt.id}/',
                        {'file': up, 'label': 'скан'})
        self.assertEqual(r.status_code, 201)
        aid = r.json()['id']
        lst = self.c.get(f'/api/attachments/receipt/{self.receipt.id}/').json()
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]['filename'], 'scan.pdf')
        self.assertEqual(lst[0]['user'], 'admin')          # автор с документа
        pr = self.c.patch(f'/api/attachments/{aid}/', {'label': 'скан УПД №1'},
                          content_type='application/json')
        self.assertEqual(pr.status_code, 200)
        self.assertEqual(pr.json()['label'], 'скан УПД №1')
        dl = self.c.get(f'/api/attachments/{aid}/download/')
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(b''.join(dl.streaming_content), b'%PDF data')
        dr = self.c.delete(f'/api/attachments/{aid}/')
        self.assertEqual(dr.status_code, 204)
        self.assertEqual(self.c.get(f'/api/attachments/receipt/{self.receipt.id}/').json(), [])

    def test_download_disposition_safe_inline_else_attachment(self):
        # PDF — inline (смотреть во вкладке), html — принудительная загрузка (XSS),
        # оба с nosniff.
        pdf = SimpleUploadedFile('scan.pdf', b'%PDF', content_type='application/pdf')
        html = SimpleUploadedFile('bom.html', b'<script>x()</script>',
                                  content_type='text/html')
        pid = self.c.post(f'/api/attachments/receipt/{self.receipt.id}/',
                          {'file': pdf}).json()['id']
        hid = self.c.post(f'/api/attachments/receipt/{self.receipt.id}/',
                          {'file': html}).json()['id']
        dp = self.c.get(f'/api/attachments/{pid}/download/')
        self.assertIn('inline', dp['Content-Disposition'])
        self.assertEqual(dp['X-Content-Type-Options'], 'nosniff')
        dh = self.c.get(f'/api/attachments/{hid}/download/')
        self.assertIn('attachment', dh['Content-Disposition'])
        self.assertEqual(dh['X-Content-Type-Options'], 'nosniff')

    def test_bad_owner_type(self):
        up = SimpleUploadedFile('x.pdf', b'x', content_type='application/pdf')
        r = self.c.post('/api/attachments/purchase/1/', {'file': up})
        self.assertEqual(r.status_code, 400)

    def test_missing_file(self):
        r = self.c.post(f'/api/attachments/receipt/{self.receipt.id}/',
                        {'label': 'нет файла'})
        self.assertEqual(r.status_code, 400)


class AuthHttpTests(TestCase):
    """Волна 12: логин-экран — вход/выход сессией, гейтинг всего /api/, авторство."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='ivan', password='s3cret-pass', first_name='Иван')
        self.prj = models.Project.objects.create(
            code='P1', name='Проект', kind=models.Project.Kind.EXTERNAL)
        self.c = Client()

    def test_anonymous_api_is_gated(self):
        # Без логина любой прикладной эндпоинт закрыт (403 — DRF без challenge).
        self.assertEqual(self.c.get('/api/projects/').status_code, 403)

    def test_ping_open_without_login(self):
        r = self.c.get('/api/ping/')
        self.assertEqual(r.status_code, 200)

    def test_me_anonymous_is_401_and_sets_csrf_cookie(self):
        r = self.c.get('/api/auth/me/')
        self.assertEqual(r.status_code, 401)
        self.assertIn('csrftoken', r.cookies)     # токен для последующего POST

    def test_login_flow_and_authorship(self):
        bad = self.c.post('/api/auth/login/',
                          {'username': 'ivan', 'password': 'wrong'},
                          content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        ok = self.c.post('/api/auth/login/',
                         {'username': 'ivan', 'password': 's3cret-pass'},
                         content_type='application/json')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()['username'], 'ivan')
        self.assertEqual(ok.json()['full_name'], 'Иван')     # get_full_name
        # После логина — доступ открыт и авторство пишется реальным юзером.
        me = self.c.get('/api/auth/me/')
        self.assertEqual(me.status_code, 200)
        cr = self.c.post('/api/kittings/', {'project_id': self.prj.id,
            'target_item_id': models.Item.objects.create(
                design_item_id='D1', description='Прибор', category=_cat(),
                produced=True).id, 'qty': 1},
            content_type='application/json')
        self.assertEqual(cr.status_code, 201)
        k = models.Kitting.objects.get(pk=cr.json()['id'])
        self.assertEqual(k.user, self.user)

    def test_logout_closes_session(self):
        self.c.force_login(self.user)
        self.assertEqual(self.c.get('/api/projects/').status_code, 200)
        out = self.c.post('/api/auth/logout/')
        self.assertEqual(out.status_code, 204)
        self.assertEqual(self.c.get('/api/projects/').status_code, 403)


class BomEditTests(EngineTestBase):
    """Редактор состава (BOM): добавление/правка/удаление, гварды дублей и циклов."""

    def test_add_update_remove_bom_line(self):
        dev = self.make_item('DEV', manufactured=True)
        comp = self.make_item('R')
        line = engine.add_bom_line(dev, comp, D(3), position='C1')
        self.assertEqual(line.qty, D(3))
        self.assertEqual(line.position, 'C1')
        engine.update_bom_line(line, qty=D(5))
        line.refresh_from_db()
        self.assertEqual(line.qty, D(5))
        engine.remove_bom_line(line)
        self.assertFalse(models.BomLine.objects.filter(pk=line.pk).exists())

    def test_bom_rejects_self_and_duplicate_and_nonpositive(self):
        dev = self.make_item('DEV', manufactured=True)
        comp = self.make_item('R')
        with self.assertRaises(ValidationError):
            engine.add_bom_line(dev, dev, D(1))           # сам на себя
        with self.assertRaises(ValidationError):
            engine.add_bom_line(dev, comp, D(0))          # qty <= 0
        engine.add_bom_line(dev, comp, D(1))
        with self.assertRaises(ValidationError):
            engine.add_bom_line(dev, comp, D(2))          # дубль (parent, component)

    def test_bom_rejects_cycle(self):
        a = self.make_item('A', manufactured=True)
        b = self.make_item('B', manufactured=True)
        c = self.make_item('C', manufactured=True)
        engine.add_bom_line(a, b, D(1))
        engine.add_bom_line(b, c, D(1))
        with self.assertRaises(ValidationError):
            engine.add_bom_line(c, a, D(1))               # C ⊃ A замкнул бы цикл A→B→C→A


class ProjectDemandEditTests(EngineTestBase):
    """Редактор потребности проекта (секция «Приборы»)."""

    def test_add_update_remove_demand(self):
        dev = self.make_item('DEV', manufactured=True, kind='device')
        d = engine.add_project_demand(self.prj, dev, D(4))
        self.assertEqual(d.qty, D(4))
        engine.update_project_demand(d, D(7))
        d.refresh_from_db()
        self.assertEqual(d.qty, D(7))
        engine.remove_project_demand(d)
        self.assertFalse(models.ProjectDemand.objects.filter(pk=d.pk).exists())

    def test_demand_rejects_duplicate_and_nonpositive(self):
        dev = self.make_item('DEV', manufactured=True, kind='device')
        with self.assertRaises(ValidationError):
            engine.add_project_demand(self.prj, dev, D(0))
        engine.add_project_demand(self.prj, dev, D(1))
        with self.assertRaises(ValidationError):
            engine.add_project_demand(self.prj, dev, D(2))

    def test_demand_blocked_on_closed_and_internal(self):
        dev = self.make_item('DEV', manufactured=True, kind='device')
        closed = models.Project.objects.create(
            code='PC', name='Закрытый', kind=models.Project.Kind.EXTERNAL,
            status=models.Project.Status.CLOSED)
        with self.assertRaises(ValidationError):
            engine.add_project_demand(closed, dev, D(1))
        internal = models.Project.objects.create(
            code='WH', name='Склад', kind=models.Project.Kind.INTERNAL_STOCK)
        with self.assertRaises(ValidationError):
            engine.add_project_demand(internal, dev, D(1))

    def test_deficit_components_aggregate(self):
        # Два прибора делят компонент R → сводная потребность суммируется.
        r = self.make_item('R')
        c = self.make_item('C')
        dev1 = self.make_item('DEV1', manufactured=True, kind='device')
        dev2 = self.make_item('DEV2', manufactured=True, kind='device')
        engine.add_bom_line(dev1, r, D(2))
        engine.add_bom_line(dev1, c, D(1))
        engine.add_bom_line(dev2, r, D(3))
        engine.add_project_demand(self.prj, dev1, D(5))   # R: 10
        engine.add_project_demand(self.prj, dev2, D(4))   # R: 12 → всего 22
        out = engine.project_deficit(self.prj)
        agg = {c['component_design_item_id']: c for c in out['components']}
        self.assertEqual(agg['R']['need'], D(22))
        self.assertEqual(agg['C']['need'], D(5))
        # Сортировка «горит вперёд»: одинаковый статус (всё к заказу) → по коду.
        codes = [c['component_design_item_id'] for c in out['components']]
        self.assertEqual(codes, ['C', 'R'])


class ItemProjectUpdateTests(EngineTestBase):
    """Правка свойств изделия и реквизитов проекта под замком формы (§6)."""

    def test_update_item_fields(self):
        it = self.make_item('X')
        cat2 = _cat('mcu', 'Микроконтроллеры')
        engine.update_item(it, {'description': 'Новое имя', 'category_id': cat2.id,
                                'uom': 'кг', 'estimated_cost': D('12.50'),
                                'temperature': '-40-85°C', 'produced': True})
        it.refresh_from_db()
        self.assertEqual(it.description, 'Новое имя')
        self.assertEqual(it.category_id, cat2.id)
        self.assertEqual(it.uom, 'кг')
        self.assertEqual(it.estimated_cost, D('12.50'))
        self.assertEqual(it.temperature, '-40-85°C')
        self.assertTrue(it.produced)

    def test_update_item_estimated_cost_can_clear(self):
        it = self.make_item('X')
        it.estimated_cost = D('5'); it.save()
        engine.update_item(it, {'estimated_cost': None})
        it.refresh_from_db()
        self.assertIsNone(it.estimated_cost)

    def test_update_item_rejects_dup_key_empty_desc_bad_category(self):
        self.make_item('A')
        it = self.make_item('B')
        with self.assertRaises(ValidationError):
            engine.update_item(it, {'design_item_id': 'A'})  # дубль ключа
        with self.assertRaises(ValidationError):
            engine.update_item(it, {'description': '   '})   # пустое описание
        with self.assertRaises(ValidationError):
            engine.update_item(it, {'category_id': 999999})  # неизвестная категория

    def test_update_item_partial_leaves_others(self):
        it = self.make_item('X')
        it.uom = 'м'; it.save()
        cat0 = it.category_id
        engine.update_item(it, {'description': 'Y'})       # прислали только описание
        it.refresh_from_db()
        self.assertEqual(it.uom, 'м')                      # uom не тронут
        self.assertEqual(it.category_id, cat0)             # категория не тронута

    def test_update_project_fields_and_clear_budget(self):
        engine.update_project(self.prj, {'name': 'Переименован',
                                         'budget': D('1000'), 'started_at': '2026-01-15'})
        self.prj.refresh_from_db()
        self.assertEqual(self.prj.name, 'Переименован')
        self.assertEqual(self.prj.budget, D('1000'))
        self.assertEqual(str(self.prj.started_at), '2026-01-15')
        engine.update_project(self.prj, {'budget': None})
        self.prj.refresh_from_db()
        self.assertIsNone(self.prj.budget)

    def test_update_project_rejects_empty_name(self):
        with self.assertRaises(ValidationError):
            engine.update_project(self.prj, {'name': '  '})

    def test_update_project_code_rename_and_guards(self):
        # WAVE14 Ф1: код правится в форме, guard как у изделия (не PK — безопасно).
        engine.update_project(self.prj, {'code': 'НОВ-КОД'})
        self.prj.refresh_from_db()
        self.assertEqual(self.prj.code, 'НОВ-КОД')
        with self.assertRaises(ValidationError):               # пустой код
            engine.update_project(self.prj, {'code': '  '})
        models.Project.objects.create(code='ЗАНЯТО', name='Другой')
        with self.assertRaises(ValidationError):               # коллизия кода
            engine.update_project(self.prj, {'code': 'ЗАНЯТО'})

    def test_project_detail_patch_code(self):
        self.c = Client()
        self.c.force_login(self.user)
        r = self.c.patch(f'/api/projects/{self.prj.id}/',
                         {'code': 'ЧЕРЕЗ-API'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.prj.refresh_from_db()
        self.assertEqual(self.prj.code, 'ЧЕРЕЗ-API')

    def test_project_detail_patch_endpoint(self):
        self.c = Client()
        self.c.force_login(self.user)
        r = self.c.patch(f'/api/projects/{self.prj.id}/',
                         {'budget': '2500'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(D(str(r.json()['budget'])), D('2500'))
        self.prj.refresh_from_db()
        self.assertEqual(self.prj.budget, D('2500'))

    def test_item_detail_patch_endpoint(self):
        it = self.make_item('Z')
        self.c = Client()
        self.c.force_login(self.user)
        r = self.c.patch(f'/api/items/{it.id}/',
                         {'description': 'Обновлён', 'estimated_cost': '9.9'},
                         content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['description'], 'Обновлён')
        it.refresh_from_db()
        self.assertEqual(it.description, 'Обновлён')
        self.assertEqual(it.estimated_cost, D('9.9'))


class UnifiedDocStatusTests(EngineTestBase):
    """Волна 13 Ф1: единый мягкий замок `status {draft⇄posted}` на всех складских
    документах (свернул `Receipt.approved`/`Transfer.posted`/`Kitting.wip-closed`)."""

    def test_all_docs_default_to_draft(self):
        """Плоское создание любого ордера рождает черновик (единый дефолт)."""
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        k = models.Kitting.objects.create(
            project=self.prj, target_item=self.make_item('DEV', manufactured=True),
            user=self.user, qty=D(1))
        inv = models.Inventory.objects.create(
            project=self.prj, user=self.user, number='И-1', date='2026-05-01')
        req = models.Requisition.objects.create(
            project=self.prj, user=self.user, number='Т-1', date='2026-05-01')
        t = models.Transfer.objects.create(
            project=self.prj, user=self.user, number='Н-1', date='2026-05-01')
        w = models.Writeoff.objects.create(
            project=self.prj, user=self.user, number='С-1', date='2026-05-01')
        for doc in (r, k, inv, req, t, w):
            self.assertEqual(doc.status, models.DocStatus.DRAFT)
            self.assertFalse(doc.is_posted)

    def test_single_guard_freezes_edits_across_doc_types(self):
        """Один `_require_draft` гейтит правку прихода / передачи / комплектации."""
        # приход
        r = models.Receipt.objects.create(
            number='У-2', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.approve_receipt(r)
        self.assertTrue(r.is_posted)
        with self.assertRaises(ValidationError):
            engine.add_receipt_lot(r, self.make_item('B'), D(1))
        # передача
        dev = self.make_item('DEV', manufactured=True)
        dlot = self.receipt_lot(dev, self.prj, 5)
        t = engine.create_transfer(self.prj, self.user, 'Н-2')
        engine.add_transfer_line(t, dlot, D(1))
        engine.post_transfer(t)
        t.refresh_from_db()
        self.assertTrue(t.is_posted)
        with self.assertRaises(ValidationError):
            engine.add_transfer_line(t, dlot, D(1))

    def test_kitting_status_projection_is_backward_compatible(self):
        """До фронт-среза (Ф1b) кокпит отдаёт исторические `wip`/`closed`."""
        k = models.Kitting.objects.create(
            project=self.prj, target_item=self.make_item('DEV', manufactured=True),
            user=self.user, qty=D(1))
        self.assertEqual(engine.kitting_cockpit(k)['status'], 'wip')   # draft
        engine.close_kitting(k)
        self.assertEqual(engine.kitting_cockpit(k)['status'], 'closed')  # posted


class Wave13Fase1bTests(EngineTestBase):
    """Волна 13 Ф1b (бэкенд-срез): обвязка post/unpost + edit-freeze для
    Инвентаризации/Требования/Списания и единое правило удаления ордеров
    (draft — свободно; posted — сперва расфиксировать; `PROTECT` бережёт лоты)."""

    def _other_project(self):
        return models.Project.objects.create(
            code='P9', name='Проект 9', kind=models.Project.Kind.EXTERNAL)

    # ── post/unpost round-trip + пустой guard ──
    def test_post_unpost_roundtrip_three_docs(self):
        """draft → posted → draft для списания/требования/инвентаризации."""
        # списание
        lot = self.receipt_lot(self.make_item('A'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'С-1')
        engine.add_writeoff_line(w, lot, D(3))
        engine.post_writeoff(w); w.refresh_from_db()
        self.assertTrue(w.is_posted)
        self.assertTrue(engine.writeoff_cockpit(w)['posted'])
        engine.unpost_writeoff(w); w.refresh_from_db()
        self.assertFalse(w.is_posted)
        # инвентаризация
        inv = engine.create_inventory(self.prj, self.user, 'И-1')
        engine.add_inventory_lot(inv, self.make_item('B'), D(4))
        engine.post_inventory(inv); inv.refresh_from_db()
        self.assertTrue(inv.is_posted)
        self.assertTrue(engine.inventory_cockpit(inv)['posted'])
        engine.unpost_inventory(inv); inv.refresh_from_db()
        self.assertFalse(inv.is_posted)
        # требование
        src = self.receipt_lot(self.make_item('C'), self._other_project(), 10)
        req = engine.create_requisition(self.prj, self.user, 'Т-1')
        engine.add_requisition_line(req, src, D(2))
        engine.post_requisition(req); req.refresh_from_db()
        self.assertTrue(req.is_posted)
        self.assertTrue(engine.requisition_cockpit(req)['posted'])
        engine.unpost_requisition(req); req.refresh_from_db()
        self.assertFalse(req.is_posted)

    def test_post_empty_doc_refused(self):
        """Пустой ордер нельзя провести (как приход/передача)."""
        w = engine.create_writeoff(self.prj, self.user, 'С-2')
        with self.assertRaises(ValidationError):
            engine.post_writeoff(w)
        inv = engine.create_inventory(self.prj, self.user, 'И-2')
        with self.assertRaises(ValidationError):
            engine.post_inventory(inv)
        req = engine.create_requisition(self.prj, self.user, 'Т-2')
        with self.assertRaises(ValidationError):
            engine.post_requisition(req)

    # ── edit-freeze: проведённый документ read-only ──
    def test_edit_freeze_blocks_edits_on_posted_three_docs(self):
        """posted-ордер гейтит правку шапки И строк (единый `_require_draft`)."""
        # списание
        lot = self.receipt_lot(self.make_item('A'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'С-3')
        line = engine.add_writeoff_line(w, lot, D(3))
        engine.post_writeoff(w)
        with self.assertRaises(ValidationError):
            engine.update_writeoff(w, number='С-3x')
        with self.assertRaises(ValidationError):
            engine.add_writeoff_line(w, lot, D(1))
        with self.assertRaises(ValidationError):
            engine.update_writeoff_line(line, D(2))
        with self.assertRaises(ValidationError):
            engine.remove_writeoff_line(line)
        # инвентаризация
        inv = engine.create_inventory(self.prj, self.user, 'И-3')
        ilot = engine.add_inventory_lot(inv, self.make_item('B'), D(4))
        engine.post_inventory(inv)
        with self.assertRaises(ValidationError):
            engine.update_inventory(inv, number='И-3x')
        with self.assertRaises(ValidationError):
            engine.add_inventory_lot(inv, self.make_item('B2'), D(1))
        with self.assertRaises(ValidationError):
            engine.update_inventory_lot(ilot, qty=D(9))
        with self.assertRaises(ValidationError):
            engine.remove_inventory_lot(ilot)
        # требование
        src = self.receipt_lot(self.make_item('C'), self._other_project(), 10)
        req = engine.create_requisition(self.prj, self.user, 'Т-3')
        rline = engine.add_requisition_line(req, src, D(2))
        engine.post_requisition(req)
        with self.assertRaises(ValidationError):
            engine.update_requisition(req, number='Т-3x')
        with self.assertRaises(ValidationError):
            engine.update_requisition_line(rline, D(1))
        with self.assertRaises(ValidationError):
            engine.remove_requisition_line(rline)

    # ── удаление: правило draft/posted ──
    def test_delete_draft_writeoff_rebuilds_source(self):
        """Удаление черновика списания снимает `−ISSUE` — источник возвращает остаток."""
        lot = self.receipt_lot(self.make_item('A'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'С-4')
        engine.add_writeoff_line(w, lot, D(4))
        self.assertEqual(engine.lot_live_qty(lot), D(6))
        engine.delete_stock_document(w)
        self.assertFalse(models.Writeoff.objects.filter(pk=w.pk).exists())
        self.assertEqual(engine.lot_live_qty(lot), D(10))   # источник освобождён

    def test_delete_posted_refused_until_unpost(self):
        """posted — «сперва расфиксировать»: удаление отклонено, после unpost — ок."""
        lot = self.receipt_lot(self.make_item('A'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'С-5')
        engine.add_writeoff_line(w, lot, D(4))
        engine.post_writeoff(w)
        with self.assertRaises(ValidationError):
            engine.delete_stock_document(w)
        engine.unpost_writeoff(w)
        engine.delete_stock_document(w)
        self.assertFalse(models.Writeoff.objects.filter(pk=w.pk).exists())

    def test_delete_draft_requisition_drops_born_and_restores_source(self):
        """Удаление черновика требования: born-потомок снят, источник восстановлен."""
        src = self.receipt_lot(self.make_item('C'), self._other_project(), 10)
        req = engine.create_requisition(self.prj, self.user, 'Т-4')
        engine.add_requisition_line(req, src, D(3))
        born = req.lots.get()
        self.assertEqual(engine.lot_live_qty(src), D(7))
        engine.delete_stock_document(req)
        self.assertFalse(models.Lot.objects.filter(pk=born.pk).exists())  # born снят
        self.assertEqual(engine.lot_live_qty(src), D(10))                 # источник цел

    def test_delete_receipt_draft_cascades_born_lot(self):
        """Удаление черновика прихода уносит рождённый им лот (born-direct)."""
        r = models.Receipt.objects.create(
            number='У-9', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.delete_stock_document(r)
        self.assertFalse(models.Receipt.objects.filter(pk=r.pk).exists())
        self.assertFalse(models.Lot.objects.filter(pk=lot.pk).exists())

    def test_delete_refused_when_born_lot_consumed_downstream(self):
        """`PROTECT` бережёт потраченные лоты: born-лот акта потреблён ниже → отказ."""
        inv = engine.create_inventory(self.prj, self.user, 'И-9')
        found = engine.add_inventory_lot(inv, self.make_item('A'), D(10))
        # потребляем найденный лот списанием (downstream `−ISSUE`)
        w = engine.create_writeoff(self.prj, self.user, 'С-9')
        engine.add_writeoff_line(w, found, D(2))
        with self.assertRaises(ValidationError):
            engine.delete_stock_document(inv)
        self.assertTrue(models.Inventory.objects.filter(pk=inv.pk).exists())


class Wave13Fase2aTests(EngineTestBase):
    """Волна 13 Ф2a: MTI-ядро — `StockDoc` (миксин) → `StockDocument` (конкретный
    родитель); 6 документов стали наследниками, id-пространство унифицировано,
    дискриминатор `kind` штампуется. (Коллапс дуг в единый FK — Ф2b, ниже.)"""

    def _one_of_each(self):
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        k = models.Kitting.objects.create(
            project=self.prj, target_item=self.make_item('DEV', manufactured=True),
            user=self.user, qty=D(1))
        inv = models.Inventory.objects.create(
            project=self.prj, user=self.user, number='И-1', date='2026-05-01')
        req = models.Requisition.objects.create(
            project=self.prj, user=self.user, number='Т-1', date='2026-05-01')
        t = models.Transfer.objects.create(
            project=self.prj, user=self.user, number='Н-1', date='2026-05-01')
        w = models.Writeoff.objects.create(
            project=self.prj, user=self.user, number='С-1', date='2026-05-01')
        return {'receipt': r, 'kitting': k, 'inventory': inv,
                'requisition': req, 'transfer': t, 'writeoff': w}

    def test_kind_stamped_on_each_doc_type(self):
        """`save()` штампует свой `kind` в родителя на плоской вставке каждого типа."""
        for kind, doc in self._one_of_each().items():
            self.assertEqual(doc.kind, kind)
            self.assertTrue(models.StockDocument.objects.filter(
                pk=doc.pk, kind=kind).exists())

    def test_child_pk_is_unified_stockdocument_id(self):
        """PK каждого ребёнка = id `StockDocument`; id глобально уникальны между таблицами
        (готовность к схлопыванию дуг `Lot.origin`/`Attachment.owner` в один FK)."""
        docs = self._one_of_each()
        pks = [d.pk for d in docs.values()]
        self.assertEqual(len(pks), len(set(pks)))          # глобально уникальны
        for d in docs.values():
            self.assertTrue(models.StockDocument.objects.filter(pk=d.pk).exists())
        # ровно один родитель на каждого ребёнка, ничего лишнего
        self.assertEqual(models.StockDocument.objects.count(), len(docs))

    def test_origin_arc_points_at_unified_parent_id(self):
        """Дуга `Lot.origin` теперь указывает на единый id (= PK ребёнка = id родителя)."""
        r = models.Receipt.objects.create(
            number='У-2', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        self.assertEqual(lot.origin_id, r.pk)
        self.assertTrue(models.StockDocument.objects.filter(pk=lot.origin_id).exists())

    def test_mti_delete_removes_parent_row(self):
        """Удаление ребёнка-черновика сносит и строку родителя (MTI-каскад вверх)."""
        w = models.Writeoff.objects.create(
            project=self.prj, user=self.user, number='С-2', date='2026-05-01')
        pk = w.pk
        w.delete()
        self.assertFalse(models.Writeoff.objects.filter(pk=pk).exists())
        self.assertFalse(models.StockDocument.objects.filter(pk=pk).exists())


class Wave13Fase2bTests(EngineTestBase):
    """Волна 13 Ф2b: коллапс дуг в единый FK на `StockDocument`. `Lot.origin` и
    `StockLine.document` — по одному FK (Check «ровно один» умер); `Attachment` —
    двухпутный владелец (Item ↔ ордер). Инвариант проекции движений сохранён."""

    def _constraint_names(self, model):
        return {c.name for c in model._meta.constraints}

    def test_lot_origin_is_single_fk_no_arc(self):
        """`Lot.origin` — один FK на родителя; старых 4 FK и Check origin нет."""
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        self.assertEqual(lot.origin_id, r.pk)
        self.assertEqual(lot.origin_kind, models.StockDocument.Kind.RECEIPT)
        field_names = {f.name for f in models.Lot._meta.get_fields()}
        self.assertIn('origin', field_names)
        self.assertFalse({'receipt', 'kitting', 'inventory', 'requisition'}
                         & field_names)
        self.assertNotIn('lot_exactly_one_origin', self._constraint_names(models.Lot))

    def test_stockline_document_is_single_fk_no_arc(self):
        """`StockLine.document` — один FK; старых 4 FK и Check document нет."""
        lot = self.receipt_lot(self.make_item('R'), self.prj, 100)
        w = engine.create_writeoff(self.prj, self.user, 'С-1')
        line = engine.add_writeoff_line(w, lot, D(3))
        self.assertEqual(line.document_id, w.pk)
        self.assertEqual(line.doc_kind, models.StockDocument.Kind.WRITEOFF)
        field_names = {f.name for f in models.StockLine._meta.get_fields()}
        self.assertIn('document', field_names)
        self.assertFalse({'kitting', 'transfer', 'writeoff', 'requisition'}
                         & field_names)
        self.assertNotIn('stockline_exactly_one_document',
                         self._constraint_names(models.StockLine))

    def test_movement_projection_source_preserved_after_collapse(self):
        """Проекция движений неизменна: source_type = document.kind, source_id = id
        родителя (то же, что раньше давали `origin_kind`/`{kind}_id`)."""
        lot = self.receipt_lot(self.make_item('R'), self.prj, 50)
        w = engine.create_writeoff(self.prj, self.user, 'С-2')
        engine.add_writeoff_line(w, lot, D(4))
        born = lot.movements.get(type=models.StockMovement.Type.RECEIPT)
        self.assertEqual(born.source_type, models.StockDocument.Kind.RECEIPT)
        self.assertEqual(born.source_id, lot.origin_id)
        issue = lot.movements.get(type=models.StockMovement.Type.ISSUE)
        self.assertEqual(issue.source_type, models.StockDocument.Kind.WRITEOFF)
        self.assertEqual(issue.source_id, w.pk)

    def test_attachment_owner_two_way_arc(self):
        """Владелец вложения — Item ИЛИ ордер: 'receipt' → `document`, 'item' → `item`;
        API-строки owner_type те же; ровно один задан (Check жив, но двухпутный)."""
        r = models.Receipt.objects.create(
            number='У-2', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        item = self.make_item('A')
        f = SimpleUploadedFile('s.pdf', b'%PDF-1.4', content_type='application/pdf')
        att_doc = engine.add_attachment('receipt', r, f, self.user)
        self.assertEqual(att_doc.document_id, r.pk)
        self.assertIsNone(att_doc.item_id)
        f2 = SimpleUploadedFile('d.pdf', b'%PDF-1.4', content_type='application/pdf')
        att_item = engine.add_attachment('item', item, f2, self.user)
        self.assertEqual(att_item.item_id, item.pk)
        self.assertIsNone(att_item.document_id)
        # список по виду ордера строг: чужой вид → пусто (id глобально уникален)
        self.assertEqual(len(engine.attachments_for('receipt', r.pk)), 1)
        self.assertEqual(len(engine.attachments_for('transfer', r.pk)), 0)
        field_names = {f.name for f in models.Attachment._meta.get_fields()}
        self.assertFalse({'transfer', 'kitting', 'inventory', 'writeoff',
                          'requisition'} & field_names)
        self.assertIn('attachment_exactly_one_owner',
                      self._constraint_names(models.Attachment))

    def test_reverse_accessors_resolve_through_mti(self):
        """Реверсы дуг живут на родителе, но доступны с ребёнка через MTI:
        `receipt.lots`, `writeoff.lines`, `receipt.attachments`."""
        r = models.Receipt.objects.create(
            number='У-3', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(7))
        self.assertEqual(list(r.lots.all()), [lot])
        w = engine.create_writeoff(self.prj, self.user, 'С-3')
        line = engine.add_writeoff_line(w, lot, D(2))
        self.assertEqual(list(w.lines.all()), [line])
        f = SimpleUploadedFile('s.pdf', b'%PDF-1.4', content_type='application/pdf')
        att = engine.add_attachment('receipt', r, f, self.user)
        self.assertEqual(list(r.attachments.all()), [att])


class Wave13Fase2cTests(EngineTestBase):
    """Волна 13 Ф2c: общие поля `project`/`user`/`date`/`number`/`note` подняты с
    6 детей в MTI-родителя `StockDocument` (дедуп). Прямой доступ с ребёнка
    прозрачен через MTI; специфика осталась на детях; реверс — `project.documents`."""

    def _one_of_each(self):
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        k = models.Kitting.objects.create(
            project=self.prj, target_item=self.make_item('DEV', manufactured=True),
            user=self.user, qty=D(1), date='2026-05-02')
        inv = models.Inventory.objects.create(
            project=self.prj, user=self.user, number='И-1', date='2026-05-03',
            note='примечание акта')
        req = models.Requisition.objects.create(
            project=self.prj, user=self.user, number='Т-1', date='2026-05-04')
        t = models.Transfer.objects.create(
            project=self.prj, user=self.user, number='Н-1', date='2026-05-05')
        w = models.Writeoff.objects.create(
            project=self.prj, user=self.user, number='С-1', date='2026-05-06',
            reason='порча')
        return {'receipt': r, 'kitting': k, 'inventory': inv,
                'requisition': req, 'transfer': t, 'writeoff': w}

    def test_common_fields_live_on_parent(self):
        """`project`/`user`/`date`/`number`/`note` — поля StockDocument, НЕ детей."""
        parent = {f.name for f in models.StockDocument._meta.get_fields()}
        for name in ('project', 'user', 'date', 'number', 'note'):
            self.assertIn(name, parent)
        # у детей своих копий этих полей больше нет (только своя специфика)
        for child in (models.Receipt, models.Kitting, models.Inventory,
                      models.Requisition, models.Transfer, models.Writeoff):
            own = {f.name for f in child._meta.get_fields()
                   if getattr(f, 'model', None) is child}
            self.assertFalse({'project', 'user', 'date', 'number', 'note'} & own,
                             f'{child.__name__} держит поднятое поле: {own}')

    def test_child_specifics_stay(self):
        """Специфика осталась на детях: Receipt.contractor/purchase, Kitting.target_item/
        qty, Writeoff.reason."""
        self.assertIn('contractor', {f.name for f in models.Receipt._meta.get_fields()})
        self.assertIn('target_item', {f.name for f in models.Kitting._meta.get_fields()})
        self.assertIn('reason', {f.name for f in models.Writeoff._meta.get_fields()})

    def test_mti_transparent_read_and_create(self):
        """Создание с общими kwargs и чтение полей прозрачны через MTI на каждом типе."""
        for kind, doc in self._one_of_each().items():
            doc.refresh_from_db()
            self.assertEqual(doc.project_id, self.prj.id)
            self.assertEqual(doc.user_id, self.user.id)
            self.assertIsNotNone(doc.date)
            # то же значение видно на строке родителя
            sd = models.StockDocument.objects.get(pk=doc.pk)
            self.assertEqual((sd.project_id, sd.user_id, sd.date),
                             (doc.project_id, doc.user_id, doc.date))

    def test_reverse_accessor_is_documents(self):
        """Реверс общего `project` — `project.documents` (единый по всем видам),
        типизированный дочерний фильтр по родительскому полю тоже работает."""
        docs = self._one_of_each()
        self.assertEqual(self.prj.documents.count(), len(docs))
        self.assertEqual(
            models.Writeoff.objects.filter(project=self.prj).count(), 1)
        self.assertEqual(
            self.prj.documents.filter(kind=models.StockDocument.Kind.TRANSFER).count(), 1)

    def test_filter_by_parent_field_on_child_manager(self):
        """Дочерний менеджер фильтрует/сортирует по поднятому полю прозрачно
        (как в движке `Writeoff.objects.filter(project=…)`)."""
        self._one_of_each()
        r2 = models.Receipt.objects.create(
            number='У-2', date='2026-06-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        latest = models.Receipt.objects.filter(project=self.prj).order_by('-date').first()
        self.assertEqual(latest, r2)


class Wave13Fase2dTests(EngineTestBase):
    """Волна 13 Ф2d: условная валидация специфики по виду — восстановление per-kind
    обязательности `date`/`number`, ослабленной подъёмом полей в родителя (Ф2c).
    Единый kind-driven источник (`StockDocument.REQUIRED_HEADER_BY_KIND`/`clean`)
    гейтит и админ-форму (`full_clean → clean`), и проведение (`_require_header`)."""

    def test_required_map_mirrors_pre_2c_notnull(self):
        """Строгие виды требуют дату+номер; kitting свободен. Ф2e: relocation стал
        строгим (реальный документ с номером), только kitting остаётся свободным."""
        req = models.StockDocument.REQUIRED_HEADER_BY_KIND
        K = models.StockDocument.Kind
        for kind in (K.RECEIPT, K.INVENTORY, K.REQUISITION, K.TRANSFER, K.WRITEOFF,
                     K.RELOCATION):
            self.assertEqual(set(req[kind]), {'date', 'number'})
        self.assertEqual(req[K.KITTING], ())

    def test_clean_rejects_blank_number(self):
        """Админ-путь: Transfer с пустым номером ловится model.clean() (ошибка по полю)."""
        t = models.Transfer(project=self.prj, user=self.user, number='', date='2026-05-01')
        with self.assertRaises(ValidationError) as cm:
            t.clean()
        self.assertIn('number', cm.exception.message_dict)

    def test_clean_rejects_null_date(self):
        """Inventory без даты — ошибка по полю `date`."""
        inv = models.Inventory(project=self.prj, user=self.user, number='И-1', date=None)
        with self.assertRaises(ValidationError) as cm:
            inv.clean()
        self.assertIn('date', cm.exception.message_dict)

    def test_clean_passes_complete_header(self):
        """Полная шапка строгого вида проходит без ошибок."""
        models.Receipt(project=self.prj, user=self.user, contractor=self.supplier,
                       number='У-1', date='2026-05-01').clean()

    def test_kitting_exempt_from_header(self):
        """Kitting освобождён: пустой номер/дата в clean() не ошибка (как до Ф2c)."""
        models.Kitting(project=self.prj, user=self.user, qty=D(1), number='', date=None,
                       target_item=self.make_item('DEV', manufactured=True)).clean()

    def test_post_gates_incomplete_header(self):
        """Проведение не выпускает неполный ордер, минуя create-guard (прямой ORM).
        Гейт после empty-check: строку добавляем, чтобы дойти до валидации шапки."""
        lot = self.receipt_lot(self.make_item('R'), self.prj, 100)
        w = models.Writeoff.objects.create(project=self.prj, user=self.user,
                                            number='', date='2026-05-01', reason='порча')
        engine.add_writeoff_line(w, lot, D(5))
        with self.assertRaises(ValidationError):
            engine.post_writeoff(w)
        w.number = 'С-1'
        w.save(update_fields=['number'])
        engine.post_writeoff(w)
        self.assertTrue(w.is_posted)

    def test_approve_receipt_gated_on_missing_date(self):
        """approve_receipt гейтит отсутствующую дату (прямой ORM-обход дефолта create)."""
        r = models.Receipt.objects.create(project=self.prj, user=self.user,
                                           contractor=self.supplier, number='У-9', date=None)
        models.Lot.objects.create(item=self.make_item('B'), project=self.prj,
                                  origin=r, qty=D(3))
        with self.assertRaises(ValidationError):
            engine.approve_receipt(r)
        r.date = '2026-05-01'
        r.save(update_fields=['date'])
        engine.approve_receipt(r)
        self.assertTrue(r.is_posted)


class Wave13Fase2eTests(EngineTestBase):
    """Волна 13 Ф2e: перемещение (`Relocation`) + мультисклад. Движок считает остаток
    по паре `(лот, локация)`; ход перемещения = пара знаковых `StockLine`
    (`−q`@источник, `+q`@приёмник), сохраняющая тотал лота."""

    def setUp(self):
        super().setUp()
        # self.main (код MAIN) уже есть; добавим второе место — станок пайки.
        self.sold = models.Location.objects.create(code='105', name='Место пайки')
        self.case = self.make_item('CASE')
        self.lot = self.receipt_lot(self.case, self.prj, 12)   # рождён на self.main

    def _reloc_move(self, qty=4):
        r = engine.create_relocation(self.prj, self.user, number='ПЕР-1',
                                     date='2026-06-05')
        engine.add_relocation_line(r, self.lot, D(qty),
                                   from_location=self.main, to_location=self.sold)
        return r

    def test_conserves_total_splits_locations(self):
        """Тотал лота сохранён (12), распределение расщеплено: 8@103 + 4@105."""
        self._reloc_move(4)
        self.assertEqual(engine.lot_live_qty(self.lot), D(12))          # тотал цел
        self.assertEqual(engine.lot_live_qty(self.lot, self.main), D(8))
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(4))

    def test_lot_locations_breakdown(self):
        self._reloc_move(4)
        by = {r['location_id']: r['qty'] for r in engine.lot_locations(self.lot)}
        self.assertEqual(by, {self.main.id: D(8), self.sold.id: D(4)})

    def test_item_available_by_location(self):
        self._reloc_move(4)
        self.assertEqual(engine.item_available(self.case, self.prj), D(12))
        self.assertEqual(engine.item_available(self.case, self.prj, self.main), D(8))
        self.assertEqual(engine.item_available(self.case, self.prj, self.sold), D(4))

    def test_available_lots_by_location(self):
        self._reloc_move(4)
        at_main = engine.available_lots(self.case, self.prj, self.main)
        at_sold = engine.available_lots(self.case, self.prj, self.sold)
        self.assertEqual(at_main[0]['live_qty'], D(8))
        self.assertEqual(at_sold[0]['live_qty'], D(4))
        # без локации — тотал (байт-в-байт со старым контрактом кокпита)
        self.assertEqual(engine.available_lots(self.case, self.prj)[0]['live_qty'], D(12))

    def test_stock_map_by_location(self):
        self._reloc_move(4)
        row = next(r for r in engine.stock_map(self.case)['rows']
                   if r['project_id'] == self.prj.id)
        self.assertEqual(row['available'], D(12))
        by = {b['location_id']: b['available'] for b in row['by_location']}
        self.assertEqual(by, {self.main.id: D(8), self.sold.id: D(4)})

    def test_add_line_creates_signed_pair(self):
        r = self._reloc_move(4)
        lines = sorted(r.lines.all(), key=lambda l: l.qty)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].qty, D(-4))   # источник
        self.assertEqual(lines[0].location_id, self.main.id)
        self.assertEqual(lines[1].qty, D(4))    # приёмник
        self.assertEqual(lines[1].location_id, self.sold.id)

    def test_update_line_adjusts_both(self):
        r = self._reloc_move(4)
        engine.update_relocation_line(r, self.lot, qty=D(7))
        self.assertEqual(engine.lot_live_qty(self.lot, self.main), D(5))
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(7))
        self.assertEqual(engine.lot_live_qty(self.lot), D(12))

    def test_remove_line_restores(self):
        r = self._reloc_move(4)
        engine.remove_relocation_line(r, self.lot)
        self.assertEqual(r.lines.count(), 0)
        self.assertEqual(engine.lot_live_qty(self.lot, self.main), D(12))
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(0))

    def test_cockpit_move(self):
        r = self._reloc_move(4)
        cp = engine.relocation_cockpit(r)
        self.assertEqual(cp['total_qty'], D(4))
        self.assertEqual(len(cp['moves']), 1)
        m = cp['moves'][0]
        self.assertEqual(m['qty'], D(4))
        self.assertEqual(m['from_location_id'], self.main.id)
        self.assertEqual(m['to_location_id'], self.sold.id)
        self.assertEqual(m['from_live_qty'], D(8))
        self.assertEqual(m['to_live_qty'], D(4))

    def test_guards(self):
        r = engine.create_relocation(self.prj, self.user, number='ПЕР-2',
                                     date='2026-06-05')
        # одно и то же место
        with self.assertRaises(ValidationError):
            engine.add_relocation_line(r, self.lot, D(1),
                                       from_location=self.main, to_location=self.main)
        # чужой проект
        other = models.Project.objects.create(code='P2', name='P2',
                                               kind=models.Project.Kind.EXTERNAL)
        foreign = self.receipt_lot(self.make_item('X'), other, 5)
        with self.assertRaises(ValidationError):
            engine.add_relocation_line(r, foreign, D(1),
                                       from_location=self.main, to_location=self.sold)
        # неположительное кол-во
        with self.assertRaises(ValidationError):
            engine.add_relocation_line(r, self.lot, D(0),
                                       from_location=self.main, to_location=self.sold)
        # дубль лота
        engine.add_relocation_line(r, self.lot, D(2),
                                   from_location=self.main, to_location=self.sold)
        with self.assertRaises(ValidationError):
            engine.add_relocation_line(r, self.lot, D(1),
                                       from_location=self.main, to_location=self.sold)

    def test_post_gates_empty_and_header(self):
        # пустое перемещение не проводится
        empty = engine.create_relocation(self.prj, self.user, number='ПЕР-3',
                                         date='2026-06-05')
        with self.assertRaises(ValidationError):
            engine.post_relocation(empty)
        # шапка обязательна на проведении (relocation стал строгим, Ф2e); прямой ORM
        # обходит create-guard пустым номером
        r = models.Relocation.objects.create(project=self.prj, user=self.user,
                                              number='', date='2026-06-05')
        engine.add_relocation_line(r, self.lot, D(2),
                                   from_location=self.main, to_location=self.sold)
        with self.assertRaises(ValidationError):
            engine.post_relocation(r)
        r.number = 'ПЕР-4'
        r.save(update_fields=['number'])
        engine.post_relocation(r)
        self.assertTrue(r.is_posted)
        # под замком правка запрещена
        with self.assertRaises(ValidationError):
            engine.add_relocation_line(r, self.lot, D(1),
                                       from_location=self.main, to_location=self.sold)

    def test_kind_stamp_and_mti(self):
        r = self._reloc_move(4)
        self.assertEqual(r.kind, models.StockDocument.Kind.RELOCATION)
        parent = models.StockDocument.objects.get(id=r.id)
        self.assertEqual(parent.kind, 'relocation')
        self.assertEqual(parent.id, r.id)   # PK == id родителя (унификация Ф2a)

    def test_source_lots_picker(self):
        self._reloc_move(4)
        picker = engine.relocation_source_lots(self.prj)
        row = next(p for p in picker if p['lot_id'] == self.lot.id)
        self.assertEqual(row['live_qty'], D(12))
        by = {b['location_id']: b['qty'] for b in row['by_location']}
        self.assertEqual(by, {self.main.id: D(8), self.sold.id: D(4)})

    def test_delete_restores_and_conserves(self):
        r = self._reloc_move(4)
        engine.delete_stock_document(r)
        self.assertFalse(models.Relocation.objects.filter(id=r.id).exists())
        self.assertEqual(engine.lot_live_qty(self.lot), D(12))
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(0))


class Wave13Fase2fTests(EngineTestBase):
    """Волна 13 Ф2f: два идентификатора партии — `lot_name` (человеческий) и
    `part_number` (машинный, MPN/децимальный). Пришли на смену `received_name`/
    `serial_number`; писатели/кокпиты/метка разводят их независимо."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')
        self.receipt = self.make_receipt()

    def make_receipt(self, approved=False):
        return models.Receipt.objects.create(
            number='UPD-2f', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user,
            status=models.DocStatus.POSTED if approved else models.DocStatus.DRAFT)

    def test_born_lot_carries_both_identifiers(self):
        lot = engine.add_receipt_lot(self.receipt, self.item, D(5),
                                     lot_name='Резистор 10к',
                                     part_number='RES-10K-0805')
        self.assertEqual(lot.lot_name, 'Резистор 10к')
        self.assertEqual(lot.part_number, 'RES-10K-0805')
        row = engine.receipt_cockpit(self.receipt)['lots'][0]
        self.assertEqual(row['lot_name'], 'Резистор 10к')
        self.assertEqual(row['part_number'], 'RES-10K-0805')

    def test_update_separates_identifiers(self):
        lot = engine.add_receipt_lot(self.receipt, self.item, D(5))
        engine.update_receipt_lot(lot, part_number='PN-1')   # только PN
        lot.refresh_from_db()
        self.assertEqual(lot.part_number, 'PN-1')
        self.assertEqual(lot.lot_name, '')                   # имя не тронуто
        engine.update_receipt_lot(lot, lot_name='Имя')       # только имя
        lot.refresh_from_db()
        self.assertEqual(lot.lot_name, 'Имя')
        self.assertEqual(lot.part_number, 'PN-1')

    def test_lot_label_prefers_lot_name_then_part_number(self):
        lot = engine.add_receipt_lot(self.receipt, self.item, D(1),
                                     part_number='PN-ONLY')
        # только PN → метка берёт PN (нет человеческого имени)
        self.assertIn('PN-ONLY', engine._lot_label(lot))
        engine.update_receipt_lot(lot, lot_name='Человек')
        lot.refresh_from_db()
        # появилось имя → приоритет у него
        label = engine._lot_label(lot)
        self.assertIn('Человек', label)
        self.assertNotIn('PN-ONLY', label)

    def test_requisition_child_inherits_both(self):
        src = engine.add_receipt_lot(self.receipt, self.item, D(10),
                                     lot_name='Исходник', part_number='PN-SRC')
        white = models.Project.objects.create(
            code='WHITE', name='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        req = engine.create_requisition(white, self.user, 'ТР-1')
        engine.add_requisition_line(req, src, D(4))
        born = models.Lot.objects.get(origin=req)
        self.assertEqual(born.lot_name, 'Исходник')
        self.assertEqual(born.part_number, 'PN-SRC')


class Wave13Fase2gTests(EngineTestBase):
    """Волна 13 Ф2f+: `Supplier → Counterparty` (единая сущность с ролями) +
    структурный контрагент на приходе (`Receipt.contractor`, поставщик) и передаче
    (`Transfer.contractor`, заказчик). Пикеры фильтруют по роли."""

    def test_supplier_role_default(self):
        # унаследованный `self.supplier` (без явных ролей) — поставщик по умолчанию
        self.assertTrue(self.supplier.is_supplier)
        self.assertFalse(self.supplier.is_customer)

    def test_receipt_cockpit_emits_contractor(self):
        r = models.Receipt.objects.create(
            number='U-g', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        cp = engine.receipt_cockpit(r)
        self.assertEqual(cp['contractor_id'], self.supplier.id)
        self.assertEqual(cp['contractor_name'], self.supplier.name)

    def test_create_transfer_with_customer(self):
        cust = models.Counterparty.objects.create(
            name='Заказчик', is_supplier=False, is_customer=True)
        t = engine.create_transfer(self.prj, self.user, 'Н-1', contractor=cust)
        self.assertEqual(t.contractor_id, cust.id)
        cp = engine.transfer_cockpit(t)
        self.assertEqual(cp['contractor_id'], cust.id)
        self.assertEqual(cp['contractor_name'], 'Заказчик')

    def test_transfer_contractor_optional_and_settable(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-2')   # без получателя
        self.assertIsNone(t.contractor_id)
        self.assertEqual(engine.transfer_cockpit(t)['contractor_name'], '')
        cust = models.Counterparty.objects.create(
            name='Поздний', is_supplier=False, is_customer=True)
        engine.update_transfer(t, contractor=cust)               # проставить позже
        t.refresh_from_db()
        self.assertEqual(t.contractor_id, cust.id)
        engine.update_transfer(t, contractor=None)               # снять (nullable)
        t.refresh_from_db()
        self.assertIsNone(t.contractor_id)

    def test_update_transfer_sentinel_keeps_contractor(self):
        """Часовой `_UNSET`: правка номера/даты не сбрасывает получателя."""
        cust = models.Counterparty.objects.create(
            name='Стойкий', is_supplier=False, is_customer=True)
        t = engine.create_transfer(self.prj, self.user, 'Н-3', contractor=cust)
        engine.update_transfer(t, number='Н-3-ред')              # contractor не передан
        t.refresh_from_db()
        self.assertEqual(t.contractor_id, cust.id)
        self.assertEqual(t.number, 'Н-3-ред')

    def test_counterparties_endpoint_role_filter(self):
        models.Counterparty.objects.create(
            name='ТолькоЗаказчик', is_supplier=False, is_customer=True)
        c = Client()
        c.force_login(self.user)
        # ?role=supplier — унаследованный поставщик, без заказчика
        sup_names = {r['name'] for r in c.get('/api/counterparties/?role=supplier').json()}
        self.assertIn('Поставщик', sup_names)
        self.assertNotIn('ТолькоЗаказчик', sup_names)
        # ?role=customer — только заказчик
        cust_names = {r['name'] for r in c.get('/api/counterparties/?role=customer').json()}
        self.assertIn('ТолькоЗаказчик', cust_names)
        self.assertNotIn('Поставщик', cust_names)
        # быстрое создание с ролью
        created = c.post('/api/counterparties/',
                         {'name': 'Новый', 'role': 'customer'},
                         content_type='application/json').json()
        self.assertTrue(created['is_customer'])
        self.assertFalse(created['is_supplier'])


class Wave13Fase2hTests(EngineTestBase):
    """Волна 13 Ф2h: admin-гибрид. Родитель `StockDocument` — read-only обзор «все
    ордера» (смешанный список видов, некликабельный, без add/change); правка —
    в дочерних админках. Удаление РОДИТЕЛЯ делегирует правам (WAVE14 Ф0.2: нужно для
    MTI-каскада из детей), но массовое «удалить выбранные» с витрины снято."""

    def test_stockdocument_admin_view_only_delete_delegates(self):
        from django.contrib import admin as dj_admin
        from django.test import RequestFactory
        ma = dj_admin.site._registry[models.StockDocument]
        su = get_user_model().objects.create_superuser('su_del', 'a@a.tld', 'x')
        req = RequestFactory().get('/admin/'); req.user = su
        # витрина смотровая: без add/change, строки некликабельны
        self.assertFalse(ma.has_add_permission(req))
        self.assertFalse(ma.has_change_permission(req))
        self.assertIsNone(ma.list_display_links)
        # НО удаление делегирует правам (MTI-каскад из детей): суперюзеру можно
        self.assertTrue(ma.has_delete_permission(req))
        # массовое «удалить выбранные» с витрины снято
        self.assertNotIn('delete_selected', ma.get_actions(req))

    def test_overview_lists_all_kinds_mixed(self):
        # два разных вида ордера рождаются детьми — оба видны в родительском обзоре
        models.Receipt.objects.create(
            number='ПР-h', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        models.Writeoff.objects.create(
            number='СП-h', date='2026-05-02', reason='порча',
            project=self.prj, user=self.user)
        qs = models.StockDocument.objects.all()
        kinds = {d.kind for d in qs}
        self.assertEqual(kinds, {models.StockDocument.Kind.RECEIPT,
                                 models.StockDocument.Kind.WRITEOFF})
        numbers = {d.number for d in qs}
        self.assertEqual(numbers, {'ПР-h', 'СП-h'})

    def test_overview_changelist_http(self):
        models.Receipt.objects.create(
            number='ПР-http', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        su = get_user_model().objects.create_superuser(
            username='root', email='r@e.x', password='x')
        c = Client()
        c.force_login(su)
        resp = c.get('/admin/plume/stockdocument/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ПР-http')            # ордер виден в обзоре
        # добавления быть не должно — кнопки «Добавить» нет
        self.assertNotContains(resp, 'stockdocument/add/')


class Wave13Fase2jTests(EngineTestBase):
    """Волна 13 Ф2j: авторство `user` редактируемо под замком на всех ордерах
    (+ Purchase/Procurement). Кокпиты несут `user_id`/`user_name`; `update_*`
    принимают `user=_UNSET` (часовой), гейтятся замком; `/api/users/` — пикер."""

    def setUp(self):
        super().setUp()
        # второй автор с человеческим именем — цель переназначения авторства
        self.author2 = get_user_model().objects.create(
            username='ivan', first_name='Иван', last_name='Пэ')

    def test_cockpit_emits_author(self):
        r = models.Receipt.objects.create(
            number='U-j', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.author2)
        cp = engine.receipt_cockpit(r)
        self.assertEqual(cp['user_id'], self.author2.id)
        self.assertEqual(cp['user_name'], 'Иван Пэ')       # get_full_name()

    def test_purchase_and_procurement_carry_author(self):
        p = engine.create_purchase(self.prj, self.author2)
        self.assertEqual(engine.purchase_cockpit(p)['user_id'], self.author2.id)
        proc = engine.create_procurement(self.author2)
        self.assertEqual(engine.procurement_cockpit(proc)['user_id'], self.author2.id)

    def test_update_changes_author(self):
        r = models.Receipt.objects.create(
            number='U-j2', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        engine.update_receipt(r, user=self.author2)
        r.refresh_from_db()
        self.assertEqual(r.user_id, self.author2.id)

    def test_author_sentinel_keeps_current(self):
        """Часовой `_UNSET`: правка номера/даты не сбрасывает автора."""
        r = models.Receipt.objects.create(
            number='U-j3', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.author2)
        engine.update_receipt(r, number='U-j3-ред')        # user не передан
        r.refresh_from_db()
        self.assertEqual(r.user_id, self.author2.id)
        self.assertEqual(r.number, 'U-j3-ред')

    def test_author_none_rejected(self):
        """Автор обязателен (FK NOT NULL) — явный `None` отклоняется."""
        r = models.Receipt.objects.create(
            number='U-j4', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        with self.assertRaises(ValidationError):
            engine.update_receipt(r, user=None)

    def test_author_edit_gated_by_lock(self):
        """Проведённый ордер (edit-freeze) не отдаёт авторство на правку."""
        lot = self.receipt_lot(self.make_item('Rj'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'СП-j', date='2026-05-01')
        engine.add_writeoff_line(w, lot, D(2))
        engine.post_writeoff(w)
        with self.assertRaises(ValidationError):
            engine.update_writeoff(w, user=self.author2)
        w.refresh_from_db()
        self.assertEqual(w.user_id, self.user.id)          # автор не сдвинулся

    def test_users_endpoint_lists_active(self):
        inactive = get_user_model().objects.create(username='ghost', is_active=False)
        c = Client()
        c.force_login(self.user)
        ids = {u['id'] for u in c.get('/api/users/').json()}
        self.assertIn(self.author2.id, ids)
        self.assertNotIn(inactive.id, ids)                 # неактивные скрыты

    def test_patch_user_id_changes_author_http(self):
        r = models.Receipt.objects.create(
            number='U-j5', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        c = Client()
        c.force_login(self.user)
        resp = c.patch(f'/api/receipts/{r.id}/', {'user_id': self.author2.id},
                       content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['user_id'], self.author2.id)
        r.refresh_from_db()
        self.assertEqual(r.user_id, self.author2.id)
        # несуществующий пользователь → дружелюбный 400 (не 500)
        bad = c.patch(f'/api/receipts/{r.id}/', {'user_id': 99999},
                      content_type='application/json')
        self.assertEqual(bad.status_code, 400)


class Wave13Fase2kTests(EngineTestBase):
    """Волна 13 Ф2k: структурные якоря шапки под замком (вторая связка «Свода
    расхождений #A»). `project` — на всех ордерах/заказе; `target_item` —
    комплектация; `procurement` — заказ. Проект — якорь: лоты/строки следуют за
    ним, поэтому менять можно только у «пустого» ордера, иначе дружелюбный отказ.
    Часовой `_UNSET`, `None`-отказ (FK NOT NULL), gate замком `_require_draft`."""

    def setUp(self):
        super().setUp()
        self.prj2 = models.Project.objects.create(
            code='P9', name='Проект 9', kind=models.Project.Kind.EXTERNAL)

    # ── project-якорь ──────────────────────────────────────────────────────
    def test_project_changes_on_empty_order(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-k', date='2026-05-01')
        engine.update_writeoff(w, project=self.prj2)
        w.refresh_from_db()
        self.assertEqual(w.project_id, self.prj2.id)

    def test_project_refused_when_lines_exist(self):
        lot = self.receipt_lot(self.make_item('Rk'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'СП-k2', date='2026-05-01')
        engine.add_writeoff_line(w, lot, D(2))
        with self.assertRaises(ValidationError):
            engine.update_writeoff(w, project=self.prj2)
        w.refresh_from_db()
        self.assertEqual(w.project_id, self.prj.id)      # якорь не сдвинулся

    def test_project_refused_when_born_lots_exist(self):
        r = models.Receipt.objects.create(
            number='U-k', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        engine.add_receipt_lot(r, self.make_item('Rk3'), D(5))   # рождает born-лот
        with self.assertRaises(ValidationError):
            engine.update_receipt(r, project=self.prj2)

    def test_project_sentinel_keeps_current(self):
        """Часовой `_UNSET`: правка номера не сбрасывает проект-якорь."""
        r = models.Receipt.objects.create(
            number='U-k2', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        engine.update_receipt(r, number='U-k2-ред')       # project не передан
        r.refresh_from_db()
        self.assertEqual(r.project_id, self.prj.id)
        self.assertEqual(r.number, 'U-k2-ред')

    def test_project_none_rejected(self):
        r = models.Receipt.objects.create(
            number='U-k3', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        with self.assertRaises(ValidationError):
            engine.update_receipt(r, project=None)        # FK NOT NULL

    def test_project_edit_gated_by_lock(self):
        """Проведённый ордер (edit-freeze) не отдаёт проект на правку."""
        lot = self.receipt_lot(self.make_item('Rk4'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'СП-k4', date='2026-05-01')
        engine.add_writeoff_line(w, lot, D(2))
        engine.post_writeoff(w)
        with self.assertRaises(ValidationError):
            engine.update_writeoff(w, project=self.prj2)

    # ── target_item-якорь (комплектация) ───────────────────────────────────
    def test_target_item_changes_on_empty_kitting(self):
        dev = self.make_item('DEV-k', manufactured=True)
        dev2 = self.make_item('DEV-k2', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1))
        engine.update_kitting(k, target_item=dev2)
        k.refresh_from_db()
        self.assertEqual(k.target_item_id, dev2.id)

    def test_target_item_refused_when_lines_exist(self):
        comp = self.make_item('Rk5')
        lot = self.receipt_lot(comp, self.prj, 10)
        dev = self.make_item('DEV-k3', manufactured=True)
        dev2 = self.make_item('DEV-k4', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1))
        engine.add_kitting_line(k, comp, lot, D(3))
        with self.assertRaises(ValidationError):
            engine.update_kitting(k, target_item=dev2)
        k.refresh_from_db()
        self.assertEqual(k.target_item_id, dev.id)

    # ── Purchase: project + procurement ────────────────────────────────────
    def test_purchase_project_changes_without_receipts(self):
        p = engine.create_purchase(self.prj, self.user)
        engine.update_purchase(p, project=self.prj2)
        p.refresh_from_db()
        self.assertEqual(p.project_id, self.prj2.id)

    def test_purchase_project_refused_with_receipts(self):
        p = engine.create_purchase(self.prj, self.user)
        models.Receipt.objects.create(                    # приход, привязан к заказу
            number='U-k6', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user, purchase=p)
        with self.assertRaises(ValidationError):
            engine.update_purchase(p, project=self.prj2)
        p.refresh_from_db()
        self.assertEqual(p.project_id, self.prj.id)

    def test_purchase_procurement_changes(self):
        p = engine.create_purchase(self.prj, self.user)
        proc2 = engine.create_procurement(self.user)
        engine.update_purchase(p, procurement=proc2)
        p.refresh_from_db()
        self.assertEqual(p.procurement_id, proc2.id)
        self.assertEqual(engine.purchase_cockpit(p)['procurement_id'], proc2.id)

    # ── HTTP-срез ──────────────────────────────────────────────────────────
    def test_patch_project_id_http(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-k7', date='2026-05-01')
        c = Client()
        c.force_login(self.user)
        resp = c.patch(f'/api/writeoffs/{w.id}/', {'project_id': self.prj2.id},
                       content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['project_id'], self.prj2.id)
        # несуществующий проект → дружелюбный 400 (не 500)
        bad = c.patch(f'/api/writeoffs/{w.id}/', {'project_id': 99999},
                      content_type='application/json')
        self.assertEqual(bad.status_code, 400)

    def test_patch_kitting_target_http(self):
        dev = self.make_item('DEV-k5', manufactured=True)
        dev2 = self.make_item('DEV-k6', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1))
        c = Client()
        c.force_login(self.user)
        resp = c.patch(f'/api/kittings/{k.id}/', {'target_id': dev2.id},
                       content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['target_id'], dev2.id)


class Wave13Fase3HttpTests(EngineTestBase):
    """Волна 13 Ф3: HTTP-слой перемещения (relocation) + справочник мест.

    Движок/модель готовы с Ф2e — здесь проверяем эндпойнты жизненного цикла:
    создание → пикер лотов/мест → добавление хода → правка → провести/расфиксировать
    → удалить. Инвариант: тотал лота сохранён (перемещение двигает распределение
    по (лот,локация), не остаток)."""

    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save()
        self.sold = models.Location.objects.create(code='105', name='Место пайки')
        self.item = self.make_item('R100')
        self.lot = self.receipt_lot(self.item, self.prj, 12)  # born @ MAIN
        self.c = Client()
        self.c.force_login(self.user)

    def _create(self):
        r = self.c.post('/api/relocations/',
                        {'project_id': self.prj.id, 'number': 'ПЕР-1'},
                        content_type='application/json')
        self.assertEqual(r.status_code, 201)
        return r.json()['id']

    def test_locations_endpoint_lists_places(self):
        rows = self.c.get('/api/locations/').json()
        codes = {row['code'] for row in rows}
        self.assertEqual(codes, {'MAIN', '105'})

    def test_source_lots_picker_shows_live_lot_with_breakdown(self):
        rid = self._create()
        rows = self.c.get(f'/api/relocations/{rid}/source-lots/').json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['lot_id'], self.lot.id)
        self.assertEqual(D(str(rows[0]['live_qty'])), D(12))
        # разбивка по местам: весь остаток на MAIN
        self.assertEqual(rows[0]['by_location'][0]['code'], 'MAIN')

    def test_add_move_splits_distribution_total_preserved(self):
        rid = self._create()
        resp = self.c.post(f'/api/relocations/{rid}/lines/',
                           {'lot_id': self.lot.id, 'qty': 5,
                            'from_location_id': self.main.id,
                            'to_location_id': self.sold.id},
                           content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        ck = resp.json()
        self.assertEqual(len(ck['moves']), 1)
        # 7 @ MAIN, 5 @ 105, тотал 12
        self.assertEqual(engine.lot_live_qty(self.lot, self.main), D(7))
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(5))
        self.assertEqual(engine.lot_live_qty(self.lot), D(12))

    def test_same_source_and_dest_rejected(self):
        rid = self._create()
        resp = self.c.post(f'/api/relocations/{rid}/lines/',
                           {'lot_id': self.lot.id, 'qty': 5,
                            'from_location_id': self.main.id,
                            'to_location_id': self.main.id},
                           content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_foreign_project_lot_rejected(self):
        other = models.Project.objects.create(code='P2', name='Проект 2',
            kind=models.Project.Kind.EXTERNAL)
        foreign = self.receipt_lot(self.item, other, 3)
        rid = self._create()
        resp = self.c.post(f'/api/relocations/{rid}/lines/',
                           {'lot_id': foreign.id, 'qty': 1,
                            'from_location_id': self.main.id,
                            'to_location_id': self.sold.id},
                           content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_update_and_delete_move_keyed_by_lot(self):
        rid = self._create()
        self.c.post(f'/api/relocations/{rid}/lines/',
                    {'lot_id': self.lot.id, 'qty': 5,
                     'from_location_id': self.main.id,
                     'to_location_id': self.sold.id},
                    content_type='application/json')
        # правка кол-ва хода (ключ хода — лот)
        upd = self.c.patch(f'/api/relocations/{rid}/lines/{self.lot.id}/',
                          {'qty': 8}, content_type='application/json')
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(8))
        # удаление хода → распределение вернулось (всё на MAIN)
        rm = self.c.delete(f'/api/relocations/{rid}/lines/{self.lot.id}/')
        self.assertEqual(rm.status_code, 200)
        self.assertEqual(engine.lot_live_qty(self.lot, self.main), D(12))

    def test_post_unpost_delete_flow(self):
        rid = self._create()
        self.c.post(f'/api/relocations/{rid}/lines/',
                    {'lot_id': self.lot.id, 'qty': 5,
                     'from_location_id': self.main.id,
                     'to_location_id': self.sold.id},
                    content_type='application/json')
        posted = self.c.post(f'/api/relocations/{rid}/post/')
        self.assertEqual(posted.status_code, 200)
        self.assertTrue(posted.json()['posted'])
        # posted — удаление отклонено (сперва расфиксировать)
        self.assertEqual(self.c.delete(f'/api/relocations/{rid}/').status_code, 400)
        # добавление хода под замком отклонено
        blocked = self.c.post(f'/api/relocations/{rid}/lines/',
                              {'lot_id': self.lot.id, 'qty': 1,
                               'from_location_id': self.main.id,
                               'to_location_id': self.sold.id},
                              content_type='application/json')
        self.assertEqual(blocked.status_code, 400)
        # расфиксировать → удалить; тотал лота цел
        self.assertEqual(self.c.post(f'/api/relocations/{rid}/unpost/').status_code, 200)
        self.assertEqual(self.c.delete(f'/api/relocations/{rid}/').status_code, 204)
        self.assertFalse(models.Relocation.objects.filter(pk=rid).exists())
        self.assertEqual(engine.lot_live_qty(self.lot), D(12))
        self.assertEqual(engine.lot_live_qty(self.lot, self.main), D(12))

    def test_empty_relocation_cannot_be_posted(self):
        rid = self._create()
        resp = self.c.post(f'/api/relocations/{rid}/post/')
        self.assertEqual(resp.status_code, 400)

    def test_patch_header_number_and_project_anchor(self):
        rid = self._create()
        # № правится свободно
        upd = self.c.patch(f'/api/relocations/{rid}/', {'number': 'ПЕР-9'},
                          content_type='application/json')
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.json()['number'], 'ПЕР-9')
        # проект-якорь: у пустого ордера сменить можно
        other = models.Project.objects.create(code='P3', name='Проект 3',
            kind=models.Project.Kind.EXTERNAL)
        moved = self.c.patch(f'/api/relocations/{rid}/', {'project_id': other.id},
                            content_type='application/json')
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()['project_id'], other.id)


class Wave13Fase4Tests(EngineTestBase):
    """Волна 13 Ф4: место хранения как сущность «Склады» — что на нём лежит + ДНК."""

    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save()
        self.sold = models.Location.objects.create(code='105', name='Место пайки')
        self.item = self.make_item('R100')
        self.lot = self.receipt_lot(self.item, self.prj, 12)  # born @ MAIN
        self.c = Client()
        self.c.force_login(self.user)

    def test_location_stock_lists_live_lots_with_project(self):
        rows = engine.location_stock(self.main)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['lot_id'], self.lot.id)
        self.assertEqual(rows[0]['qty'], D(12))
        self.assertEqual(rows[0]['project_code'], self.prj.code)
        # второе место пусто
        self.assertEqual(engine.location_stock(self.sold), [])

    def test_location_stock_reflects_relocation_split(self):
        rel = engine.create_relocation(self.prj, self.user, 'ПЕР-1')
        engine.add_relocation_line(rel, self.lot, D(5), self.main, self.sold)
        main_rows = engine.location_stock(self.main)
        sold_rows = engine.location_stock(self.sold)
        self.assertEqual(main_rows[0]['qty'], D(7))
        self.assertEqual(sold_rows[0]['qty'], D(5))

    def test_create_location_and_duplicate_code_rejected(self):
        loc = engine.create_location('201', 'Архив', kind='хранилище')
        self.assertEqual(loc.kind, 'хранилище')
        with self.assertRaises(ValidationError):
            engine.create_location('201', 'Дубль')

    def test_update_location_dna_and_duplicate_guard(self):
        engine.update_location(self.sold, name='Пайка-2', kind='цех')
        self.sold.refresh_from_db()
        self.assertEqual(self.sold.name, 'Пайка-2')
        self.assertEqual(self.sold.kind, 'цех')
        # код на занятый — дружелюбный отказ
        with self.assertRaises(ValidationError):
            engine.update_location(self.sold, code='MAIN')

    def test_http_location_cockpit_and_patch(self):
        resp = self.c.get(f'/api/locations/{self.main.id}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['code'], 'MAIN')
        self.assertEqual(len(body['stock']), 1)
        # PATCH вида (свободный текст)
        patched = self.c.patch(f'/api/locations/{self.main.id}/',
                              {'kind': 'основной'}, content_type='application/json')
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()['kind'], 'основной')

    def test_http_create_location(self):
        resp = self.c.post('/api/locations/',
                          {'code': '301', 'name': 'Резерв'},
                          content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(models.Location.objects.filter(code='301').exists())
        # дубль кода → 400
        dup = self.c.post('/api/locations/',
                        {'code': '301', 'name': 'Дубль'},
                        content_type='application/json')
        self.assertEqual(dup.status_code, 400)


class EntityDeleteTests(EngineTestBase):
    """WAVE14 Ф2: консистентное удаление справочных сущностей из UI (Изделие/Склад/
    Заказ/Закупка/Проект) — единый friendly-guard движка, как у ордеров."""

    # ── Изделие ──
    def test_delete_item_free_when_unlinked(self):
        it = self.make_item('FREE')
        engine.delete_item(it)
        self.assertFalse(models.Item.objects.filter(pk=it.pk).exists())

    def test_delete_item_blocked_by_lot(self):
        it = self.make_item('WITHLOT')
        self.receipt_lot(it, self.prj, 5)
        with self.assertRaises(ValidationError):
            engine.delete_item(it)
        self.assertTrue(models.Item.objects.filter(pk=it.pk).exists())

    def test_delete_item_blocked_when_used_in_bom(self):
        parent = self.make_item('P', manufactured=True)
        comp = self.make_item('C')
        engine.add_bom_line(parent, comp, D(2))
        with self.assertRaises(ValidationError):
            engine.delete_item(comp)                 # входит в чужой BOM
        # родителя (свой BOM — каскад) сносим свободно
        parent_id = parent.pk
        engine.delete_item(parent)
        self.assertFalse(models.Item.objects.filter(pk=parent_id).exists())
        self.assertFalse(models.BomLine.objects.filter(parent_id=parent_id).exists())

    def test_delete_item_blocked_by_demand(self):
        dev = self.make_item('DEV', manufactured=True)
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(1))
        with self.assertRaises(ValidationError):
            engine.delete_item(dev)

    # ── Склад ──
    def test_delete_location_free_when_empty(self):
        loc = models.Location.objects.create(code='EMPTY', name='Пустой склад')
        engine.delete_location(loc)
        self.assertFalse(models.Location.objects.filter(pk=loc.pk).exists())

    def test_delete_location_blocked_by_movements(self):
        self.receipt_lot(self.make_item('X'), self.prj, 3)   # рождает движение на MAIN
        with self.assertRaises(ValidationError):
            engine.delete_location(self.main)
        self.assertTrue(models.Location.objects.filter(pk=self.main.pk).exists())

    # ── Заказ ──
    def test_delete_purchase_draft_cascades_lines(self):
        p = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(p, self.make_item('A'), D(4))
        pid = p.pk
        engine.delete_purchase(p)
        self.assertFalse(models.Purchase.objects.filter(pk=pid).exists())
        self.assertFalse(models.PurchaseLine.objects.filter(purchase_id=pid).exists())

    def test_delete_purchase_blocked_when_sent(self):
        p = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(p, self.make_item('A'), D(4))
        engine.send_purchase(p)
        with self.assertRaises(ValidationError):
            engine.delete_purchase(p)                # отправлен — сперва в черновик

    def test_delete_purchase_blocked_by_receipt(self):
        p = engine.create_purchase(self.prj, self.user)
        self.receipt_lot(self.make_item('A'), self.prj, 5, purchase=p)
        with self.assertRaises(ValidationError):
            engine.delete_purchase(p)                # привязан приход

    # ── Закупка (план) ──
    def test_delete_procurement_draft_free(self):
        proc = engine.create_procurement(self.user)
        engine.add_procurement_line(proc, self.make_item('A'), D(3))
        pid = proc.pk
        engine.delete_procurement(proc)
        self.assertFalse(models.Procurement.objects.filter(pk=pid).exists())
        self.assertFalse(models.ProcurementLine.objects.filter(procurement_id=pid).exists())

    def test_delete_procurement_blocked_by_purchase(self):
        p = engine.create_purchase(self.prj, self.user)   # авто-создаёт procurement-родителя
        proc = p.procurement
        with self.assertRaises(ValidationError):
            engine.delete_procurement(proc)          # привязан заказ

    # ── Проект ──
    def test_delete_project_free_when_empty(self):
        prj = models.Project.objects.create(
            code='EMPTY-PRJ', name='Пустой', kind=models.Project.Kind.EXTERNAL)
        engine.delete_project(prj)
        self.assertFalse(models.Project.objects.filter(pk=prj.pk).exists())

    def test_delete_project_blocked_by_lot(self):
        self.receipt_lot(self.make_item('X'), self.prj, 3)
        with self.assertRaises(ValidationError):
            engine.delete_project(self.prj)

    def test_delete_project_blocked_by_demand(self):
        dev = self.make_item('DEV', manufactured=True)
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(1))
        with self.assertRaises(ValidationError):
            engine.delete_project(self.prj)

    def test_delete_project_internal_forbidden(self):
        stock = models.Project.objects.create(
            code='WHITE', name='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        with self.assertRaises(ValidationError):
            engine.delete_project(stock)


class EntityDeleteHttpTests(TestCase):
    """WAVE14 Ф2: HTTP-путь DELETE справочных сущностей (204 успех / 400 friendly-guard)."""

    def setUp(self):
        self.user = get_user_model().objects.create(username='admin', is_superuser=True)
        self.main = models.Location.objects.create(code='MAIN', name='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', name='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.sup = models.Counterparty.objects.create(name='П')
        self.c = Client()
        self.c.force_login(self.user)

    def test_item_delete_204_and_guard_400(self):
        it = models.Item.objects.create(design_item_id='FREE', description='FREE', category=_cat())
        self.assertEqual(self.c.delete(f'/api/items/{it.id}/').status_code, 204)
        self.assertFalse(models.Item.objects.filter(pk=it.pk).exists())
        # с лотом → 400
        it2 = models.Item.objects.create(design_item_id='WL', description='WL', category=_cat())
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01',
            contractor=self.sup, project=self.prj, user=self.user)
        lot = models.Lot.objects.create(item=it2, project=self.prj, origin=r, qty=D(1))
        engine.rebuild_movements(lot)
        self.assertEqual(self.c.delete(f'/api/items/{it2.id}/').status_code, 400)

    def test_location_delete_204_and_guard_400(self):
        loc = models.Location.objects.create(code='EMPTY', name='Пустой')
        self.assertEqual(self.c.delete(f'/api/locations/{loc.id}/').status_code, 204)
        r = models.Receipt.objects.create(number='U-2', date='2026-05-01',
            contractor=self.sup, project=self.prj, user=self.user)
        lot = models.Lot.objects.create(
            item=models.Item.objects.create(design_item_id='M', description='M', category=_cat()),
            project=self.prj, origin=r, qty=D(1))
        engine.rebuild_movements(lot)               # движение на MAIN
        self.assertEqual(self.c.delete(f'/api/locations/{self.main.id}/').status_code, 400)

    def test_project_delete_204_and_guard_400(self):
        empty = models.Project.objects.create(
            code='E', name='E', kind=models.Project.Kind.EXTERNAL)
        self.assertEqual(self.c.delete(f'/api/projects/{empty.id}/').status_code, 204)
        r = models.Receipt.objects.create(number='U-3', date='2026-05-01',
            contractor=self.sup, project=self.prj, user=self.user)
        lot = models.Lot.objects.create(
            item=models.Item.objects.create(design_item_id='Q', description='Q', category=_cat()),
            project=self.prj, origin=r, qty=D(1))
        engine.rebuild_movements(lot)
        self.assertEqual(self.c.delete(f'/api/projects/{self.prj.id}/').status_code, 400)

    def test_purchase_delete_204(self):
        p = engine.create_purchase(self.prj, self.user)
        self.assertEqual(self.c.delete(f'/api/purchases/{p.id}/').status_code, 204)
        self.assertFalse(models.Purchase.objects.filter(pk=p.pk).exists())

    def test_procurement_delete_204(self):
        proc = engine.create_procurement(self.user)
        self.assertEqual(self.c.delete(f'/api/procurements/{proc.id}/').status_code, 204)
        self.assertFalse(models.Procurement.objects.filter(pk=proc.pk).exists())
