"""Демо-данные волны 1: один проект, на котором движок даёт непустой дефицит и
карту остатков. Идемпотентна — каждый запуск пересоздаёт демо начисто.

Сценарий (проект ПРБ-1, потребность ИЗДЕЛИЕ-А ×10):
- КОРПУС-1 (покупной): на складе 12 → строка ✓ (10 покрыто, 2 излишек).
- ВИНТ-М3 (материал): нужно 40, заказано 25 (sent), склада нет → ●25 ▲15.
- ПЛАТА-1 (производимая): сделано 3 (закрытая комплектация), делается 4 (wip) →
  ✓3 ●4 ▲3.
Плюс КОРПУС-1 лежит и на «Собственном складе» (5) — для карты остатков.
"""
import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from plume import models
from plume.engine import rebuild_all

D = datetime.date


class Command(BaseCommand):
    help = 'Создать/пересоздать демо-данные волны 1.'

    @transaction.atomic
    def handle(self, *args, **opts):
        self._wipe()
        user = self._superuser()
        main, white, grey = self._infrastructure()
        supplier = models.Supplier.objects.create(name='ООО «Поставщик»', inn='7700000000')

        # --- справочник изделий + BOM ---------------------------------- #
        device = models.Item.objects.create(
            code='ИЗДЕЛИЕ-А', name='Прибор А', kind=models.Item.Kind.DEVICE,
            uom='шт', is_manufactured=True)
        board = models.Item.objects.create(
            code='ПЛАТА-1', name='Плата управления', kind=models.Item.Kind.COMPONENT,
            uom='шт', is_manufactured=True, estimated_cost=1500)
        case = models.Item.objects.create(
            code='КОРПУС-1', name='Корпус алюминиевый', kind=models.Item.Kind.COMPONENT,
            uom='шт', estimated_cost=800)
        screw = models.Item.objects.create(
            code='ВИНТ-М3', name='Винт М3×8', kind=models.Item.Kind.MATERIAL,
            uom='шт', estimated_cost=2)
        res = models.Item.objects.create(
            code='РЕЗ-10К', name='Резистор 10 кОм', kind=models.Item.Kind.COMPONENT,
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
            number='УПД-1', date=D(2026, 5, 20), supplier=supplier, project=prj,
            user=user, approved=True)
        models.Lot.objects.create(item=case, project=prj, receipt=receipt, qty=12,
                                  unit_cost=800, received_name='Корпус Al')

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
            number='УПД-2', date=D(2026, 5, 21), supplier=supplier, project=prj, user=user)
        res_lot = models.Lot.objects.create(item=res, project=prj, receipt=r_res,
                                            qty=100, unit_cost=1, received_name='Резистор')

        closed_k = models.Kitting.objects.create(
            project=prj, target_item=board, user=user, qty=3, date=D(2026, 5, 25),
            status=models.Kitting.Status.CLOSED)
        models.StockLine.objects.create(kitting=closed_k, lot=res_lot,
                                        location=main, qty=-6, date=D(2026, 5, 25))
        models.Lot.objects.create(item=board, project=prj, kitting=closed_k, qty=3,
                                  unit_cost=1506, serial_number='ПЛ-001..003')

        wip_k = models.Kitting.objects.create(
            project=prj, target_item=board, user=user, qty=4, date=D(2026, 6, 1),
            status=models.Kitting.Status.WIP)
        models.StockLine.objects.create(kitting=wip_k, lot=res_lot,
                                        location=main, qty=-4, date=D(2026, 6, 2))

        # --- КОРПУС-1 на «Собственном складе» (5) — для карты ---------- #
        inv = models.Inventory.objects.create(
            project=white, user=user, number='ИНВ-1', date=D(2026, 6, 3),
            note='Остаток с прошлого НИР')
        models.Lot.objects.create(item=case, project=white, inventory=inv, qty=5,
                                  unit_cost=800, received_name='Корпус Al (остаток)')

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
                  models.Requisition, models.Inventory, models.Purchase,
                  models.Procurement, models.Item, models.Supplier,
                  models.Project, models.Location):
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
        main = models.Location.objects.create(code='MAIN', name='Основной склад')
        white = models.Project.objects.create(
            code='WHITE', name='Собственный склад',
            kind=models.Project.Kind.INTERNAL_STOCK, status=models.Project.Status.ACTIVE)
        grey = models.Project.objects.create(
            code='GREY', name='Свободные неучтённые',
            kind=models.Project.Kind.INTERNAL_WRITEOFF, status=models.Project.Status.ACTIVE)
        return main, white, grey
