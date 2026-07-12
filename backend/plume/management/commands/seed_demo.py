"""Демо-данные волны 1: один проект, на котором движок даёт непустой дефицит и
карту остатков. Идемпотентна — каждый запуск пересоздаёт демо начисто.

Сценарий (проект ПРБ-1, потребность ИЗДЕЛИЕ-А ×10):
- КОРПУС-1 (покупной): на складе 12 → строка ✓ (10 покрыто, 2 излишек).
- ВИНТ-М3 (материал): нужно 40, заказано 25 (sent), склада нет → ●25 ▲15.
- ПЛАТА-1 (производимая): сделано 3 (закрытая комплектация), делается 4 (wip) →
  ✓3 ●4 ▲3.
Плюс КОРПУС-1 лежит и на «Собственном складе» (5) — для карты остатков.

Мультисклад (волна 13, Ф2e): два места хранения — «103» (основной) и «105» (пайка);
перемещение ПЕР-1 двигает 4 КОРПУС-1 с 103 на 105 (тотал лота 12 сохранён: 8@103 + 4@105).
"""
import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from plume import engine, models
from plume.engine import rebuild_all

D = datetime.date


class Command(BaseCommand):
    help = 'Создать/пересоздать демо-данные волны 1.'

    @transaction.atomic
    def handle(self, *args, **opts):
        self._wipe()
        user = self._superuser()
        main, sold, white, grey = self._infrastructure()
        supplier = models.Counterparty.objects.create(
            name='ООО «Поставщик»', inn='7700000000', is_supplier=True)
        models.Counterparty.objects.create(
            name='АО «Заказчик»', inn='7811111111',
            is_supplier=False, is_customer=True)

        # --- категории: 5 канонических из библиотеки + демо-классы под демо-BOM --- #
        # 5 библиотечных всплывают через ensure_category (канон label/icon); демо-классы
        # (прибор/плата/механика/крепёж/резистор) — синтетические, только для дебага.
        for code in engine.LIBRARY_CATEGORIES:
            engine.ensure_category(code)
        cat_device = models.Category.objects.create(code='device', label='Приборы', icon='vm')
        cat_board = models.Category.objects.create(code='board', label='Платы', icon='circuit-board')
        cat_mech = models.Category.objects.create(code='mechanical', label='Механика', icon='package')
        cat_fastener = models.Category.objects.create(code='fasteners', label='Крепёж', icon='settings-gear')
        cat_res = models.Category.objects.create(code='resistors', label='Резисторы', icon='symbol-constant')

        # --- справочник изделий + BOM ---------------------------------- #
        device = models.Item.objects.create(
            design_item_id='ИЗДЕЛИЕ-А', description='Прибор А', category=cat_device,
            uom='шт', produced=True)
        board = models.Item.objects.create(
            design_item_id='ПЛАТА-1', description='Плата управления', category=cat_board,
            uom='шт', produced=True, estimated_cost=1500)
        case = models.Item.objects.create(
            design_item_id='КОРПУС-1', description='Корпус алюминиевый', category=cat_mech,
            uom='шт', estimated_cost=800)
        screw = models.Item.objects.create(
            design_item_id='ВИНТ-М3', description='Винт М3×8', category=cat_fastener,
            uom='шт', estimated_cost=2)
        res = models.Item.objects.create(
            design_item_id='РЕЗ-10К', description='Резистор 10 кОм', category=cat_res,
            uom='шт', estimated_cost=1)

        models.BomLine.objects.create(parent=device, component=board, qty=1)
        models.BomLine.objects.create(parent=device, component=case, qty=1)
        models.BomLine.objects.create(parent=device, component=screw, qty=4)
        models.BomLine.objects.create(parent=board, component=res, qty=2)

        # --- проект и потребность -------------------------------------- #
        prj = models.Project.objects.create(
            code='ПРБ-1', name='НИР «Прибор А»', kind=models.Project.Kind.EXTERNAL,
            status=models.Project.Status.ACTIVE, budget=200000, started_at=D(2026, 5, 1))
        models.ProjectDemand.objects.create(project=prj, target_item=device, qty=10)

        # --- КОРПУС-1: приход 12 (✓) ----------------------------------- #
        receipt = models.Receipt.objects.create(
            number='УПД-1', date=D(2026, 5, 20), contractor=supplier, project=prj,
            user=user, status=models.DocStatus.POSTED)
        case_lot = models.Lot.objects.create(item=case, project=prj, origin=receipt,
                                             qty=12, unit_cost=800,
                                             lot_name='Корпус Al',
                                             part_number='AL-CASE-100')

        # --- ВИНТ-М3: открытый заказ 25 (●), склада нет ---------------- #
        proc = models.Procurement.objects.create(
            user=user, status=models.Procurement.Status.SENT, date=D(2026, 5, 10))
        models.ProcurementLine.objects.create(procurement=proc, item=screw, qty=25)
        purchase = models.Purchase.objects.create(
            procurement=proc, project=prj, user=user,
            status=models.Purchase.Status.SENT, date=D(2026, 5, 12))
        models.PurchaseLine.objects.create(purchase=purchase, item=screw, qty=25)

        # --- ПЛАТА-1: сделано 3 (закрытая компл.) + делается 4 (wip) --- #
        # источник под пайку резисторов: приход РЕЗ-10К 100
        r_res = models.Receipt.objects.create(
            number='УПД-2', date=D(2026, 5, 21), contractor=supplier, project=prj, user=user)
        res_lot = models.Lot.objects.create(item=res, project=prj, origin=r_res,
                                            qty=100, unit_cost=1, lot_name='Резистор',
                                            part_number='RES-10K-0805')

        closed_k = models.Kitting.objects.create(
            project=prj, target_item=board, user=user, qty=3, date=D(2026, 5, 25),
            status=models.DocStatus.POSTED)
        models.StockLine.objects.create(document=closed_k, lot=res_lot,
                                        location=main, qty=-6, date=D(2026, 5, 25))
        models.Lot.objects.create(item=board, project=prj, origin=closed_k, qty=3,
                                  unit_cost=1506, lot_name='ПЛ-001..003')

        wip_k = models.Kitting.objects.create(
            project=prj, target_item=board, user=user, qty=4, date=D(2026, 6, 1),
            status=models.DocStatus.DRAFT)
        models.StockLine.objects.create(document=wip_k, lot=res_lot,
                                        location=main, qty=-4, date=D(2026, 6, 2))

        # --- КОРПУС-1 на «Собственном складе» (5) — для карты ---------- #
        inv = models.Inventory.objects.create(
            project=white, user=user, number='ИНВ-1', date=D(2026, 6, 3),
            note='Остаток с прошлого НИР')
        models.Lot.objects.create(item=case, project=white, origin=inv, qty=5,
                                  unit_cost=800, lot_name='Корпус Al (остаток)')

        # --- мультисклад: перемещение 4 КОРПУС-1 на место пайки (105) --- #
        # Волна 13, Ф2e: тотал лота (12) сохранён, распределение — 8@103 + 4@105.
        reloc = engine.create_relocation(prj, user, number='ПЕР-1', date=D(2026, 6, 5))
        engine.add_relocation_line(reloc, case_lot, 4, from_location=main,
                                   to_location=sold)
        engine.post_relocation(reloc)

        # --- пересборка проекции склада -------------------------------- #
        rebuild_all()

        self.stdout.write(self.style.SUCCESS(
            'Демо создано. Проект ПРБ-1, потребность ИЗДЕЛИЕ-А ×10. '
            'Admin: admin / admin.'))

    # ------------------------------------------------------------------ #
    def _wipe(self):
        """Снести демо/учётные данные (auth не трогаем). Порядок child→parent."""
        for m in (models.StockMovement, models.StockLine, models.Attachment,
                  models.Lot, models.PurchaseLine, models.ProcurementLine,
                  models.ProjectDemand, models.BomLine,
                  models.Receipt, models.Kitting, models.Transfer, models.Writeoff,
                  models.Requisition, models.Inventory, models.Relocation,
                  models.Purchase,
                  models.Procurement, models.Item, models.Category,
                  models.Counterparty, models.Project, models.Location):
            m.objects.all().delete()

    def _superuser(self):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username='admin', defaults={'is_staff': True, 'is_superuser': True,
                                        'email': 'admin@example.com'})
        if created:
            user.set_password('admin')
            user.save()
        return user

    def _infrastructure(self):
        main = models.Location.objects.create(code='103', name='Основной склад')
        sold = models.Location.objects.create(code='105', name='Место пайки',
                                              kind='workshop')
        white = models.Project.objects.create(
            code='WHITE', name='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK, status=models.Project.Status.ACTIVE)
        grey = models.Project.objects.create(
            code='GREY', name='Свободные неучтённые',
            kind=models.Project.Kind.INTERNAL_WRITEOFF, status=models.Project.Status.ACTIVE)
        return main, sold, white, grey
