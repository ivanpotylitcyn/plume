"""Юнит-тесты движка волны 1 — гарантия корректности формул (вместо прод-обкатки).

Каждый тест строит минимальный сценарий и проверяет одну формулу.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase

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


class TransferCockpitTests(EngineTestBase):
    """Волна 5: кокпит передачи — отгрузка партии заказчику (`−ISSUE`), пикер
    отдаваемых лотов, guard чужого проекта, коррекция строк."""

    def setUp(self):
        super().setUp()
        self.device = self.make_item('DEV', manufactured=True,
                                      kind=models.Item.Kind.DEVICE)
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
        self.lot.serial_number = 'ЗН-42'
        self.lot.save(update_fields=['serial_number'])
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
        self.src.serial_number = 'ЗН-9'
        self.src.save(update_fields=['unit_cost', 'serial_number'])
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
        dev = self.make_item('DEV', manufactured=True, kind=models.Item.Kind.DEVICE)
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
            supplier=self.supplier, project=self.prj, user=self.user)
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
            user=self.user, qty=D(1), status=models.Kitting.Status.WIP)
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
        dev = self.make_item(f'DEV{screw.code}{suffix}', manufactured=True,
                             kind=models.Item.Kind.DEVICE)
        models.BomLine.objects.create(parent=dev, component=screw, qty=D(qty_per))
        return dev

    def test_rolls_up_by_item_across_projects(self):
        scr = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
        dev = self._device_with_screw(scr, 4)
        prj2 = models.Project.objects.create(code='P2', name='Проект 2',
                                             kind=models.Project.Kind.EXTERNAL)
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=prj2, target_item=dev, qty=D(5))

        rows = {r['item_code']: r for r in engine.command_deficit()['rows']}
        row = rows['SCR']
        self.assertEqual(row['need'], D(60))         # 40 + 20
        self.assertEqual(row['to_order'], D(60))     # склада/заказов нет
        self.assertEqual(row['status'], 'to_order')
        self.assertEqual(len(row['by_project']), 2)

    def test_stock_and_order_no_cross_project_netting(self):
        scr = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
        dev = self._device_with_screw(scr, 4)
        prj2 = models.Project.objects.create(code='P2', name='Проект 2',
                                             kind=models.Project.Kind.EXTERNAL)
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=prj2, target_item=dev, qty=D(5))
        # склад лежит только в P1 (10 шт) — НЕ должен гасить нужду P2
        self.receipt_lot(scr, self.prj, 10)

        row = {r['item_code']: r for r in engine.command_deficit()['rows']}['SCR']
        self.assertEqual(row['have'], D(10))          # только P1 покрыт
        self.assertEqual(row['to_order'], D(50))      # 30 (P1) + 20 (P2), не 40
        self.assertEqual(row['need'], D(60))

    def test_closed_and_internal_projects_excluded(self):
        scr = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
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
        scr = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
        dev_a = self._device_with_screw(scr, 4, suffix='A')
        dev_b = self._device_with_screw(scr, 3, suffix='B')
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev_a, qty=D(2))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev_b, qty=D(2))

        row = {r['item_code']: r for r in engine.command_deficit()['rows']}['SCR']
        self.assertEqual(row['need'], D(14))          # 2×4 + 2×3
        self.assertEqual(len(row['by_project']), 1)   # агрегат по проекту

    def test_sorted_worst_first(self):
        red = self.make_item('RED', kind=models.Item.Kind.MATERIAL)
        green = self.make_item('GRN', kind=models.Item.Kind.MATERIAL)
        dev = self.make_item('DEVX', manufactured=True, kind=models.Item.Kind.DEVICE)
        models.BomLine.objects.create(parent=dev, component=red, qty=D(1))
        models.BomLine.objects.create(parent=dev, component=green, qty=D(1))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(5))
        self.receipt_lot(green, self.prj, 100)        # GRN покрыт ✓, RED красный ▲

        codes = [r['item_code'] for r in engine.command_deficit()['rows']]
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
        item = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
        p1 = engine.add_to_procurement(item, D(15), self.user)
        self.assertEqual(p1.lines.get(item=item).qty, D(15))
        p2 = engine.add_to_procurement(item, D(10), self.user)
        self.assertEqual(p1.id, p2.id)                 # тот же черновик
        self.assertEqual(p2.lines.get(item=item).qty, D(25))

    def test_bridge_ignores_solo_purchase_stub(self):
        # заказ волны 4 плодит 1:1-заглушку Procurement — мост её не должен трогать
        engine.create_purchase(self.prj, self.user)      # заглушка (draft, с purchase)
        item = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
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
        self.scr = self.make_item('SCR', kind=models.Item.Kind.MATERIAL)
        dev = self.make_item('DEV', manufactured=True, kind=models.Item.Kind.DEVICE)
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
        self.item = models.Item.objects.create(code='R100', name='R100')
        self.sup = models.Supplier.objects.create(name='П')
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01',
            supplier=self.sup, project=self.prj,
            user=get_user_model().objects.first())
        self.lot = models.Lot.objects.create(item=self.item, project=self.prj,
            receipt=r, qty=D(10))
        engine.rebuild_movements(self.lot)
        self.c = Client()

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
        self.scr = models.Item.objects.create(code='SCR', name='Винт',
            kind=models.Item.Kind.MATERIAL)
        self.dev = models.Item.objects.create(code='DEV', name='Прибор',
            kind=models.Item.Kind.DEVICE, is_manufactured=True)
        models.BomLine.objects.create(parent=self.dev, component=self.scr, qty=D(4))
        models.ProjectDemand.objects.create(project=self.prj, target_item=self.dev,
            qty=D(10))
        self.c = Client()

    def test_command_deficit_and_bridge(self):
        svod = self.c.get('/api/command-deficit/')
        self.assertEqual(svod.status_code, 200)
        rows = {r['item_code']: r for r in svod.json()['rows']}
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
        self.scr = models.Item.objects.create(code='SCR', name='Винт',
            kind=models.Item.Kind.MATERIAL)
        dev = models.Item.objects.create(code='DEV', name='Прибор',
            kind=models.Item.Kind.DEVICE, is_manufactured=True)
        models.BomLine.objects.create(parent=dev, component=self.scr, qty=D(4))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=self.prj2, target_item=dev, qty=D(5))
        self.c = Client()
        add = self.c.post('/api/command-deficit/add-to-procurement/',
            {'item_id': self.scr.id, 'qty': 60}, content_type='application/json')
        self.pid = add.json()['procurement_id']

    def test_pegging_projection_and_autopeg(self):
        peg = self.c.get(f'/api/procurements/{self.pid}/pegging/')
        self.assertEqual(peg.status_code, 200)
        row = peg.json()['rows'][0]
        self.assertEqual(row['item_code'], 'SCR')
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
        x = models.Item.objects.create(code='X', name='X')
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
        i = engine.create_item('R100', 'Резистор', kind=models.Item.Kind.MATERIAL,
                               uom='шт', is_manufactured=False, estimated_cost=D('1.50'))
        self.assertEqual(i.code, 'R100')
        self.assertEqual(i.kind, models.Item.Kind.MATERIAL)
        self.assertEqual(i.estimated_cost, D('1.50'))
        # дефолты: kind=component, uom=шт
        j = engine.create_item(' B1 ', ' Плата ')
        self.assertEqual(j.code, 'B1')                 # обрезка пробелов
        self.assertEqual(j.kind, models.Item.Kind.COMPONENT)
        self.assertEqual(j.uom, 'шт')

    def test_create_item_rejects_dup_empty_and_bad_kind(self):
        engine.create_item('R100', 'Резистор')
        with self.assertRaises(ValidationError):
            engine.create_item('R100', 'Дубль')        # дубль артикула
        with self.assertRaises(ValidationError):
            engine.create_item('', 'Без кода')
        with self.assertRaises(ValidationError):
            engine.create_item('X1', '')               # без названия
        with self.assertRaises(ValidationError):
            engine.create_item('X2', 'Плохой вид', kind='gadget')

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

    def test_create_item_http(self):
        r = self.c.post('/api/items/', {'code': 'R100', 'name': 'Резистор',
            'kind': 'material', 'is_manufactured': False},
            content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['code'], 'R100')
        # появляется в списке
        lst = self.c.get('/api/items/').json()
        self.assertTrue(any(i['code'] == 'R100' for i in lst))
        # дубль → 400
        dup = self.c.post('/api/items/', {'code': 'R100', 'name': 'Дубль'},
            content_type='application/json')
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
