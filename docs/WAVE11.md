# Волна 11 — вложения к документам и изделиям (`Attachment`: PDF/сканы)

Чеклист одиннадцатой волны. Цель — оживить **последнюю модель без UI** — `Attachment`
(была в замороженной схеме, только в admin). Даёт прикрепить **подписанный документ**
(PDF/скан УПД, накладной, акта) к его кокпиту и **datasheet/КД** к изделию. Закрывает
явные заглушки-обещания «подпис. документ приложим отдельно» из кокпитов (JOURNAL, В5).
Продолжает паттерн волн 2–10 (записываемая надстройка + движок = единственный источник
правил + переиспуемая панель-проекция). Значимые решения — в [JOURNAL.md](JOURNAL.md)
(запись 2026-07-04, «Волна 11»).

**Цель волны 11:** в 7 экранах-владельцах (приход / передача / комплектация /
инвентаризация / списание / требование + изделие) — панель **«Вложения»**: выбрать
файл → загрузить (метаданные с сервера) → список со скачиванием, правкой подписи,
удалением. Файлы на диске (`MEDIA_ROOT`), скачивание — через прикладной эндпоинт
(публичного `/media/` нет).

## Объём

**Входит:** MEDIA-настройки (`MEDIA_ROOT`/`MEDIA_URL`, `MAX_ATTACHMENT_SIZE`) → движок
вложений (`add_attachment` / `attachments_for` / `attachment_row` / `update_attachment`
/ `delete_attachment` / `resolve_attachment_owner`) → DRF (`GET/POST
/api/attachments/<owner_type>/<owner_id>/`, `PATCH/DELETE /api/attachments/<pk>/`, `GET
/api/attachments/<pk>/download/`) → фронт: переиспуемая `AttachmentPanel` в 7 экранах +
`upload()`-хелпер (multipart) в `api.ts` → юнит-тесты + HTTP-smoke.

**НЕ входит (следующая — финальная — волна):**
- Логин-экран (аутентификация SPA; автор пока — дефолтный суперюзер `_actor`). Скачивание
  вложений — естественное место навесить проверку логина/прав на документ.

## Решения (проектные — в JOURNAL 2026-07-04, «Волна 11»)

- **Схему БД не трогаем** (как В6–В10). `Attachment` (FileField на диск + exclusive-arc
  владелец из 7 FK, `OWNER_FIELDS`) уже в замороженной модели. Диаграммы README **не
  меняются**.
- **Владельцы — 7 (не 9).** `ATTACHMENT_OWNER_FIELDS` = item / receipt / transfer /
  kitting / inventory / writeoff / requisition. **`Purchase`/`Procurement` вложений НЕ
  имеют** (нет FK) — панели там нет, консистентно. `owner_type` в API = **имя FK-поля**,
  модель выводим из него (`item→Item`, …) — без отдельного реестра типов.
- **Файлы на диске, не BLOB** (как задумано в модели: `upload_to='attachments/%Y/%m/'`).
  Метаданные (`filename`/`size`/`content_type`) заполняет **сервер** из загруженного
  файла — клиенту не верим.
- **Публичного `/media/` нет — скачивание через эндпоинт** (`FileResponse` из
  `attachment_download`). Портируемо (dev + прод-Passenger без Apache Alias — грабля
  соседнего проекта), файл не по угадываемому URL, и это **естественное место под логин**
  следующей волны. Загрузка синхронна в запросе (без Celery — как весь движок).
- **Отдача inline только для безопасных типов (защита от XSS).** PDF и растровые
  картинки — `inline` (смотреть во вкладке); всё прочее (html/svg с JS, zip, STEP, xlsx,
  …) — принудительная **загрузка** (`Content-Disposition: attachment`) + заголовок
  `X-Content-Type-Options: nosniff`. Иначе html/svg-вложение (напр. интерактивный BOM)
  исполнилось бы в **нашем origin** — хранимый XSS (доступ к сессии/CSRF, вызовы API от
  лица юзера, особенно после волны логина). nosniff защищает и от подделки `content_type`.
  Интерактивный BOM скачивается и открывается локально (`file://`) — полностью рабочий,
  но не в нашем origin.
- **Расширения НЕ ограничиваем** (whitelist’а нет — любой тип грузится: pdf/zip/STEP/xlsx/
  html/png/… и будущие). Единственный фактический лимит — размер. Инпут на фронте тоже
  открыт (без `accept`) — не греем будущие форматы.
- **Потолок размера** (`MAX_ATTACHMENT_SIZE`, дефолт **50 МБ**, override через env) —
  хватает на STEP-модели, интерактивный BOM (html), zip производственного пакета к заказу;
  защита shared-диска и памяти WSGI.
- **Панель самодостаточна и переиспуема.** `AttachmentPanel(ownerType, ownerId)` грузит
  свой список и перечитывает после мутаций; вложения не двигают склад — соседние панели
  освежать не нужно (в отличие от кокпитов с `onChanged`). Правка подписи — тем же
  автосейвом `CommitInput`, что и кокпиты.

## Этапы

### Этап 1 — Движок вложений (Python + тесты) ← ядро волны
- [x] `ATTACHMENT_OWNERS` (owner_type → модель) + `resolve_attachment_owner`.
- [x] `add_attachment` (файл на диск, метаданные с сервера, exclusive-arc,
  `full_clean`, потолок размера).
- [x] `attachments_for` / `attachment_row` (проекция; URL скачивания, автор с документа).
- [x] `update_attachment` (подпись) / `delete_attachment` (строка + файл с диска).
- [x] Юнит-тесты (5, `AttachmentTests`): метаданные+владелец; список свежие-сверху;
  неизвестный owner_type отклонён (в т.ч. `purchase`); потолок размера; удаление
  сносит файл с диска.
- _Готово, когда:_ тесты зелёные; изолированный `MEDIA_ROOT` в тестах. ✓

### Этап 2 — DRF-эндпоинты
- [x] `GET/POST /api/attachments/<owner_type>/<owner_id>/` (список / multipart-загрузка).
- [x] `PATCH/DELETE /api/attachments/<pk>/` (подпись / удаление).
- [x] `GET /api/attachments/<pk>/download/` (`FileResponse`; inline только для
  безопасных типов, остальное — attachment + nosniff).
- [x] MEDIA-настройки (потолок 50 МБ) + `backend/media/` в `.gitignore`.
- [x] HTTP-smoke (`AttachmentHttpTests`, 4): полный цикл
  upload→list→patch→download→delete; disposition (pdf inline / html attachment + nosniff);
  плохой owner_type → 400; без файла → 400.

### Этап 3 — Фронт: панель + встраивание
- [x] `api.ts`: тип `AttachmentRow`, `upload()`-хелпер (FormData+CSRF), методы
  `attachments`/`uploadAttachment`/`updateAttachment`/`deleteAttachment`.
- [x] `AttachmentPanel.tsx` (список + file input + скачивание + автосейв подписи +
  удаление; формат размера).
- [x] Встроена в 7 экранов: `ReceiptView`/`TransferView`/`KittingView`/`InventoryView`/
  `WriteoffView`/`RequisitionView`/`ItemView`.
- [x] Статус-бар → волна 11.
- _Готово, когда:_ `tsc -b && vite build` чист. ✓

## Приёмка (правки Ивана 2026-07-04)
- Потолок размера **25 → 50 МБ** (STEP/html-BOM/zip к заказу).
- Расширения оставлены **открытыми** (whitelist не вводим — «не плодить сущности»;
  фактически их и не было). Инпут без `accept`.
- **Подводный камень (поднят до правок):** отдача html/svg inline = хранимый XSS →
  inline только для PDF/картинок, остальное принудительно download + nosniff.

## Проверено
- 145 юнит/HTTP-тестов зелёные (136 волн 1–10 + 9 новых: 5 движок + 4 HTTP).
- `tsc -b` без ошибок; `vite build` собран.
- HTTP-smoke прогоняет реальный путь (Client → urls → views → engine → FileSystemStorage
  → FileResponse), включая стриминг скачивания и удаление файла с диска.
