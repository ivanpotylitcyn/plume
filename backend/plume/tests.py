"""Юнит-тесты движка волны 1 — гарантия корректности формул (вместо прод-обкатки).

Каждый тест строит минимальный сценарий и проверяет одну формулу.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
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


class KittingCockpitTests(EngineTestBase):
    """Волна 2: кокпит комплектации — призрачные строки, пайка, закрытие."""

    def setUp(self):
        super().setUp()
        self.device = self.make_item('DEV', manufactured=True,
                                     kind=models.Item.Kind.DEVICE)
        self.case = self.make_item('CASE')
        self.res = self.make_item('RES')
        # прибор из 1 корпуса и 2 резисторов
        models.BomLine.objects.create(parent=self.device, component=self.case, qty=D(1))
        models.BomLine.objects.create(parent=self.device, component=self.res, qty=D(2))

    def make_kitting(self, qty=2):
        return models.Kitting.objects.create(
            project=self.prj, target_item=self.device, user=self.user,
            qty=D(qty), status=models.Kitting.Status.WIP)

    def test_ghost_rows_before_piercing(self):
        # склад пуст → обе призрачные строки красные (▲ to_order)
        k = self.make_kitting(qty=2)
        c = engine.kitting_cockpit(k)
        rows = {r['component_code']: r for r in c['rows']}
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
        row = {r['component_code']: r for r in c['rows']}['CASE']
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
        row = {r['component_code']: r for r in c['rows']}['CASE']
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
        self.assertEqual(k.status, models.Kitting.Status.CLOSED)
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
        self.assertEqual(k.status, models.Kitting.Status.WIP)
        self.assertFalse(models.Lot.objects.filter(pk=lot.pk).exists())

    def test_reopen_blocked_when_device_consumed(self):
        k = self.make_kitting(qty=1)
        device_lot = engine.close_kitting(k)
        # прибор передан заказчику → потомок вниз, переоткрытие запрещено
        transfer = models.Transfer.objects.create(
            project=self.prj, user=self.user, date='2026-06-01', number='TN-1')
        models.TransferLine.objects.create(transfer=transfer, lot=device_lot, qty=D(1))
        engine.rebuild_movements(device_lot)
        with self.assertRaises(ValidationError):
            engine.reopen_kitting(k)


class ReceiptCockpitTests(EngineTestBase):
    """Волна 3: кокпит прихода — строки-лоты УПД, рождение +RECEIPT, замок."""

    def make_receipt(self, approved=False):
        return models.Receipt.objects.create(
            number='УПД-Т', date='2026-05-01', supplier=self.supplier,
            project=self.prj, user=self.user, approved=approved)

    def test_add_lot_births_receipt_movement(self):
        r = self.make_receipt()
        case = self.make_item('CASE')
        lot = engine.add_receipt_lot(r, case, D(12), unit_cost=D(800),
                                     received_name='Корпус Al')
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
        engine.update_receipt_lot(lot, unit_cost=D(42), received_name='Ы')
        lot.refresh_from_db()
        self.assertEqual(lot.unit_cost, D(42))
        self.assertEqual(lot.received_name, 'Ы')

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
                                          status=models.Kitting.Status.WIP)
        engine.add_kitting_line(k, comp, lot, D(30))   # спаяли — потреблён ниже
        with self.assertRaises(ValidationError):
            engine.remove_receipt_lot(lot)

    def test_approve_locks_edits(self):
        r = self.make_receipt()
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.approve_receipt(r)
        r.refresh_from_db()
        self.assertTrue(r.approved)
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
        self.assertFalse(r.approved)
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
                                          status=models.Kitting.Status.WIP)
        c = engine.kitting_cockpit(k)
        row = {r['component_code']: r for r in c['rows']}['R']
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
        item = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
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
        item = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
        p = engine.create_purchase(self.prj, self.user)
        line = engine.add_purchase_line(p, item, D(40))
        engine.send_purchase(p)
        engine.unsend_purchase(p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))
        engine.update_purchase_line(line, D(30))       # снова можно
        self.assertEqual(line.qty, D(30))

    def test_cancel_drops_from_on_order(self):
        item = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
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
        item = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
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
            number='УПД-Х', date='2026-05-01', supplier=self.supplier,
            project=self.prj, user=self.user)
        with self.assertRaises(ValidationError):
            engine.set_receipt_purchase(r, p)           # заказ чужого проекта

    def test_deficit_bridge_creates_and_increments_line(self):
        item = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
        p1 = engine.add_to_project_order(self.prj, item, D(15), self.user)
        self.assertEqual(p1.lines.get(item=item).qty, D(15))
        # повтор той же позиции — инкремент в том же черновике
        p2 = engine.add_to_project_order(self.prj, item, D(10), self.user)
        self.assertEqual(p1.id, p2.id)
        self.assertEqual(p2.lines.get(item=item).qty, D(25))
