# Волна 7 — планирование закупок (командный свод + записываемый Procurement + order.xlsx)

Чеклист седьмой волны. Цель — поднять **верхний уровень закупок**: сквозной
**командный свод** по оси Item через все проекты (сколько всего надо купить, ничего
не забыть) → собрать из него записываемый **план закупки** (`Procurement` /
`ProcurementLine`) → отдать поставщику **`order.xlsx`**. Это north-star линзы —
снимает экспертную боль «составить заказ по всем проектам разом и держать остатки в
голове» (см. [[order-assistant-lens]]). Продолжает паттерн волн 2–6 (записываемый
документ + движок = единственный источник правил + витрина-проекция). Значимые
решения — в [JOURNAL.md](JOURNAL.md) (запись 2026-07-02, «Волна 7»).

**Цель волны 7:** в командном своде (новый режим ⛁) видеть по каждому Item **суммарный
дефицит по всем активным проектам** (`Σ` проектных дефицитов, без перенеттинга) →
чек-боксом «в закупку» набрать позиции в записываемый `Procurement` (кокпит с
автосейвом кол-ва) → **экспортнуть `order.xlsx`** для контрагента. `Procurement` в В7 —
**самостоятельный план** (без проекта, «маркер командной высоты»); нарезка обратно на
проектные `Purchase` (pegging) — волна 8.

## Объём

**Входит:** движок командного свода (`command_deficit`) + записываемый `Procurement`
(`procurement_cockpit` + create/`add|update|remove` строк + `send`/`cancel`) + мост
«свод → закупка» (`add_to_procurement`, аналог `add_to_project_order`) + экспорт
`order.xlsx` (openpyxl на бэке) → DRF-эндпоинты → фронт: девятый режим activity-bar
(⛁ «Закупки-план») со сводом + кокпит `ProcurementView` + кнопка выгрузки → юнит-тесты
+ HTTP-smoke.

**НЕ входит (следующие волны):**
- **Pegging / нарезка `Procurement → Purchase`** (обратный срез общего плана на
  проектные заказы; ломка 1:1-заглушки `_solo_procurement` → общий `Procurement` →
  веер `Purchase`) — **волна 8**. В7 не трогает связь заказа с закупкой-родителем.
- Инвентаризация (`Inventory`), два числа бюджета + себестоимость/экономия,
  логин-экран, UI вложений (`Attachment`).

## Решения (проектные — зафиксировать в JOURNAL 2026-07-02, «Волна 7»)

- **Схему БД не трогаем.** `Procurement` / `ProcurementLine` уже в модели (заморожена);
  сейчас `ProcurementLine` в движке не используется, а `Procurement` — вырожденная
  1:1-заглушка под проектный заказ ([`_solo_procurement`](../backend/plume/engine.py)).
  В7 добавляет только записываемую надстройку над существующими сущностями. Диаграммы
  README **не меняются**.
- **Командный свод = консолидация-проекция, не таблица** (сквозной принцип «слить
  запросом можно всегда, разорвать слитое — нет»). `command_deficit` = `Σ` по Item
  **проектных** дефицитов (переиспользует `_coverage`/`item_available`/`item_on_order`
  из `project_deficit`), а НЕ перенеттинг остатков между проектами (чужие ФЛС/склады не
  смешиваем). Итог по Item = сколько всего **не покрыто** (красный `▲` член) по активным
  внешним проектам. Read-only витрина.
- **`Procurement` в В7 — самостоятельный план** без проекта (маркер командной высоты).
  Записывается как отдельный документ; **не** привязывается к проектным `Purchase` в
  этой волне (это pegging, В8). `ProcurementLine` = `(item, qty)`, `(procurement, item)`
  трактуем как одну строку (инкремент при повторном добавлении — как мост
  `add_to_project_order`). Замок = `status` (`draft → sent`/`cancelled`), зеркалит
  `Purchase.send`/`cancel`: строки правятся только в черновике.
- **Мост «свод → закупка»** (`add_to_procurement`, payoff как «дефицит → заказ»): из
  строки свода один клик кладёт Item в последний draft-`Procurement` (или создаёт) с
  предложенным кол-вом (суммарный дефицит); дальше руками дотачивается в кокпите.
- **`order.xlsx` генерит бэк** (openpyxl — новая зависимость; на reg.ru shared ставится
  в venv, тяжёлых рантаймов не требует — синхронно в запросе, файл небольшой). Endpoint
  отдаёт `application/vnd.openxmlformats-...` с `Content-Disposition: attachment`. Формат
  — колонки как исторический `order.xlsx` (артикул / наименование / кол-во / ед.);
  структуру согласовать на обкатке. Экспорт — только по `Procurement` (план), не по
  проектному заказу.

## Этапы

### Этап 1 — Движок планирования (чистый Python + тесты) ← ядро волны
- [x] `command_deficit()` — свод по оси Item через активные внешние проекты:
  `{item, need, have, on_order, to_order, status, is_manufactured, by_project[]}`.
  На проект потребность агрегируется по Item (Σ через потребности BOM), покрытие —
  один раз (`_coverage`/`item_available`/`item_on_order`); **НЕ перенеттит** между
  проектами. Худшее наверх.
- [x] `procurement_cockpit(procurement)` — шапка + строки (`item`, `qty`) + `editable`
  (только draft) + `total_qty`. Чистая проекция.
- [x] `create_procurement(user, ...)` + `add|update|remove_procurement_line`
  (guard draft, `qty>0`, `(procurement, item)` одна строка) + `send`/`unsend`/`cancel`/
  `restore_procurement` (мягкий замок, зеркалит `Purchase`) + `update_procurement` (шапка).
- [x] `add_to_procurement(item, qty, user)` — мост «свод → закупка» (find-or-create
  draft-**плана**, инкремент строки). `_plan_procurements()` (`purchases__isnull=True`)
  отделяет планы В7 от 1:1-заглушек проектных заказов (В4).
- [x] `procurement_xlsx(procurement) -> bytes` — генерация `order.xlsx` (openpyxl,
  артикул/наименование/кол-во/ед.).
- [x] Юнит-тесты (13): свод = `Σ` проектных (два проекта на Item → сумма; закрытый/
  внутренний не в счёт; внутрипроектная агрегация потребностей; сортировка «красное
  наверх»; отсутствие перенеттинга); кокпит editable только в draft; строки CRUD +
  guard sent; мост инкрементит и игнорирует заглушку; send/unsend/cancel/restore;
  правка шапки; xlsx — байты с ожидаемыми ячейками.
- _Готово, когда:_ тесты зелёные; свод по Item сходится с движком. ✓

### Этап 2 — Записываемый DRF
- [x] `GET /api/command-deficit/` — командный свод (витрина).
- [x] `GET/POST /api/procurements/` (список = только планы), `GET/PATCH /api/procurements/<pk>/`,
  `POST .../lines/`, `PATCH/DELETE /api/procurement-lines/<pk>/`,
  `POST .../send|unsend|cancel|restore/`.
- [x] `POST /api/command-deficit/add-to-procurement/` — мост.
- [x] `GET /api/procurements/<pk>/order.xlsx` — выгрузка (`HttpResponse`,
  xlsx content-type + `attachment`).
- [x] HTTP-smoke (класс `ProcurementHttpTests`, 3 теста): свод 200 + мост 201,
  create/line 201, дубль 400, send 200 + замок 400, xlsx 200 (zip-сигнатура `PK`).

### Этап 3 — Фронт: режим «Закупки-план» (свод + кокпит + выгрузка)
- [x] Девятый режим activity-bar ⛁ «Закупки-план»: пункт «Командный свод» +
  «＋ Новая закупка» + список планов.
- [x] `CommandDeficitView` — таблица Item × разбор ✓/●/▲, раскрытие по проектам,
  «＋ в закупку» → мост → кокпит.
- [x] `ProcurementView` — кокпит плана: строки `(item, qty)` автосейвом/удалением,
  замок `draft→sent`, read-only под замком, правка шапки, кнопка «Скачать order.xlsx».
- [x] API-клиент: типы (`CommandDeficit`, `ProcurementRow`, `ProcurementCockpit`) +
  мутирующие хелперы + `orderXlsxUrl` (скачивание `<a download>`); статус-бар «волна 7».
- _Готово, когда:_ из свода набираешь план → правишь кол-ва → скачиваешь `order.xlsx`. ✓

## Проверено

108 юнит-тестов зелёные (92 волн 1–6 + 13 движка + 3 HTTP-smoke волны 7);
`tsc -b && vite build` чист; `makemigrations --check` — **схема не менялась**;
`openpyxl==3.1.5` добавлен в `requirements.txt` (установлен в venv). HTTP-smoke на
реальном MySQL 8.0.25 (`ProcurementHttpTests`): свод 200 / мост 201 → кокпит total=40;
create 201 / строка 201 / дубль item 400 / send 200 status=sent / строка под замком
400 / `order.xlsx` 200 (zip-сигнатура). Живой smoke на runserver: план create → строка
(total 7) → выгрузка `order.xlsx` = Microsoft Excel 2007+, список планов исключает
1:1-заглушки заказов.

## Отложено в В8 (pegging)

Нарезка общего `Procurement` → веер проектных `Purchase` + ломка 1:1-заглушки
`_solo_procurement` (общий план, нарезаемый чек-боксом по проектам/контрагенту). Пока
план В7 живёт отдельно от проектных заказов (`_plan_procurements` = `purchases__isnull`).

## Локальный запуск (памятка)

```
cd backend && docker compose up -d           # MySQL 8.0.25 на :3307
cd backend && .venv/bin/python manage.py runserver 8000
cd frontend && npm run dev                    # http://localhost:5173
```

Режим «Закупки-план» (⛁) в activity-bar; командный свод — сверху, кокпит плана —
в рабочей области, кнопка выгрузки `order.xlsx` — в шапке кокпита.
