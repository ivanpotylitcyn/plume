# Волна 13 — «Ордер»: единый складской документ (разморозка, MTI, фазами)

Чеклист тринадцатой волны — **первая после заморозки схемы**. Цель — свернуть
документы-близнецы, двигающие лоты, к одной сущности **`StockDocument` (UI: «Ордер»)**
по образу `Item`: **один режим «Ордера» (как «Изделия»), один список вперемешку с
фильтром по типу, одна форма — `kind` рулит полями**. Тип = поле одной сущности, а не
отдельная сущность. Это снимает напряжение схемы (шесть раздельных документов, в
которых легко закопаться) и задаёт курс к понятному open-source продукту.

**Полярная звезда:** «Ордер» — второй `Item`. Решения — в [JOURNAL.md](JOURNAL.md)
(записи 2026-07-07 и 2026-07-08).

**Опора:** унифицирующая сущность уже наполовину есть — `StockMovement` — цельная
проекция; волна поднимает эту цельность на слой документов над ней.

## Виды ордера (`kind`) — 7

| kind | Что делает | born-лоты | StockLine |
|---|---|:---:|:---:|
| `receipt` (Приход/УПД) | приём от поставщика | + | — |
| `inventory` (Инвентаризация) | «найденные» лоты | + | — |
| `kitting` (Комплектация) | расход компонентов + рождение прибора | + | − |
| `requisition` (Требование/отпочкование) | рождение лота в проекте-получателе | + | − |
| `transfer` (Передача) | отгрузка заказчику (терминально) | — | − |
| `writeoff` (Списание) | порча/убыль | — | − |
| **`relocation` (Перемещение)** ← НОВЫЙ | лот между локациями (внутри) | — | ± |

`Procurement`/`Purchase` (закупка-план / заказ) — **вне** объединения (лотов не
трогают — планирование/обязательство).

## Две кристальные сущности движения

```
Ордер (StockDocument) ─┬─ born-лоты   Lot.origin → StockDocument     → +RECEIPT (born-direct, без дубля)
                       └─ StockLine   (document, lot, location, qty ±) → движение существующего лота
```

- **Рождение** = НОВЫЙ лот (своя цена/серийник/origin) через `Lot.origin`.
- **Движение** = СУЩЕСТВУЮЩИЙ лот (любой знак, между локациями) через `StockLine`.
  Перемещение = 2 строки (`−q` на источнике, `+q` на приёмнике), зеркалят `StockMovement`.

## Целевая модель (Ф2, MTI)

```
StockDocument (parent)   kind, project, user, date, number, note, status{draft⇄posted}
 ├ ReceiptDoc     supplier NOT NULL, purchase
 ├ KittingDoc     target_item NOT NULL, qty
 ├ InventoryDoc   (note в parent)
 ├ RequisitionDoc —
 ├ TransferDoc    (display_name → на StockLine)
 ├ WriteoffDoc    reason
 └ RelocationDoc  —
StockLine(document, lot, location, qty ±)   ← 4 таблицы строк-расхода + перемещение
Lot.origin  → FK(StockDocument)             ← origin-дуга (4 nullable FK + Check) умирает
Attachment.owner → FK(StockDocument) + Item ← 7-путная дуга схлопывается
```

## Замок и удаление

- **Единый мягкий замок**, `status {draft ⇄ posted}`. posted = edit-freeze (чистая
  форма без инпутов); склад **НЕ гейтится** (замок интерфейсный — поведение остатков
  1:1 с текущим).
- **Канон меняем:** тот же мягкий замок + индикатор «сохранено / редактируется» — на
  **все** формы, включая `Item`/`Project` (раньше §5/§6 фиксации там не ставили).
- **`cancelled` убран.** Отмена = удаление: draft — свободно; posted — сначала
  расфиксировать; потраченные ниже лоты бережёт `PROTECT`. Чинит баг фантомного
  прибора у отменённой комплектации.

## Мультисклад (активация `Location`)

`StockMovement.location` и `Location` были заглушены синглтоном «Основной склад»
(матрица A4). «Перемещение» их оживляет: минимум два физических места (напр. основной
склад «103» и место пайки «105»).
- [x] Движок считает остаток по паре **`(лот, локация)`**, не только по лоту
      (`lot_live_qty(…, location)`, `item_available(…, location)`, `available_lots(…,
      location)` — опциональный фильтр, по умолчанию тотал; `lot_locations` — разбивка;
      `stock_map.by_location` — аддитивно). ✅ 2026-07-09 (Ф2e).
- [x] `Location` редактируемо (админка + сид двух мест 103/105) — MVP-синглтон снят.
      ✅ 2026-07-09 (Ф2e). Справочник-форма в React — «вьюхи потом».

## Переименования полей `Lot` и контрагент

- **`Lot`: два идентификатора вместо `serial_number`/`received_name`** —
  `part_number` (строгий машинный: MPN с datasheet / децимальный номер; для станка
  автомонтажа) и `lot_name` (человеческий: имена из УПД + заводские №). `part_number` ∈
  `Lot`, не `Item` (упаковка/исполнение варьируются от поставки; `Item.code` —
  абстрактный артикул). Детали — JOURNAL 2026-07-08 (продолжение).
  **Миграция (НЕ простой rename):**
  `lot_name ← coalesce(received_name, serial_number)`; `part_number ←` новое пустое;
  `drop serial_number`. (Заводские № уходят в `lot_name`, НЕ в `part_number`.)
- **`Supplier → Counterparty`** — единая сущность контрагента (роль/вид:
  поставщик/заказчик). `Receipt.supplier → contractor` (поставщик); **`Transfer`
  получает структурного контрагента** (заказчик) — сейчас получателя-сущности нет.
  Виды `receipt`/`transfer` **не сливаем** (born-direct vs StockLine — хребет ясности),
  но оба ссылаются на `Counterparty` + направление несёт `kind`. Это закрывает
  отложенную симметрию «Передача = перемещение к внешней точке».

## Фазы

### Ф0 — `StockLine` + знак/локация (безопасно, ортогонально глубине) ✅ 2026-07-09
- [x] `StockLine(document, lot, location, qty ±)` + миграция из
      `KittingLine/TransferLine/WriteoffLine/RequisitionLine`. **Владелец в Ф0 — 4 FK +
      Check (exclusive arc, как `Lot.origin`)**; схлопнётся в один FK на MTI-родитель в
      Ф2. `qty` знаковый (− расход); `component` строки комплектации не храним —
      выводится из `lot.item`. Миграция `0003_stockline_consolidation` (create → copy со
      сменой знака → drop 4 таблиц), реверсивна; передача приземлена на `MAIN`.
- [x] `rebuild_movements` читает `StockLine`; born-лоты остаются на `Lot.origin`.
- [x] Инвариант: остаток по лоту до/после миграции не изменился — тест данных миграции
      (forward+reverse) + движковый `test_stockline_rebuild_invariant_across_docs`.
      Все 166 тестов + smoke `seed_demo` зелёные; проекции кокпитов **байт-в-байт** (фронт
      не тронут). Прогнано и на SQLite, и на **боевом локальном MySQL 8.0.25** (Docker):
      166 тестов + тест данных миграции зелёные; на реальной базе `0003` применилась,
      детектор дрейфа движений = 0 (консолидация точно эквивалентна старым 4 таблицам).

### Ф1 — единый мягкий замок + режим «Ордера» (высокая ценность / низкий риск)

**Ф1a — бэкенд-срез (модель+движок), API байт-в-байт ✅ 2026-07-09**
- [x] Общая шапка **абстрактно**: `StockDoc` (миксин) несёт единый `status` +
      `DocStatus{DRAFT,POSTED}` + `is_posted`; наследуют все 6 складских документов.
      Закрывает свод матрицы **#7 симметрия замка** на уровне модели (#1 авторство
      `user` уже на каждом документе; вынос в MTI-родителя — Ф2).
- [x] Единый `status {draft⇄posted}` на всех ордерах; `Receipt.approved`/
      `Transfer.posted`/`Kitting.{wip/closed/cancelled}` свёрнуты; `cancelled` снят.
      Инв/Треб/Списание получили поле (обвязка post/unpost — Ф1b). Единый guard
      `_require_draft`; skip-фильтр отменённой комплектации убран (умер путь фантома).
- [x] Миграция `0004_unified_doc_status` (реверсивна, проверена forward/reverse на
      боевом MySQL — статусы+остаток инвариантны). 169 тестов зелёные; `seed_demo` ок.
      Компат-шим проекций (`approved`/`posted`/`wip`/`closed`) держит фронт нетронутым.
- **Грабли:** прямое `posted_kitting.delete()` бьёт CHECK `exactly_one_origin` (каскад
      обнуляет `kitting_id` born-лота) → на MySQL это БД-замок «сперва расфиксировать»
      (reopen → delete). См. JOURNAL 2026-07-09 Ф1a.

**Ф1b — фронт-срез + правило удаления (вьюхи потом)**

*Бэкенд-подрез Ф1b — DELETE-эндпойнты + post/unpost/edit-freeze трёх ордеров ✅ 2026-07-09*
- [x] Обвязка post/unpost + edit-freeze для Инвентаризации/Требования/Списания.
      Единый `_require_draft` теперь гейтит правку шапки И строк этих трёх (раньше не
      гейтил — поле `status` завели в Ф1a, обвязки не было). Общие хелперы
      `post_document`/`unpost_document` (пустой-guard + `draft⇄posted`, зеркалят
      `approve_receipt`/`post_transfer`); тонкие обёртки `post_writeoff`/`post_requisition`/
      `post_inventory` (+ unpost). Кокпиты трёх отдают `posted` (аддитивно, под фронт Ф1b).
- [x] DELETE-эндпойнты **всех 6** ордеров + единый friendly-guard `delete_stock_document`:
      draft — свободно; **posted — «сперва расфиксировать»**; `PROTECT` бережёт
      потраченные лоты (born-лот потреблён ниже → дружелюбный отказ, не сырой
      `ProtectedError`). Механика обходит грабли CHECK `exactly_one_origin` (JOURNAL Ф1a):
      born-лоты и их движения сносим **явно** (как `reopen_kitting`), затем документ
      (каскад `StockLine`+вложения), затем `rebuild_movements` источников (снять `−ISSUE`).
      Файлы вложений чистим отдельно (каскад БД их бы осиротил). `DELETE` на 6 detail-вью
      (`_delete_order` → 204/400).
- [x] **Проверка:** 179 тестов (было 169; +8 движковых `Wave13Fase1bTests` +2 HTTP
      `OrderDeleteHttpTests`) зелёные на SQLite **и** боевом MySQL 8.0.25; `makemigrations
      --check` чист (модель не менялась — миграции не нужно); `seed_demo` ок; **живой
      end-to-end** на dev-MySQL (posted-delete заблокирован, unpost+delete вернул остаток
      источника 12→11→12).

*Фронт-подрез Ф1b — вьюхи:*
- [x] Канон: мягкий замок + «сохранено/редактируется» на `Item`/`Project` — **уже стоял**
      с чистового прохода 2026-07-05 (`ItemView` через `FormHeader`+`useFormLock`; внешний
      проект `DeficitView` — свой замок+индикатор; внутренний `ProjectStockPanel` read-only,
      замок не нужен). Верифицировано, доделок нет.
- [x] Фронт: кнопки провести/расфиксировать/удалить у Инв/Треб/Списания (2026-07-09).
      Три вьюхи переведены с чисто-локального замка на **серверный post/unpost** (как
      `Transfer`): `fixed = c.posted`, чип «проведено» + `onUnfix`, кнопка «Провести ·
      зафиксировать»; кокпиты/строки-списки отдают `posted` (доб. в 3 row-сериализатора).
      Глиф замка 🔒/○ в списках трёх. `api.ts`: `post*/unpost*` для трёх + `delete*` для
      всех 6 ордеров.
- [x] **Delete-симметрия (сверх плана):** `onDelete` вынесен в общий `FormHeader`
      (кнопка 🗑, только у черновика — posted перехватывает ветка чипа, зеркалит бэкенд-guard
      «сперва расфиксировать»). Подключён ко **всем 6** ордерам (Receipt/Transfer/Kitting +
      три); `onDeleted` в `App.tsx` перезагружает список и сбрасывает выбор.
      Проверка: `tsc -b && vite build` чист; 179 тестов зелёные на MySQL 8.0.25;
      `makemigrations --check` — без изменений; живой round-trip post→unpost→delete на dev-MySQL.
- [x] Фронт: единый режим «Ордера» (список+фильтр по `kind`) + `<NewOrder kind=...>`
      ✅ 2026-07-09 (**оболочка + диспетчер**, согл. с Иваном). Одна иконка `package`
      вместо шести; один смешанный список `OrderList` (клиентский фид из 6 массивов,
      новейшие сверху, два фильтра — тип+проект; строка = 🔒/○ · № · подпись типа);
      единая форма создания `NewOrder` (селектор типа рулит полями, переиспользует
      6 `New*`). Detail-область **диспетчеризует на существующие 6 вьюх** (замок/удаление
      уже стоят). `tsc -b && vite build` чист; 179 тестов зелёные на MySQL 8.0.25 (бэкенд
      не тронут, `makemigrations --check` — без изменений).
      **Отложено (глубже флагмана):** свод тел кокпитов 6 detail-вьюх в **одну**
      `<OrderForm kind=...>` (общая шапка + kind-переключаемое тело) — отдельным заходом.

### Ф2 — MTI, убить дугу (осознанный слом заморозки) — фазами

**Ф2a — MTI-ядро: родитель `StockDocument` + 6 детей-наследников ✅ 2026-07-09**
- [x] `StockDoc` (абстрактный миксин) → `StockDocument` (**конкретный MTI-родитель**);
      6 складских документов (`Receipt`/`Kitting`/`Inventory`/`Requisition`/`Transfer`/
      `Writeoff`) стали наследниками — их PK = единый `id` родителя (**унификация
      id-пространства**, готовность к схлопыванию дуг в один FK). Дискриминатор `kind`
      (7 значений, `relocation` — на будущее) штампуется в `save()` каждого ребёнка.
- [x] **Lean-глубина (API байт-в-байт):** в родителя подняты только `status`+`kind`;
      специфичные и общие FK-поля (`project`/`user`/`date`/`number`/`supplier`/…) пока
      на детях → обратные аксессоры (`project.writeoffs`, `purchase.receipts`) целы,
      прямые (`receipt.project`) прозрачны через MTI. Ноль правок в engine/views/`api.ts`.
- [x] Миграция `0005_stockdocument_mti` (реверсивна): `CreateModel(StockDocument)` реально
      + превращение детей через `SeparateDatabaseAndState` (СОСТОЯНИЕ декларируем сами,
      ФИЗИКА — raw-SQL под `FK_CHECKS=0`: раздать parent-id, перецепить 14 входящих дуг
      Lot×4/Attachment×6/StockLine×4, PK ребёнка → ptr, снять `status`; констрейнты — по
      интроспекции, не хардкод). `makemigrations --check` чист.
- [x] **Проверка:** 183 теста (было 179; +4 `Wave13Fase2aTests` — штамп `kind` ×6, PK=id
      родителя+глобальная уникальность, дуга на едином id, MTI-каскад удаления) зелёные на
      MySQL 8.0.25. Круговой прогон на `seed_demo`-данных (scratch-БД): reverse+forward
      remap **побайтово** сохранил остатки лотов/счётчики/дуги (SNAP_A==SNAP_C). Dev-MySQL
      догнан на 0005 (остаток движений инвариантен). Обе mermaid-диаграммы README обновлены.

**Ф2b — коллапс дуг: три exclusive-arc → один FK на `StockDocument` ✅ 2026-07-09**
- [x] `Lot.origin` → один NOT-NULL FK на `StockDocument`; снесены `LOT_ORIGIN_FIELDS` и
      Check `lot_exactly_one_origin` (вид = `origin.kind`). `_exactly_one_q` жив (нужен
      двухпутному `Attachment`).
- [x] `StockLine.document` → один NOT-NULL FK; снесены `STOCKLINE_DOC_FIELDS` + Check.
      `Attachment.owner` → двухпутный `item ↔ document(StockDocument)`; `ATTACHMENT_OWNER_FIELDS
      = ('item','document')`, Check переопределён (6 документных FK схлопнуты в один).
- [x] Миграция `0006_collapse_arcs` (реверсивна): бэкфилл `COALESCE` (id ребёнка == id
      родителя после Ф2a — ремап не нужен) + обратный раздатчик по `kind`; `RemoveConstraint`
      первым → `AddConstraint` последним при откате (не падает на пустых колонках). Движок:
      `origin_kind`/`doc_kind` из `.kind`, query-lookups `origin__kind=…`; реверсы дуг
      (`receipt.lots`/`kitting.lines`/`receipt.attachments`) целы через MTI; API байт-в-байт
      (фронт не тронут). Admin-инлайны `StockLine` → `fk_name='document'` (MTI `get_parent_list`).
- [x] **Проверка:** 188 тестов (+5 `Wave13Fase2bTests`) зелёные на MySQL 8.0.25;
      `makemigrations --check` чист. Круговой прогон seed@0006→reverse@0005→forward@0006 —
      SNAP_A==SNAP_C побайтово (sha256), при 0005 арк-колонки восстановлены по видам.
      Dev-MySQL догнан на 0006 (stale pre-Ф2a `source_id` починены rebuild'ом, drift=0).
      Обе mermaid-диаграммы README + проза обновлены. См. JOURNAL 2026-07-09 Ф2b.

**Ф2c — подъём общих полей ордера в родителя (дедуп) ✅ 2026-07-09**
- [x] `project`/`user`/`date`/`number`/`note` подняты с 6 детей в `StockDocument`
      (реверс — `project.documents`/`user.documents`); специфика (`Receipt.supplier`/
      `purchase`, `Kitting.target_item`/`qty`, `Writeoff.reason`) осталась на детях.
      `date` — nullable (Kitting-черновик), `number`/`note` — blank (видимость по `kind`
      → форма/матрица, Ф2c #7). Единственная рябь в коде — `project.writeoffs` (engine)
      → `Writeoff.objects.filter(project=…)`; прямой доступ (`receipt.project`),
      `.objects.create(project=…)`, `select_related('project')`, admin `list_filter`/
      `search_fields` — прозрачны через MTI (API байт-в-байт, фронт/вьюхи не тронуты).
- [x] Миграция `0007_lift_common_fields` (реверсивна): **`SeparateDatabaseAndState`**
      (как 0005) — в MTI поле родителя и одноимённое поле ребёнка не сосуществуют в
      состоянии (клэш), поэтому СОСТОЯНИЕ = операции автодетектора (RemoveField детей →
      AddField родителя; `--check` чист), ФИЗИКА = raw-SQL под `FK_CHECKS=0` (бэкфилл по
      `p.id = ch.stockdocument_ptr_id`, без ремапа — id едины с Ф2a). MySQL-only.
- [x] **Проверка:** 193 теста (было 188; +5 `Wave13Fase2cTests`) зелёные на MySQL 8.0.25;
      `makemigrations --check` чист; `seed_demo` ок; system check 0 issues (admin через
      MTI). Круговой прогон на dev-БД (0007 → reverse@0006 → forward@0007): **SNAP_A ==
      SNAP_C побайтово** (sha256 остатков/движений/шапок), при 0006 дочерние колонки
      восстановлены с данными и NOT-NULL/FK. Обе mermaid-диаграммы README + проза обновлены.

**Ф2d — условная валидация специфики по `kind` ✅ 2026-07-09**
- [x] Единый **kind-driven** источник правила на модели: `StockDocument.REQUIRED_HEADER_BY_KIND`
      (5 строгих видов — `date`+`number`; `kitting`/`relocation` — свободны, как до Ф2c) +
      `clean()` с ошибками **по полям**. Восстанавливает per-kind NOT-NULL, осознанно
      ослабленный подъёмом полей в родителя (Ф2c: `date`→nullable, `number`→blank — одной
      колонкой на общий MTI-родитель per-kind NOT NULL не выразить). Правило теперь живёт в
      одном месте (зеркалит reverse-часть 0007), а не в 5 разбросанных `if not number`.
- [x] **Врезка:** admin-форма гейтится автоматически (`ModelForm.full_clean → model.clean`);
      движок дублирует гейтом полноты на **проведении** — `_require_header(doc)` в
      `post_document`/`approve_receipt`/`post_transfer` не выпускает неполный ордер незав. от
      пути создания (API/админ/прямой ORM). `create_*`/`update_*` остаются быстрым фаст-фейлом
      входного слоя (дружелюбные per-kind сообщения + дефолт даты); авторитет — на модели.
- [x] **Проверка:** 200 тестов (было 193; +7 `Wave13Fase2dTests` — карта зеркалит до-Ф2c
      NOT-NULL, `clean` ловит пустой номер/дату по полю, полная шапка проходит, kitting
      освобождён, проведение гейтит неполноту мимо create-guard ×2) зелёные на MySQL 8.0.25;
      `makemigrations --check` чист (**без миграции** — `clean()` + класс-атрибут + движок,
      схема не тронута); `seed_demo` ок; system check 0 issues. Фронт/API байт-в-байт (валидные
      документы из `create_*` всегда полны → ноль регрессии). Прод не трогали.

**Ф2e — новый вид `relocation` + активация мультисклада ✅ 2026-07-09**
- [x] `Relocation(StockDocument)` — 7-й MTI-ребёнок (`KIND=relocation`, безполевой);
      миграция `0008_relocation_child` (реверсивна, один `CreateModel` с parent_link).
      `REQUIRED_HEADER_BY_KIND[relocation]` → строгий (`date`+`number`); свободен только
      kitting. Движок: остаток по паре `(лот, локация)` (опциональный `location`-фильтр,
      тотал байт-в-байт; `lot_locations`, `stock_map.by_location` аддитивно); жизненный
      цикл перемещения (`create_relocation`/`relocation_cockpit`/`add|update|remove_
      relocation_line` — пара `−q`/`+q` на ход/`post|unpost_relocation`/`relocation_
      source_lots`), тотал лота сохранён (`−q+q=0`). Админка `RelocationAdmin`+инлайн;
      сид — два места (103/105) + демо ПЕР-1. 214 тестов (+14) на MySQL 8.0.25; `check`
      0 issues; `seed_demo`+живой shell. Обе диаграммы README + JOURNAL 2026-07-09 (Ф2e).
      **Отложено (вьюхи потом):** HTTP-эндпойнты + React-форма перемещения.

**Ф2f — переименования `Lot`: `part_number` + `lot_name` ✅ 2026-07-10**
- [x] `Lot`: пара `serial_number`/`received_name` → **два идентификатора** —
      `part_number` (строгий машинный: MPN/децимальный; для станка автомонтажа) и
      `lot_name` (человеческий: имена из УПД + заводские №). Миграция
      `0009_lot_identifiers` (реверсивна): `AddField part_number` (пусто) →
      `RenameField received_name→lot_name` → `RunPython` слияние
      `lot_name ← COALESCE(received_name, serial_number)` → `RemoveField serial_number`.
      Реверс структурно-полный, значение сохранно (`lot_name → received_name`, serial → ''),
      лоссов лишь по «в каком поле лежал зав.№» → round-trip остаток инвариантен.
- [x] Движок/сериализаторы: писатели (`add/update_receipt_lot`, `add/update_inventory_lot`,
      `add_requisition_line`-наследование) разводят `lot_name`+`part_number` независимо;
      каждый лот-содержащий кокпит несёт оба (rows с одним id-полем отдают человеческий
      `lot_name` — историческ. зав.№ живёт там после слияния); `_lot_label` = `lot_name or
      part_number or code`. `admin.py`/`seed_demo` обновлены (демо-PN у покупных лотов).
- [x] Фронт: `api.ts` — типы/параметры (`lot_name`/`part_number`); born-lot формы
      (Приход/Инвентаризация) получили **редактируемый `part_number`** рядом с названием
      (иначе поле мёртвое); справочник изделия — колонки «Part number» + «Название»;
      пикеры/дисплеи (Передача/Списание/Требование/КомплектацияProjectStock/ре-материализация)
      показывают `lot_name`.
- [x] **Проверка:** 218 тестов (было 214; +4 `Wave13Fase2fTests` — оба идентификатора на
      born-лоте, независимая правка, приоритет метки, наследование требованием) зелёные на
      SQLite **и** боевом MySQL 8.0.25; `makemigrations --check` чист; `tsc -b`+`vite build`
      чисты; `seed_demo` ок (кокпит отдаёт PN). Круговой прогон на dev-MySQL: 0009 → reverse
      @0008 → forward@0009 — значение стабильно (lot 53 `ПЛ-001..003` цел), live-qty инвариантен.
      Прод не трогали (Ф2 на прод — отдельной экскурсией).

**Ф2g — `Supplier → Counterparty` (роли) + контрагент на передаче ✅ 2026-07-10**
- [x] `Supplier → Counterparty` — единая внешняя сторона с ролями `is_supplier`
      (default True — историческая роль) / `is_customer`. Одно юрлицо может нести обе.
      `Receipt.supplier → contractor` (RenameField, FK цел); **`Transfer.contractor`** —
      новый nullable FK (структурный заказчик; закрывает отложенную симметрию «передача =
      перемещение к внешней точке» — раньше получатель жил только текстом в
      `StockLine.display_name`). Виды `receipt`/`transfer` **не слиты** (born-direct vs
      StockLine — хребет ясности), оба ссылаются на `Counterparty` + направление несёт `kind`.
- [x] Миграция `0010_counterparty` (реверсивна): `RenameModel` + `AddField` ролей
      (default True/False — бэкфилл поставщиков автоматом) + `RenameField` + `AddField`.
      Схема-only, MySQL и SQLite. Круговой прогон на dev-MySQL (0010 → reverse@0009 →
      forward@0010): **SNAP_A == SNAP_C** по приход×контрагент и счётчику (FK-связи
      инвариантны). Единственный лосс — роль-флаги (аддитивны; reverse их сбрасывает,
      forward defaults `is_supplier=True`) — как «в каком поле лежал зав.№» у Ф2f.
- [x] Движок: проекции перешли на **`contractor_*`** (симметрия приход/передача —
      `receipt_cockpit`/`transfer_cockpit`/purchase-receipts-row; UI-метка по `kind`:
      «Поставщик»/«Заказчик»). `create_transfer`/`update_transfer` получили контрагента
      (часовой `_UNSET` — правка номера/даты не сбрасывает получателя, `None` снимает).
      Эндпойнт `/api/suppliers/` → **`/api/counterparties/?role=supplier|customer`** (один
      справочник под оба пикера) + быстрое создание с ролью. Admin/`seed_demo` обновлены
      (демо-заказчик «АО Заказчик»).
- [x] Фронт: `api.ts` типы/эндпойнты (`CounterpartyRow`, `contractor_*`); `NewReceipt`
      (поставщик-контрагент), `NewTransfer`+`TransferView` (пикер заказчика +
      быстрое создание, редактируемо под замком), `ReceiptView`/`PurchaseView`
      (`contractor_name`). `tsc -b`+`vite build` чисты.
- [x] **Проверка:** 224 теста (было 218; +6 `Wave13Fase2gTests` — роль по умолчанию,
      `contractor_*` в кокпите прихода/передачи, опциональный+редактируемый получатель,
      часовой `_UNSET`, HTTP-фильтр `?role=`) зелёные на боевом MySQL 8.0.25 **и** SQLite;
      `makemigrations --check` чист; `seed_demo` ок (кокпит несёт контрагента). Прод не
      трогали (Ф2 на прод — отдельной экскурсией).

**Ф2h — admin-гибрид (родитель-обзор + правка по типу) ✅ 2026-07-10**
- [x] **`StockDocumentAdmin` — read-only обзор «все ордера»** (зеркало режима «Ордер»):
      смешанный список 7 видов, `list_filter = (kind, status, project)`, `ordering
      ('-id')` (новейшие сверху), `list_select_related`. Некликабельный
      (`list_display_links = None`) + три `has_*_permission → False` (add/change/delete):
      bare-родителя не создаём (вид штампует ребёнок в `save()`), правка/удаление — в
      дочерних админках (инлайны строк + guard'ы движка). Схема не тронута — миграции нет.
- [x] **Проверка:** 227 тестов (было 224; +3 `Wave13Fase2hTests` — read-only пермишены,
      смешанный список видов через родителя, HTTP-changelist рендерит ордер и не даёт
      кнопку «Добавить») зелёные на MySQL 8.0.25; `makemigrations --check` чист; `check`
      0 issues. См. JOURNAL 2026-07-10 (Ф2h).

**Ф2i — свод матрицы полей + единая `<OrderForm kind=…>` ✅ 2026-07-10**
- [x] **Матрица → один row-set.** B1–B4 + C1–C2 схлопнуты в раздел «B. Ордер
      (`StockDocument`)»: две таблицы (шапка + строка/born-лот) с колонкой «Виды»
      (RCP/KIT/INV/REQ/TRF/WOF/REL) — видимость поля определяет `kind`. Сверено с моделью
      после Ф2c–g (общие поля в MTI-родителе, `part_number`/`lot_name`, `contractor`-роли,
      `status {draft⇄posted}`, `REQUIRED_HEADER_BY_KIND`, мультисклад); `Purchase`/
      `Procurement` (C3/C4) — вне объединения. Канон свёрнут в `UI_GUIDE §6`
      (`[ОТКРЫТО]` → `[ЗАКРЫТО Ф2i]`). Остаток — «Свод расхождений #A» (правка якорей/
      авторства шапки на форме; поля есть, форма не показывает).
- [x] **Свод оболочки (не «мегакомпонент»).** Тела 6 кокпитов несводимы (разные типы/
      пикеры/API) → свели **оболочку**: генеричный `useOrderCockpit<C>` в `FormHeader.tsx`
      (fetch/`run`/`del`/замок/ошибка; специфика — колбэками), все 6 вьюх на нём
      (−~90 строк). `OrderForm.tsx` (`export type OrderKind` + switch) заменил 6 условных
      веток в `App` одним `<OrderForm kind id …>` + `reloadOrderKind`.
- [x] **Проверка:** только фронт (схема не тронута — `--check` чист, диаграммы не меняются).
      `tsc -b`+`vite build` чисты (37 модулей); 227 тестов на MySQL 8.0.25 зелёные (контракт
      не поехал); `seed_demo` ок; rules-of-hooks/висячие ссылки проверены. Браузерный смоук —
      не в неинтерактивной сессии. См. JOURNAL 2026-07-10 (Ф2i).

**Ф2j — авторство `user` редактируемо под замком (сквозная #A) ✅ 2026-07-10**
- [x] Первая связка «Свода расхождений #A» — сквозная авторская дыра. `user` (автор)
      был на всех ордерах и поднят в MTI-родителя (Ф2c), но форма не давала его править
      (проставлялся только при создании). Теперь редактируемо под замком на **всех 8**
      документах (6 ордеров + Purchase + Procurement). Движок: часовой `_set_author`
      (`_UNSET`/`User`/`None`-отказ — автор обязателен, FK NOT NULL); `user=_UNSET` в 8
      `update_*` (унаследовали edit-freeze из `_require_draft`); 9 form-кокпитов несут
      `user_id`+`user_name`. Views: `GET /api/users/` (пикер, активные), `_resolve_author`,
      8 PATCH прокинули `user` + ловят `User.DoesNotExist`→400. Фронт: общий `<AuthorField>`
      (модульный кэш `api.users()`) в `hdr-edit` всех 8 форм; `Authored`-миксин на 8
      кокпит-типах, `user_id?` в 8 update-параметрах.
- [x] **Схема не тронута** (миграции нет — только проекции/хелперы/read-only эндпойнт).
- [x] **Проверка:** 235 тестов (было 227; +8 `Wave13Fase2jTests`) зелёные на боевом MySQL
      8.0.25 **и** SQLite; `makemigrations --check` чист; `check` 0 issues; `tsc -b`+`vite
      build` чисты; `seed_demo` ок + живой shell. См. JOURNAL 2026-07-10 (Ф2j). **Остаток
      #A** — структурные якоря ⚓ на форме (`project`/`contractor`/`target_item`/`purchase`).

**Ф2g+ — оставшееся Ф2 (следующими укусами):**
- [ ] Миграция данных на живой прод-базе (развёрнут 2026-07-01).
- [x] ~~Свернуть матрицу полей: B1–B4 + C1–C2 → один row-set с видимостью по `kind`.~~ ✅ Ф2i.
- [x] ~~Авторство `user` на форме (сквозная связка #A).~~ ✅ Ф2j.
- [ ] Структурные якоря ⚓ на форме (вторая связка #A): `project` (все) + `contractor`
      (Приход/Передача) + `target_item` (Комплектация) + `procurement`/`project` (Purchase).
- [ ] Вьюхи Ф2e: HTTP + React-форма перемещения (комплектовщик собирает ход из целых
      лотов) + справочник `Location`.

### Дисциплина
**Модель + движок — сейчас; вьюхи — потом.** Форму комплектовщика/пайки (собрать
перемещение из целых лотов, печать Ордера с полями для оффлайн-заметок) настраиваем
отдельно, когда боевая БД устойчиво копит лоты и движения.

## Отложено (не схлопываем сейчас)
- **Полное слияние `receipt`+`transfer` в один `kind`-УПД** — не делаем: born-direct
  vs StockLine. Общность выражена через `Counterparty` + `kind`-направление, этого
  достаточно.

## НЕ входит
- `Procurement`/`Purchase` (вне объединения).
- Отложенные пункты матрицы (заказ↔поставщик, `expected_date`) — своя ветка.
- Деплой Ф2 на прод — отдельной экскурсией (как В6–В12).
