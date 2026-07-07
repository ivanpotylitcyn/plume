# Волна 13 — единый складской документ (разморозка, MTI, фазами)

Чеклист тринадцатой волны — **первая волна после заморозки схемы**. Цель — свернуть
шесть документов-близнецов (`Receipt`/`Kitting`/`Inventory`/`Requisition`/`Transfer`/
`Writeoff`), двигающих лоты, к одной сущности **«Ордер» (StockDocument)** так, чтобы:
одна ДНК шапки и форм, один замок, честное авторство в одном месте, **исключающая дуга
на `Lot` (и 7-путная на `Attachment`) заменяется одним FK** — при этом NOT NULL
kind-специфичных полей сохраняется (за счёт MTI). Значимые решения — в
[JOURNAL.md](JOURNAL.md) (запись 2026-07-07, «Разморозка»).

**Ключевая опора:** унифицирующая сущность уже наполовину есть — `StockMovement` —
цельная проекция (`type` RECEIPT/ISSUE/RETURN + полиморфный `source_type/source_id`);
волна поднимает эту цельность на слой документов над ней.

## Целевая модель (Ф2, MTI)

```
StockDocument (parent)        kind, project, user, date, number, note, status(замок)
 ├ ReceiptDoc     supplier NOT NULL, purchase
 ├ KittingDoc     target_item NOT NULL, qty
 ├ InventoryDoc   (note уже в parent)
 ├ RequisitionDoc —
 ├ TransferDoc    (display_name → на строку)
 └ WriteoffDoc    reason
StockLine(document, lot, qty, direction)   ← сворачивает 4 таблицы строк-расхода
Lot.origin  → FK(StockDocument)            ← origin-дуга (4 nullable FK + Check) умирает
Attachment.owner → FK(StockDocument) + Item ← 7-путная дуга схлопывается
```

Граница: `Procurement`/`Purchase` **вне** объединения (лотов не трогают —
планирование/обязательство).

## Фазы

### Ф0 — `StockLine` (безопасно, ортогонально глубине)
Свернуть `KittingLine`/`TransferLine`/`WriteoffLine`/`RequisitionLine` (почти
одинаковые: `lot`, `qty`, `location`) в один `StockLine(document, lot, qty, direction)`.
Строки-рождения `Receipt`/`Inventory` (лот=строка напрямую) пока не трогаем.
- [ ] Модель `StockLine` + миграция данных из 4 таблиц.
- [ ] Пересчёт `StockMovement` читает `StockLine`.
- [ ] Сериализаторы/вьюхи строк унифицированы.
- [ ] Тесты движка на инвариантах (остаток по лоту не изменился до/после).

### Ф1 — абстрактная шапка (высокая ценность / низкий риск)
Общую шапку (`project/user/date/number/note` + замок) — в абстрактный миксин; шесть
таблиц пока остаются своими. Закрывает своды матрицы:
- [ ] **#1 авторство** — `user` редактируемо под замком на всех документах.
- [ ] **#7 симметрия замка** — один `status`/lock-контракт вместо `approved`/`posted`/
      `status` + «замка нет». *(решить: у Inventory/Requisition/Writeoff вводим замок?)*
- [ ] Общий фронт-компонент формы `<StockDocForm kind=...>` + `BaseStockDocSerializer`.

### Ф2 — MTI, убить дугу (осознанный слом заморозки)
- [ ] Родитель `StockDocument`(шапка+`kind`) + дочерние под специфику.
- [ ] `Lot.origin` → один FK; снести `LOT_ORIGIN_FIELDS`, `_exactly_one_q`, Check.
- [ ] `Attachment.owner` → FK(StockDocument)+Item; снести `ATTACHMENT_OWNER_FIELDS`.
- [ ] Условная валидация специфики по `kind` (что NOT NULL на дочерней — то БД держит).
- [ ] Миграция данных на живой прод-базе (развёрнут 2026-07-01).
- [ ] **Обновить ОБЕ mermaid-диаграммы README** в этом же изменении (диаграммы=правда).
- [ ] Свернуть матрицу полей: B1–B4 + C1–C2 → один row-set с видимостью по `kind`.

## Открытые вопросы (решить до Ф2)

- **Имя сущности:** «Ордер» vs «Складской документ» (JOURNAL — фаворит «Ордер»).
- **Замок для Inventory/Requisition/Writeoff:** вводим единый `status` или часть
  документов остаётся «всегда живой» (свод матрицы #7 — по решению Ивана).
- **Строки-рождения:** Receipt/Inventory держат born-лот напрямую (Lot несёт
  `unit_cost/received_name/serial`). Оставляем born-direct или тоже через `StockLine`
  с `direction=in`? (born-direct = меньше хирургии, но лёгкая асимметрия со `StockLine`.)
- **Django-admin:** MTI-документы в админке через parent+inlines; проверить, что
  внутренние операции PLM не деградируют (проект опирается на админку).

## НЕ входит
- `Procurement`/`Purchase` (вне объединения — не трогают лоты).
- Отложенные пункты матрицы (заказ↔поставщик, `expected_date`) — своя ветка.
- Деплой Ф2 на прод — отдельной экскурсией (как В6–В12).
