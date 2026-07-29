"""Юнит-тесты движка волны 1 — гарантия корректности формул (вместо прод-обкатки).

Каждый тест строит минимальный сценарий и проверяет одну формулу.
"""
import json
import os
import shutil
import tempfile
from decimal import Decimal
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from plume import admin
from plume import models
from plume import engine
from plume import views


def D(x):
    return Decimal(str(x))


def _cat(code='test', description='Тест'):
    """Категория-заглушка для тестов (волна 15: `Item.category` — обязательный FK).
    Класс изделия в движке логику не ветвит, поэтому одной общей категории хватает."""
    c, _ = models.Category.objects.get_or_create(code=code, defaults={'description': description})
    return c


# Изолированный MEDIA_ROOT для тестов вложений (волна 11): загрузки не пачкают
# рабочий backend/media; чистим на выходе модуля.
_TEST_MEDIA = tempfile.mkdtemp(prefix='plume-test-media-')


def tearDownModule():
    shutil.rmtree(_TEST_MEDIA, ignore_errors=True)


class EngineTestBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='t')
        self.main = models.Location.objects.create(code='MAIN', description='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', description='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.supplier = models.Counterparty.objects.create(description='Поставщик')

    def make_item(self, code, manufactured=False, kind=None):
        # `kind` — исторический хинт (движок по классу не ветвит); категория —
        # общая заглушка `_cat()`. `manufactured` → ось `native` (волна 15).
        return models.Item.objects.create(
            code=code, description=code, category=_cat(),
            native=manufactured)

    def make_purchase(self, project=None, contractor=None, **kw):
        """Заказ-черновик, готовый к фиксации: **с контрагентом**.

        Ф17: контрагент обязателен к фиксации заказа («у кого купили»), поэтому фикстура
        «настоящий заказ» его несёт. Тесты самого гейта заводят заказ голым
        `engine.create_purchase` и контрагента не ставят.
        """
        p = engine.create_purchase(project or self.prj, self.user, **kw)
        return engine.update_purchase(p, contractor=contractor or self.supplier)

    def receipt_lot(self, item, project, qty, purchase=None, locked=True):
        """Партия, приехавшая по УПД. Волна 19, Ф15: поставка **зафиксирована** —
        иначе её партия на складе не лежит (замок гейтит склад), а фикстура значит
        именно «товар на складе». `locked=False` — для тестов самого гейта."""
        r = models.Receipt.objects.create(
            number=f'UPD-{item.code}-{qty}', date='2026-05-01', contractor=self.supplier,
            project=project, user=self.user, purchase=purchase, locked=locked)
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
                                          locked=True)     # Ф15: спаяно = зафиксировано
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
                                          locked=True)
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
        born = engine.lock_kitting(k)              # posted + рождается лот-прибор
        self.assertTrue(models.Lot.objects.filter(pk=born.pk).exists())
        engine.unlock_kitting(k)                    # расфиксировать: born-лот снят
        self.assertFalse(models.Lot.objects.filter(pk=born.pk).exists())  # не фантом
        self.assertFalse(k.locked)
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
        # Ф15: расход виден складу только у зафиксированных документов — фикстура
        # моделирует свершившийся факт, поэтому все три заведены под замком.
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1),
                                          locked=True)
        w = models.Writeoff.objects.create(project=self.prj, user=self.user,
                                           number='W-1', date='2026-06-01',
                                           locked=True)
        cust = models.Project.objects.create(
            code='P2', description='Проект 2', kind=models.Project.Kind.EXTERNAL)
        t = models.Transfer.objects.create(project=self.prj, user=self.user,
                                            number='T-1', date='2026-06-01',
                                            locked=True)
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
        # Ф17: заказ самодостаточен (закупка-план опциональна), контрагент обязателен
        # к фиксации — CHECK `purchase_locked_has_contractor`.
        purchase = models.Purchase.objects.create(
            project=self.prj, user=self.user, contractor=self.supplier,
            locked=True)
        models.PurchaseLine.objects.create(purchase=purchase, item=item, qty=D(40))
        # поступило 15 по этому заказу
        self.receipt_lot(item, self.prj, 15, purchase=purchase)
        self.assertEqual(engine.item_on_order(item, self.prj), D(25))

    def test_draft_purchase_not_counted(self):
        item = self.make_item('SCR', kind='material')
        purchase = models.Purchase.objects.create(
            project=self.prj, user=self.user, locked=False)   # черновик — без контрагента
        models.PurchaseLine.objects.create(purchase=purchase, item=item, qty=D(40))
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))

    def test_manufactured_wip_is_on_order(self):
        board = self.make_item('BRD', manufactured=True)
        models.Kitting.objects.create(project=self.prj, target_item=board,
                                      user=self.user, qty=D(4),
                                      locked=False)
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
        # SCR: заказано 25 (зафиксировано), склада нет → ●25 ▲15
        purchase = models.Purchase.objects.create(
            project=self.prj, user=self.user, contractor=self.supplier,
            locked=True)
        models.PurchaseLine.objects.create(purchase=purchase, item=screw, qty=D(25))

        d = engine.project_deficit(self.prj)
        dm = d['demands'][0]
        self.assertEqual(dm['status'], 'to_order')   # worst-of (SCR ▲)
        # аккордеон-дерево: CASE/SCR — прямые покупные листья прибора (depth 0)
        lines = {ln['component_code']: ln for ln in dm['tree']}
        self.assertEqual(lines['CASE']['status'], 'available')
        self.assertEqual(lines['CASE']['have'], D(10))
        self.assertTrue(lines['CASE']['is_leaf'])
        self.assertEqual(lines['SCR']['need'], D(40))
        self.assertEqual(lines['SCR']['on_order'], D(25))
        self.assertEqual(lines['SCR']['to_order'], D(15))


class PurchaseCoverageTests(EngineTestBase):
    """Ф1b: цвет заказа в списке — покрытие строк лотами приходов."""

    def _purchase_with_line(self, item, qty):
        p = engine.create_purchase(self.prj, self.user)
        models.PurchaseLine.objects.create(purchase=p, item=item, qty=D(qty))
        return p

    def test_empty_purchase_to_order(self):
        p = engine.create_purchase(self.prj, self.user)
        self.assertEqual(engine.purchase_coverage(p), 'to_order')

    def test_nothing_received_to_order(self):
        p = self._purchase_with_line(self.make_item('R1'), 10)
        self.assertEqual(engine.purchase_coverage(p), 'to_order')

    def test_partial_on_order(self):
        item = self.make_item('R1')
        p = self._purchase_with_line(item, 10)
        self.receipt_lot(item, self.prj, 4, purchase=p)
        self.assertEqual(engine.purchase_coverage(p), 'on_order')

    def test_fully_received_available(self):
        item = self.make_item('R1')
        p = self._purchase_with_line(item, 10)
        self.receipt_lot(item, self.prj, 10, purchase=p)
        self.assertEqual(engine.purchase_coverage(p), 'available')

    def test_one_line_open_keeps_on_order(self):
        a, b = self.make_item('A'), self.make_item('B')
        p = engine.create_purchase(self.prj, self.user)
        models.PurchaseLine.objects.create(purchase=p, item=a, qty=D(5))
        models.PurchaseLine.objects.create(purchase=p, item=b, qty=D(5))
        self.receipt_lot(a, self.prj, 5, purchase=p)      # A закрыт, B пуст
        self.assertEqual(engine.purchase_coverage(p), 'on_order')


class ProjectHealthTests(EngineTestBase):
    """Ф1b: цвет проекта в списке — worst-of здоровья (вычисляемая проекция)."""

    def _device_demand(self, qty):
        dev = self.make_item('DEV', manufactured=True, kind='device')
        case = self.make_item('CASE')
        models.BomLine.objects.create(parent=dev, component=case, qty=D(1))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(qty))
        return dev, case

    def test_internal_project_none(self):
        white = models.Project.objects.create(
            code='W', description='Собственный склад', kind=models.Project.Kind.INTERNAL_STOCK)
        self.assertIsNone(engine.project_health(white))

    def test_empty_project_none(self):
        self.assertIsNone(engine.project_health(self.prj))

    def test_component_to_order_red(self):
        self._device_demand(5)                    # склад пуст → CASE к заказу
        self.assertEqual(engine.project_health(self.prj), 'to_order')

    def test_available_but_unassembled_orange(self):
        _dev, case = self._device_demand(2)
        self.receipt_lot(case, self.prj, 10)      # компонент есть, приборы не собраны
        self.assertEqual(engine.project_health(self.prj), 'on_order')

    def test_all_assembled_green(self):
        dev, case = self._device_demand(1)
        lot = self.receipt_lot(case, self.prj, 5)
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1), locked=False)
        engine.add_kitting_line(k, case, lot, D(1))
        engine.lock_kitting(k)                     # рождает прибор → собрано
        self.assertEqual(engine.project_health(self.prj), 'available')


class StockMapTests(EngineTestBase):
    def test_map_across_projects_sorted(self):
        white = models.Project.objects.create(
            code='WHITE', description='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        item = self.make_item('CASE')
        self.receipt_lot(item, self.prj, 12)
        inv = models.Inventory.objects.create(project=white, user=self.user,
                                              number='INV-1', date='2026-06-01',
                                              locked=True)   # Ф15: иначе не на складе
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


class KittingFormTests(EngineTestBase):
    """Волна 2: форма комплектации — призрачные строки, пайка, закрытие."""

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
            qty=D(qty), locked=False)

    def test_ghost_rows_before_piercing(self):
        # склад пуст → обе призрачные строки красные (▲ to_order)
        k = self.make_kitting(qty=2)
        c = engine.kitting_form(k)
        rows = {r['component_code']: r for r in c['rows']}
        self.assertEqual(rows['CASE']['need'], D(2))     # 1×2
        self.assertEqual(rows['RES']['need'], D(4))      # 2×2
        self.assertEqual(rows['CASE']['pierced'], D(0))
        self.assertEqual(rows['CASE']['ghost']['status'], 'to_order')
        self.assertEqual(c['worst_status'], 'to_order')

    def test_ghost_available_when_stock_exists(self):
        # есть лот корпуса → призрачная строка зелёная + лот-кандидат
        self.receipt_lot(self.case, self.prj, 10)
        k = self.make_kitting(qty=2)
        c = engine.kitting_form(k)
        row = {r['component_code']: r for r in c['rows']}['CASE']
        self.assertEqual(row['ghost']['status'], 'available')
        self.assertEqual(len(row['ghost']['candidate_lots']), 1)
        self.assertEqual(row['ghost']['candidate_lots'][0]['live_qty'], D(10))

    def test_pierce_creates_line_and_issue(self):
        lot = self.receipt_lot(self.case, self.prj, 10)
        k = self.make_kitting(qty=2)
        engine.add_kitting_line(k, self.case, lot, D(2))
        # Ф15: пайка черновика склад не двигает — компонент ещё целиком свой
        self.assertEqual(engine.lot_live_qty(lot), D(10))
        engine.lock_kitting(k)                   # фиксация материализует −ISSUE
        self.assertEqual(engine.lot_live_qty(lot), D(8))
        c = engine.kitting_form(k)
        row = {r['component_code']: r for r in c['rows']}['CASE']
        self.assertEqual(row['pierced'], D(2))
        self.assertEqual(row['remaining'], D(0))
        self.assertIsNone(row['ghost'])          # покрыто — призрака нет
        self.assertEqual(len(row['real_lines']), 1)

    def test_pierce_rejects_foreign_project_lot(self):
        other = models.Project.objects.create(code='P2', description='Другой')
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
        engine.lock_kitting(k)                   # Ф15: расход виден с фиксации
        self.assertEqual(engine.lot_live_qty(lot), D(5))

    def test_remove_line_restores_qty(self):
        """Ф15: правка черновика склад не трогает вовсе — ни добавление строки, ни
        её снятие; проверяем через фиксацию (расход) и расфиксацию (возврат)."""
        lot = self.receipt_lot(self.case, self.prj, 10)
        k = self.make_kitting(qty=2)
        line = engine.add_kitting_line(k, self.case, lot, D(3))
        self.assertEqual(engine.lot_live_qty(lot), D(10))   # черновик не двигает
        engine.lock_kitting(k)
        self.assertEqual(engine.lot_live_qty(lot), D(7))
        engine.unlock_kitting(k)                            # расход отпущен
        self.assertEqual(engine.lot_live_qty(lot), D(10))
        engine.remove_kitting_line(line)
        engine.lock_kitting(k)
        self.assertEqual(engine.lot_live_qty(lot), D(10))

    def test_close_births_device_lot_with_cost_snapshot(self):
        case_lot = self.receipt_lot(self.case, self.prj, 10)
        case_lot.unit_cost = D(800); case_lot.save()
        res_lot = self.receipt_lot(self.res, self.prj, 100)
        res_lot.unit_cost = D(1); res_lot.save()
        k = self.make_kitting(qty=2)
        engine.add_kitting_line(k, self.case, case_lot, D(2))   # 2×800
        engine.add_kitting_line(k, self.res, res_lot, D(4))     # 4×1
        lot = engine.lock_kitting(k)
        k.refresh_from_db()
        self.assertTrue(k.locked)
        self.assertEqual(lot.qty, D(2))
        # (2×800 + 4×1) / 2 = 802
        self.assertEqual(lot.unit_cost, D('802.00'))
        self.assertEqual(engine.lot_live_qty(lot), D(2))

    def test_close_only_wip(self):
        k = self.make_kitting(qty=1)
        engine.lock_kitting(k)
        with self.assertRaises(ValidationError):
            engine.lock_kitting(k)

    def test_pierce_blocked_after_close(self):
        lot = self.receipt_lot(self.case, self.prj, 10)
        k = self.make_kitting(qty=1)
        engine.lock_kitting(k)
        with self.assertRaises(ValidationError):
            engine.add_kitting_line(k, self.case, lot, D(1))

    def test_reopen_restores_wip_and_removes_lot(self):
        k = self.make_kitting(qty=1)
        lot = engine.lock_kitting(k)
        engine.unlock_kitting(k)
        k.refresh_from_db()
        self.assertFalse(k.locked)
        self.assertFalse(models.Lot.objects.filter(pk=lot.pk).exists())

    def test_reopen_blocked_when_device_consumed(self):
        k = self.make_kitting(qty=1)
        device_lot = engine.lock_kitting(k)
        # прибор передан заказчику → потомок вниз, переоткрытие запрещено
        transfer = models.Transfer.objects.create(
            project=self.prj, user=self.user, date='2026-06-01', number='TN-1')
        models.StockLine.objects.create(document=transfer, lot=device_lot,
                                        location=self.main, qty=D(-1))
        engine.rebuild_movements(device_lot)
        with self.assertRaises(ValidationError):
            engine.unlock_kitting(k)


class ReceiptFormTests(EngineTestBase):
    """Волна 3: форма прихода — строки-лоты УПД, рождение +RECEIPT, замок."""

    def make_receipt(self, approved=False):
        return models.Receipt.objects.create(
            number='УПД-Т', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user,
            locked=approved)

    def test_add_lot_births_receipt_movement(self):
        r = self.make_receipt()
        case = self.make_item('CASE')
        lot = engine.add_receipt_lot(r, case, D(12), unit_cost=D(800),
                                     lot_name='Корпус Al')
        self.assertEqual(lot.project_id, r.project_id)   # проект наследован
        # Ф15: партия черновой поставки на складе не лежит — движение рождает замок
        self.assertEqual(engine.lot_live_qty(lot), D(0))
        self.assertEqual(lot.movements.count(), 0)
        engine.lock_receipt(r)
        self.assertEqual(engine.lot_live_qty(lot), D(12))
        mv = lot.movements.get()
        self.assertEqual(mv.type, models.StockMovement.Type.RECEIPT)
        self.assertEqual(mv.qty, D(12))

    def test_form_shows_lines_and_total(self):
        r = self.make_receipt()
        engine.add_receipt_lot(r, self.make_item('A'), D(2), unit_cost=D(100))
        engine.add_receipt_lot(r, self.make_item('B'), D(3), unit_cost=D(10))
        c = engine.receipt_form(r)
        self.assertEqual(len(c['lots']), 2)
        self.assertEqual(c['total_cost'], D(230))        # 2×100 + 3×10
        self.assertFalse(c['locked'])

    def test_add_lot_rejects_nonpositive_qty(self):
        r = self.make_receipt()
        with self.assertRaises(ValidationError):
            engine.add_receipt_lot(r, self.make_item('A'), D(0))

    def test_update_lot_qty_rebuilds(self):
        r = self.make_receipt()
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(10))
        engine.update_receipt_lot(lot, qty=D(7))
        engine.lock_receipt(r)                   # Ф15: склад видит с фиксации
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
                                          locked=False)
        engine.add_kitting_line(k, comp, lot, D(30))   # спаяли — потреблён ниже
        with self.assertRaises(ValidationError):
            engine.remove_receipt_lot(lot)

    def test_approve_locks_edits(self):
        r = self.make_receipt()
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.lock_receipt(r)
        r.refresh_from_db()
        self.assertTrue(r.locked)
        with self.assertRaises(ValidationError):
            engine.update_receipt_lot(lot, qty=D(9))
        with self.assertRaises(ValidationError):
            engine.add_receipt_lot(r, self.make_item('B'), D(1))

    def test_approve_rejects_empty(self):
        r = self.make_receipt()
        with self.assertRaises(ValidationError):
            engine.lock_receipt(r)

    def test_unapprove_reenables_edits(self):
        r = self.make_receipt()
        lot = engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.lock_receipt(r)
        self.assertEqual(engine.lot_live_qty(lot), D(5))
        engine.unlock_receipt(r)
        r.refresh_from_db()
        self.assertFalse(r.locked)
        self.assertEqual(engine.lot_live_qty(lot), D(0))   # Ф15: ушла со склада
        engine.update_receipt_lot(lot, qty=D(9))           # снова можно править
        engine.lock_receipt(r)
        self.assertEqual(engine.lot_live_qty(lot), D(9))

    def test_received_lot_feeds_kitting_form(self):
        # сверенный приход РЕЗ → лот виден форме комплектации как кандидат
        # (Ф15: именно сверенный — черновая поставка складу не видна)
        r = self.make_receipt()
        comp = self.make_item('R')
        engine.add_receipt_lot(r, comp, D(50))
        engine.lock_receipt(r)
        dev = self.make_item('DEV', manufactured=True)
        models.BomLine.objects.create(parent=dev, component=comp, qty=D(2))
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1),
                                          locked=False)
        c = engine.kitting_form(k)
        row = {r['component_code']: r for r in c['rows']}['R']
        self.assertEqual(row['ghost']['status'], 'available')
        self.assertEqual(len(row['ghost']['candidate_lots']), 1)


class PurchaseFormTests(EngineTestBase):
    """Волна 4: форма заказа — строки-обязательства, замок отправки, гашение
    приходом, мост «дефицит → заказ»."""

    def test_create_purchase_leaves_plan_and_contractor_empty(self):
        """Ф17: заказ рождается БЕЗ закупки-плана (и без контрагента).

        До Ф17 `procurement` был NOT NULL, и рождение тихо плодило закупку-пустышку;
        теперь заказ — самостоятельная сущность, план и контрагент выбирают в форме.
        """
        p = engine.create_purchase(self.prj, self.user)
        self.assertFalse(p.locked)
        self.assertIsNone(p.procurement_id)
        self.assertIsNone(p.contractor_id)
        self.assertEqual(p.project_id, self.prj.id)
        self.assertFalse(models.Procurement.objects.exists())   # пустышек не бывает

    def test_add_line_and_form_totals(self):
        p = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(p, self.make_item('A'), D(10))
        engine.add_purchase_line(p, self.make_item('B'), D(5))
        c = engine.purchase_form(p)
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

    def test_post_counts_in_on_order(self):
        item = self.make_item('SCR', kind='material')
        p = self.make_purchase()
        engine.add_purchase_line(p, item, D(40))
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))  # draft не в счёте
        engine.lock_purchase(p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(40))

    def test_post_rejects_empty(self):
        p = self.make_purchase()
        with self.assertRaises(ValidationError):
            engine.lock_purchase(p)

    def test_lines_locked_after_post(self):
        p = self.make_purchase()
        line = engine.add_purchase_line(p, self.make_item('A'), D(10))
        engine.lock_purchase(p)
        with self.assertRaises(ValidationError):
            engine.update_purchase_line(line, D(5))
        with self.assertRaises(ValidationError):
            engine.add_purchase_line(p, self.make_item('B'), D(1))

    def test_unpost_reenables_and_drops_from_on_order(self):
        item = self.make_item('SCR', kind='material')
        p = self.make_purchase()
        line = engine.add_purchase_line(p, item, D(40))
        engine.lock_purchase(p)
        engine.unlock_purchase(p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))
        engine.update_purchase_line(line, D(30))       # снова можно
        self.assertEqual(line.qty, D(30))

    def test_delete_drops_from_on_order(self):
        """Отмена = удаление (волна 19, Р1): статуса `cancelled` больше нет, снять
        обязательство можно только удалив заказ — и сперва сняв замок."""
        item = self.make_item('SCR', kind='material')
        p = self.make_purchase()
        engine.add_purchase_line(p, item, D(40))
        engine.lock_purchase(p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(40))
        with self.assertRaises(ValidationError):        # утверждённый не удалить
            engine.delete_purchase(p)
        engine.unlock_purchase(p)
        engine.delete_purchase(p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))
        self.assertFalse(models.Purchase.objects.filter(pk=p.pk).exists())

    def test_linked_receipt_reduces_on_order_and_closes_line(self):
        item = self.make_item('SCR', kind='material')
        p = self.make_purchase()
        line = engine.add_purchase_line(p, item, D(40))
        engine.lock_purchase(p)
        # приход 15, связанный с заказом → поступило 15, «заказано» 25
        self.receipt_lot(item, self.prj, 15, purchase=p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(25))
        c = engine.purchase_form(p)
        row = c['rows'][0]
        self.assertEqual(row['received'], D(15))
        self.assertEqual(row['remaining'], D(25))
        self.assertEqual(row['status'], 'on_order')     # ● частично
        self.assertEqual(len(c['receipts']), 1)
        # добираем остаток → строка закрыта (✓), «заказано» 0
        self.receipt_lot(item, self.prj, 25, purchase=p)
        self.assertEqual(engine.item_on_order(item, self.prj), D(0))
        row = engine.purchase_form(p)['rows'][0]
        self.assertEqual(row['status'], 'available')

    def test_set_receipt_purchase_rejects_foreign_project(self):
        other = models.Project.objects.create(
            code='P2', description='Проект 2', kind=models.Project.Kind.EXTERNAL)
        p = engine.create_purchase(other, self.user)
        r = models.Receipt.objects.create(
            number='УПД-Х', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        with self.assertRaises(ValidationError):
            engine.set_receipt_purchase(r, p)           # заказ чужого проекта

    def test_deficit_bridge_creates_and_increments_line(self):
        item = self.make_item('SCR', kind='material')
        p1 = engine.add_to_project_purchase(self.prj, item, D(15), self.user)
        self.assertEqual(p1.lines.get(item=item).qty, D(15))
        # повтор той же позиции — инкремент в том же черновике
        p2 = engine.add_to_project_purchase(self.prj, item, D(10), self.user)
        self.assertEqual(p1.id, p2.id)
        self.assertEqual(p2.lines.get(item=item).qty, D(25))


class ReceiptFromPurchaseTests(EngineTestBase):
    """Волна 19, Ф6: поток «Заказ → УПД» — накладная преднабивается остатком заказа."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('SCR', kind='material')
        self.other = self.make_item('CAP', kind='material')
        self.p = self.make_purchase()
        engine.add_purchase_line(self.p, self.item, D(40))
        engine.add_purchase_line(self.p, self.other, D(10))
        # Ф17: поставщик поставки приезжает из ЗАКАЗА (Р3 отменена) — он у заказа свой.
        engine.lock_purchase(self.p)

    def test_prefills_lines_from_order(self):
        r = engine.create_receipt_from_purchase(self.p, self.user)
        self.assertEqual(r.purchase_id, self.p.id)
        self.assertEqual(r.project_id, self.prj.id)
        self.assertEqual(r.contractor_id, self.supplier.id)   # Ф17: из заказа
        self.assertFalse(r.locked)                            # черновик
        lots = {lot.item_id: lot for lot in r.lots.all()}
        self.assertEqual(lots[self.item.id].qty, D(40))
        self.assertEqual(lots[self.other.id].qty, D(10))
        # Цена — 0, НЕ estimated_cost: оценка, забытая при фиксации, стала бы фактом
        # трат проекта неотличимо от реальной цены УПД.
        self.assertEqual(lots[self.item.id].unit_cost, D(0))
        self.assertEqual(lots[self.item.id].lot_name, self.item.description)

    def test_draft_purchase_rejected(self):
        engine.unlock_purchase(self.p)
        with self.assertRaises(ValidationError):
            engine.create_receipt_from_purchase(self.p, self.user)

    def test_closed_purchase_rejected(self):
        self.receipt_lot(self.item, self.prj, 40, purchase=self.p)
        self.receipt_lot(self.other, self.prj, 10, purchase=self.p)
        with self.assertRaises(ValidationError):
            engine.create_receipt_from_purchase(self.p, self.user)

    def test_second_call_covers_remainder(self):
        """Поставка частями: зафиксировали первую накладную → вторая идёт на остаток."""
        # номер обязателен к ФИКСАЦИИ, а не к рождению (Ф12e) — здесь задаём сразу
        r1 = engine.create_receipt_from_purchase(self.p, self.user, number='УПД-1')
        # приехало меньше заказанного — правим по бумажной накладной и фиксируем
        lot = r1.lots.get(item=self.item)
        engine.update_receipt_lot(lot, qty=D(15))
        engine.remove_receipt_lot(r1.lots.get(item=self.other))
        engine.lock_receipt(r1)

        r2 = engine.create_receipt_from_purchase(self.p, self.user)
        lots = {lot.item_id: lot for lot in r2.lots.all()}
        self.assertEqual(lots[self.item.id].qty, D(25))       # 40 − 15
        self.assertEqual(lots[self.other.id].qty, D(10))      # не приезжало вовсе

    def test_open_draft_blocks_second_call(self):
        """Черновик заказ не гасит — значит повторный клик плодил бы близнеца."""
        engine.create_receipt_from_purchase(self.p, self.user)
        with self.assertRaises(ValidationError):
            engine.create_receipt_from_purchase(self.p, self.user)

    def test_draft_receipt_does_not_close_line(self):
        """Ф6: закрытость заказа гейтит тот же замок, что склад и деньги (Ф15).

        До правки черновая накладная гасила строку — заказ показывал ✓ до приёмки,
        а позиция исчезала и из «заказано», и со склада разом.
        """
        engine.create_receipt_from_purchase(self.p, self.user)
        row = next(r for r in engine.purchase_form(self.p)['rows']
                   if r['item_id'] == self.item.id)
        self.assertEqual(row['received'], D(0))
        self.assertEqual(row['remaining'], D(40))
        self.assertEqual(row['status'], 'to_order')
        self.assertEqual(row['receipts'], [])
        # и в дефиците позиция всё ещё «заказана» (оранжевый член цел)
        self.assertEqual(engine.item_on_order(self.item, self.prj), D(40))

    def test_line_carries_closing_receipts(self):
        """Обратная связь: строка знает, какими накладными закрыта."""
        engine.create_receipt_from_purchase(self.p, self.user, number='УПД-7')
        r = models.Receipt.objects.get(purchase=self.p)
        engine.update_receipt_lot(r.lots.get(item=self.item), qty=D(15))
        engine.lock_receipt(r)
        row = next(x for x in engine.purchase_form(self.p)['rows']
                   if x['item_id'] == self.item.id)
        self.assertEqual([c['receipt_id'] for c in row['receipts']], [r.id])
        self.assertEqual(row['receipts'][0]['qty'], D(15))
        self.assertEqual(row['received'], D(15))

    def test_http_creates_receipt_and_returns_its_form(self):
        c = Client()
        c.force_login(self.user)
        resp = c.post(f'/api/purchases/{self.p.id}/receipt/')
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['purchase_id'], self.p.id)
        self.assertEqual(len(body['lots']), 2)


class PurchaseContractorTests(EngineTestBase):
    """Волна 19, Ф17: контрагент у всех трёх уровней контура.

    Закупка = ЧТО купить · Заказ = У КОГО купить · Поставка = КТО привёз. Каждый уровень
    знает своего контрагента и не зависит от того, есть ли над ним родитель.
    """

    def setUp(self):
        super().setUp()
        self.item = self.make_item('SCR', kind='material')
        self.other_cp = models.Counterparty.objects.create(description='Другой поставщик')

    # ── обязательность на фиксации, а не при рождении ──────────────────────
    def test_lock_without_contractor_refuses_friendly(self):
        """Внятный отказ движка, а не `IntegrityError 3819` от CHECK (урок Ф12e)."""
        p = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(p, self.item, D(5))
        with self.assertRaises(ValidationError) as cm:
            engine.lock_purchase(p)
        self.assertIn('контрагента', cm.exception.messages[0])
        p.refresh_from_db()
        self.assertFalse(p.locked)

    def test_lock_passes_once_contractor_chosen(self):
        p = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(p, self.item, D(5))
        engine.update_purchase(p, contractor=self.supplier)
        engine.lock_purchase(p)
        self.assertTrue(p.locked)

    # ── самостоятельность уровней ─────────────────────────────────────────
    def test_purchase_without_plan_goes_the_whole_way_to_receipt(self):
        """Заказ без закупки проходит путь целиком — до Ф17 он не знал поставщика."""
        p = self.make_purchase()
        self.assertIsNone(p.procurement_id)
        engine.add_purchase_line(p, self.item, D(7))
        engine.lock_purchase(p)
        r = engine.create_receipt_from_purchase(p, self.user)
        self.assertEqual(r.contractor_id, self.supplier.id)   # из ЗАКАЗА, не сквозь план
        self.assertEqual(r.lots.get(item=self.item).qty, D(7))

    def test_peg_copies_plan_contractor_then_fields_live_apart(self):
        """Наследование — копией при рождении: дальше поля независимы."""
        plan = engine.create_procurement(self.user)
        engine.set_procurement_scope(plan, [self.prj])
        engine.add_procurement_line(plan, self.item, D(10))
        engine.update_procurement(plan, contractor=self.supplier)
        engine.peg_procurement_line(plan, self.item, self.prj, D(10), self.user)
        pu = plan.purchases.get()
        self.assertEqual(pu.contractor_id, self.supplier.id)
        # правка заказа план не трогает…
        engine.update_purchase(pu, contractor=self.other_cp)
        plan.refresh_from_db()
        self.assertEqual(plan.contractor_id, self.supplier.id)
        # …и наоборот
        engine.update_procurement(plan, contractor=None)
        pu.refresh_from_db()
        self.assertEqual(pu.contractor_id, self.other_cp.id)

    # ── расхождение: флаг, а не гейт ──────────────────────────────────────
    def test_mismatch_flag_is_advisory_and_does_not_block_lock(self):
        plan = engine.create_procurement(self.user)
        engine.update_procurement(plan, contractor=self.supplier)
        p = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(p, self.item, D(3))
        engine.update_purchase(p, procurement=plan, contractor=self.other_cp)
        self.assertTrue(engine.purchase_form(p)['contractor_mismatch'])
        engine.lock_purchase(p)                    # предупреждение не останавливает
        self.assertTrue(p.locked)

    def test_no_mismatch_when_either_side_empty_or_equal(self):
        """Пустой сверху/снизу — это «не выбран», а не расхождение."""
        plan = engine.create_procurement(self.user)          # у плана контрагента нет
        p = engine.create_purchase(self.prj, self.user)
        engine.update_purchase(p, procurement=plan, contractor=self.supplier)
        self.assertFalse(engine.purchase_form(p)['contractor_mismatch'])
        engine.update_purchase(p, contractor=None)           # нет и у заказа
        self.assertFalse(engine.purchase_form(p)['contractor_mismatch'])
        engine.update_procurement(plan, contractor=self.supplier)
        engine.update_purchase(p, contractor=self.supplier)  # совпали
        self.assertFalse(engine.purchase_form(p)['contractor_mismatch'])

    def test_receipt_mismatch_compares_with_its_purchase(self):
        """У поставки тот же флаг — «кто привёз» против «у кого купили»."""
        p = self.make_purchase()
        engine.add_purchase_line(p, self.item, D(4))
        engine.lock_purchase(p)
        r = engine.create_receipt_from_purchase(p, self.user)
        self.assertFalse(engine.receipt_form(r)['contractor_mismatch'])
        engine.update_receipt(r, contractor=self.other_cp)
        self.assertTrue(engine.receipt_form(r)['contractor_mismatch'])

    # ── HTTP-срез ─────────────────────────────────────────────────────────
    def test_patch_contractor_and_null_plan_http(self):
        p = engine.create_purchase(self.prj, self.user)
        c = Client()
        c.force_login(self.user)
        resp = c.patch(f'/api/purchases/{p.id}/',
                       {'contractor_id': self.supplier.id},
                       content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['contractor_id'], self.supplier.id)
        # `procurement_id: null` — законное «закупка не выбрана», а не 400
        resp = c.patch(f'/api/purchases/{p.id}/', {'procurement_id': None},
                       content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['procurement_id'])
        # несуществующий контрагент → дружелюбный 400 (не 500)
        bad = c.patch(f'/api/purchases/{p.id}/', {'contractor_id': 99999},
                      content_type='application/json')
        self.assertEqual(bad.status_code, 400)


class TransferFormTests(EngineTestBase):
    """Волна 5: форма передачи — отгрузка партии заказчику (`−ISSUE`), пикер
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
        # Ф15: черновая накладная ничего не отгружает — партия ещё вся на складе
        self.assertEqual(engine.lot_live_qty(self.lot), D(5))
        self.assertFalse(self.lot.movements.filter(type='ISSUE').exists())
        engine.lock_transfer(t)                                 # «отгружено»
        self.assertEqual(engine.lot_live_qty(self.lot), D(3))   # 5 − 2
        self.assertTrue(self.lot.movements.filter(type='ISSUE', qty=D(-2)).exists())

    def test_form_totals_and_live(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.add_transfer_line(t, self.lot, D(2), display_name='Прибор зав.№7')
        engine.lock_transfer(t)
        c = engine.transfer_form(t)
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

    def test_number_required_at_lock_not_at_birth(self):
        """Ф12e: накладная рождается без номера, но не фиксируется без него."""
        t = engine.create_transfer(self.prj, self.user)
        engine.add_transfer_line(t, self.lot, D(1))
        with self.assertRaises(ValidationError):
            engine.lock_transfer(t)
        engine.update_transfer(t, number='Н-7')
        engine.lock_transfer(t)
        self.assertTrue(models.Transfer.objects.get(pk=t.pk).locked)

    def test_add_line_rejects_foreign_project_lot(self):
        other = models.Project.objects.create(
            code='P2', description='Проект 2', kind=models.Project.Kind.EXTERNAL)
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
        engine.lock_transfer(t)
        self.assertEqual(engine.lot_live_qty(self.lot), D(-3))  # недостача информативна

    def test_update_qty_rebuilds_and_remove_restores(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        line = engine.add_transfer_line(t, self.lot, D(2))
        engine.update_transfer_line(line, qty=D(4))
        engine.lock_transfer(t)
        self.assertEqual(engine.lot_live_qty(self.lot), D(1))   # 5 − 4
        engine.unlock_transfer(t)                               # Ф15: правка — под замком снятым
        engine.update_transfer_line(line, display_name='новое имя')
        line.refresh_from_db()
        self.assertEqual(line.display_name, 'новое имя')
        engine.remove_transfer_line(line)
        self.assertEqual(engine.lot_live_qty(self.lot), D(5))   # источник восстановлен

    def test_available_lots_picker(self):
        # ещё один лот проекта + чужой проект + нулевой остаток → в пикере только живой свой
        other = models.Project.objects.create(
            code='P2', description='Проект 2', kind=models.Project.Kind.EXTERNAL)
        self.receipt_lot(self.device, other, 3)                 # чужой проект
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.add_transfer_line(t, self.lot, D(5))             # свой лот в ноль
        engine.lock_transfer(t)                                 # Ф15: отгружено фиксацией
        picker = engine.project_available_lots(self.prj)
        self.assertEqual(picker, [])                            # живых своих лотов нет
        self.assertEqual(len(engine.project_available_lots(other)), 1)

    def test_post_locks_edits(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        line = engine.add_transfer_line(t, self.lot, D(2))
        engine.lock_transfer(t)
        self.assertTrue(engine.transfer_form(t)['locked'])
        with self.assertRaises(ValidationError):
            engine.update_transfer_line(line, qty=D(1))
        with self.assertRaises(ValidationError):
            engine.add_transfer_line(t, self.lot, D(1))
        with self.assertRaises(ValidationError):
            engine.remove_transfer_line(line)

    def test_post_rejects_empty(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        with self.assertRaises(ValidationError):
            engine.lock_transfer(t)

    def test_unpost_reenables_edits(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        line = engine.add_transfer_line(t, self.lot, D(2))
        engine.lock_transfer(t)
        engine.unlock_transfer(t)
        self.assertFalse(engine.transfer_form(t)['locked'])
        self.assertEqual(engine.lot_live_qty(self.lot), D(5))  # Ф15: отгрузка отпущена
        engine.update_transfer_line(line, qty=D(3))            # снова можно править
        engine.lock_transfer(t)
        self.assertEqual(engine.lot_live_qty(self.lot), D(2))

    def test_item_movements_projection(self):
        """Лента движений изделия (волна 19, Ф12a): рождение партии + все ордера,
        которые её двигали. Знак сохраняем — расход виден расходом."""
        t = engine.create_transfer(self.prj, self.user, 'Н-7')
        engine.add_transfer_line(t, self.lot, D(2), display_name='Прибор №7')
        rows = engine.item_movements(self.device)
        self.assertEqual(len(rows), 2)                  # рождение + передача
        born = next(r for r in rows if r['event'] == 'born')
        move = next(r for r in rows if r['event'] == 'move')
        self.assertEqual(born['lot_id'], self.lot.id)
        self.assertEqual(born['qty'], self.lot.qty)
        self.assertEqual(move['kind'], models.StockDocument.Kind.TRANSFER)
        self.assertEqual(move['number'], 'Н-7')
        self.assertEqual(move['qty'], D(-2))            # знаковое: отгрузка = расход
        self.assertFalse(move['locked'])


class WriteoffFormTests(EngineTestBase):
    """Волна 6: списание — чистый `−ISSUE` из проекта (серый путь), guard чужого
    проекта, коррекция строк, пересписание в минус (не клампим)."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')
        self.lot = self.receipt_lot(self.item, self.prj, 10)

    def test_add_line_issues_from_lot(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1', reason='брак')
        engine.add_writeoff_line(w, self.lot, D(4))
        # Ф15: черновой акт ничего не списывает — партия целиком на месте
        self.assertEqual(engine.lot_live_qty(self.lot), D(10))
        engine.lock_writeoff(w)                                  # проведён
        self.assertEqual(engine.lot_live_qty(self.lot), D(6))
        self.assertTrue(self.lot.movements.filter(type='ISSUE', qty=D(-4)).exists())

    def test_form_totals(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1', reason='брак')
        engine.add_writeoff_line(w, self.lot, D(4))
        engine.lock_writeoff(w)
        c = engine.writeoff_form(w)
        self.assertEqual(c['number'], 'СП-1')
        self.assertEqual(c['reason'], 'брак')
        self.assertEqual(c['total_qty'], D(4))
        self.assertEqual(c['lines'][0]['lot_live_qty'], D(6))

    def test_number_required_at_lock_not_at_birth(self):
        """Ф12e: акт рождается без номера, но не фиксируется без него."""
        w = engine.create_writeoff(self.prj, self.user)
        engine.add_writeoff_line(w, self.lot, D(1))
        with self.assertRaises(ValidationError):
            engine.lock_writeoff(w)
        engine.update_writeoff(w, number='СП-7')
        engine.lock_writeoff(w)
        self.assertTrue(models.Writeoff.objects.get(pk=w.pk).locked)

    def test_add_line_rejects_foreign_project(self):
        other = models.Project.objects.create(
            code='P2', description='Проект 2', kind=models.Project.Kind.EXTERNAL)
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
        engine.lock_writeoff(w)
        self.assertEqual(engine.lot_live_qty(self.lot), D(-4))

    def test_update_and_remove_restores(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1')
        line = engine.add_writeoff_line(w, self.lot, D(4))
        engine.update_writeoff_line(line, D(7))
        engine.lock_writeoff(w)
        self.assertEqual(engine.lot_live_qty(self.lot), D(3))
        engine.unlock_writeoff(w)                      # Ф15: списание отпущено
        engine.remove_writeoff_line(line)
        self.assertEqual(engine.lot_live_qty(self.lot), D(10))


class RequisitionFormTests(EngineTestBase):
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
            code='WHITE', description='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)

    def test_add_line_issues_source_and_births_child(self):
        req = engine.create_requisition(self.white, self.user, 'ТР-1')
        engine.add_requisition_line(req, self.src, D(4))
        # Ф15: черновое требование не двигает ни источник, ни потомка
        self.assertEqual(engine.lot_live_qty(self.src), D(10))
        engine.lock_requisition(req)
        self.assertEqual(engine.lot_live_qty(self.src), D(6))    # источник просел
        born = engine._requisition_born_lot(req, self.src)
        self.assertIsNotNone(born)
        self.assertEqual(born.project_id, self.white.id)
        self.assertEqual(born.qty, D(4))
        self.assertEqual(born.unit_cost, D('2.50'))              # цена унаследована
        self.assertEqual(born.predecessor_id, self.src.id)      # генеалогия
        self.assertEqual(engine.lot_live_qty(born), D(4))       # +RECEIPT у потомка

    def test_form_shows_source_and_born(self):
        req = engine.create_requisition(self.white, self.user, 'ТР-1')
        engine.add_requisition_line(req, self.src, D(4))
        engine.lock_requisition(req)
        c = engine.requisition_form(req)
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
        engine.lock_requisition(req)
        born = engine._requisition_born_lot(req, self.src)
        self.assertEqual(engine.lot_live_qty(self.src), D(3))
        self.assertEqual(engine.lot_live_qty(born), D(7))

    def test_remove_restores_source_and_deletes_child(self):
        req = engine.create_requisition(self.white, self.user, 'ТР-1')
        line = engine.add_requisition_line(req, self.src, D(4))
        engine.lock_requisition(req)
        self.assertEqual(engine.lot_live_qty(self.src), D(6))
        engine.unlock_requisition(req)                  # Ф15: отпочкование отпущено
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
            engine.lock_project(self.prj)

    def test_writeoff_bridge_then_close(self):
        # Ф15: мост кладёт остаток в черновой акт, в 0 он уходит на фиксации акта
        w = engine.writeoff_lot(self.prj, self.lot, D(10), self.user)
        self.assertEqual(engine.project_closure(self.prj)['residual_positive'], D(10))
        engine.lock_writeoff(w)
        c = engine.project_closure(self.prj)
        self.assertEqual(c['residuals'], [])
        self.assertTrue(c['can_close'])
        engine.lock_project(self.prj)
        self.prj.refresh_from_db()
        self.assertTrue(self.prj.locked)
        # Ф1c: дата `closed` информационная — фиксация её НЕ штампует.
        self.assertIsNone(self.prj.closed)

    def test_requisition_bridge_moves_to_white(self):
        req = engine.requisition_lot(self.prj, self.lot, D(10), self.user)
        engine.lock_requisition(req)                            # Ф15: перекладка = фиксация
        self.assertEqual(engine.lot_live_qty(self.lot), D(0))
        white = engine._internal_project(models.Project.Kind.INTERNAL_STOCK)
        moved = engine.item_available(self.item, white)
        self.assertEqual(moved, D(10))                          # оказалось на балансе
        self.assertTrue(engine.project_closure(self.prj)['can_close'])

    def test_negative_residual_is_anomaly_and_blocks(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1')
        engine.add_writeoff_line(w, self.lot, D(14))            # пересписали → −4
        engine.lock_writeoff(w)
        c = engine.project_closure(self.prj)
        self.assertEqual(c['anomaly_count'], 1)
        self.assertTrue(c['residuals'][0]['anomaly'])
        self.assertFalse(c['can_close'])

    def test_internal_project_not_closable(self):
        white = models.Project.objects.create(
            code='WHITE', description='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        c = engine.project_closure(white)
        self.assertFalse(c['is_external'])
        self.assertFalse(c['can_close'])
        with self.assertRaises(ValidationError):
            engine.lock_project(white)

    def test_unlock_restores_editable(self):
        engine.lock_writeoff(engine.writeoff_lot(self.prj, self.lot, D(10), self.user))
        engine.lock_project(self.prj)
        engine.unlock_project(self.prj)
        self.prj.refresh_from_db()
        self.assertFalse(self.prj.locked)


class HeaderEditTests(EngineTestBase):
    """Волна 6 (докрутка): правка шапки форм — номер/дата/мягкие поля,
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
        engine.lock_transfer(t)
        with self.assertRaises(ValidationError):
            engine.update_transfer(t, number='Н-100')        # под замком нельзя

    def test_receipt_header_locked(self):
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01',
            contractor=self.supplier, project=self.prj, user=self.user)
        engine.add_receipt_lot(r, self.make_item('A'), D(2))
        engine.update_receipt(r, number='U-2')
        r.refresh_from_db()
        self.assertEqual(r.number, 'U-2')
        engine.lock_receipt(r)
        with self.assertRaises(ValidationError):
            engine.update_receipt(r, number='U-3')

    def test_purchase_code_description_and_clear_date(self):
        p = engine.create_purchase(self.prj, self.user, date='2026-05-01', description='x')
        engine.update_purchase(p, code='Нева-1', description='новое', date='')  # '' → NULL (nullable)
        p.refresh_from_db()
        self.assertEqual(p.code, 'Нева-1')
        self.assertEqual(p.description, 'новое')
        self.assertIsNone(p.date)

    def test_kitting_qty_rescales_needs(self):
        comp = self.make_item('R')
        self.receipt_lot(comp, self.prj, 100)
        dev = self.make_item('DEV', manufactured=True)
        models.BomLine.objects.create(parent=dev, component=comp, qty=D(2))
        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
            user=self.user, qty=D(1), locked=False)
        self.assertEqual(engine.kitting_form(k)['rows'][0]['need'], D(2))
        engine.update_kitting(k, qty=D(3))
        self.assertEqual(engine.kitting_form(k)['rows'][0]['need'], D(6))
        engine.lock_kitting(k)
        with self.assertRaises(ValidationError):
            engine.update_kitting(k, qty=D(4))               # не wip — нельзя

    def test_writeoff_and_requisition_header(self):
        w = engine.create_writeoff(self.prj, self.user, 'СП-1')
        engine.update_writeoff(w, number='СП-2', reason='брак')
        w.refresh_from_db()
        self.assertEqual((w.number, w.reason), ('СП-2', 'брак'))
        white = models.Project.objects.create(code='WHITE', description='Склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        req = engine.create_requisition(white, self.user, 'ТР-1')
        engine.update_requisition(req, number='ТР-2', date='2026-06-01')
        req.refresh_from_db()
        self.assertEqual(req.number, 'ТР-2')


class ScopeDeficitTests(EngineTestBase):
    """Свод по охвату — Σ проектных дефицитов по Item, без перенеттинга (В7; охват В19)."""

    def _device_with_screw(self, screw, qty_per, suffix=''):
        dev = self.make_item(f'DEV{screw.code}{suffix}', manufactured=True,
                             kind='device')
        models.BomLine.objects.create(parent=dev, component=screw, qty=D(qty_per))
        return dev

    def test_rolls_up_by_item_across_projects(self):
        scr = self.make_item('SCR', kind='material')
        dev = self._device_with_screw(scr, 4)
        prj2 = models.Project.objects.create(code='P2', description='Проект 2',
                                             kind=models.Project.Kind.EXTERNAL)
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=prj2, target_item=dev, qty=D(5))

        rows = {r['item_code']: r
                for r in engine.scope_deficit([self.prj, prj2])['rows']}
        row = rows['SCR']
        self.assertEqual(row['need'], D(60))         # 40 + 20
        self.assertEqual(row['to_order'], D(60))     # склада/заказов нет
        self.assertEqual(row['status'], 'to_order')
        self.assertEqual(len(row['by_project']), 2)

    def test_stock_and_order_no_cross_project_netting(self):
        scr = self.make_item('SCR', kind='material')
        dev = self._device_with_screw(scr, 4)
        prj2 = models.Project.objects.create(code='P2', description='Проект 2',
                                             kind=models.Project.Kind.EXTERNAL)
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=prj2, target_item=dev, qty=D(5))
        # склад лежит только в P1 (10 шт) — НЕ должен гасить нужду P2
        self.receipt_lot(scr, self.prj, 10)

        row = {r['item_code']: r
               for r in engine.scope_deficit([self.prj, prj2])['rows']}['SCR']
        self.assertEqual(row['have'], D(10))          # только P1 покрыт
        self.assertEqual(row['to_order'], D(50))      # 30 (P1) + 20 (P2), не 40
        self.assertEqual(row['need'], D(60))

    def test_closed_and_internal_projects_excluded(self):
        scr = self.make_item('SCR', kind='material')
        dev = self._device_with_screw(scr, 2)
        closed = models.Project.objects.create(code='PC', description='Закрытый',
            kind=models.Project.Kind.EXTERNAL, locked=True)
        white = models.Project.objects.create(code='WHITE', description='Склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        models.ProjectDemand.objects.create(project=closed, target_item=dev, qty=D(3))
        models.ProjectDemand.objects.create(project=white, target_item=dev, qty=D(3))
        # оба в охвате явно — и всё равно не считаются: закрытый проект не закупают,
        # а внутренний склад не потребитель (инвариант арифметики, не фильтр вызова)
        self.assertEqual(engine.scope_deficit([closed, white])['rows'], [])

    def test_intra_project_need_aggregated_across_demands(self):
        # два прибора в одном проекте делят компонент → потребность суммируется,
        # покрытие считается один раз (одна by_project-строка на проект)
        scr = self.make_item('SCR', kind='material')
        dev_a = self._device_with_screw(scr, 4, suffix='A')
        dev_b = self._device_with_screw(scr, 3, suffix='B')
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev_a, qty=D(2))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev_b, qty=D(2))

        row = {r['item_code']: r
               for r in engine.scope_deficit([self.prj])['rows']}['SCR']
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

        codes = [r['item_code'] for r in engine.scope_deficit([self.prj])['rows']]
        self.assertEqual(codes, ['RED', 'GRN'])       # красное наверх


class ProcurementFormTests(EngineTestBase):
    """Волна 7: записываемый план закупки — строки, замок отправки, мост, xlsx."""

    def test_create_and_form_totals(self):
        p = engine.create_procurement(self.user, description='весна')
        engine.add_procurement_line(p, self.make_item('A'), D(10))
        engine.add_procurement_line(p, self.make_item('B'), D(5))
        c = engine.procurement_form(p)
        self.assertEqual(len(c['lines']), 2)
        self.assertEqual(c['total_qty'], D(15))
        self.assertTrue(c['editable'])
        self.assertFalse(c['locked'])
        self.assertEqual(c['description'], 'весна')

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

    def test_post_locks_and_rejects_empty(self):
        p = engine.create_procurement(self.user)
        with self.assertRaises(ValidationError):
            engine.lock_procurement(p)                 # пустую нельзя
        line = engine.add_procurement_line(p, self.make_item('A'), D(10))
        engine.lock_procurement(p)
        self.assertTrue(p.locked)
        with self.assertRaises(ValidationError):
            engine.update_procurement_line(line, D(5))  # строки под замком
        with self.assertRaises(ValidationError):
            engine.add_procurement_line(p, self.make_item('B'), D(1))

    def test_unpost_reopens_and_delete_replaces_cancel(self):
        """Замок снимается и возвращается; отмены нет — только удаление (Р1)."""
        p = engine.create_procurement(self.user)
        line = engine.add_procurement_line(p, self.make_item('A'), D(10))
        engine.lock_procurement(p)
        engine.unlock_procurement(p)
        engine.update_procurement_line(line, D(30))    # снова можно
        self.assertEqual(line.qty, D(30))
        engine.lock_procurement(p)
        with self.assertRaises(ValidationError):        # утверждённую не удалить
            engine.delete_procurement(p)
        engine.unlock_procurement(p)
        self.assertFalse(p.locked)
        engine.delete_procurement(p)
        self.assertFalse(models.Procurement.objects.filter(pk=p.pk).exists())

    def test_bridge_tops_up_line_without_doubling(self):
        # Ф13: мост кладёт в ЭТУ закупку и доводит строку ДО наводки (топ-ап), а не
        # плюсует: повторный клик по той же строке витрины ничего не удваивает.
        item = self.make_item('SCR', kind='material')
        p = engine.create_procurement(self.user)
        engine.add_to_procurement(p, item, D(15))
        self.assertEqual(p.lines.get(item=item).qty, D(15))
        engine.add_to_procurement(p, item, D(15))
        self.assertEqual(p.lines.get(item=item).qty, D(15))
        engine.add_to_procurement(p, item, D(25))        # наводка выросла — догоняем
        self.assertEqual(p.lines.get(item=item).qty, D(25))

    def test_bridge_never_cuts_manual_qty(self):
        # набранное руками сверх наводки топ-ап не срезает (мутабельная ДНК: расхождение
        # информативнее молчаливого выравнивания)
        item = self.make_item('SCR', kind='material')
        p = engine.create_procurement(self.user)
        engine.add_procurement_line(p, item, D(100))
        engine.add_to_procurement(p, item, D(10))
        self.assertEqual(p.lines.get(item=item).qty, D(100))

    def test_bridge_refuses_locked_procurement(self):
        item = self.make_item('SCR', kind='material')
        p = engine.create_procurement(self.user)
        engine.add_procurement_line(p, self.make_item('OTH'), D(1))
        engine.lock_procurement(p)
        with self.assertRaises(ValidationError):
            engine.add_to_procurement(p, item, D(5))

    def test_update_header(self):
        p = engine.create_procurement(self.user)
        engine.update_procurement(p, date='2026-07-10', code='ЗАК-1', description='осень')
        p.refresh_from_db()
        self.assertEqual(str(p.date), '2026-07-10')
        self.assertEqual(p.code, 'ЗАК-1')
        self.assertEqual(p.description, 'осень')
        engine.update_procurement(p, date='')          # пустая строка → NULL
        p.refresh_from_db()
        self.assertIsNone(p.date)

    def test_code_soft_uniqueness(self):
        # Волна 19, Ф10 (правило Ивана): занятый код ловим дружелюбно (ValidationError),
        # не IntegrityError/500. Пустой код у нескольких — легально (NULL).
        engine.update_procurement(engine.create_procurement(self.user), code='ДЗЗ-1')
        with self.assertRaises(ValidationError):
            engine.update_procurement(engine.create_procurement(self.user), code='ДЗЗ-1')
        # два без кода не конфликтуют
        engine.create_procurement(self.user)
        engine.create_procurement(self.user)      # не бросает

    def test_update_contractor(self):
        # Волна 19, Ф4: контрагент-поставщик у закупки-плана. Часовой `_UNSET`:
        # не передан → не трогаем; Counterparty → выставить; None → снять.
        p = engine.create_procurement(self.user)
        self.assertIsNone(p.contractor_id)
        engine.update_procurement(p, contractor=self.supplier)
        p.refresh_from_db()
        self.assertEqual(p.contractor_id, self.supplier.id)
        # проекция формы отдаёт контрагента
        cock = engine.procurement_form(p)
        self.assertEqual(cock['contractor_id'], self.supplier.id)
        self.assertEqual(cock['contractor_name'], self.supplier.description)
        # не передан → не трогаем (правка только даты)
        engine.update_procurement(p, date='2026-07-10')
        p.refresh_from_db()
        self.assertEqual(p.contractor_id, self.supplier.id)
        # None → снять
        engine.update_procurement(p, contractor=None)
        p.refresh_from_db()
        self.assertIsNone(p.contractor_id)
        self.assertEqual(engine.procurement_form(p)['contractor_name'], '')

    def test_contractor_set_null_on_counterparty_delete(self):
        # SET_NULL: удаление контрагента не роняет план-закупку — поле опустевает.
        p = engine.create_procurement(self.user)
        engine.update_procurement(p, contractor=self.supplier)
        self.supplier.delete()
        p.refresh_from_db()
        self.assertIsNone(p.contractor_id)

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
            code='P2', description='Проект 2', kind=models.Project.Kind.EXTERNAL)
        self.scr = self.make_item('SCR', kind='material')
        dev = self.make_item('DEV', manufactured=True, kind='device')
        models.BomLine.objects.create(parent=dev, component=self.scr, qty=D(4))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=self.prj2, target_item=dev, qty=D(5))
        self.plan = engine.create_procurement(self.user, description='свод')   # need 40 + 20
        # Ф13: наводка живёт по охвату — без него плану нечего раскладывать
        engine.set_procurement_scope(self.plan, [self.prj, self.prj2])
        # Ф17: намерение плана — «у кого собираемся купить»; рождённые пеггингом заказы
        # наследуют его копией, иначе их нечем зафиксировать.
        engine.update_procurement(self.plan, contractor=self.supplier)
        engine.add_procurement_line(self.plan, self.scr, D(60))

    def test_peg_creates_project_purchase_under_plan(self):
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(40), self.user)
        pu = self.plan.purchases.get(project=self.prj)
        self.assertEqual(pu.procurement_id, self.plan.id)   # заказ висит на плане
        self.assertEqual(pu.contractor_id, self.supplier.id)   # Ф17: контрагент копией
        self.assertFalse(pu.locked)
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
        white = models.Project.objects.create(code='WHITE', description='Свой склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        with self.assertRaises(ValidationError):            # не внешний проект
            engine.peg_procurement_line(self.plan, self.scr, white, D(1), self.user)
        closed = models.Project.objects.create(code='CL', description='Закрыт',
            kind=models.Project.Kind.EXTERNAL, locked=True)
        with self.assertRaises(ValidationError):            # не активный проект
            engine.peg_procurement_line(self.plan, self.scr, closed, D(1), self.user)

    def test_unpeg_removes_and_blocks_sent(self):
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(40), self.user)
        engine.unpeg_procurement_line(self.plan, self.scr, self.prj)
        pu = self.plan.purchases.get(project=self.prj)
        self.assertFalse(pu.lines.exists())                 # пег снят
        # пег в отправленном заказе — снять нельзя, пока не снят send
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(40), self.user)
        engine.lock_purchase(pu)
        with self.assertRaises(ValidationError):
            engine.unpeg_procurement_line(self.plan, self.scr, self.prj)

    def test_plan_list_shows_every_procurement(self):
        """Ф17: список закупок = ВСЕ закупки — прятать больше нечего.

        Раньше одиночный заказ рождал закупку-пустышку, и список отсекал её эвристикой
        «есть заказы, но нет строк». `procurement` стал nullable — пустышки не рождаются,
        эвристика умерла вместе с ними.
        """
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(10), self.user)
        engine.create_purchase(self.prj, self.user)         # заказ без плана
        c = Client()
        c.force_login(self.user)
        ids = {row['id'] for row in c.get('/api/procurements/').json()}
        self.assertEqual(ids, {self.plan.id})               # заказ пустышки не создал

    # --- Ф13: охват задаёт область расчёта --------------------------------- #

    def test_scope_narrows_suggestion_to_its_projects(self):
        # до Ф13 в аккордеон ЛЮБОГО плана лезли проекты всей организации
        engine.set_procurement_scope(self.plan, [self.prj])
        row = engine.procurement_pegging(self.plan)['rows'][0]
        self.assertEqual([bp['project_code'] for bp in row['by_project']], ['P1'])

    def test_empty_scope_gives_no_suggestion_and_autopeg_does_nothing(self):
        engine.set_procurement_scope(self.plan, [])
        row = engine.procurement_pegging(self.plan)['rows'][0]
        self.assertEqual(row['by_project'], [])             # пусто = пусто
        engine.autopeg_procurement(self.plan, self.user)
        self.assertEqual(self.plan.purchases.count(), 0)    # раскладывать нечего

    def test_project_outside_scope_still_shows_what_is_pegged(self):
        # охват правит НАВОДКУ, а не факт: разложенное вручную видно всегда, иначе
        # сужение охвата прятало бы существующие обязательства
        engine.peg_procurement_line(self.plan, self.scr, self.prj2, D(7), self.user)
        engine.set_procurement_scope(self.plan, [self.prj])
        by = {bp['project_code']: bp for bp in
              engine.procurement_pegging(self.plan)['rows'][0]['by_project']}
        self.assertEqual(by['P2']['pegged'], D(7))
        self.assertEqual(by['P2']['suggest'], D(0))         # но наводки по нему нет

    def test_scope_refuses_internal_and_locked_plan(self):
        white = models.Project.objects.create(code='WHITE', description='Свой склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        with self.assertRaises(ValidationError):
            engine.set_procurement_scope(self.plan, [white])
        engine.lock_procurement(self.plan)
        with self.assertRaises(ValidationError):            # область расчёта под замком
            engine.set_procurement_scope(self.plan, [self.prj])

    # --- Ф5: пеггинг в явный заказ (Р2) ------------------------------------ #

    def test_peg_into_explicit_purchase(self):
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(10), self.user)
        first = self.plan.purchases.get(project=self.prj)
        # «＋ новый заказ»: второе обязательство под тем же проектом
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(5), self.user,
                                    new_purchase=True)
        self.assertEqual(self.plan.purchases.filter(project=self.prj).count(), 2)
        second = self.plan.purchases.filter(project=self.prj).exclude(pk=first.pk).get()
        self.assertEqual(second.lines.get(item=self.scr).qty, D(5))
        # явный выбор кладёт именно туда, куда указано (фолбэк взял бы последний черновик)
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(3), self.user,
                                    purchase=first)
        self.assertEqual(first.lines.get(item=self.scr).qty, D(13))
        self.assertEqual(second.lines.get(item=self.scr).qty, D(5))

    def test_peg_into_wrong_or_locked_purchase_refused(self):
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(10), self.user)
        mine = self.plan.purchases.get(project=self.prj)
        engine.peg_procurement_line(self.plan, self.scr, self.prj2, D(10), self.user)
        other_project = self.plan.purchases.get(project=self.prj2)
        with self.assertRaises(ValidationError):            # заказ другого проекта
            engine.peg_procurement_line(self.plan, self.scr, self.prj, D(1), self.user,
                                        purchase=other_project)
        alien = engine.create_procurement(self.user)
        engine.add_procurement_line(alien, self.scr, D(5))
        engine.peg_procurement_line(alien, self.scr, self.prj, D(5), self.user)
        with self.assertRaises(ValidationError):            # заказ под другим планом
            engine.peg_procurement_line(self.plan, self.scr, self.prj, D(1), self.user,
                                        purchase=alien.purchases.get())
        engine.lock_purchase(mine)
        with self.assertRaises(ValidationError):            # зафиксированный заказ
            engine.peg_procurement_line(self.plan, self.scr, self.prj, D(1), self.user,
                                        purchase=mine)

    def test_purchase_fan_per_project_in_projection(self):
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(10), self.user)
        engine.peg_procurement_line(self.plan, self.scr, self.prj, D(5), self.user,
                                    new_purchase=True)
        by = {bp['project_code']: bp for bp in
              engine.procurement_pegging(self.plan)['rows'][0]['by_project']}
        self.assertEqual(len(by['P1']['purchases']), 2)     # есть из чего выбрать
        self.assertEqual(by['P2']['purchases'], [])         # под P2 заказов ещё нет


class ItemUsageTests(EngineTestBase):
    """Ф5: обратное разузлование — «зачем этот Item проекту» (третий уровень аккордеона)."""

    def _tree(self):
        # DEV ×1 → SUB ×2 → SCR ×3  (плюс SCR ×1 напрямую в DEV)
        scr = self.make_item('SCR', kind='material')
        sub = self.make_item('SUB', manufactured=True)
        dev = self.make_item('DEV', manufactured=True, kind='device')
        models.BomLine.objects.create(parent=sub, component=scr, qty=D(3))
        models.BomLine.objects.create(parent=dev, component=sub, qty=D(2))
        models.BomLine.objects.create(parent=dev, component=scr, qty=D(1))
        return dev, sub, scr

    def test_usage_counts_through_all_levels(self):
        dev, sub, scr = self._tree()
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        usage = engine.item_usage_in_project(scr, self.prj)
        self.assertEqual(len(usage), 1)                     # одно применение — прибор DEV
        self.assertEqual(usage[0]['target_code'], 'DEV')
        self.assertEqual(usage[0]['per_unit'], D(7))        # 2×3 через SUB + 1 напрямую
        self.assertEqual(usage[0]['demand_qty'], D(10))
        self.assertEqual(usage[0]['total'], D(70))          # совпадает с нуждой проекта

    def test_usage_splits_by_target_device(self):
        dev, sub, scr = self._tree()
        dev2 = self.make_item('DEV2', manufactured=True, kind='device')
        models.BomLine.objects.create(parent=dev2, component=scr, qty=D(5))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(1))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev2, qty=D(2))
        usage = {u['target_code']: u for u in engine.item_usage_in_project(scr, self.prj)}
        self.assertEqual(usage['DEV']['total'], D(7))
        self.assertEqual(usage['DEV2']['total'], D(10))
        # сумма применений = нужда проекта по этому Item (сходимость с прямым сводом)
        need = engine.scope_deficit([self.prj])['rows']
        row = {r['item_code']: r for r in need}['SCR']
        self.assertEqual(sum(u['total'] for u in usage.values()), row['need'])

    def test_usage_empty_for_item_outside_bom(self):
        dev, sub, scr = self._tree()
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(1))
        self.assertEqual(engine.item_usage_in_project(self.make_item('OTH'), self.prj), [])


class ClosureHttpTests(TestCase):
    """Волна 6: HTTP-путь через test Client — провязка urls/views + мапинг ошибок."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.main = models.Location.objects.create(code='MAIN', description='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', description='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.item = models.Item.objects.create(code='R100', description='R100', category=_cat())
        self.sup = models.Counterparty.objects.create(description='П')
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01',
            contractor=self.sup, project=self.prj, locked=True,   # Ф15: партия на складе
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
        other = models.Project.objects.create(code='P2', description='П2',
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
        # мост «на баланс» → черновое требование; Ф15: остаток уйдёт на его фиксации
        r = self.c.post(f'/api/projects/{self.prj.id}/stock-lot/',
            {'lot_id': self.lot.id, 'qty': 10}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['can_close'])
        drafts = r.json()['closing_drafts']
        self.assertEqual(len(drafts), 1)                    # панель показывает черновик
        self.assertEqual(drafts[0]['kind'], 'requisition')
        lock = self.c.post(f'/api/requisitions/{drafts[0]["document_id"]}/lock/')
        self.assertEqual(lock.status_code, 200)
        panel = self.c.get(f'/api/projects/{self.prj.id}/closure/').json()
        self.assertTrue(panel['can_close'])
        # закрытие 200 + повторное закрытие → 400
        c1 = self.c.post(f'/api/projects/{self.prj.id}/lock/')
        self.assertEqual(c1.status_code, 200)
        self.assertTrue(c1.json()['locked'])
        c2 = self.c.post(f'/api/projects/{self.prj.id}/lock/')
        self.assertEqual(c2.status_code, 400)
        # переоткрытие
        ro = self.c.post(f'/api/projects/{self.prj.id}/unlock/')
        self.assertFalse(ro.json()['locked'])

    def test_requisition_flow(self):
        white = models.Project.objects.create(code='WHITE', description='Собственный склад',
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
    """Волна 7: HTTP-путь — свод, записываемый Procurement, мост, xlsx-бланк."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.prj = models.Project.objects.create(
            code='P1', description='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.scr = models.Item.objects.create(code='SCR', description='Винт',
            category=_cat())
        self.dev = models.Item.objects.create(code='DEV', description='Прибор',
            category=_cat(), native=True)
        models.BomLine.objects.create(parent=self.dev, component=self.scr, qty=D(4))
        models.ProjectDemand.objects.create(project=self.prj, target_item=self.dev,
            qty=D(10))
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_scope_deficit_and_bridge(self):
        # Ф13: витрина живёт ВНУТРИ закупки и считает по её охвату
        pid = self.c.post('/api/procurements/', {'description': 'весна'},
            content_type='application/json').json()['id']
        blind = self.c.get(f'/api/procurements/{pid}/deficit/')
        self.assertEqual(blind.status_code, 200)
        self.assertEqual(blind.json()['rows'], [])            # пусто = пусто
        scope = self.c.patch(f'/api/procurements/{pid}/',
            {'project_ids': [self.prj.id]}, content_type='application/json')
        self.assertEqual(scope.status_code, 200)
        self.assertEqual([p['code'] for p in scope.json()['projects']], ['P1'])
        svod = self.c.get(f'/api/procurements/{pid}/deficit/')
        rows = {r['item_code']: r for r in svod.json()['rows']}
        self.assertEqual(float(rows['SCR']['to_order']), 40.0)
        self.assertEqual(float(rows['SCR']['planned']), 0.0)   # в плане ещё ничего
        # мост кладёт позицию В ЭТУ закупку
        add = self.c.post(f'/api/procurements/{pid}/take/',
            {'item_id': self.scr.id, 'qty': 40}, content_type='application/json')
        self.assertEqual(add.status_code, 200)
        self.assertEqual(float(add.json()['total_qty']), 40.0)
        again = self.c.get(f'/api/procurements/{pid}/deficit/').json()
        self.assertEqual(float(again['rows'][0]['planned']), 40.0)

    def test_scope_refuses_internal_project(self):
        white = models.Project.objects.create(code='WHITE', description='Свой склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        pid = self.c.post('/api/procurements/', {}, content_type='application/json').json()['id']
        bad = self.c.patch(f'/api/procurements/{pid}/', {'project_ids': [white.id]},
            content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        self.assertIn('не закупаются', bad.json()['detail'])

    def test_procurement_crud_lock_and_xlsx(self):
        r = self.c.post('/api/procurements/', {'description': 'весна'},
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
        # утверждение → строки под замком
        posted = self.c.post(f'/api/procurements/{pid}/lock/')
        self.assertEqual(posted.status_code, 200)
        self.assertTrue(posted.json()['locked'])
        locked = self.c.post(f'/api/procurements/{pid}/lines/',
            {'item_id': self.dev.id, 'qty': 1}, content_type='application/json')
        self.assertEqual(locked.status_code, 400)
        # выгрузка xlsx — бинарное тело, xlsx content-type
        xlsx = self.c.get(f'/api/procurements/{pid}/xlsx/')
        self.assertEqual(xlsx.status_code, 200)
        self.assertIn('spreadsheetml', xlsx['Content-Type'])
        self.assertTrue(xlsx['Content-Disposition'].startswith('attachment'))
        self.assertTrue(xlsx.content[:2] == b'PK')      # zip-сигнатура xlsx

    def test_xlsx_filename_is_procurement_code(self):
        """Имя файла = `code` закупки (2026-07-26), с фолбэком по id у пустого кода.

        Коды человек вводит кириллицей и с пробелами («Нева ДЗЗ 1») — заголовок обязан
        нести RFC 5987 (`filename*=utf-8''…`), иначе имя приедет мусором.
        """
        r = self.c.post('/api/procurements/', {'code': 'Нева ДЗЗ 1'},
            content_type='application/json')
        pid = r.json()['id']
        cd = self.c.get(f'/api/procurements/{pid}/xlsx/')['Content-Disposition']
        self.assertIn("filename*=utf-8''", cd)
        self.assertIn(quote('Нева ДЗЗ 1.xlsx'), cd)
        # Ф12e: рождённая без кода закупка получает фолбэк «Закупка 42» ещё в движке,
        # поэтому имя файла осмысленно уже здесь.
        r2 = self.c.post('/api/procurements/', {'description': 'без кода'},
            content_type='application/json')
        pid2 = r2.json()['id']
        cd2 = self.c.get(f'/api/procurements/{pid2}/xlsx/')['Content-Disposition']
        self.assertIn(quote(f'Закупка {pid2}.xlsx'), cd2)
        # Код можно очистить руками — тогда работает страховочный фолбэк по id.
        engine.update_procurement(models.Procurement.objects.get(pk=pid2), code='')
        cd3 = self.c.get(f'/api/procurements/{pid2}/xlsx/')['Content-Disposition']
        self.assertIn(quote(f'закупка-{pid2}.xlsx'), cd3)
        self.assertNotIn('order', cd3)


class PeggingHttpTests(TestCase):
    """Волна 8: HTTP-путь pegging — проекция, peg/unpeg/autopeg, гварды."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.prj = models.Project.objects.create(code='P1', description='Проект 1',
            kind=models.Project.Kind.EXTERNAL)
        self.prj2 = models.Project.objects.create(code='P2', description='Проект 2',
            kind=models.Project.Kind.EXTERNAL)
        self.scr = models.Item.objects.create(code='SCR', description='Винт',
            category=_cat())
        dev = models.Item.objects.create(code='DEV', description='Прибор',
            category=_cat(), native=True)
        models.BomLine.objects.create(parent=dev, component=self.scr, qty=D(4))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        models.ProjectDemand.objects.create(project=self.prj2, target_item=dev, qty=D(5))
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))
        self.pid = self.c.post('/api/procurements/', {'description': 'свод'},
            content_type='application/json').json()['id']
        self.c.patch(f'/api/procurements/{self.pid}/',
            {'project_ids': [self.prj.id, self.prj2.id]},
            content_type='application/json')
        self.c.post(f'/api/procurements/{self.pid}/lines/',
            {'item_id': self.scr.id, 'qty': 60}, content_type='application/json')

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
        x = models.Item.objects.create(code='X', description='X', category=_cat())
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

    def test_peg_chooses_purchase_explicitly(self):
        # Р2: под проектом заказов может быть несколько — выбор едет в теле запроса
        body = {'item_id': self.scr.id, 'project_id': self.prj.id, 'qty': 10}
        self.c.post(f'/api/procurements/{self.pid}/peg/', body,
                    content_type='application/json')
        fresh = self.c.post(f'/api/procurements/{self.pid}/peg/',
            {**body, 'qty': 5, 'purchase_id': 'new'}, content_type='application/json')
        self.assertEqual(fresh.status_code, 200)
        by = {b['project_code']: b for b in fresh.json()['rows'][0]['by_project']}
        self.assertEqual(len(by['P1']['purchases']), 2)
        target = by['P1']['purchases'][0]['id']
        into = self.c.post(f'/api/procurements/{self.pid}/peg/',
            {**body, 'qty': 1, 'purchase_id': target}, content_type='application/json')
        self.assertEqual(into.status_code, 200)
        self.assertEqual(float(into.json()['rows'][0]['pegged']), 16.0)
        alien = self.c.post(f'/api/procurements/{self.pid}/peg/',
            {**body, 'qty': 1, 'purchase_id': 999999}, content_type='application/json')
        self.assertEqual(alien.status_code, 400)


class ReferenceCreateTests(EngineTestBase):
    """Канон «＋ Новая» (2026-07-03): создание изделий и проектов из справочников."""

    def test_create_item_defaults_and_fields(self):
        cat = _cat('mcu', 'Микроконтроллеры')
        i = engine.create_item('R100', 'Резистор', category_id=cat.id,
                               uom='шт', native=False, estimated_cost=D('1.50'),
                               temperature='-40-125°C')
        self.assertEqual(i.code, 'R100')
        self.assertEqual(i.category_id, cat.id)
        self.assertEqual(i.temperature, '-40-125°C')
        self.assertEqual(i.estimated_cost, D('1.50'))
        # обрезка пробелов; дефолты uom=шт, native=False
        j = engine.create_item(' B1 ', ' Плата ', category_id=cat.id)
        self.assertEqual(j.code, 'B1')
        self.assertEqual(j.uom, 'шт')
        self.assertFalse(j.native)

    def test_create_item_rejects_dup_and_bad_category(self):
        cat = _cat()
        engine.create_item('R100', 'Резистор', category_id=cat.id)
        # Ф3b: дубль кода ловит ОБЩИЙ `require_unique_code` (тот же, что у закупок/
        # заказов/документов с Ф10) — своей реализации у Item больше нет.
        with self.assertRaises(ValidationError) as ctx:
            engine.create_item('R100', 'Дубль', category_id=cat.id)   # дубль ключа
        self.assertIn('уже занят', ctx.exception.messages[0])
        with self.assertRaises(ValidationError):
            engine.create_item('X3', 'Плохая', category_id=999999)    # неизвестная категория

    def test_create_project_is_external_unlocked(self):
        p = engine.create_project('НИР-1', 'Тема', budget=D('100000'))
        self.assertEqual(p.kind, models.Project.Kind.EXTERNAL)
        self.assertFalse(p.locked)
        self.assertEqual(p.budget, D('100000'))

    def test_create_project_rejects_dup(self):
        engine.create_project('НИР-1', 'Тема')
        with self.assertRaises(ValidationError):
            engine.create_project('НИР-1', 'Дубль')    # дубль кода


class ReferenceCreateHttpTests(TestCase):
    """Канон «＋ Новая»: HTTP-путь создания изделия/проекта."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_create_item_http(self):
        cat = _cat()
        r = self.c.post('/api/items/', {'code': 'R100', 'description': 'Резистор',
            'category_id': cat.id, 'native': False},
            content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['code'], 'R100')
        # появляется в списке
        lst = self.c.get('/api/items/').json()
        self.assertTrue(any(i['code'] == 'R100' for i in lst))
        # дубль → 400
        dup = self.c.post('/api/items/', {'code': 'R100', 'description': 'Дубль',
            'category_id': cat.id}, content_type='application/json')
        self.assertEqual(dup.status_code, 400)

    def test_create_project_http(self):
        r = self.c.post('/api/projects/', {'code': 'НИР-1', 'description': 'Тема',
            'budget': '100000'}, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body['kind'], 'external')
        self.assertFalse(body['locked'])


class BornByClickTests(EngineTestBase):
    """Волна 19, Ф12e: «＋ Новый» рождает сущность СРАЗУ, поэтому обязательные поля
    обязаны пережить рождение пустыми.

    Правило не «поля стали необязательными», а «обязательность переехала с рождения
    на ФИКСАЦИЮ» — каждый тест проверяет обе половины: родилось пустым И не
    фиксируется, пока не заполнено. Пустой `code` — исключение: он идентичность,
    его добирает фолбэк «Поставка 12» (решение Ивана 2026-07-28)."""

    def test_item_born_without_code_category_description(self):
        i = engine.create_item()
        self.assertEqual(i.code, f'Изделие {i.id}')
        self.assertEqual(i.description, '')
        self.assertIsNone(i.category_id)

    def test_item_without_category_does_not_lock(self):
        i = engine.create_item()
        with self.assertRaises(ValidationError) as ctx:
            engine.lock_item(i)
        self.assertIn('категорию', ctx.exception.messages[0])
        engine.update_item(i, {'category_id': _cat().id})
        engine.lock_item(i)
        self.assertTrue(models.Item.objects.get(pk=i.pk).locked)

    def test_item_lock_refusal_is_400_not_500(self):
        """Отказ фиксации должен доехать до формы строкой, а не пятисоткой.

        `lock_item` до Ф12e не умел отказывать вовсе, поэтому вьюха его не
        оборачивала — новый гейт вылезал `ValidationError` наружу."""
        i = engine.create_item()
        c = Client()
        c.force_login(self.user)
        r = c.post(f'/api/items/{i.id}/lock/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('категорию', r.json()['detail'])

    def test_project_and_location_born_with_fallback_code(self):
        p = engine.create_project()
        self.assertEqual(p.code, f'Проект {p.id}')
        loc = engine.create_location()
        self.assertEqual(loc.code, f'Место {loc.id}')

    def test_fallback_code_steps_aside_from_taken_one(self):
        """Человек мог руками занять ровно тот код, который сгенерит фолбэк."""
        p = engine.create_project()
        engine.update_project(p, {'code': 'своё имя'})       # освободили фолбэк-код
        engine.create_project(f'Проект {p.id}', 'чужак')     # и заняли его руками
        engine.fallback_code(p, 'Проект')
        self.assertEqual(p.code, f'Проект {p.id}-2')

    def test_orders_born_without_number_and_get_kind_code(self):
        for create, label in (
                (engine.create_receipt, 'Поставка'),
                (engine.create_transfer, 'Передача'),
                (engine.create_writeoff, 'Списание'),
                (engine.create_requisition, 'Требование'),
                (engine.create_inventory, 'Инвентаризация'),
                (engine.create_relocation, 'Перемещение')):
            doc = create(self.prj, self.user)
            self.assertEqual(doc.number, '', label)
            self.assertEqual(doc.code, f'{label} {doc.id}', label)

    def test_order_code_space_is_shared_across_kinds(self):
        """Код ордера уникален на ВСЕ семь видов, а `Receipt.objects` фильтрует по
        `kind` — фолбэк обязан искать по родителю, иначе выдаст занятый код."""
        r = engine.create_receipt(self.prj, self.user)
        engine.update_receipt(r, code='своё имя')            # освободили фолбэк-код
        engine.update_writeoff(engine.create_writeoff(self.prj, self.user),
                               code=f'Поставка {r.id}')      # занял ордер ДРУГОГО вида
        engine.fallback_code(r, 'Поставка')
        self.assertEqual(r.code, f'Поставка {r.id}-2')

    def test_receipt_without_contractor_does_not_lock(self):
        r = engine.create_receipt(self.prj, self.user, 'УПД-1')
        engine.add_receipt_lot(r, self.make_item('R1'), D(1), D(1))
        with self.assertRaises(ValidationError):
            engine.lock_receipt(r)              # контрагент обязателен к фиксации

    def test_kitting_born_without_target(self):
        k = engine.create_kitting(self.prj, self.user)
        self.assertIsNone(k.target_item_id)
        self.assertIsNone(k.qty)
        self.assertEqual(k.code, f'Комплектация {k.id}')

    def test_every_list_endpoint_survives_empty_drafts(self):
        """Родить пустой черновик КАЖДОЙ сущности и прочитать ВСЕ списки.

        Пробел, который это закрывает: проверялись detail-проекции, а падали
        СПИСОЧНЫЕ (`_receipt_row` разыменовывал контрагента) — их читает сайдбар,
        то есть 500 ловил бы любой пользователь сразу после клика."""
        c = Client()
        c.force_login(self.user)
        paths = ['projects', 'items', 'locations', 'purchases', 'procurements',
                 'receipts', 'kittings', 'transfers', 'writeoffs',
                 'requisitions', 'inventories', 'relocations']
        for path in paths:
            self.assertEqual(
                c.post(f'/api/{path}/', {}, content_type='application/json')
                .status_code, 201, path)
        for path in paths:                      # каждый список после каждого рождения
            self.assertEqual(c.get(f'/api/{path}/').status_code, 200, path)

    def test_kitting_form_survives_missing_target(self):
        """Форма пустой комплектации открывается: разузловывать пока нечего."""
        form = engine.kitting_form(engine.create_kitting(self.prj, self.user))
        self.assertIsNone(form['target_id'])
        self.assertEqual(form['rows'], [])

    def test_kitting_without_target_does_not_lock(self):
        k = engine.create_kitting(self.prj, self.user)
        with self.assertRaises(ValidationError) as ctx:
            engine.lock_kitting(k)
        self.assertIn('прибор-цель', ctx.exception.messages[0])

    def test_receipt_contractor_is_editable_in_form(self):
        """Поставщик правится В ФОРМЕ, а не только при рождении (Ф12e).

        До Ф12e он задавался лишь в форме создания и в шапке не жил вовсе — после
        сноса той формы поставку было бы не зафиксировать никогда."""
        r = engine.create_receipt(self.prj, self.user, 'УПД-1')
        cp = models.Counterparty.objects.create(description='ООО Поставщик',
                                                is_supplier=True)
        c = Client()
        c.force_login(self.user)
        body = c.patch(f'/api/receipts/{r.id}/', {'contractor_id': cp.id},
                       content_type='application/json').json()
        self.assertEqual(body['contractor_id'], cp.id)
        engine.add_receipt_lot(r, self.make_item('R1'), D(1), D(1))
        engine.lock_receipt(models.Receipt.objects.get(pk=r.pk))   # теперь пускает

    def test_order_born_anchored_to_own_stock_when_project_unset(self):
        """Проект-якорь NOT NULL: фолбэк — белый «Собственный склад», не чужой НИР."""
        anchor = engine.default_document_project()
        self.assertEqual(anchor.kind, models.Project.Kind.INTERNAL_STOCK)
        r = self.client_post_document()
        self.assertEqual(r['project_id'], anchor.id)

    def client_post_document(self):
        c = Client()
        c.force_login(self.user)
        return c.post('/api/receipts/', {}, content_type='application/json').json()


class InventoryFormTests(EngineTestBase):
    """Волна 9: инвентаризация — рождение «найденных» партий (`+RECEIPT`, 4-й
    origin) + серая ре-материализация списанного лота с наследованием провенанса."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')
        self.grey = models.Project.objects.create(
            code='GREY', description='Свободные неучтённые',
            kind=models.Project.Kind.INTERNAL_WRITEOFF)

    def test_add_lot_births_receipt_movement(self):
        inv = engine.create_inventory(self.prj, self.user, 'ИНВ-1')
        lot = engine.add_inventory_lot(inv, self.item, D(7), unit_cost=D('1.50'),
                                       lot_name='Резистор')
        self.assertEqual(lot.origin_kind, 'inventory')
        self.assertEqual(lot.project_id, self.prj.id)
        self.assertEqual(engine.lot_live_qty(lot), D(0))       # Ф15: акт — черновик
        engine.lock_inventory(inv)                              # проведён
        self.assertEqual(engine.lot_live_qty(lot), D(7))       # +RECEIPT
        self.assertTrue(lot.movements.filter(type='RECEIPT', qty=D(7)).exists())

    def test_form_totals_and_description(self):
        inv = engine.create_inventory(self.prj, self.user, 'ИНВ-1')
        engine.update_inventory(inv, description='пересчёт')
        engine.add_inventory_lot(inv, self.item, D(4), unit_cost=D('2'))
        engine.lock_inventory(inv)
        c = engine.inventory_form(inv)
        self.assertEqual(c['number'], 'ИНВ-1')
        self.assertEqual(c['description'], 'пересчёт')
        self.assertEqual(c['total_cost'], D(8))                # 4 × 2
        self.assertEqual(c['lots'][0]['live_qty'], D(4))

    def test_number_required_at_lock_not_at_birth(self):
        """Ф12e: акт рождается без номера, но не фиксируется без него."""
        inv = engine.create_inventory(self.prj, self.user)
        engine.add_inventory_lot(inv, self.item, D(1), unit_cost=D('1.00'))
        with self.assertRaises(ValidationError):
            engine.lock_inventory(inv)
        engine.update_inventory(inv, number='ИНВ-7')
        engine.lock_inventory(inv)
        self.assertTrue(models.Inventory.objects.get(pk=inv.pk).locked)

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
        engine.lock_inventory(inv)
        self.assertEqual(engine.lot_live_qty(lot), D(9))
        engine.unlock_inventory(inv)                 # Ф15: правка — под снятым замком
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
        engine.lock_writeoff(w)                              # Ф15: списано фиксацией
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
        engine.lock_inventory(inv)
        self.assertEqual(born.project_id, self.grey.id)
        self.assertEqual(born.predecessor_id, src.id)
        self.assertEqual(born.unit_cost, D('2.50'))
        self.assertEqual(engine.lot_live_qty(born), D(6))
        c = engine.inventory_form(inv)
        self.assertEqual(c['lots'][0]['predecessor_id'], src.id)
        self.assertTrue(c['lots'][0]['predecessor_label'])


class InventoryHttpTests(TestCase):
    """Волна 9: HTTP-путь инвентаризации — create/строка/правка/пикер/ре-материализация."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.main = models.Location.objects.create(code='MAIN', description='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', description='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.grey = models.Project.objects.create(
            code='GREY', description='Свободные неучтённые',
            kind=models.Project.Kind.INTERNAL_WRITEOFF)
        self.item = models.Item.objects.create(code='R100', description='R100', category=_cat())
        self.sup = models.Counterparty.objects.create(description='П')
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01', locked=True,
            contractor=self.sup, project=self.prj, user=get_user_model().objects.first())
        self.lot = models.Lot.objects.create(item=self.item, project=self.prj,
            origin=r, qty=D(10), unit_cost=D('2.50'), part_number='ЗН-9')
        engine.rebuild_movements(self.lot)
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_inventory_crud_flow(self):
        r = self.c.post('/api/inventories/', {'project_id': self.prj.id,
            'number': 'ИНВ-1'}, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        iid = r.json()['id']
        # строка = найденная партия (+RECEIPT)
        line = self.c.post(f'/api/inventories/{iid}/lots/',
            {'item_id': self.item.id, 'qty': 7, 'unit_cost': '1.5',
             'lot_name': 'Резистор'}, content_type='application/json')
        self.assertEqual(line.status_code, 201)
        body = line.json()
        self.assertEqual(float(body['total_cost']), 10.5)
        self.assertEqual(float(body['lots'][0]['live_qty']), 0.0)   # Ф15: черновик
        posted = self.c.post(f'/api/inventories/{iid}/lock/')
        self.assertEqual(float(posted.json()['lots'][0]['live_qty']), 7.0)
        self.assertEqual(self.c.post(f'/api/inventories/{iid}/unlock/').status_code, 200)
        # нонпозитив qty → 400
        bad = self.c.post(f'/api/inventories/{iid}/lots/',
            {'item_id': self.item.id, 'qty': 0}, content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        # правка шапки
        patch = self.c.patch(f'/api/inventories/{iid}/', {'description': 'обновлено'},
            content_type='application/json')
        self.assertEqual(patch.json()['description'], 'обновлено')

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
        self.main = models.Location.objects.create(code='MAIN', description='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', description='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.item = models.Item.objects.create(code='R100', description='R100', category=_cat())
        self.sup = models.Counterparty.objects.create(description='П')
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01', locked=True,
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
        posted = self.c.post(f'/api/writeoffs/{wid}/lock/')
        self.assertEqual(posted.status_code, 200)
        self.assertTrue(posted.json()['locked'])
        # posted — удаление отклонено (сперва расфиксировать)
        blocked = self.c.delete(f'/api/writeoffs/{wid}/')
        self.assertEqual(blocked.status_code, 400)
        # расфиксировать → удалить
        self.assertEqual(self.c.post(f'/api/writeoffs/{wid}/unlock/').status_code, 200)
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
        r = models.Receipt.objects.create(number='U-2', date='2026-05-02', locked=True,
            contractor=self.supplier, project=self.prj, user=self.user)
        paid = models.Lot.objects.create(item=case, project=self.prj, origin=r,
            qty=D(3), unit_cost=D(800))
        engine.rebuild_movements(paid)
        # заём из белого склада → born-лот в prj (origin requisition), цена наследуется
        white = models.Project.objects.create(code='WHT', description='Склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        src = models.Lot.objects.create(item=case, project=white,
            origin=models.Inventory.objects.create(project=white, user=self.user,
                number='INV-W', date='2026-05-01', locked=True),
            qty=D(5), unit_cost=D(700))
        engine.rebuild_movements(src)
        req = engine.create_requisition(self.prj, self.user, 'ТРБ-1')
        engine.add_requisition_line(req, src, D(2))
        engine.lock_requisition(req)                 # Ф15: заём материализуется фиксацией

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
        r = models.Receipt.objects.create(number='U-3', date='2026-05-03', locked=True,
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
        r = models.Receipt.objects.create(number='U-4', date='2026-05-04', locked=True,
            contractor=self.supplier, project=self.prj, user=self.user)
        case_lot = models.Lot.objects.create(item=case, project=self.prj, origin=r,
            qty=D(1), unit_cost=D(800))
        engine.rebuild_movements(case_lot)
        # RES: заём 2 @ 10 из белого склада
        white = models.Project.objects.create(code='WHT', description='Склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        src = models.Lot.objects.create(item=res, project=white,
            origin=models.Inventory.objects.create(project=white, user=self.user,
                number='INV-W2', date='2026-05-01', locked=True),
            qty=D(2), unit_cost=D(10))
        engine.rebuild_movements(src)
        req = engine.create_requisition(self.prj, self.user, 'ТРБ-2')
        engine.add_requisition_line(req, src, D(2))
        engine.lock_requisition(req)                 # Ф15: заём материализуется фиксацией
        res_lot = req.lots.first()

        # собираем прибор
        k = models.Kitting.objects.create(project=self.prj, target_item=device,
            user=self.user, qty=D(1), locked=False)
        engine.add_kitting_line(k, case, case_lot, D(1))
        engine.add_kitting_line(k, res, res_lot, D(2))
        engine.lock_kitting(k)

        b = engine.project_budget(self.prj)
        self.assertEqual(b['spent'], D(800))    # только CASE
        self.assertEqual(b['cost'], D(820))     # снимок: 800 + 2×10 (заём по реальной цене)
        self.assertEqual(b['economy'], D(20))   # польза заёма = 2×10

    def test_compass_none_without_budget(self):
        b = engine.project_budget(self.prj)
        self.assertIsNone(b['budget'])
        self.assertIsNone(b['compass'])


class MultiLevelDemandTests(EngineTestBase):
    """Ф5 (волна 16): потребность и план разузловываются до покупных листьев, а не на
    1 уровень. Прибор из подсборок → деньги/дефицит живут на листьях (подсборку купить
    нельзя). Стоимость опущена до листьев — узел (роллап) в план не задваивается."""

    def _tree(self):
        # 3 уровня: DEV → {SUB×2, A×1}; SUB → {A×2, B×3}. Листья A(@100), B(@10).
        # На 1 DEV: A = 2×2 + 1 = 5, B = 2×3 = 6. Лист A виден из двух путей (через
        # SUB и напрямую) → агрегируется.
        a = self.make_item('A', kind='material')
        b = self.make_item('B', kind='material')
        a.estimated_cost = D(100); a.save()
        b.estimated_cost = D(10); b.save()
        sub = self.make_item('SUB', manufactured=True)
        dev = self.make_item('DEV', manufactured=True, kind='device')
        models.BomLine.objects.create(parent=sub, component=a, qty=D(2))
        models.BomLine.objects.create(parent=sub, component=b, qty=D(3))
        models.BomLine.objects.create(parent=dev, component=sub, qty=D(2))
        models.BomLine.objects.create(parent=dev, component=a, qty=D(1))
        return dev, sub, a, b

    def test_leaf_demand_explodes_and_multiplies(self):
        dev, sub, a, b = self._tree()
        leaves, incomplete = engine.project_leaf_demand(self.prj)  # пусто без потребности
        self.assertEqual(leaves, {})
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        leaves, incomplete = engine.project_leaf_demand(self.prj)
        # только листья A/B, узел SUB не в потребности; кол-во перемножено сквозь дерево
        self.assertEqual({i.code: q for i, q in leaves.items()},
                         {'A': D(50), 'B': D(60)})
        self.assertEqual(incomplete, [])

    def test_deficit_components_are_leaves(self):
        dev, sub, a, b = self._tree()
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        d = engine.project_deficit(self.prj)
        comps = {c['component_code']: c for c in d['components']}
        self.assertEqual(set(comps), {'A', 'B'})     # свод: SUB не просочился (купить нельзя)
        self.assertEqual(comps['A']['need'], D(50))
        self.assertEqual(comps['B']['need'], D(60))
        # аккордеон — ДЕРЕВО BOM (Ф5b): виден узел SUB + вложенные листья + прямой A.
        # Ключ (код, глубина): A на depth1 (под SUB) и depth0 (прямой) — разные строки.
        tree = {(n['component_code'], n['depth']): n
                for n in d['demands'][0]['tree']}
        self.assertEqual(set(tree), {('SUB', 0), ('A', 1), ('B', 1), ('A', 0)})
        self.assertFalse(tree[('SUB', 0)]['is_leaf'])   # SUB — узел, не лист
        self.assertEqual(tree[('SUB', 0)]['need'], D(20))   # 10 приборов × 2
        self.assertTrue(tree[('A', 1)]['is_leaf'])
        self.assertEqual(tree[('A', 1)]['need'], D(40))     # 20 SUB × 2
        self.assertEqual(tree[('B', 1)]['need'], D(60))     # 20 SUB × 3
        self.assertEqual(tree[('A', 0)]['need'], D(10))     # прямой в приборе

    def test_plan_sums_leaf_costs_no_double_count(self):
        # Ровно репортнутый баг: план подсборки должен пробрасываться в прогноз.
        dev, sub, a, b = self._tree()
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        bud = engine.project_budget(self.prj)
        # план = 50×100 + 60×10 = 5600 (роллап SUB=230 НЕ добавлен вторым разом)
        self.assertEqual(bud['plan'], D(5600))
        self.assertEqual(bud['unestimated'], [])

    def test_scope_deficit_explodes_to_leaves(self):
        dev, sub, a, b = self._tree()
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(1))
        rows = {r['item_code']: r for r in engine.scope_deficit([self.prj])['rows']}
        self.assertEqual(set(rows), {'A', 'B'})
        self.assertEqual(rows['A']['need'], D(5))
        self.assertEqual(rows['B']['need'], D(6))

    def test_tree_intermediate_status_is_worst_of_subtree(self):
        # Ф5b: цвет узла-подсборки в дереве = worst-of поддерева (где под ним «горит»).
        dev, sub, a, b = self._tree()
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(1))
        self.receipt_lot(a, self.prj, 100)   # лист A покрыт, лист B — нет
        tree = {(n['component_code'], n['depth']): n
                for n in engine.project_deficit(self.prj)['demands'][0]['tree']}
        self.assertEqual(tree[('A', 1)]['status'], 'available')   # ✓ покрыт
        self.assertEqual(tree[('B', 1)]['status'], 'to_order')    # ▲ надо купить
        self.assertEqual(tree[('SUB', 0)]['status'], 'to_order')  # узел = worst-of (B горит)

    def test_produced_without_bom_is_incomplete_zero(self):
        # производимый узел без состава оценить нечем: 0 в план, помечен неполнотой,
        # без краха. (Витрина неполноты — отдельно; здесь важно, что не падает и не врёт.)
        empty = self.make_item('EMPTY', manufactured=True)
        dev = self.make_item('DEV', manufactured=True, kind='device')
        models.BomLine.objects.create(parent=dev, component=empty, qty=D(1))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(5))
        leaves, incomplete = engine.project_leaf_demand(self.prj)
        self.assertEqual(leaves, {})
        self.assertEqual(incomplete, ['EMPTY'])
        self.assertEqual(engine.project_budget(self.prj)['plan'], D(0))
        self.assertEqual(engine.project_deficit(self.prj)['components'], [])

    def test_leaf_coverage_nets_stock_and_order(self):
        # нетинг — на листе (через _coverage), не на подсборке. Купили часть листа A.
        dev, sub, a, b = self._tree()
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        self.receipt_lot(a, self.prj, 20)                # A: склад 20 из нужных 50
        comps = {c['component_code']: c
                 for c in engine.project_deficit(self.prj)['components']}
        self.assertEqual(comps['A']['need'], D(50))
        self.assertEqual(comps['A']['have'], D(20))
        self.assertEqual(comps['A']['to_order'], D(30))
        # план оценивает только докупаемое (30×100) + весь B (60×10) = 3600
        self.assertEqual(engine.project_budget(self.prj)['plan'], D(3600))


class ProjectBudgetHttpTests(TestCase):
    """Волна 10: HTTP-путь бюджета проекта."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.main = models.Location.objects.create(code='MAIN', description='Основной склад')
        self.prj = models.Project.objects.create(code='P1', description='Проект 1',
            kind=models.Project.Kind.EXTERNAL, budget=D(5000))
        self.sup = models.Counterparty.objects.create(description='П')
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_budget_projection(self):
        device = models.Item.objects.create(code='DEV', description='DEV',
            category=_cat(), native=True)
        scr = models.Item.objects.create(code='SCR', description='SCR',
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
                                    self.user, description='  скан УПД ')
        self.assertEqual(att.document_id, self.receipt.id)
        self.assertEqual(att.filename, 'scan.pdf')
        self.assertEqual(att.size, len(b'%PDF-1.4 test'))
        self.assertEqual(att.content_type, 'application/pdf')
        self.assertEqual(att.description, 'скан УПД')            # подрезано
        self.assertEqual(att.user_id, self.user.id)
        self.assertIsNone(att.item_id)                     # ровно один владелец (item↔document)

    def test_attachments_for_lists_newest_first(self):
        a1 = engine.add_attachment('receipt', self.receipt, self._file('a.pdf'), self.user)
        a2 = engine.add_attachment('receipt', self.receipt, self._file('b.pdf'), self.user)
        rows = engine.attachments_for('receipt', self.receipt.id)
        self.assertEqual([r['id'] for r in rows], [a2.id, a1.id])
        self.assertEqual(rows[0]['url'], f'/api/attachments/{a2.id}/download/')

    def test_unknown_owner_type_rejected(self):
        # Волна 19, Ф12b: владельцев стало шесть, но список закрытый — склад и
        # категория в него намеренно не входят.
        with self.assertRaises(ValidationError):
            engine.resolve_attachment_owner('location', 1)
        with self.assertRaises(ValidationError):
            engine.attachments_for('bogus', 1)

    def test_non_order_owners_hold_own_field(self):
        """Волна 19, Ф12b: проект/закупка/заказ/контрагент держат СВОЁ поле (в MTI не
        входят, в `document` не схлопываются); дуга по-прежнему из ровно одного."""
        proc = models.Procurement.objects.create(user=self.user)
        purch = models.Purchase.objects.create(procurement=proc, project=self.prj,
                                               user=self.user)
        owners = {'project': self.prj, 'procurement': proc, 'purchase': purch,
                  'counterparty': self.supplier}
        for owner_type, owner in owners.items():
            with self.subTest(owner_type):
                att = engine.add_attachment(owner_type, owner,
                                            self._file(f'{owner_type}.pdf'), self.user)
                self.assertEqual(getattr(att, f'{owner_type}_id'), owner.pk)
                others = set(models.ATTACHMENT_OWNER_FIELDS) - {owner_type}
                for f in others:
                    self.assertIsNone(getattr(att, f'{f}_id'))
                rows = engine.attachments_for(owner_type, owner.pk)
                self.assertEqual([r['id'] for r in rows], [att.id])

    def test_owner_delete_sweeps_files(self):
        """Каскад БД унёс бы строку, оставив файл на диске сиротой — владельцы
        подметают за собой так же, как ордер и изделие."""
        proc = models.Procurement.objects.create(user=self.user)
        purch = models.Purchase.objects.create(procurement=proc, project=self.prj,
                                               user=self.user)
        prj = models.Project.objects.create(code='P-DEL', description='На снос',
                                            kind=models.Project.Kind.EXTERNAL)
        cases = [('purchase', purch, engine.delete_purchase),
                 ('procurement', proc, engine.delete_procurement),
                 ('project', prj, engine.delete_project)]
        for owner_type, owner, delete in cases:       # заказ раньше закупки (PROTECT)
            with self.subTest(owner_type):
                att = engine.add_attachment(owner_type, owner,
                                            self._file(f'{owner_type}.pdf'), self.user)
                path = att.file.path
                delete(owner)
                self.assertFalse(models.Attachment.objects.filter(pk=att.id).exists())
                self.assertFalse(os.path.exists(path))

    def test_oversize_rejected(self):
        big = SimpleUploadedFile('big.bin', b'x' * 10, content_type='application/octet-stream')
        with override_settings(MAX_ATTACHMENT_SIZE=5):
            with self.assertRaises(ValidationError):
                engine.add_attachment('receipt', self.receipt, big, self.user)

    def test_state_tracks_file_on_disk(self):
        """Волна 19, Ф12a: витрина красит глиф вложения по тому, что реально на диске —
        совпадает (ok), перезаписан мимо Plume (changed), пропал (missing)."""
        att = engine.add_attachment('receipt', self.receipt, self._file(), self.user)
        self.assertEqual(engine.attachment_state(att), 'ok')
        with open(att.file.path, 'wb') as f:               # подменили содержимое мимо нас
            f.write(b'%PDF-1.4 tampered longer body')
        self.assertEqual(engine.attachment_state(att), 'changed')
        os.remove(att.file.path)                           # файл унесли, запись осталась
        self.assertEqual(engine.attachment_state(att), 'missing')

    def test_update_and_delete_removes_file(self):
        att = engine.add_attachment('receipt', self.receipt, self._file(), self.user)
        path = att.file.path
        self.assertTrue(os.path.exists(path))
        engine.update_attachment(att, description='новая подпись')
        att.refresh_from_db()
        self.assertEqual(att.description, 'новая подпись')
        engine.delete_attachment(att)
        self.assertFalse(models.Attachment.objects.filter(pk=att.id).exists())
        self.assertFalse(os.path.exists(path))             # файл удалён с диска


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class AttachmentHttpTests(TestCase):
    """Волна 11: HTTP-путь вложений — multipart upload → list → patch → download → delete."""

    def setUp(self):
        self.user = get_user_model().objects.create(username='admin', is_superuser=True)
        self.supplier = models.Counterparty.objects.create(description='П')
        self.prj = models.Project.objects.create(
            code='P1', description='Проект', kind=models.Project.Kind.EXTERNAL)
        self.receipt = models.Receipt.objects.create(
            number='УПД-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        self.c = Client()
        # Волна 12: весь /api/ за логином — HTTP-путь ходит от суперюзера-админа.
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def test_full_cycle(self):
        up = SimpleUploadedFile('scan.pdf', b'%PDF data', content_type='application/pdf')
        r = self.c.post(f'/api/attachments/receipt/{self.receipt.id}/',
                        {'file': up, 'description': 'скан'})
        self.assertEqual(r.status_code, 201)
        aid = r.json()['id']
        lst = self.c.get(f'/api/attachments/receipt/{self.receipt.id}/').json()
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]['filename'], 'scan.pdf')
        self.assertEqual(lst[0]['user'], 'admin')          # автор с документа
        pr = self.c.patch(f'/api/attachments/{aid}/', {'description': 'скан УПД №1'},
                          content_type='application/json')
        self.assertEqual(pr.status_code, 200)
        self.assertEqual(pr.json()['description'], 'скан УПД №1')
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
        r = self.c.post('/api/attachments/location/1/', {'file': up})
        self.assertEqual(r.status_code, 400)

    def test_owner_not_found(self):
        """Тип известен (волна 19, Ф12b), а записи нет — тоже 400, но по другой причине."""
        up = SimpleUploadedFile('x.pdf', b'x', content_type='application/pdf')
        r = self.c.post('/api/attachments/purchase/999/', {'file': up})
        self.assertEqual(r.status_code, 400)

    def test_missing_file(self):
        r = self.c.post(f'/api/attachments/receipt/{self.receipt.id}/',
                        {'description': 'нет файла'})
        self.assertEqual(r.status_code, 400)


class AuthHttpTests(TestCase):
    """Волна 12: логин-экран — вход/выход сессией, гейтинг всего /api/, авторство."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='ivan', password='s3cret-pass', first_name='Иван')
        self.prj = models.Project.objects.create(
            code='P1', description='Проект', kind=models.Project.Kind.EXTERNAL)
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
                code='D1', description='Прибор', category=_cat(),
                native=True).id, 'qty': 1},
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
            code='PC', description='Закрытый', kind=models.Project.Kind.EXTERNAL,
            locked=True)
        with self.assertRaises(ValidationError):
            engine.add_project_demand(closed, dev, D(1))
        internal = models.Project.objects.create(
            code='WH', description='Склад', kind=models.Project.Kind.INTERNAL_STOCK)
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
        agg = {c['component_code']: c for c in out['components']}
        self.assertEqual(agg['R']['need'], D(22))
        self.assertEqual(agg['C']['need'], D(5))
        # Сортировка «горит вперёд»: одинаковый статус (всё к заказу) → по коду.
        codes = [c['component_code'] for c in out['components']]
        self.assertEqual(codes, ['C', 'R'])


class ItemProjectUpdateTests(EngineTestBase):
    """Правка свойств изделия и реквизитов проекта под замком формы (§6)."""

    def test_update_item_fields(self):
        it = self.make_item('X')
        cat2 = _cat('mcu', 'Микроконтроллеры')
        engine.update_item(it, {'description': 'Новое имя', 'category_id': cat2.id,
                                'uom': 'кг', 'estimated_cost': D('12.50'),
                                'temperature': '-40-85°C', 'native': True})
        it.refresh_from_db()
        self.assertEqual(it.description, 'Новое имя')
        self.assertEqual(it.category_id, cat2.id)
        self.assertEqual(it.uom, 'кг')
        self.assertEqual(it.estimated_cost, D('12.50'))
        self.assertEqual(it.temperature, '-40-85°C')
        self.assertTrue(it.native)

    def test_update_item_estimated_cost_can_clear(self):
        it = self.make_item('X')
        it.estimated_cost = D('5'); it.save()
        engine.update_item(it, {'estimated_cost': None})
        it.refresh_from_db()
        self.assertIsNone(it.estimated_cost)

    def test_update_item_rejects_dup_key_and_bad_category(self):
        self.make_item('A')
        it = self.make_item('B')
        with self.assertRaises(ValidationError):
            engine.update_item(it, {'code': 'A'})  # дубль ключа
        with self.assertRaises(ValidationError):
            engine.update_item(it, {'category_id': 999999})  # неизвестная категория
        # Ф12e: очистка описания/категории легальна — заполнить можно, передумать тоже.
        engine.update_item(it, {'description': '   ', 'category_id': None})
        it.refresh_from_db()
        self.assertEqual(it.description, '')
        self.assertIsNone(it.category_id)

    def test_update_item_partial_leaves_others(self):
        it = self.make_item('X')
        it.uom = 'м'; it.save()
        cat0 = it.category_id
        engine.update_item(it, {'description': 'Y'})       # прислали только описание
        it.refresh_from_db()
        self.assertEqual(it.uom, 'м')                      # uom не тронут
        self.assertEqual(it.category_id, cat0)             # категория не тронута

    def test_update_project_fields_and_clear_budget(self):
        engine.update_project(self.prj, {'description': 'Переименован',
                                         'budget': D('1000'), 'started': '2026-01-15'})
        self.prj.refresh_from_db()
        self.assertEqual(self.prj.description, 'Переименован')
        self.assertEqual(self.prj.budget, D('1000'))
        self.assertEqual(str(self.prj.started), '2026-01-15')
        engine.update_project(self.prj, {'budget': None})
        self.prj.refresh_from_db()
        self.assertIsNone(self.prj.budget)

    def test_update_project_allows_clearing_name(self):
        """Ф12e: описание не идентичность (её держит `code`) — очистка легальна."""
        engine.update_project(self.prj, {'description': '  '})
        self.prj.refresh_from_db()
        self.assertEqual(self.prj.description, '')

    def test_update_project_code_rename_and_guards(self):
        # WAVE14 Ф1: код правится в форме, guard как у изделия (не PK — безопасно).
        engine.update_project(self.prj, {'code': 'НОВ-КОД'})
        self.prj.refresh_from_db()
        self.assertEqual(self.prj.code, 'НОВ-КОД')
        with self.assertRaises(ValidationError):               # пустой код
            engine.update_project(self.prj, {'code': '  '})
        models.Project.objects.create(code='ЗАНЯТО', description='Другой')
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


class UnifiedLockTests(EngineTestBase):
    """Волна 13 Ф1: единый мягкий замок `locked` на всех складских
    документах (свернул `Receipt.approved`/`Transfer.posted`/`Kitting.wip-closed`)."""

    def test_all_docs_default_to_unlocked(self):
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
            self.assertFalse(doc.locked)
            self.assertFalse(doc.locked)

    def test_single_guard_freezes_edits_across_doc_types(self):
        """Один `_require_draft` гейтит правку прихода / передачи / комплектации."""
        # приход
        r = models.Receipt.objects.create(
            number='У-2', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        engine.add_receipt_lot(r, self.make_item('A'), D(5))
        engine.lock_receipt(r)
        self.assertTrue(r.locked)
        with self.assertRaises(ValidationError):
            engine.add_receipt_lot(r, self.make_item('B'), D(1))
        # передача
        dev = self.make_item('DEV', manufactured=True)
        dlot = self.receipt_lot(dev, self.prj, 5)
        t = engine.create_transfer(self.prj, self.user, 'Н-2')
        engine.add_transfer_line(t, dlot, D(1))
        engine.lock_transfer(t)
        t.refresh_from_db()
        self.assertTrue(t.locked)
        with self.assertRaises(ValidationError):
            engine.add_transfer_line(t, dlot, D(1))

    def test_kitting_lock_projection(self):
        """До фронт-среза (Ф1b) форма отдаёт исторические `wip`/`closed`."""
        k = models.Kitting.objects.create(
            project=self.prj, target_item=self.make_item('DEV', manufactured=True),
            user=self.user, qty=D(1))
        self.assertFalse(engine.kitting_form(k)['locked'])
        engine.lock_kitting(k)
        self.assertTrue(engine.kitting_form(k)['locked'])


class DocumentLockAndDeleteRulesTests(EngineTestBase):
    """Фиксация/расфиксация ордера, заморозка правки под замком и единое правило
    удаления: черновик — свободно, зафиксированный — сперва расфиксируй, `PROTECT`
    бережёт потраченные лоты (волна 13, Ф1b; ось `locked` — волна 19, Ф1c)."""

    def _other_project(self):
        return models.Project.objects.create(
            code='P9', description='Проект 9', kind=models.Project.Kind.EXTERNAL)

    # ── post/unpost round-trip + пустой guard ──
    def test_post_unpost_roundtrip_three_docs(self):
        """draft → posted → draft для списания/требования/инвентаризации."""
        # списание
        lot = self.receipt_lot(self.make_item('A'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'С-1')
        engine.add_writeoff_line(w, lot, D(3))
        engine.lock_writeoff(w); w.refresh_from_db()
        self.assertTrue(w.locked)
        self.assertTrue(engine.writeoff_form(w)['locked'])
        engine.unlock_writeoff(w); w.refresh_from_db()
        self.assertFalse(w.locked)
        # инвентаризация
        inv = engine.create_inventory(self.prj, self.user, 'И-1')
        engine.add_inventory_lot(inv, self.make_item('B'), D(4))
        engine.lock_inventory(inv); inv.refresh_from_db()
        self.assertTrue(inv.locked)
        self.assertTrue(engine.inventory_form(inv)['locked'])
        engine.unlock_inventory(inv); inv.refresh_from_db()
        self.assertFalse(inv.locked)
        # требование
        src = self.receipt_lot(self.make_item('C'), self._other_project(), 10)
        req = engine.create_requisition(self.prj, self.user, 'Т-1')
        engine.add_requisition_line(req, src, D(2))
        engine.lock_requisition(req); req.refresh_from_db()
        self.assertTrue(req.locked)
        self.assertTrue(engine.requisition_form(req)['locked'])
        engine.unlock_requisition(req); req.refresh_from_db()
        self.assertFalse(req.locked)

    def test_post_empty_doc_refused(self):
        """Пустой ордер нельзя провести (как приход/передача)."""
        w = engine.create_writeoff(self.prj, self.user, 'С-2')
        with self.assertRaises(ValidationError):
            engine.lock_writeoff(w)
        inv = engine.create_inventory(self.prj, self.user, 'И-2')
        with self.assertRaises(ValidationError):
            engine.lock_inventory(inv)
        req = engine.create_requisition(self.prj, self.user, 'Т-2')
        with self.assertRaises(ValidationError):
            engine.lock_requisition(req)

    # ── edit-freeze: проведённый документ read-only ──
    def test_edit_freeze_blocks_edits_on_posted_three_docs(self):
        """posted-ордер гейтит правку шапки И строк (единый `_require_draft`)."""
        # списание
        lot = self.receipt_lot(self.make_item('A'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'С-3')
        line = engine.add_writeoff_line(w, lot, D(3))
        engine.lock_writeoff(w)
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
        engine.lock_inventory(inv)
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
        engine.lock_requisition(req)
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
        # Ф15: черновик источник не двигал — снимаем его вместе с намерением
        self.assertEqual(engine.lot_live_qty(lot), D(10))
        engine.delete_stock_document(w)
        self.assertFalse(models.Writeoff.objects.filter(pk=w.pk).exists())
        self.assertEqual(engine.lot_live_qty(lot), D(10))   # источник освобождён

    def test_delete_posted_refused_until_unpost(self):
        """posted — «сперва расфиксировать»: удаление отклонено, после unpost — ок."""
        lot = self.receipt_lot(self.make_item('A'), self.prj, 10)
        w = engine.create_writeoff(self.prj, self.user, 'С-5')
        engine.add_writeoff_line(w, lot, D(4))
        engine.lock_writeoff(w)
        with self.assertRaises(ValidationError):
            engine.delete_stock_document(w)
        engine.unlock_writeoff(w)
        engine.delete_stock_document(w)
        self.assertFalse(models.Writeoff.objects.filter(pk=w.pk).exists())

    def test_delete_draft_requisition_drops_born_and_restores_source(self):
        """Удаление черновика требования: born-потомок снят, источник восстановлен."""
        src = self.receipt_lot(self.make_item('C'), self._other_project(), 10)
        req = engine.create_requisition(self.prj, self.user, 'Т-4')
        engine.add_requisition_line(req, src, D(3))
        born = req.lots.get()
        self.assertEqual(engine.lot_live_qty(src), D(10))   # Ф15: черновик не двигал
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


class DocumentKindStampTests(EngineTestBase):
    """Вид ордера живёт дискриминатором `kind` в единой таблице `StockDocument`:
    `save()` штампует его по классу, а менеджер proxy-вида сужает выборку до своего.

    Класс родился в волне 13 (Ф2a) про MTI-ядро и после Ф14 (снос MTI) переписан:
    три теста из четырёх проверяли равенство PK ребёнка и родителя — у proxy это
    верно **по построению** и сломаться не может. Живое здесь — штамп вида и
    `_KindManager`: на нём держатся 108 обращений `models.<Вид>.objects` в движке."""

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

    def test_kind_manager_shows_only_own_kind(self):
        """`_KindManager` держит иллюзию семи таблиц: менеджер вида видит только свои
        документы, а базовая таблица — все. Иллюзия load-bearing: на ней пережил снос
        MTI весь движок (`Receipt.objects.filter(...)` и per-kind функции)."""
        docs = self._one_of_each()
        self.assertEqual(models.StockDocument.objects.count(), len(docs))
        for kind, doc in docs.items():
            proxy = type(doc)
            self.assertEqual([d.pk for d in proxy.objects.all()], [doc.pk],
                             f'{proxy.__name__}.objects видит чужие виды')
        # и наоборот: чужой вид по своему же id не находится
        self.assertFalse(
            models.Receipt.objects.filter(pk=docs['writeoff'].pk).exists())


class DocumentOwnershipFkTests(EngineTestBase):
    """Владение — по одному FK на `StockDocument`, а не дугой из типизированных FK.

    `Lot.origin` и `StockLine.document` — единственный FK каждый (Check «ровно один
    origin» умер вместе с дугой); у `Attachment` дуга жива, но ордера в ней занимают
    один путь из шести. Проекция движений при этом читает вид из `document.kind`
    (волна 13, Ф2b; шесть путей владельца вложения — волна 19, Ф12b)."""

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
        engine.lock_writeoff(w)                     # Ф15: движение есть у проведённого
        born = lot.movements.get(type=models.StockMovement.Type.RECEIPT)
        self.assertEqual(born.source_type, models.StockDocument.Kind.RECEIPT)
        self.assertEqual(born.source_id, lot.origin_id)
        issue = lot.movements.get(type=models.StockMovement.Type.ISSUE)
        self.assertEqual(issue.source_type, models.StockDocument.Kind.WRITEOFF)
        self.assertEqual(issue.source_id, w.pk)

    def test_attachment_owner_is_one_path_of_six(self):
        """Шесть видов ордера схлопнуты в один FK `document`, остальные владельцы держат
        своё поле: 'receipt' → `document`, 'item' → `item`; API-строки owner_type те же;
        ровно один задан (Check жив, теперь на шесть путей — волна 19, Ф12b)."""
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
        # не-ордерные владельцы, наоборот, поля имеют (Ф12b)
        self.assertLessEqual({'project', 'procurement', 'purchase', 'counterparty'},
                             field_names)
        self.assertIn('attachment_exactly_one_owner',
                      self._constraint_names(models.Attachment))

    def test_reverse_accessors_read_from_document(self):
        """Реверсы дуг объявлены на `StockDocument`, но читаются с любого вида:
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


class DocumentHeaderFieldsTests(EngineTestBase):
    """Все колонки ордера — общая шапка И специфика вида — живут в ОДНОЙ таблице.

    Волна 13 (Ф2c) подняла общие поля `project`/`user`/`date`/`number` с шести детей
    в родителя, волна 19 добавила туда `code`/`description` (Ф10) и увела туда же
    специфику видов (Ф14, снос MTI). Своих колонок у видов не осталось вовсе —
    именно это здесь и проверяется; реверс общего поля — `project.documents`."""

    def _one_of_each(self):
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        k = models.Kitting.objects.create(
            project=self.prj, target_item=self.make_item('DEV', manufactured=True),
            user=self.user, qty=D(1), date='2026-05-02')
        inv = models.Inventory.objects.create(
            project=self.prj, user=self.user, number='И-1', date='2026-05-03',
            description='примечание акта')
        req = models.Requisition.objects.create(
            project=self.prj, user=self.user, number='Т-1', date='2026-05-04')
        t = models.Transfer.objects.create(
            project=self.prj, user=self.user, number='Н-1', date='2026-05-05')
        w = models.Writeoff.objects.create(
            project=self.prj, user=self.user, number='С-1', date='2026-05-06',
            reason='порча')
        return {'receipt': r, 'kitting': k, 'inventory': inv,
                'requisition': req, 'transfer': t, 'writeoff': w}

    def test_all_columns_live_on_one_table(self):
        """Шапка и специфика — колонки `StockDocument`; у видов своих колонок НЕТ.

        До Ф14 второй половиной этого теста было «специфика осталась на детях» — она
        осталась зелёной и после сноса MTI (proxy наследует поля родителя), продолжая
        утверждать снесённое. Проверка перевёрнута: своих полей у вида ноль — регресс,
        вернувший детскую колонку, теперь виден.
        """
        parent = {f.name for f in models.StockDocument._meta.get_fields()}
        for name in ('project', 'user', 'date', 'number', 'code', 'description',
                     'contractor', 'purchase', 'target_item', 'qty', 'reason'):
            self.assertIn(name, parent)
        for child in (models.Receipt, models.Kitting, models.Inventory,
                      models.Requisition, models.Transfer, models.Writeoff,
                      models.Relocation):
            own = {f.name for f in child._meta.get_fields()
                   if getattr(f, 'model', None) is child}
            self.assertFalse(own, f'{child.__name__} завёл свою колонку: {own}')
            self.assertTrue(child._meta.proxy, f'{child.__name__} перестал быть proxy')

    def test_reverse_accessor_is_documents(self):
        """Реверс общего `project` — `project.documents` (единый по всем видам),
        типизированный дочерний фильтр по родительскому полю тоже работает."""
        docs = self._one_of_each()
        self.assertEqual(self.prj.documents.count(), len(docs))
        self.assertEqual(
            models.Writeoff.objects.filter(project=self.prj).count(), 1)
        self.assertEqual(
            self.prj.documents.filter(kind=models.StockDocument.Kind.TRANSFER).count(), 1)

    def test_kind_manager_filters_and_orders_by_header(self):
        """Менеджер вида фильтрует/сортирует по полю шапки прозрачно
        (как в движке `Writeoff.objects.filter(project=…)`)."""
        self._one_of_each()
        r2 = models.Receipt.objects.create(
            number='У-2', date='2026-06-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        latest = models.Receipt.objects.filter(project=self.prj).order_by('-date').first()
        self.assertEqual(latest, r2)


class HeaderRequiredByKindTests(EngineTestBase):
    """Обязательность шапки — по виду: строгим видам нужны дата и номер, комплектации
    не нужно ничего. Единый kind-driven источник (`REQUIRED_HEADER_BY_KIND`/`clean`)
    гейтит и админ-форму (`full_clean → clean`), и фиксацию (`_require_header`);
    правило восстанавливает per-kind NOT NULL, ослабленный подъёмом полей в общую
    таблицу (волна 13, Ф2c/Ф2d)."""

    def test_strict_kinds_require_date_and_number(self):
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
            engine.lock_writeoff(w)
        w.number = 'С-1'
        w.save(update_fields=['number'])
        engine.lock_writeoff(w)
        self.assertTrue(w.locked)

    def test_approve_receipt_gated_on_missing_date(self):
        """lock_receipt гейтит отсутствующую дату (прямой ORM-обход дефолта create)."""
        r = models.Receipt.objects.create(project=self.prj, user=self.user,
                                           contractor=self.supplier, number='У-9', date=None)
        models.Lot.objects.create(item=self.make_item('B'), project=self.prj,
                                  origin=r, qty=D(3))
        with self.assertRaises(ValidationError):
            engine.lock_receipt(r)
        r.date = '2026-05-01'
        r.save(update_fields=['date'])
        engine.lock_receipt(r)
        self.assertTrue(r.locked)


class RelocationAndLocationStockTests(EngineTestBase):
    """Остаток считается по паре `(лот, локация)`, а ход перемещения — пара знаковых
    строк (`−q`@источник, `+q`@приёмник), сохраняющая тотал лота (волна 13, Ф2e)."""

    def setUp(self):
        super().setUp()
        # self.main (код MAIN) уже есть; добавим второе место — станок пайки.
        self.sold = models.Location.objects.create(code='105', description='Место пайки')
        self.case = self.make_item('CASE')
        self.lot = self.receipt_lot(self.case, self.prj, 12)   # рождён на self.main

    def _reloc_move(self, qty=4, lock=True):
        """Ход перемещения. Ф15: по умолчанию **проводим** — до фиксации перемещение
        склад не двигает, а тесты ниже проверяют именно расщепление по местам."""
        r = engine.create_relocation(self.prj, self.user, number='ПЕР-1',
                                     date='2026-06-05')
        engine.add_relocation_line(r, self.lot, D(qty),
                                   from_location=self.main, to_location=self.sold)
        if lock:
            engine.lock_relocation(r)
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
        # без локации — тотал (байт-в-байт со старым контрактом формы)
        self.assertEqual(engine.available_lots(self.case, self.prj)[0]['live_qty'], D(12))

    def test_stock_map_by_location(self):
        self._reloc_move(4)
        row = next(r for r in engine.stock_map(self.case)['rows']
                   if r['project_id'] == self.prj.id)
        self.assertEqual(row['available'], D(12))
        by = {b['location_id']: b['available'] for b in row['by_location']}
        self.assertEqual(by, {self.main.id: D(8), self.sold.id: D(4)})

    def test_add_line_creates_signed_pair(self):
        r = self._reloc_move(4, lock=False)          # строки есть и в черновике
        lines = sorted(r.lines.all(), key=lambda l: l.qty)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].qty, D(-4))   # источник
        self.assertEqual(lines[0].location_id, self.main.id)
        self.assertEqual(lines[1].qty, D(4))    # приёмник
        self.assertEqual(lines[1].location_id, self.sold.id)

    def test_update_line_adjusts_both(self):
        r = self._reloc_move(4, lock=False)
        engine.update_relocation_line(r, self.lot, qty=D(7))
        engine.lock_relocation(r)                    # Ф15: провели — места разъехались
        self.assertEqual(engine.lot_live_qty(self.lot, self.main), D(5))
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(7))
        self.assertEqual(engine.lot_live_qty(self.lot), D(12))

    def test_remove_line_restores(self):
        r = self._reloc_move(4, lock=False)
        engine.remove_relocation_line(r, self.lot)
        self.assertEqual(r.lines.count(), 0)
        self.assertEqual(engine.lot_live_qty(self.lot, self.main), D(12))
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(0))

    def test_form_move(self):
        r = self._reloc_move(4)
        cp = engine.relocation_form(r)
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
        other = models.Project.objects.create(code='P2', description='P2',
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
            engine.lock_relocation(empty)
        # шапка обязательна на проведении (relocation стал строгим, Ф2e); прямой ORM
        # обходит create-guard пустым номером
        r = models.Relocation.objects.create(project=self.prj, user=self.user,
                                              number='', date='2026-06-05')
        engine.add_relocation_line(r, self.lot, D(2),
                                   from_location=self.main, to_location=self.sold)
        with self.assertRaises(ValidationError):
            engine.lock_relocation(r)
        r.number = 'ПЕР-4'
        r.save(update_fields=['number'])
        engine.lock_relocation(r)
        self.assertTrue(r.locked)
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
        r = self._reloc_move(4, lock=False)          # удаляют только расфиксированное
        engine.delete_stock_document(r)
        self.assertFalse(models.Relocation.objects.filter(id=r.id).exists())
        self.assertEqual(engine.lot_live_qty(self.lot), D(12))
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(0))


class LotIdentifiersTests(EngineTestBase):
    """У партии два независимых идентификатора: `lot_name` (человеческий, из УПД) и
    `part_number` (машинный — MPN/децимальный). Писатели, формы и метка лота разводят
    их порознь и не подменяют один другим (волна 13, Ф2f)."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')
        self.receipt = self.make_receipt()

    def make_receipt(self, approved=False):
        return models.Receipt.objects.create(
            number='UPD-2f', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user,
            locked=approved)

    def test_born_lot_carries_both_identifiers(self):
        lot = engine.add_receipt_lot(self.receipt, self.item, D(5),
                                     lot_name='Резистор 10к',
                                     part_number='RES-10K-0805')
        self.assertEqual(lot.lot_name, 'Резистор 10к')
        self.assertEqual(lot.part_number, 'RES-10K-0805')
        row = engine.receipt_form(self.receipt)['lots'][0]
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
            code='WHITE', description='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        req = engine.create_requisition(white, self.user, 'ТР-1')
        engine.add_requisition_line(req, src, D(4))
        born = models.Lot.objects.get(origin=req)
        self.assertEqual(born.lot_name, 'Исходник')
        self.assertEqual(born.part_number, 'PN-SRC')


class CounterpartyRolesTests(EngineTestBase):
    """Контрагент — одна сущность с ролями (поставщик/заказчик), а не два справочника:
    у поставки он поставщик, у передачи заказчик, направление читается из вида;
    пикеры фильтруют по роли (волна 13, Ф2f+; одна колонка — волна 19, Ф14)."""

    def test_supplier_role_default(self):
        # унаследованный `self.supplier` (без явных ролей) — поставщик по умолчанию
        self.assertTrue(self.supplier.is_supplier)
        self.assertFalse(self.supplier.is_customer)

    def test_receipt_form_emits_contractor(self):
        r = models.Receipt.objects.create(
            number='U-g', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        cp = engine.receipt_form(r)
        self.assertEqual(cp['contractor_id'], self.supplier.id)
        self.assertEqual(cp['contractor_name'], self.supplier.description)

    def test_create_transfer_with_customer(self):
        cust = models.Counterparty.objects.create(
            description='Заказчик', is_supplier=False, is_customer=True)
        t = engine.create_transfer(self.prj, self.user, 'Н-1', contractor=cust)
        self.assertEqual(t.contractor_id, cust.id)
        cp = engine.transfer_form(t)
        self.assertEqual(cp['contractor_id'], cust.id)
        self.assertEqual(cp['contractor_name'], 'Заказчик')

    def test_transfer_contractor_optional_and_settable(self):
        t = engine.create_transfer(self.prj, self.user, 'Н-2')   # без получателя
        self.assertIsNone(t.contractor_id)
        self.assertEqual(engine.transfer_form(t)['contractor_name'], '')
        cust = models.Counterparty.objects.create(
            description='Поздний', is_supplier=False, is_customer=True)
        engine.update_transfer(t, contractor=cust)               # проставить позже
        t.refresh_from_db()
        self.assertEqual(t.contractor_id, cust.id)
        engine.update_transfer(t, contractor=None)               # снять (nullable)
        t.refresh_from_db()
        self.assertIsNone(t.contractor_id)

    def test_update_transfer_sentinel_keeps_contractor(self):
        """Часовой `_UNSET`: правка номера/даты не сбрасывает получателя."""
        cust = models.Counterparty.objects.create(
            description='Стойкий', is_supplier=False, is_customer=True)
        t = engine.create_transfer(self.prj, self.user, 'Н-3', contractor=cust)
        engine.update_transfer(t, number='Н-3-ред')              # contractor не передан
        t.refresh_from_db()
        self.assertEqual(t.contractor_id, cust.id)
        self.assertEqual(t.number, 'Н-3-ред')

    def test_counterparties_endpoint_role_filter(self):
        models.Counterparty.objects.create(
            description='ТолькоЗаказчик', is_supplier=False, is_customer=True)
        c = Client()
        c.force_login(self.user)
        # ?role=supplier — унаследованный поставщик, без заказчика
        sup_names = {r['description'] for r in c.get('/api/counterparties/?role=supplier').json()}
        self.assertIn('Поставщик', sup_names)
        self.assertNotIn('ТолькоЗаказчик', sup_names)
        # ?role=customer — только заказчик
        cust_names = {r['description'] for r in c.get('/api/counterparties/?role=customer').json()}
        self.assertIn('ТолькоЗаказчик', cust_names)
        self.assertNotIn('Поставщик', cust_names)
        # быстрое создание с ролью
        created = c.post('/api/counterparties/',
                         {'description': 'Новый', 'role': 'customer'},
                         content_type='application/json').json()
        self.assertTrue(created['is_customer'])
        self.assertFalse(created['is_supplier'])


class OrderAdminTests(EngineTestBase):
    """Админка ордера — ОДИН пункт на семь видов, и она не подменяет движок.

    До Ф16 здесь было восемь регистраций на одну таблицу (read-only обзор + семь
    per-kind админок) — пережиток MTI, который Ф14 сделала бессмысленным. Теперь
    список и форма одни, вид рулит составом полей и инлайнов, а всё, что двигает
    склад (замок, удаление, строки, партии), из админки недоступно: инвариант
    «движения ⟺ документ зафиксирован» держит движок, и молча обойти его нельзя.
    """

    def _admin(self):
        from django.contrib import admin as dj_admin
        return dj_admin.site._registry[models.StockDocument]

    def _request(self):
        from django.test import RequestFactory
        su = get_user_model().objects.create_superuser('su_adm', 'a@a.tld', 'x')
        req = RequestFactory().get('/admin/')
        req.user = su
        return req

    def test_seven_kind_admins_collapsed_to_one(self):
        """В сайдбаре ордер ровно один: proxy-виды не зарегистрированы."""
        from django.contrib import admin as dj_admin
        self.assertIn(models.StockDocument, dj_admin.site._registry)
        for proxy in (models.Receipt, models.Kitting, models.Inventory,
                      models.Requisition, models.Transfer, models.Writeoff,
                      models.Relocation):
            self.assertNotIn(proxy, dj_admin.site._registry,
                             f'{proxy.__name__} снова отдельным пунктом сайдбара')

    def test_form_shape_follows_kind(self):
        """Поля и инлайны формы зависят от вида: специфика чужого вида не показывается
        (её колонка обязана быть пустой — CHECK `doc_*_only_*`)."""
        ma, req = self._admin(), self._request()
        r = models.Receipt.objects.create(
            number='ПР-f', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        k = models.Kitting.objects.create(
            project=self.prj, user=self.user, qty=D(1),
            target_item=self.make_item('DEV-f', manufactured=True))
        w = models.Writeoff.objects.create(
            project=self.prj, user=self.user, number='СП-f', date='2026-05-02')

        receipt_fields = ma.get_fields(req, r)
        self.assertIn('contractor', receipt_fields)
        self.assertIn('purchase', receipt_fields)
        self.assertNotIn('target_item', receipt_fields)
        self.assertNotIn('reason', receipt_fields)

        kitting_fields = ma.get_fields(req, k)
        self.assertIn('target_item', kitting_fields)
        self.assertIn('qty', kitting_fields)
        self.assertNotIn('contractor', kitting_fields)
        self.assertNotIn('number', kitting_fields)      # у комплектации номера нет

        self.assertIn('reason', ma.get_fields(req, w))

        # инлайны: строки — у видов, которые расходуют; born-лоты — у рождающих
        self.assertEqual(ma.get_inlines(req, r), [admin.BornLotsInline])
        self.assertEqual(ma.get_inlines(req, k),
                         [admin.KittingLinesInline, admin.BornLotsInline])
        self.assertEqual(ma.get_inlines(req, w), [admin.StockLinesInline])
        self.assertEqual(ma.get_inlines(req, None), [])   # на форме добавления вида нет

    def test_lock_and_delete_belong_to_engine(self):
        """Замок read-only, удаления нет, вид у существующего ордера не меняется."""
        ma, req = self._admin(), self._request()
        r = models.Receipt.objects.create(
            number='ПР-g', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        self.assertIn('locked', ma.get_readonly_fields(req, r))
        self.assertIn('kind', ma.get_readonly_fields(req, r))
        self.assertIn('locked', ma.get_readonly_fields(req, None))
        self.assertNotIn('kind', ma.get_readonly_fields(req, None))  # при заводе — выбор
        self.assertFalse(ma.has_delete_permission(req, r))
        self.assertNotIn('delete_selected', ma.get_actions(req))

    def test_engine_owned_tables_are_read_only(self):
        """Партии, движения, строки и вложения админка только показывает."""
        from django.contrib import admin as dj_admin
        req = self._request()
        for model in (models.Lot, models.StockMovement, models.StockLine,
                      models.Attachment):
            ma = dj_admin.site._registry[model]
            self.assertFalse(ma.has_add_permission(req), model.__name__)
            self.assertFalse(ma.has_change_permission(req), model.__name__)
            self.assertFalse(ma.has_delete_permission(req), model.__name__)

    def test_changelist_and_form_http(self):
        """HTTP-путь: смешанный список видит все виды, форма вида открывается."""
        r = models.Receipt.objects.create(
            number='ПР-http', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        models.Writeoff.objects.create(
            number='СП-http', date='2026-05-02', reason='порча',
            project=self.prj, user=self.user)
        su = get_user_model().objects.create_superuser(
            username='root', email='r@e.x', password='x')
        c = Client()
        c.force_login(su)
        lst = c.get('/admin/plume/stockdocument/')
        self.assertEqual(lst.status_code, 200)
        self.assertContains(lst, 'ПР-http')              # оба вида вперемешку
        self.assertContains(lst, 'СП-http')
        form = c.get(f'/admin/plume/stockdocument/{r.pk}/change/')
        self.assertEqual(form.status_code, 200)
        self.assertContains(form, 'ПР-http')
        # удалять ордер из админки нельзя — кнопки нет
        self.assertNotContains(form, f'/admin/plume/stockdocument/{r.pk}/delete/')

    def test_change_form_renders_for_every_kind(self):
        """Форма открывается у всех семи видов. Инлайн-витрина ломается конфигом
        (поля/`readonly_fields`/`max_num`), и ломается она в РЕНДЕРЕ — 500 админки
        сюита не видит, пока страницу не запросили."""
        su = get_user_model().objects.create_superuser(
            username='root2', email='r2@e.x', password='x')
        c = Client()
        c.force_login(su)
        Kind = models.StockDocument.Kind
        docs = {
            Kind.RECEIPT: models.Receipt.objects.create(
                number='ПР-r', date='2026-05-01', contractor=self.supplier,
                project=self.prj, user=self.user),
            Kind.KITTING: models.Kitting.objects.create(
                project=self.prj, user=self.user, qty=D(1),
                target_item=self.make_item('DEV-r', manufactured=True)),
            Kind.INVENTORY: models.Inventory.objects.create(
                number='ИН-r', date='2026-05-01', project=self.prj, user=self.user),
            Kind.REQUISITION: models.Requisition.objects.create(
                number='ТР-r', date='2026-05-01', project=self.prj, user=self.user),
            Kind.TRANSFER: models.Transfer.objects.create(
                number='НК-r', date='2026-05-01', project=self.prj, user=self.user),
            Kind.WRITEOFF: models.Writeoff.objects.create(
                number='СП-r', date='2026-05-01', project=self.prj, user=self.user),
            Kind.RELOCATION: models.Relocation.objects.create(
                number='ПМ-r', date='2026-05-01', project=self.prj, user=self.user),
        }
        for kind, doc in docs.items():
            resp = c.get(f'/admin/plume/stockdocument/{doc.pk}/change/')
            self.assertEqual(resp.status_code, 200, f'форма вида {kind} не открылась')
        # и форма заведения нового ордера (вида ещё нет — специфики на ней тоже)
        self.assertEqual(c.get('/admin/plume/stockdocument/add/').status_code, 200)


class DocumentAuthorTests(EngineTestBase):
    """Автор — поле документа, а не системный штамп: переназначается на всех ордерах
    (плюс заказ и закупка), пока документ расфиксирован. Формы несут `user_id`/
    `user_name`, `update_*` принимают часового `_UNSET`, `/api/users/` кормит пикер
    (волна 13, Ф2j)."""

    def setUp(self):
        super().setUp()
        # второй автор с человеческим именем — цель переназначения авторства
        self.author2 = get_user_model().objects.create(
            username='ivan', first_name='Иван', last_name='Пэ')

    def test_form_emits_author(self):
        r = models.Receipt.objects.create(
            number='U-j', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.author2)
        cp = engine.receipt_form(r)
        self.assertEqual(cp['user_id'], self.author2.id)
        self.assertEqual(cp['user_name'], 'Иван Пэ')       # get_full_name()

    def test_purchase_and_procurement_carry_author(self):
        p = engine.create_purchase(self.prj, self.author2)
        self.assertEqual(engine.purchase_form(p)['user_id'], self.author2.id)
        proc = engine.create_procurement(self.author2)
        self.assertEqual(engine.procurement_form(proc)['user_id'], self.author2.id)

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
        engine.lock_writeoff(w)
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


class OrderAnchorTests(EngineTestBase):
    """Структурные якоря шапки (`project` у всех ордеров и заказа, `target_item` у
    комплектации, `procurement` у заказа) меняются только у «пустого» документа:
    за якорем следуют лоты и строки, поэтому при непустом — дружелюбный отказ.
    Часовой `_UNSET`, `None`-отказ (FK NOT NULL), гейт замком (волна 13, Ф2k)."""

    def setUp(self):
        super().setUp()
        self.prj2 = models.Project.objects.create(
            code='P9', description='Проект 9', kind=models.Project.Kind.EXTERNAL)

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
        engine.lock_writeoff(w)
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
        self.assertEqual(engine.purchase_form(p)['procurement_id'], proc2.id)

    def test_purchase_procurement_clears_to_none(self):
        """Ф17: закупка-план опциональна — якорь снимается, заказ живёт дальше."""
        p = engine.create_purchase(self.prj, self.user)
        engine.update_purchase(p, procurement=engine.create_procurement(self.user))
        engine.update_purchase(p, procurement=None)
        p.refresh_from_db()
        self.assertIsNone(p.procurement_id)
        self.assertIsNone(engine.purchase_form(p)['procurement_id'])

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


class RelocationHttpTests(EngineTestBase):
    """HTTP-слой перемещения и справочника мест: создание → пикер лотов/мест →
    добавление хода → правка → фиксация/расфиксация → удаление. Инвариант тот же,
    что у движка: тотал лота сохранён — перемещение двигает распределение по
    `(лот, локация)`, а не остаток (волна 13, Ф3)."""

    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save()
        self.sold = models.Location.objects.create(code='105', description='Место пайки')
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
        self.assertEqual(self.c.post(f'/api/relocations/{rid}/lock/').status_code, 200)
        # Ф15: провели → 7 @ MAIN, 5 @ 105, тотал 12
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
        other = models.Project.objects.create(code='P2', description='Проект 2',
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
        self.assertEqual(self.c.post(f'/api/relocations/{rid}/lock/').status_code, 200)
        self.assertEqual(engine.lot_live_qty(self.lot, self.sold), D(8))
        # удаление хода (после расфиксации) → распределение вернулось (всё на MAIN)
        self.assertEqual(self.c.post(f'/api/relocations/{rid}/unlock/').status_code, 200)
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
        posted = self.c.post(f'/api/relocations/{rid}/lock/')
        self.assertEqual(posted.status_code, 200)
        self.assertTrue(posted.json()['locked'])
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
        self.assertEqual(self.c.post(f'/api/relocations/{rid}/unlock/').status_code, 200)
        self.assertEqual(self.c.delete(f'/api/relocations/{rid}/').status_code, 204)
        self.assertFalse(models.Relocation.objects.filter(pk=rid).exists())
        self.assertEqual(engine.lot_live_qty(self.lot), D(12))
        self.assertEqual(engine.lot_live_qty(self.lot, self.main), D(12))

    def test_empty_relocation_cannot_be_posted(self):
        rid = self._create()
        resp = self.c.post(f'/api/relocations/{rid}/lock/')
        self.assertEqual(resp.status_code, 400)

    def test_patch_header_number_and_project_anchor(self):
        rid = self._create()
        # № правится свободно
        upd = self.c.patch(f'/api/relocations/{rid}/', {'number': 'ПЕР-9'},
                          content_type='application/json')
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.json()['number'], 'ПЕР-9')
        # проект-якорь: у пустого ордера сменить можно
        other = models.Project.objects.create(code='P3', description='Проект 3',
            kind=models.Project.Kind.EXTERNAL)
        moved = self.c.patch(f'/api/relocations/{rid}/', {'project_id': other.id},
                            content_type='application/json')
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()['project_id'], other.id)


class LocationEntityTests(EngineTestBase):
    """Место хранения — полноценная сущность «Склады»: что на нём лежит и его ДНК
    (код/описание/вид), включая guard на дубль кода (волна 13, Ф4)."""

    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save()
        self.sold = models.Location.objects.create(code='105', description='Место пайки')
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
        engine.lock_relocation(rel)                 # Ф15: расщепление — с фиксации
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
        engine.update_location(self.sold, description='Пайка-2', kind='цех')
        self.sold.refresh_from_db()
        self.assertEqual(self.sold.description, 'Пайка-2')
        self.assertEqual(self.sold.kind, 'цех')
        # код на занятый — дружелюбный отказ
        with self.assertRaises(ValidationError):
            engine.update_location(self.sold, code='MAIN')

    def test_http_location_form_and_patch(self):
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
                          {'code': '301', 'description': 'Резерв'},
                          content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(models.Location.objects.filter(code='301').exists())
        # дубль кода → 400
        dup = self.c.post('/api/locations/',
                        {'code': '301', 'description': 'Дубль'},
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
        loc = models.Location.objects.create(code='EMPTY', description='Пустой склад')
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
        p = self.make_purchase()
        engine.add_purchase_line(p, self.make_item('A'), D(4))
        engine.lock_purchase(p)
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
        proc = engine.create_procurement(self.user)
        p = engine.create_purchase(self.prj, self.user)
        engine.update_purchase(p, procurement=proc)      # Ф17: план выбирают, а не плодят
        with self.assertRaises(ValidationError):
            engine.delete_procurement(proc)          # привязан заказ

    # ── Проект ──
    def test_delete_project_free_when_empty(self):
        prj = models.Project.objects.create(
            code='EMPTY-PRJ', description='Пустой', kind=models.Project.Kind.EXTERNAL)
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
            code='WHITE', description='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK)
        with self.assertRaises(ValidationError):
            engine.delete_project(stock)


class EntityDeleteHttpTests(TestCase):
    """WAVE14 Ф2: HTTP-путь DELETE справочных сущностей (204 успех / 400 friendly-guard)."""

    def setUp(self):
        self.user = get_user_model().objects.create(username='admin', is_superuser=True)
        self.main = models.Location.objects.create(code='MAIN', description='Основной склад')
        self.prj = models.Project.objects.create(
            code='P1', description='Проект 1', kind=models.Project.Kind.EXTERNAL)
        self.sup = models.Counterparty.objects.create(description='П')
        self.c = Client()
        self.c.force_login(self.user)

    def test_item_delete_204_and_guard_400(self):
        it = models.Item.objects.create(code='FREE', description='FREE', category=_cat())
        self.assertEqual(self.c.delete(f'/api/items/{it.id}/').status_code, 204)
        self.assertFalse(models.Item.objects.filter(pk=it.pk).exists())
        # с лотом → 400
        it2 = models.Item.objects.create(code='WL', description='WL', category=_cat())
        r = models.Receipt.objects.create(number='U-1', date='2026-05-01',
            contractor=self.sup, project=self.prj, user=self.user)
        lot = models.Lot.objects.create(item=it2, project=self.prj, origin=r, qty=D(1))
        engine.rebuild_movements(lot)
        self.assertEqual(self.c.delete(f'/api/items/{it2.id}/').status_code, 400)

    def test_location_delete_204_and_guard_400(self):
        loc = models.Location.objects.create(code='EMPTY', description='Пустой')
        self.assertEqual(self.c.delete(f'/api/locations/{loc.id}/').status_code, 204)
        r = models.Receipt.objects.create(number='U-2', date='2026-05-01', locked=True,
            contractor=self.sup, project=self.prj, user=self.user)   # Ф15: движение есть
        lot = models.Lot.objects.create(
            item=models.Item.objects.create(code='M', description='M', category=_cat()),
            project=self.prj, origin=r, qty=D(1))
        engine.rebuild_movements(lot)               # движение на MAIN
        self.assertEqual(self.c.delete(f'/api/locations/{self.main.id}/').status_code, 400)

    def test_project_delete_204_and_guard_400(self):
        empty = models.Project.objects.create(
            code='E', description='E', kind=models.Project.Kind.EXTERNAL)
        self.assertEqual(self.c.delete(f'/api/projects/{empty.id}/').status_code, 204)
        r = models.Receipt.objects.create(number='U-3', date='2026-05-01',
            contractor=self.sup, project=self.prj, user=self.user)
        lot = models.Lot.objects.create(
            item=models.Item.objects.create(code='Q', description='Q', category=_cat()),
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


# Полная 8-колоночная схема библиотеки (парсер ищет нужные колонки по имени, но
# тесты кормят реальный заголовок — терпимость к лишним колонкам заодно проверена).
_LIB_HEADER = ['Design Item Id', 'Comment', 'Description', 'Footprint Path',
               'Footprint Ref', 'Library Path', 'Library Ref', 'Temperature']


def _lib_csv(items):
    """CP1251-байты CSV библиотеки из списка `(code, description, temperature)`.
    Разделитель `;`, финальный LF (как в реальных выгрузках Altium)."""
    lines = [';'.join(_LIB_HEADER)]
    for did, desc, temp in items:
        lines.append(';'.join([did, '', desc, '', '', '', '', temp]))
    return ('\n'.join(lines) + '\n').encode('cp1251')


class LibraryParseTests(TestCase):
    """Волна 15 Ф1: парсер CSV библиотеки (CP1251, `;`, мульти-файл)."""

    def test_parse_basic(self):
        raw = _lib_csv([('CAP-1', 'Конденсатор 1', '-55-125°C'),
                        ('CAP-2', 'Конденсатор 2', '-40-85°C')])
        cat, rows = engine.parse_library_file('csv/capacitors.csv', raw)
        self.assertEqual(cat, 'capacitors')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {'code': 'CAP-1', 'description': 'Конденсатор 1',
                                   'temperature': '-55-125°C', 'category': 'capacitors'})

    def test_trailing_blank_line_skipped(self):
        raw = _lib_csv([('X', 'Икс', '')]) + b'\n'      # лишний финальный перевод
        _, rows = engine.parse_library_file('sensors.csv', raw)
        self.assertEqual(len(rows), 1)

    def test_missing_column(self):
        bad = 'Design Item Id;Comment\nX;y\n'.encode('cp1251')
        with self.assertRaises(ValidationError):
            engine.parse_library_file('mcu.csv', bad)

    def test_empty_key(self):
        raw = _lib_csv([('', 'без ключа', '')])
        with self.assertRaises(ValidationError):
            engine.parse_library_file('mcu.csv', raw)

    def test_duplicate_key_in_file(self):
        raw = _lib_csv([('D', 'раз', ''), ('D', 'два', '')])
        with self.assertRaises(ValidationError):
            engine.parse_library_file('mcu.csv', raw)

    def test_cp1251_decode(self):
        # Кириллица в CP1251 читается верно (в отличие от наивного UTF-8-декода).
        raw = _lib_csv([('X', 'Микросхема ЦАП', '-40-125°C')])
        _, rows = engine.parse_library_file('mcu.csv', raw)
        self.assertEqual(rows[0]['description'], 'Микросхема ЦАП')
        self.assertEqual(rows[0]['temperature'], '-40-125°C')

    def test_multi_file_aggregate(self):
        files = [('capacitors.csv', _lib_csv([('C1', 'к', '')])),
                 ('mcu.csv', _lib_csv([('M1', 'м', '')]))]
        parsed = engine.parse_library(files)
        self.assertEqual(set(parsed['categories']), {'capacitors', 'mcu'})
        self.assertEqual(len(parsed['rows']), 2)

    def test_duplicate_category(self):
        files = [('capacitors.csv', _lib_csv([('C1', 'к', '')])),
                 ('capacitors.csv', _lib_csv([('C2', 'к', '')]))]
        with self.assertRaises(ValidationError):
            engine.parse_library(files)

    def test_duplicate_key_across_files(self):
        files = [('capacitors.csv', _lib_csv([('DUP', 'к', '')])),
                 ('mcu.csv', _lib_csv([('DUP', 'м', '')]))]
        with self.assertRaises(ValidationError):
            engine.parse_library(files)

    def test_empty_upload(self):
        with self.assertRaises(ValidationError):
            engine.parse_library([])


class LibraryDiffTests(TestCase):
    """Волна 15 Ф2: диф загруженной библиотеки против справочника."""

    def _cat(self, code):
        return engine.ensure_category(code)

    def _item(self, did, cat, desc='desc', temp='', native=False):
        return models.Item.objects.create(
            code=did, description=desc, category=self._cat(cat),
            temperature=temp, native=native)

    def _diff(self, files):
        return engine.library_diff(engine.parse_library(files))

    def _by_key(self, rows):
        return {r['code']: r for r in rows}

    def test_new_changed_same(self):
        self._item('CAP-1', 'capacitors', desc='старое', temp='-40-85°C')
        c2 = self._item('CAP-2', 'capacitors', desc='совпадает', temp='-55-125°C')
        c2.synced = True; c2.save()          # совпадает И уже помечено библиотечным → same
        files = [('capacitors.csv', _lib_csv([
            ('CAP-1', 'новое', '-40-85°C'),     # description изменился
            ('CAP-2', 'совпадает', '-55-125°C'), # без изменений
            ('CAP-3', 'новый', '')])),           # нет в БД
        ]
        rows = self._by_key(self._diff(files))
        self.assertEqual(rows['CAP-1']['status'], 'changed')
        self.assertIn('description', rows['CAP-1']['changes'])
        self.assertEqual(rows['CAP-2']['status'], 'same')
        self.assertEqual(rows['CAP-3']['status'], 'new')

    def test_mark_when_unsynced_matches_library(self):
        # Ф3a: содержимое совпадает, но изделие ещё не помечено библиотечным → mark.
        self._item('CAP-9', 'capacitors', desc='совп', temp='')   # synced=False по умолчанию
        rows = self._by_key(self._diff([('capacitors.csv', _lib_csv([('CAP-9', 'совп', '')]))]))
        self.assertEqual(rows['CAP-9']['status'], 'mark')
        self.assertFalse(rows['CAP-9']['current']['synced'])

    def test_gone_when_unused(self):
        self._item('CAP-OLD', 'capacitors')      # в БД, не в загрузке, не используется
        rows = self._by_key(self._diff([('capacitors.csv', _lib_csv([('CAP-1', 'к', '')]))]))
        self.assertEqual(rows['CAP-OLD']['status'], 'gone')

    def test_orphan_when_used(self):
        used = self._item('CAP-USED', 'capacitors')
        parent = self._item('DEV', 'capacitors', native=True)
        models.BomLine.objects.create(parent=parent, component=used, qty=D(1))
        # DEV тоже в капаситорах и не в загрузке → сам gone/orphan; CAP-USED — orphan.
        rows = self._by_key(self._diff([('capacitors.csv', _lib_csv([('CAP-1', 'к', '')]))]))
        self.assertEqual(rows['CAP-USED']['status'], 'orphan')

    def test_missing_scoped_by_category(self):
        # Изделие класса mcu не считается пропавшим, если грузили только capacitors.
        self._item('MCU-X', 'mcu')
        rows = self._by_key(self._diff([('capacitors.csv', _lib_csv([('CAP-1', 'к', '')]))]))
        self.assertNotIn('MCU-X', rows)

    def test_category_change_detected(self):
        self._item('MULTI', 'capacitors')
        rows = self._by_key(self._diff([('mcu.csv', _lib_csv([('MULTI', 'desc', '')]))]))
        self.assertEqual(rows['MULTI']['status'], 'changed')
        self.assertIn('category', rows['MULTI']['changes'])


class LibraryApplyTests(TestCase):
    """Волна 15 Ф2: применение подтверждённых строк дифа."""

    def _item(self, did, cat, desc='desc', temp='', native=False):
        return models.Item.objects.create(
            code=did, description=desc, category=engine.ensure_category(cat),
            temperature=temp, native=native)

    def test_apply_creates_new(self):
        files = [('sensors.csv', _lib_csv([('S-1', 'Датчик', '-40-85°C')]))]
        parsed = engine.parse_library(files)
        summary = engine.apply_library_diff(parsed, ['S-1'])
        self.assertEqual(summary['created'], 1)
        item = models.Item.objects.get(code='S-1')
        self.assertFalse(item.native)                  # импорт → покупное
        self.assertTrue(item.synced)                     # рождается библиотечным
        self.assertFalse(item.locked)                    # но НЕ запертым — готово под цену
        self.assertIsNone(item.estimated_cost)           # цена — за Plume
        self.assertEqual(item.category.code, 'sensors')  # категория заведена на лету
        self.assertEqual(item.category.description, 'Датчики') # канон LIBRARY_CATEGORIES

    def test_apply_updates_changed(self):
        self._item('S-1', 'sensors', desc='старое', temp='')
        parsed = engine.parse_library([('sensors.csv', _lib_csv([('S-1', 'новое', '-40-85°C')]))])
        engine.apply_library_diff(parsed, ['S-1'])
        item = models.Item.objects.get(code='S-1')
        self.assertEqual(item.description, 'новое')
        self.assertEqual(item.temperature, '-40-85°C')
        self.assertTrue(item.synced)                     # синк подтвердил библиотечность

    def test_apply_deletes_gone(self):
        self._item('S-OLD', 'sensors')
        parsed = engine.parse_library([('sensors.csv', _lib_csv([('S-1', 'к', '')]))])
        summary = engine.apply_library_diff(parsed, ['S-OLD'])
        self.assertEqual(summary['deleted'], 1)
        self.assertFalse(models.Item.objects.filter(code='S-OLD').exists())

    def test_apply_only_confirmed(self):
        self._item('S-OLD', 'sensors')                   # gone, НЕ подтверждаем
        parsed = engine.parse_library([('sensors.csv', _lib_csv([
            ('S-1', 'новый A', ''), ('S-2', 'новый B', '')]))])
        summary = engine.apply_library_diff(parsed, ['S-1'])   # только S-1
        self.assertEqual(summary['created'], 1)
        self.assertTrue(models.Item.objects.filter(code='S-1').exists())
        self.assertFalse(models.Item.objects.filter(code='S-2').exists())
        self.assertTrue(models.Item.objects.filter(code='S-OLD').exists())

    def test_apply_mark_sets_synced(self):
        # Ф3a: совпадающее по содержимому непомеченное изделие → mark → synced=True,
        # locked не трогаем (решение Ивана 2026-07-24).
        it = self._item('S-1', 'sensors', desc='датчик', temp='')   # synced=False, совпадает
        parsed = engine.parse_library([('sensors.csv', _lib_csv([('S-1', 'датчик', '')]))])
        summary = engine.apply_library_diff(parsed, ['S-1'])
        self.assertEqual(summary['marked'], 1)
        self.assertEqual(summary['updated'], 0)   # содержимое не трогали
        it.refresh_from_db()
        self.assertTrue(it.synced)
        self.assertFalse(it.locked)               # замок не тронут

    def test_apply_mark_only_confirmed(self):
        # Не подтверждённый mark — не помечается.
        it = self._item('S-1', 'sensors', desc='датчик', temp='')
        parsed = engine.parse_library([('sensors.csv', _lib_csv([('S-1', 'датчик', '')]))])
        summary = engine.apply_library_diff(parsed, [])   # ничего не подтверждаем
        self.assertEqual(summary['marked'], 0)
        it.refresh_from_db()
        self.assertFalse(it.synced)

    def test_orphan_not_deleted_even_if_confirmed(self):
        used = self._item('S-USED', 'sensors')
        parent = self._item('DEV', 'sensors', native=True)
        models.BomLine.objects.create(parent=parent, component=used, qty=D(1))
        parsed = engine.parse_library([('sensors.csv', _lib_csv([('S-1', 'к', '')]))])
        summary = engine.apply_library_diff(parsed, ['S-USED'])   # подтверждаем сироту
        self.assertEqual(summary['deleted'], 0)          # orphan — не действие
        self.assertTrue(models.Item.objects.filter(code='S-USED').exists())


class ItemStatusTests(EngineTestBase):
    """Волна 17, фаза 1: статус изделия `draft ⇄ posted` (фиксация), гейт мутаций,
    синк библиотеки → posted, проброс статуса в сериализацию."""


    def test_manual_item_defaults_draft(self):
        i = engine.create_item('R100', 'Резистор', category_id=_cat().id)
        self.assertFalse(i.locked)
        self.assertFalse(i.synced)                # ручное — не из библиотеки

    def test_post_unpost_idempotent(self):
        i = self.make_item('R')
        engine.lock_item(i)
        i.refresh_from_db()
        self.assertTrue(i.locked)
        engine.lock_item(i)                       # повторно — без падения
        i.refresh_from_db()
        self.assertTrue(i.locked)
        engine.unlock_item(i)
        i.refresh_from_db()
        self.assertFalse(i.locked)
        engine.unlock_item(i)                     # повторно — без падения
        i.refresh_from_db()
        self.assertFalse(i.locked)

    def test_gate_blocks_property_edit_when_posted(self):
        i = self.make_item('R')
        engine.lock_item(i)
        with self.assertRaises(ValidationError):
            engine.update_item(i, {'description': 'нельзя'})
        # расфиксировали — правка снова проходит
        engine.unlock_item(i)
        engine.update_item(i, {'description': 'можно'})
        i.refresh_from_db()
        self.assertEqual(i.description, 'можно')

    def test_gate_blocks_bom_edits_when_parent_posted(self):
        dev = self.make_item('DEV', manufactured=True)
        comp = self.make_item('R')
        line = engine.add_bom_line(dev, comp, D(2))
        engine.lock_item(dev)
        with self.assertRaises(ValidationError):
            engine.add_bom_line(dev, self.make_item('C'), D(1))
        with self.assertRaises(ValidationError):
            engine.update_bom_line(line, qty=D(5))
        with self.assertRaises(ValidationError):
            engine.remove_bom_line(line)
        line.refresh_from_db()
        self.assertEqual(line.qty, D(2))          # не изменилось

    def test_gate_blocks_delete_when_posted(self):
        i = self.make_item('R')
        engine.lock_item(i)
        with self.assertRaises(ValidationError):
            engine.delete_item(i)
        self.assertTrue(models.Item.objects.filter(pk=i.pk).exists())
        engine.unlock_item(i)
        engine.delete_item(i)
        self.assertFalse(models.Item.objects.filter(pk=i.pk).exists())

    def test_library_new_is_synced_unlocked(self):
        # Ф3a: новое библиотечное — synced=True, но locked=False (готово под цену).
        parsed = engine.parse_library([('sensors.csv', _lib_csv([('S-1', 'Датчик', '')]))])
        engine.apply_library_diff(parsed, ['S-1'])
        item = models.Item.objects.get(code='S-1')
        self.assertTrue(item.synced)
        self.assertFalse(item.locked)

    def test_library_changed_marks_synced_clears_stale_lock(self):
        # заведено руками и залочено (наследие волны 17), затем совпало с библиотекой →
        # синк метит synced И снимает стухший замок (инвариант synced ⟹ not locked)
        models.Item.objects.create(code='S-1', description='старое',
                                   category=engine.ensure_category('sensors'), locked=True)
        parsed = engine.parse_library([('sensors.csv', _lib_csv([('S-1', 'новое', '-40-85°C')]))])
        engine.apply_library_diff(parsed, ['S-1'])
        item = models.Item.objects.get(code='S-1')
        self.assertTrue(item.synced)
        self.assertFalse(item.locked)             # стухший замок снят
        self.assertEqual(item.description, 'новое')

    def test_library_mark_clears_stale_lock(self):
        # содержимое совпадает, но изделие залочено со времён волны 17 → mark снимает
        # замок вместе с пометкой synced (инвариант synced ⟹ not locked)
        models.Item.objects.create(code='S-1', description='датчик',
                                   category=engine.ensure_category('sensors'), locked=True)
        parsed = engine.parse_library([('sensors.csv', _lib_csv([('S-1', 'датчик', '')]))])
        summary = engine.apply_library_diff(parsed, ['S-1'])
        self.assertEqual(summary['marked'], 1)
        item = models.Item.objects.get(code='S-1')
        self.assertTrue(item.synced)
        self.assertFalse(item.locked)

    def test_library_deletes_gone_locked(self):
        # ушедшее из библиотеки изделие — зафиксировано; синк расфиксирует и удалит (гейт не мешает)
        gone = models.Item.objects.create(code='S-OLD', description='ушло',
                                          category=engine.ensure_category('sensors'),
                                          locked=True)
        parsed = engine.parse_library([('sensors.csv', _lib_csv([('S-1', 'к', '')]))])
        summary = engine.apply_library_diff(parsed, ['S-OLD'])
        self.assertEqual(summary['deleted'], 1)
        self.assertFalse(models.Item.objects.filter(pk=gone.pk).exists())

    def test_status_in_item_serialization(self):
        i = self.make_item('R')
        engine.lock_item(i)
        i.refresh_from_db()
        self.assertTrue(views._item_row(i)['locked'])
        self.assertTrue(views._item_detail_payload(i)['locked'])

    def test_component_status_in_bom_and_demand(self):
        dev = self.make_item('DEV', manufactured=True)
        comp = self.make_item('R')                # покупной лист
        engine.lock_item(comp)
        engine.add_bom_line(dev, comp, D(2))
        # BOM в форме изделия несёт статус компонента
        bom = views._item_detail_payload(dev)['bom']
        self.assertTrue(bom[0]['component_locked'])
        # Потребность проекта: свод по листьям + дерево несут статус компонента
        engine.add_project_demand(self.prj, dev, D(1))
        deficit = engine.project_deficit(self.prj)
        leaf = next(c for c in deficit['components'] if c['component_id'] == comp.id)
        self.assertTrue(leaf['component_locked'])
        tree_leaf = next(n for n in deficit['demands'][0]['tree'] if n['component_id'] == comp.id)
        self.assertTrue(tree_leaf['component_locked'])

    def test_http_post_unpost_endpoints(self):
        get_user_model().objects.filter(username='t').update(
            is_staff=True, is_superuser=True)
        c = Client()
        c.force_login(self.user)
        i = self.make_item('R')
        r = c.post(f'/api/items/{i.id}/lock/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['locked'])
        i.refresh_from_db()
        self.assertTrue(i.locked)
        r = c.post(f'/api/items/{i.id}/unlock/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['locked'])


class ItemAxesTests(EngineTestBase):
    """Ф3a (волна 19): три оси native/synced/locked — инвариант + матрица правки."""

    def test_synced_implies_not_native_constraint(self):
        # CheckConstraint: библиотечное (`synced`) не может быть нашим (`native`).
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                models.Item.objects.create(
                    code='BAD', description='x', category=_cat(),
                    synced=True, native=True)

    def test_synced_implies_not_locked_constraint(self):
        # CheckConstraint: библиотечное (`synced`) не запирается (`locked`) — две оси
        # защиты взаимоисключающи.
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                models.Item.objects.create(
                    code='BAD2', description='x', category=_cat(),
                    synced=True, locked=True)

    def test_synced_item_edits_price_only(self):
        # Библиотечное расфиксированное: правится ТОЛЬКО оценочная стоимость.
        i = self.make_item('R')
        i.synced = True; i.save()
        engine.update_item(i, {'estimated_cost': D('1.50')})   # цена — можно
        i.refresh_from_db()
        self.assertEqual(i.estimated_cost, D('1.50'))
        with self.assertRaises(ValidationError):               # прочее — нельзя
            engine.update_item(i, {'description': 'ручная правка'})

    def test_manual_item_edits_all(self):
        # Ручное (synced=False) расфиксированное: правится всё.
        i = self.make_item('R')
        engine.update_item(i, {'description': 'новое имя', 'estimated_cost': D('2')})
        i.refresh_from_db()
        self.assertEqual(i.description, 'новое имя')


class RollupCostTests(TestCase):
    """Волна 15 Ф4: рекурсивный роллап оценочной стоимости по BOM."""

    def _item(self, did, native=False, cost=None):
        return models.Item.objects.create(
            code=did, description=did, category=_cat(),
            native=native, estimated_cost=(D(cost) if cost is not None else None))

    def _bom(self, parent, component, qty):
        models.BomLine.objects.create(parent=parent, component=component, qty=D(qty))

    def test_recursive_rollup_writes_all_produced(self):
        l1 = self._item('L1', cost=10)
        l2 = self._item('L2', cost=5)
        board = self._item('BOARD', native=True)
        dev = self._item('DEV', native=True)
        self._bom(board, l1, 2)         # 2×10
        self._bom(board, l2, 3)         # 3×5 → плата 35
        self._bom(dev, board, 1)        # 1×35
        self._bom(dev, l1, 1)           # 1×10 → прибор 45
        res = engine.rollup_estimated_cost(dev)
        self.assertEqual(res['estimated_cost'], D(45))
        board.refresh_from_db(); dev.refresh_from_db()
        self.assertEqual(board.estimated_cost, D(35))   # промежуточный узел тоже переоценён
        self.assertEqual(dev.estimated_cost, D(45))
        self.assertEqual(set(res['updated']), {'BOARD', 'DEV'})
        self.assertEqual(res['incomplete'], [])

    def test_incomplete_flags_unknown_leaf(self):
        leaf = self._item('L-NOCOST')                   # покупной без цены
        dev = self._item('DEV', native=True)
        self._bom(dev, leaf, 2)
        res = engine.rollup_estimated_cost(dev)
        self.assertEqual(res['estimated_cost'], D(0))   # неизвестное считаем 0
        self.assertIn('L-NOCOST', res['incomplete'])

    def test_produced_without_bom_is_incomplete(self):
        dev = self._item('DEV', native=True)
        res = engine.rollup_estimated_cost(dev)
        self.assertIn('DEV', res['incomplete'])
        self.assertEqual(res['estimated_cost'], D(0))

    def test_non_produced_rejected(self):
        leaf = self._item('L', cost=10)
        with self.assertRaises(ValidationError):
            engine.rollup_estimated_cost(leaf)

    def test_cycle_guarded(self):
        a = self._item('A', native=True)
        b = self._item('B', native=True)
        self._bom(a, b, 1)
        models.BomLine.objects.create(parent=b, component=a, qty=D(1))  # цикл в обход guard'а
        with self.assertRaises(ValidationError):
            engine.rollup_estimated_cost(a)


class LibrarySyncHttpTests(TestCase):
    """Волна 15 Ф6: HTTP-путь синка — диф (без записи) → применение → пересчёт цены."""

    def setUp(self):
        get_user_model().objects.create(username='admin', is_superuser=True)
        self.c = Client()
        self.c.force_login(get_user_model().objects.get(is_superuser=True))

    def _upload(self, name, items):
        return SimpleUploadedFile(name, _lib_csv(items), content_type='text/csv')

    def test_diff_then_apply(self):
        models.Item.objects.create(code='CAP-OLD', description='старьё',
                                   category=engine.ensure_category('capacitors'))
        up = self._upload('capacitors.csv', [('CAP-1', 'Конденсатор', '-55-125°C')])
        r = self.c.post('/api/library/diff/', {'files': up})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['categories'], ['capacitors'])
        by = {row['code']: row for row in body['rows']}
        self.assertEqual(by['CAP-1']['status'], 'new')
        self.assertEqual(by['CAP-OLD']['status'], 'gone')
        # применяем: заводим новый, старый удаляем
        up2 = self._upload('capacitors.csv', [('CAP-1', 'Конденсатор', '-55-125°C')])
        a = self.c.post('/api/library/apply/',
                        {'files': up2, 'confirmed': json.dumps(['CAP-1', 'CAP-OLD'])})
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.json(), {'created': 1, 'updated': 0, 'marked': 0, 'deleted': 1})
        self.assertTrue(models.Item.objects.filter(code='CAP-1').exists())
        self.assertFalse(models.Item.objects.filter(code='CAP-OLD').exists())

    def test_recalc_cost_endpoint(self):
        cat = _cat()
        leaf = models.Item.objects.create(code='L', description='L', category=cat,
                                          estimated_cost=D(7))
        dev = models.Item.objects.create(code='D', description='D', category=cat,
                                         native=True)
        models.BomLine.objects.create(parent=dev, component=leaf, qty=D(3))
        r = self.c.post(f'/api/items/{dev.id}/recalc-cost/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(float(body['estimated_cost']), 21.0)
        self.assertEqual(body['rollup']['updated'], ['D'])
        dev.refresh_from_db()
        self.assertEqual(dev.estimated_cost, D(21))

    def test_recalc_cost_rejects_non_produced(self):
        item = models.Item.objects.create(code='P', description='P',
                                          category=_cat(), estimated_cost=D(5))
        r = self.c.post(f'/api/items/{item.id}/recalc-cost/')
        self.assertEqual(r.status_code, 400)


class LotOriginProjectionTests(EngineTestBase):
    """Волна 19, Ф12c: глиф партии (§7a) = форма по origin + цвет по остатку, поэтому
    `origin` обязан быть В КАЖДОЙ проекции, где строка = партия. Раньше вид рождения
    знали только форма изделия и внутренний склад — списки склада/ордеров молчали."""

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')
        self.lot = self.receipt_lot(self.item, self.prj, 10)   # origin = поставка

    def test_location_stock_carries_origin(self):
        rows = engine.location_stock(self.main)
        self.assertEqual(rows[0]['origin'], models.StockDocument.Kind.RECEIPT)

    def test_project_closure_residuals_carry_origin(self):
        row = engine.project_closure(self.prj)['residuals'][0]
        self.assertEqual(row['origin'], models.StockDocument.Kind.RECEIPT)

    def test_order_lines_carry_origin_of_source_lot(self):
        wo = engine.create_writeoff(self.prj, self.user, 'СП-1')
        engine.add_writeoff_line(wo, self.lot, D(2))
        self.assertEqual(engine.writeoff_form(wo)['lines'][0]['origin'],
                         models.StockDocument.Kind.RECEIPT)
        tr = engine.create_transfer(self.prj, self.user, 'НАК-1')
        engine.add_transfer_line(tr, self.lot, D(1))
        self.assertEqual(engine.transfer_form(tr)['lines'][0]['origin'],
                         models.StockDocument.Kind.RECEIPT)

    def test_purchase_rows_carry_item_axes(self):
        """Строка заказа несёт оси изделия — глиф строки один (форма = изделие,
        цвет = закрытость), как в форме закупки-плана."""
        purchase = engine.create_purchase(self.prj, self.user)
        engine.add_purchase_line(purchase, self.item, D(5))
        row = engine.purchase_form(purchase)['rows'][0]
        self.assertEqual(
            (row['item_native'], row['item_synced'], row['item_locked']),
            (self.item.native, self.item.synced, self.item.locked))


class DraftDoesNotMoveStockTests(EngineTestBase):
    """Волна 19, Ф15: **замок гейтит склад** — черновик ничего не двигает.

    Правило одно на семь видов ордера: пока `locked=False`, документ существует и
    правится, но его партии не лежат на складе, его строки не расходуют чужие, а
    бюджет проекта его не видит. Фиксация материализует, расфиксация снимает.
    Единственная точка врезки — `rebuild_movements`; всё остальное (остатки, дефицит,
    карта складов, деньги) читает движения и подчиняется автоматически.
    """

    def setUp(self):
        super().setUp()
        self.item = self.make_item('R100')

    # ── рождение партии: поставка / инвентаризация ──
    def test_draft_receipt_lot_is_not_on_stock(self):
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        lot = engine.add_receipt_lot(r, self.item, D(10), unit_cost=D(100))
        self.assertTrue(models.Lot.objects.filter(pk=lot.pk).exists())  # партия есть
        self.assertEqual(lot.movements.count(), 0)                      # склада нет
        self.assertEqual(engine.item_available(self.item, self.prj), D(0))

    def test_lock_materializes_unlock_takes_back(self):
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        lot = engine.add_receipt_lot(r, self.item, D(10))
        engine.lock_receipt(r)
        self.assertEqual(engine.item_available(self.item, self.prj), D(10))
        engine.unlock_receipt(r)
        self.assertEqual(engine.item_available(self.item, self.prj), D(0))
        self.assertEqual(lot.movements.count(), 0)

    def test_draft_inventory_lot_is_not_on_stock(self):
        inv = engine.create_inventory(self.prj, self.user, 'ИНВ-1')
        lot = engine.add_inventory_lot(inv, self.item, D(5))
        self.assertEqual(engine.lot_live_qty(lot), D(0))
        engine.lock_inventory(inv)
        self.assertEqual(engine.lot_live_qty(lot), D(5))

    # ── расход существующей партии: все знаковые виды ──
    def test_draft_consumers_do_not_touch_source(self):
        """Пять расходных видов в черновике не двигают источник; фиксация двигает."""
        lot = self.receipt_lot(self.item, self.prj, 100)
        other = models.Project.objects.create(
            code='P2', description='Проект 2', kind=models.Project.Kind.EXTERNAL)
        dev = self.make_item('DEV', manufactured=True)

        k = models.Kitting.objects.create(project=self.prj, target_item=dev,
                                          user=self.user, qty=D(1))
        engine.add_kitting_line(k, self.item, lot, D(2))
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.add_transfer_line(t, lot, D(3))
        w = engine.create_writeoff(self.prj, self.user, 'СП-1')
        engine.add_writeoff_line(w, lot, D(4))
        req = engine.create_requisition(other, self.user, 'ТР-1')
        engine.add_requisition_line(req, lot, D(5))
        rel = engine.create_relocation(self.prj, self.user, 'ПЕР-1')
        engine.add_relocation_line(rel, lot, D(6), self.main,
                                   models.Location.objects.create(code='105',
                                                                  description='Пайка'))
        # все пять — черновики: остаток нетронут, движение ровно одно (рождение)
        self.assertEqual(engine.lot_live_qty(lot), D(100))
        self.assertEqual(lot.movements.count(), 1)

        engine.lock_kitting(k); engine.lock_transfer(t); engine.lock_writeoff(w)
        engine.lock_requisition(req); engine.lock_relocation(rel)
        # 100 − 2 − 3 − 4 − 5 = 86 (перемещение тотал не меняет: −6/+6)
        self.assertEqual(engine.lot_live_qty(lot), D(86))

    def test_issue_from_draft_receipt_goes_negative(self):
        """Решение Ивана: расход непринятой партии **пускаем в минус** — не клампим,
        недостача информативнее (канон мутабельной ДНК)."""
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        lot = engine.add_receipt_lot(r, self.item, D(10))
        t = engine.create_transfer(self.prj, self.user, 'Н-1')
        engine.add_transfer_line(t, lot, D(4))
        engine.lock_transfer(t)                      # накладная проведена, УПД — нет
        self.assertEqual(engine.lot_live_qty(lot), D(-4))

    # ── производные проекции подчиняются автоматически ──
    def test_draft_receipt_does_not_cover_deficit(self):
        dev = self.make_item('DEV', manufactured=True)
        models.BomLine.objects.create(parent=dev, component=self.item, qty=D(1))
        models.ProjectDemand.objects.create(project=self.prj, target_item=dev, qty=D(10))
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        engine.add_receipt_lot(r, self.item, D(10))
        row = engine.project_deficit(self.prj)['components'][0]
        self.assertEqual(row['status'], 'to_order')          # черновик не покрывает
        engine.lock_receipt(r)
        row = engine.project_deficit(self.prj)['components'][0]
        self.assertEqual(row['status'], 'available')         # сверен → покрыл

    def test_draft_receipt_does_not_spend_budget(self):
        """Деньги — единственное чтение мимо движений, поэтому гейт продублирован в
        `_project_spent`: черновой УПД не двигает бюджет проекта (Ф15)."""
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        engine.add_receipt_lot(r, self.item, D(3), unit_cost=D(800))
        self.assertEqual(engine.project_budget(self.prj)['spent'], D(0))
        engine.lock_receipt(r)
        self.assertEqual(engine.project_budget(self.prj)['spent'], D(2400))

    def test_closure_panel_shows_draft_closing_documents(self):
        """Мост панели кладёт остаток в ЧЕРНОВОЙ документ — панель это показывает и
        называет причиной отказа, иначе кнопка выглядела бы несработавшей."""
        lot = self.receipt_lot(self.item, self.prj, 10)
        w = engine.writeoff_lot(self.prj, lot, D(10), self.user)
        panel = engine.project_closure(self.prj)
        self.assertFalse(panel['can_close'])
        self.assertEqual(len(panel['closing_drafts']), 1)
        self.assertEqual(panel['closing_drafts'][0]['document_id'], w.id)
        self.assertEqual(panel['closing_drafts'][0]['qty'], D(10))
        self.assertIn('черновик', panel['blocker'].lower())
        engine.lock_writeoff(w)
        panel = engine.project_closure(self.prj)
        self.assertEqual(panel['closing_drafts'], [])
        self.assertTrue(panel['can_close'])

    def test_item_screen_keeps_draft_lot_but_marks_it(self):
        """Таб «Склад» изделия показывает партии НЕЗАВИСИМО от движений — так виден
        входящий поток («10 едет, 0 принято»). Значит проекция обязана отдать замок
        origin-документа: иначе вью не отличит непринятую партию от израсходованной
        (обе с остатком 0) и подпишет её «исчерпана»."""
        r = models.Receipt.objects.create(
            number='У-1', date='2026-05-01', contractor=self.supplier,
            project=self.prj, user=self.user)
        engine.add_receipt_lot(r, self.item, D(10))
        row = views._item_detail_payload(self.item)['lots'][0]
        self.assertEqual(row['qty_born'], D(10))     # рождено — видно
        self.assertEqual(row['live_qty'], D(0))      # на складе — нет
        self.assertFalse(row['origin_locked'])       # и вью знает, почему
        engine.lock_receipt(r)
        row = views._item_detail_payload(self.item)['lots'][0]
        self.assertEqual(row['live_qty'], D(10))
        self.assertTrue(row['origin_locked'])

    def test_bridge_reuses_only_draft_document(self):
        """Мост переиспользует лишь расфиксированный акт — зафиксированный правке не
        подлежит, поэтому для следующего остатка заводится новый."""
        a = self.receipt_lot(self.item, self.prj, 4)
        b = self.receipt_lot(self.make_item('R200'), self.prj, 6)
        w1 = engine.writeoff_lot(self.prj, a, D(4), self.user)
        w2 = engine.writeoff_lot(self.prj, b, D(6), self.user)
        self.assertEqual(w1.id, w2.id)                    # черновик переиспользован
        engine.lock_writeoff(w1)
        c = self.receipt_lot(self.make_item('R300'), self.prj, 2)
        w3 = engine.writeoff_lot(self.prj, c, D(2), self.user)
        self.assertNotEqual(w3.id, w1.id)                 # под замком — новый акт
