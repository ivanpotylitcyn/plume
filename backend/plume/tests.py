"""Юнит-тесты движка волны 1 — гарантия корректности формул (вместо прод-обкатки).

Каждый тест строит минимальный сценарий и проверяет одну формулу.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from plume import models
from plume import engine


def D(x):
    return Decimal(str(x))


class EngineTestBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='t')
        self.main = models.Location.objects.create(code='MAIN', name='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', name='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.supplier = models.Supplier.objects.create(name='Поставщик')

    def make_item(self, code, manufactured=False, kind=models.Item.Kind.COMPONENT):
        return models.Item.objects.create(code=code, name=code, kind=kind,
                                          is_manufactured=manufactured)

    def receipt_lot(self, item, project, qty, purchase=None):
        r = models.Receipt.objects.create(
            number=f'UPD-{item.code}-{qty}', date='2026-05-01', supplier=self.supplier,
            project=project, user=self.user, purchase=purchase)
        lot = models.Lot.objects.create(item=item, project=project, receipt=r, qty=D(qty))
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
                                          status=models.Kitting.Status.WIP)
        models.KittingLine.objects.create(kitting=k, component=comp, lot=lot,
                                          location=self.main, qty=D(30))
        engine.rebuild_movements(lot)
        self.assertEqual(engine.lot_live_qty(lot), D(70))

    def test_available_can_be_negative(self):
        comp = self.make_item('R')
        lot = self.receipt_lot(comp, self.prj, 5)
        dev = self.make_item('DEV', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1),
                                          status=models.Kitting.Status.WIP)
        models.KittingLine.objects.create(kitting=k, component=comp, lot=lot,
                                          location=self.main, qty=D(8))
        engine.rebuild_movements(lot)
        self.assertEqual(engine.item_available(comp, self.prj), D(-3))
        self.assertTrue(engine.item_has_negative_lot(comp, self.prj))

    def test_cancelled_kitting_does_not_issue(self):
        comp = self.make_item('R')
        lot = self.receipt_lot(comp, self.prj, 10)
        dev = self.make_item('DEV', manufactured=True)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1),
                                          status=models.Kitting.Status.CANCELLED)
        models.KittingLine.objects.create(kitting=k, component=comp, lot=lot,
                                          location=self.main, qty=D(4))
        engine.rebuild_movements(lot)
        self.assertEqual(engine.lot_live_qty(lot), D(10))


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
        item = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
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
        item = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
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
                                      status=models.Kitting.Status.WIP)
        self.assertEqual(engine.item_on_order(board, self.prj), D(4))


class DeficitTests(EngineTestBase):
    def test_full_deficit_scenario(self):
        device = self.make_item('DEV', manufactured=True, kind=models.Item.Kind.DEVICE)
        case = self.make_item('CASE')
        screw = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
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
        lines = {ln['component_code']: ln for ln in dm['lines']}
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
        lot = models.Lot.objects.create(item=item, project=white, inventory=inv, qty=D(5))
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
