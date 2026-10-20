// Витрина волны 1: экран изделия = панель свойств + окружение из связей.
// Партии на складе (по проектам, с живым остатком), where-used, состав.
// Волна 19 (Ф12a): форма по канону §13 — табы Состав · Применение · Склад ·
// Движения · Файлы. «Движения» пришли на смену узкому «Отгружено»: вся лента
// ордеров, коснувшихся изделия (рождение партий + расходы), `engine.item_movements`.
import { Fragment, useEffect, useMemo, useState } from 'react'
import { api, type ItemDetail, type ItemMoney, type ItemRow, type Category, type RollupResult } from './api'
import { Chevron, Cost, num, money, moneyCol, count, CounterpartyRef, ItemGlyph, LotGlyph,
  ProcurementGlyph, PurchaseGlyph, StatusGlyph, paretoKeys, rowNumbers,
  unitMoney, visibleTree } from './status'
import { ORDER_LABEL, type OrderKind } from './orders'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { ItemPicker } from './Picker'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { CommitInput } from './CommitInput'
import { Field, TextField, viewDate } from './FormField'
import { Stat, StatGroup, StatPanel, StatWarn } from './StatPanel'
import { Dropdown } from './Dropdown'
import { useCategoryFilter } from './ColumnFilter'
import { EntityLink } from './EntityLink'
import { ask } from './dialog'

export function ItemView({ itemId, items, isNew, openItem, openOrder, openProcurement,
  openPurchase, openCounterparty, onChanged, onDeleted }:
  { itemId: number; items: ItemRow[]; isNew: boolean; openItem: (id: number) => void
    openOrder: (kind: OrderKind, id: number) => void   // лента движений кликабельна (§8)
    openProcurement: (id: number) => void; openPurchase: (id: number) => void
    openCounterparty: (id: number) => void
    onChanged?: () => void; onDeleted?: () => void }) {
  const [d, setD] = useState<ItemDetail | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rollup, setRollup] = useState<RollupResult | null>(null)
  const { unlocked, toggle } = useFormLock(itemId, isNew)   // §5: существующее — в просмотре
  const att = useAttachments('item', itemId)   // загрузка — команда шапки (§13.8)
  // Фильтр состава по категории компонента — общий движок (2026-08-10): «покажи только
  // конденсаторы». Ключ сброса — изделие: у другого прибора состав свой.
  const bomFilter = useCategoryFilter(d?.bom, b => b.component_category, itemId)
  const bomNo = rowNumbers(d?.bom)      // постоянный номер строки состава

  useEffect(() => {
    setD(null); setErr(null); setRollup(null)
    api.item(itemId).then(setD).catch(e => setErr(String(e)))
  }, [itemId])
  useEffect(() => { api.categories().then(setCategories).catch(() => {}) }, [])

  // Обёртка мутации состава: ответ = свежий экран изделия, + пинок дереву (where-used).
  const run = (p: Promise<ItemDetail>) => {
    setBusy(true); setErr(null)
    p.then(next => { setD(next); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Пересчёт оценочной стоимости роллапом по BOM (волна 15). Ответ = свежий экран
  // изделия + сводка `updated`/`incomplete` — показываем под кнопкой.
  const recalc = () => {
    setBusy(true); setErr(null); setRollup(null)
    api.recalcCost(itemId)
      .then(next => { const { rollup, ...det } = next; setD(det); setRollup(rollup); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // «Взять в оценку» (волна 26): оценка покупного ← последняя цена по счёту, одним
  // кликом. Команда видна, только когда блок «Деньги» поднял расхождение.
  const adopt = () => run(api.adoptPrice(itemId))

  // Удаление изделия (WAVE14 Ф2) под замком: confirm + friendly-guard бэка → сброс выбора.
  const del = async () => {
    if (!d || !(await ask({ title: `Удалить изделие «${d.code}» из справочника?`, verb: 'Удалить', icon: 'ci-trash', danger: true }))) return
    setBusy(true); setErr(null)
    api.deleteItem(d.id).then(() => { onChanged?.(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !d) return <div className="empty">Ошибка: {err}</div>
  if (!d) return <div className="empty">Загрузка…</div>

  // Состав правим у производимых (или если он уже задан) — у покупных BOM нет.
  const composable = d.native || d.bom.length > 0

  // Фиксация (волна 17) — ровно как у StockDocument (см. ReceiptView): `d.locked` =
  // изделие зафиксировано (форма read-only, бэк гейтит мутации), чип вместо замка.
  // `locked` = фиксация ИЛИ закрытый личный мягкий замок → всё в форме read-only.
  const fixed = d.locked
  const locked = fixed || !unlocked
  // Матрица synced×locked (Ф3a): библиотечное (`synced`) расфиксированное — правится
  // ТОЛЬКО оценочная стоимость; остальные поля приходят из библиотеки (read-only).
  // `metaLocked` запирает «библиотечные» свойства; Оценка гейтится обычным `locked`.
  const metaLocked = locked || d.synced
  // Цена зафиксированного КОМПОНЕНТА правится (волна 23, Ф5, решение Ивана) — синхронно
  // с библиотечным: под «Редактировать» открывается только «Оценка». Изделие заперто
  // целиком — его цена роллап по составу. Форма read-only, когда заперто и то и другое.
  const priceLocked = !unlocked || (fixed && d.native)
  const formLocked = metaLocked && priceLocked

  // Табы (§13.7): порядок — от сути изделия к его следам на складе. Глифы взяты у
  // РЕЖИМОВ навигации (§2): состав = `chip` (Компоненты), применение = `rocket`
  // (Изделия), склад = `layers` (Склады), отгружено = `notebook` (Ордера) — одна
  // сущность носит один знак, где бы ни встретилась. Счётчиков в табах нет: числа
  // ушли в мету. «Состав» появляется только там, где состав вообще бывает.
  const tabs: FormTab[] = []
  if (composable) tabs.push({
    key: 'bom', label: 'Состав', icon: 'chip',
    content: <>
      {d.bom.length === 0 && <div className="tab-empty">
        {locked ? 'Состав пуст.' : 'Состав пуст — добавьте компонент ниже.'}</div>}
      {d.bom.length > 0 &&
        <table className="grid">
          <thead><tr><th className="rn">№</th><th className="gl" />
            {/* Фильтр — в ячейке подписи, как «Остаток» заказа и члены баланса
                «Потребности»: он относится к колонке, а не к таблице целиком. */}
            <th className="c-key">Компонент{bomFilter.head}</th>
            <th className="c-desc">Описание</th>
            <th className="num">Кол-во</th><th className="uom">Ед.</th>
            {/* 2026-10-20: во сколько строка обойдётся (кол-во × оценка; у своего
                компонента — живой роллап). Оранжевые — Парето: дают 80% стоимости. */}
            <th className="num c-money" title="кол-во × оценка компонента; оранжевые — строки, дающие 80% стоимости прибора">Оценка, ₽</th>
            {!locked && <th className="act" />}</tr></thead>
          <BomBody lines={bomFilter.shown} no={b => bomNo.get(b)} locked={locked}
            busy={busy} openItem={openItem} run={run} />
        </table>}
      {/* Добавление компонента — только когда форма редактируема (мягкий замок открыт
          и не зафиксировано). Под замком/фиксацией состав = read-only список. */}
      {!locked && <AddComponent items={items} parentId={d.id} bom={d.bom} busy={busy}
        add={(component_id, qty) => run(api.addBomLine(d.id, { component_id, qty }))} />}
    </>,
  })
  tabs.push({
    key: 'where', label: 'Применение', icon: 'rocket',
    content: d.where_used.length === 0
      ? <div className="tab-empty">Нигде (не входит в BOM)</div>
      : <table className="grid">
          <thead><tr><th className="rn">№</th><th className="gl" /><th className="c-key">Изделие</th><th className="c-desc">Описание</th>
            <th className="num">Кол-во</th>
            <th className="uom">Ед.</th></tr></thead>
          <tbody>{d.where_used.map((w, i) => (
            <tr key={w.parent_id} className="row">
              <td className="rn">{i + 1}</td>
              {/* Глиф родителя — по его собственным осям (Ф3a: ровно один по режиму). */}
              <td className="gl"><ItemGlyph native={w.parent_native} synced={w.parent_synced}
                locked={w.parent_locked} /></td>
              <td className="c-key">
                <EntityLink kind="item" id={w.parent_id} open={openItem}>
                  {w.parent_code}</EntityLink></td>
              <td className="c-desc">
                <span className="cell-ellip" title={w.parent_description}>{w.parent_description}</span></td>
              <td className="num">{num(w.qty)}</td>
              <td className="uom">{d.uom}</td>
            </tr>))}</tbody>
        </table>,
  })
  // «Закупки» и «Заказы» (2026-10-20) — только у покупного: где позиция в плане и где
  // уже под обязательством поставщика. Стоят за «Применением» — по потоку: куда идёт →
  // что решили купить → что заказали → что лежит. Порядок строк — движка (`_newest_first`,
  // то же правило, что `newestFirst` списков): живое сверху, и xlsx повторяет экран.
  // Количества — этой позиции, а не документа целиком.
  if (!d.native) {
    tabs.push({
      key: 'procurements', label: 'Закупки', icon: 'law',
      content: d.procurements.length === 0
        ? <div className="tab-empty">Ни в одной закупке не планируется</div>
        : <table className="grid">
            <thead><tr><th className="rn">№</th><th className="gl" />
              <th className="c-key">Закупка</th><th className="c-desc">Описание</th>
              <th className="c-cp">Проект</th><th className="c-date">Дата</th>
              <th className="num">План</th>
              {/* Взято зафиксированными заказами — то же правило, что зелёный замок. */}
              <th className="num" title="Взято зафиксированными заказами">Заказано</th>
              <th className="uom">Ед.</th></tr></thead>
            <tbody>{d.procurements.map((p, i) => (
              <tr key={p.id} className="row">
                <td className="rn">{i + 1}</td>
                <td className="gl"><ProcurementGlyph locked={p.locked} closed={p.closed} /></td>
                <td className="c-key">
                  <EntityLink kind="procurement" id={p.id} open={openProcurement}>
                    {p.code || `Закупка #${p.id}`}</EntityLink></td>
                <td className="c-desc">
                  <span className="cell-ellip" title={p.description}>{p.description}</span></td>
                <td className="c-cp code">{p.project_code}</td>
                <td className="c-date">{p.date ? viewDate(p.date) : ''}</td>
                <td className="num">{num(p.qty)}</td>
                <td className="num">{num(p.ordered)}</td>
                <td className="uom">{d.uom}</td>
              </tr>))}</tbody>
          </table>,
    })
    tabs.push({
      key: 'purchases', label: 'Заказы', icon: 'package',
      content: d.purchases.length === 0
        ? <div className="tab-empty">Ни в одном заказе нет</div>
        : <table className="grid">
            <thead><tr><th className="rn">№</th><th className="gl" />
              <th className="c-key">Заказ</th>
              <th className="c-cp">Проект</th><th className="c-cp">Поставщик</th>
              <th className="c-date">Дата</th>
              <th className="num">Кол-во</th>
              <th className="num" title="По зафиксированным поставкам">Поступило</th>
              <th className="uom">Ед.</th>
              {/* Цена всей строки по счёту, как в «Строках» заказа; нет — прочерк. */}
              <th className="num c-money">Цена, ₽</th></tr></thead>
            <tbody>{d.purchases.map((p, i) => (
              <tr key={p.id} className="row">
                <td className="rn">{i + 1}</td>
                <td className="gl"><PurchaseGlyph locked={p.locked} files={p.files} /></td>
                <td className="c-key">
                  <EntityLink kind="purchase" id={p.id} open={openPurchase}>
                    {p.code || `Заказ #${p.id}`}</EntityLink></td>
                <td className="c-cp code">{p.project_code}</td>
                <td className="c-cp">
                  <CounterpartyRef code={p.contractor_code} name={p.contractor_name}
                    id={p.contractor_id} open={openCounterparty} /></td>
                <td className="c-date">{p.date ? viewDate(p.date) : ''}</td>
                <td className="num">{num(p.qty)}</td>
                <td className="num">{num(p.received)}</td>
                <td className="uom">{d.uom}</td>
                <td className="num c-money">
                  {p.price === null ? <span className="dim">—</span> : moneyCol(p.price)}</td>
              </tr>))}</tbody>
          </table>,
    })
  }
  tabs.push({
    key: 'lots', label: 'Склад', icon: 'layers',
    content: d.lots.length === 0
      ? <div className="tab-empty">Нет партий</div>
      // Глиф партии (Ф12c): форма = откуда родилась, цвет = живость остатка. Текстовый
      // чип «origin» снят — вид рождения теперь несёт сам глиф (§7a: одна строка —
      // один знак). Ф15: партия расфиксированного origin остаётся в списке (видно
      // входящий поток), но идёт нейтральным тоном — она не «исчерпана», а не принята.
      : <table className="grid">
          <thead><tr><th className="rn">№</th><th className="gl" /><th className="c-key">Партия</th>
            <th className="c-fit">Проект</th>
            <th className="num">Рожд.</th>
            <th className="num">Остаток</th>
            <th className="uom">Ед.</th>
            <th className="c-fit">Part number</th><th className="c-desc">Название</th>
          </tr></thead>
          <tbody>{d.lots.map((l, i) => (
            <tr key={l.id} className="row">
              <td className="rn">{i + 1}</td>
              <td className="gl"><LotGlyph origin={l.origin} liveQty={l.live_qty}
                draft={!l.origin_locked} /></td>
              <td className="c-key">#{l.id}</td>
              <td className="c-fit code">{l.project_code}</td>
              <td className="num">{num(l.qty_born)}</td>
              {/* Ф15: у партии черновика остатка нет вовсе — прочерк, а не 0 (ноль
                  здесь читался бы как «израсходована»). Рождённое кол-во остаётся:
                  это и есть входящий поток «едет, ещё не принято». */}
              <td className="num" title={l.origin_locked ? undefined
                : 'Партия ещё не на складе — зафиксируйте документ-origin'}>
                {l.origin_locked ? num(l.live_qty) : '—'}</td>
              <td className="uom">{d.uom}</td>
              <td className="c-fit">{l.part_number || '—'}</td>
              <td className="c-desc">{l.lot_name || '—'}</td>
            </tr>))}</tbody>
        </table>,
  })
  // «Движения» (2026-07-26, вместо узкого «Отгружено»): ВСЕ ордера, коснувшиеся
  // изделия — рождение партии (поставка/комплектация/инвентаризация/требование) и её
  // движения (пайка, передача, списание, перемещение). Знак сохраняем: расход виден
  // расходом. Ордер кликабелен (§8), глиф — ось фиксации документа.
  tabs.push({
    key: 'moves', label: 'Движения', icon: 'notebook',
    content: d.movements.length === 0
      ? <div className="tab-empty">Изделие ещё не двигалось по складу</div>
      : <table className="grid">
          <thead><tr><th className="rn">№</th><th className="gl" /><th className="c-key">Ордер</th><th>Вид</th><th>Дата</th><th>Проект</th>
            <th>Партия</th>
            <th className="num">Кол-во</th>
            <th className="uom">Ед.</th></tr></thead>
          <tbody>{d.movements.map((m, i) => (
            <tr key={`${m.kind}-${m.document_id}-${m.lot_id}-${i}`}
              className="row">
              <td className="rn">{i + 1}</td>
              <td className="gl"><StatusGlyph locked={m.locked} /></td>
              <td className="c-key">
                <EntityLink kind={m.kind as OrderKind} id={m.document_id}
                  open={id => openOrder(m.kind as OrderKind, id)}>
                  {m.code || m.number || `${ORDER_LABEL[m.kind as OrderKind]} #${m.document_id}`}
                </EntityLink></td>
              <td>
                {ORDER_LABEL[m.kind as OrderKind] ?? m.kind}
                {m.event === 'born' && <span className="hint">партия рождена</span>}</td>
              <td>{m.date ?? '—'}</td>
              <td className="code">{m.project_code}</td>
              <td>#{m.lot_id}{m.lot_name && ` · ${m.lot_name}`}</td>
              <td className="num">{m.qty > 0 ? `+${num(m.qty)}` : num(m.qty)}</td>
              <td className="uom">{d.uom}</td>
            </tr>))}</tbody>
        </table>,
  })
  tabs.push({
    key: 'files', label: 'Файлы', icon: 'files',
    content: <AttachmentList att={att} locked={locked} />,
  })

  return (
    <FormShell
      id={d.id} code={d.code} entity="изделие" locked={formLocked} error={err}
      // Мета (§13.6) — СЧЁТ ПО ТАБАМ в их порядке, число впереди подписи («17
      // компонентов · 2 вхождения»): читается фразой. Поля не повторяет, глифа нет
      // (он есть в списке и однозначно читается по доступным командам).
      // «Спящий» — не счётчик: это «ни одной живой ссылки, можно удалять» (шире
      // вхождений — сюда же лоты, строки заказов, потребность, комплектации).
      // Обратное («используется») молчит: об этом говорят сами счётчики.
      meta={<>
        {composable && <>{count(d.bom.length, 'компонент', 'компонента', 'компонентов')} · </>}
        {count(d.where_used.length, 'вхождение', 'вхождения', 'вхождений')} ·{' '}
        {!d.native && <>
          {count(d.procurements.length, 'закупка', 'закупки', 'закупок')} ·{' '}
          {count(d.purchases.length, 'заказ', 'заказа', 'заказов')} ·{' '}
        </>}
        {count(d.lots.length, 'партия', 'партии', 'партий')} ·{' '}
        {count(d.movements.length, 'движение', 'движения', 'движений')} ·{' '}
        {count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
        {!d.used && <span className="sub"> · спящий</span>}
        {(d.synced || (fixed && !d.native)) && unlocked &&
          <span className="sub"> · правится только цена</span>}
        {d.native && rollup && <span className="sub">
          {' · '}переоценено узлов {rollup.updated.length}
          {rollup.incomplete.length > 0 &&
            <span className="anomaly"> · без цены: {rollup.incomplete.join(', ')}</span>}
        </span>}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed} editWhenFixed={fixed && !d.native}
      // Фиксация — у всего, что не библиотечное (Ф5, волна 23): изделие и ручной
      // компонент. Библиотечный защищён библиотекой (`synced ⟹ not locked`).
      onFixate={d.synced ? undefined : () => run(api.lockItem(d.id))}
      fixateTitle={d.native ? 'Зафиксировать: заморозить состав (BOM) и свойства изделия'
        : 'Зафиксировать: заморозить свойства компонента'}
      onUnfix={() => run(api.unlockItem(d.id))}
      fixation={`items/${d.id}`}
      onDelete={del}
      /* Выгрузка (2026-07-30) — ВСЕГДА, в отличие от бланка закупки: состав нужен и
         черновиком, а библиотечный компонент не фиксируется вовсе (synced ⟹ not locked),
         и правило «только у запертого» оставило бы его без кнопки навсегда. Две цели
         → меню; глиф пункта — глиф вкладки, которую он выгружает (§2). */
      download={{
        title: 'Скачать xlsx (имя файла = код изделия)',
        options: [
          { label: 'Только состав', icon: 'chip', href: api.itemXlsxUrl(d.id, 'bom'),
            title: 'Один лист «Состав» — прямые компоненты, один уровень' },
          { label: 'Все вкладки', icon: 'table', href: api.itemXlsxUrl(d.id, 'all'),
            title: 'Листы по вкладкам формы, кроме «Файлов»' },
        ],
      }}
      actions={[
        ...(d.native ? [{ onClick: recalc, label: 'Переоценить', icon: 'ci-symbol-operator',
          title: 'Пересчитать стоимость: оценка = Σ(компонент × кол-во), рекурсивно по BOM до листьев',
          disabled: busy }] : []),
        ...(!d.native && d.money.last != null && d.money.estimate_off
          ? [{ onClick: adopt, label: 'Взять в оценку', icon: 'ci-arrow-swap',
            title: 'Оценка ← последняя цена по счёту (до копейки)', disabled: busy }] : []),
        { onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
          title: 'Загрузить файл (datasheet, КД) — появится в табе «Файлы»',
          disabled: att.busy },
      ]}
      fields={<>
        <TextField label="Код" code value={d.code} locked={metaLocked} busy={busy}
          onCommit={v => run(api.updateItem(d.id, { code: v }))}
          validate={v => v.trim() !== ''} />
        {/* Единственное длинное поле шапки (§13.3) — описание бывает в строку и больше. */}
        <TextField label="Описание" wide value={d.description} locked={metaLocked} busy={busy}
          onCommit={v => run(api.updateItem(d.id, { description: v }))}
          validate={v => v.trim() !== ''} />
        {/* Категория — описанием, не кодом (решение Ивана 2026-10-15: имена короткие,
            целые слова читаются лучше), и только своей стороны: у изделия — категории
            изделий, у компонента — компонентов (`Category.native`, гейт в движке). */}
        <Field label="Категория" locked={metaLocked} view={d.category?.description}>
          {/* Ф12e: изделие рождается по клику без категории — пустое поле честно
              говорит «ещё не выбрана» (фиксация без неё не пройдёт). */}
          <Dropdown options={categories.filter(c => c.native === d.native)
            .map(c => ({ value: c.id, label: c.description }))}
            value={d.category?.id ?? ''} disabled={busy} placeholder="— не выбрана —"
            onPick={v => run(api.updateItem(d.id, { category_id: Number(v) }))} />
        </Field>
        {/* Поля «Производимое» нет (снято 2026-07-26): `native` — не свойство на правку,
            а ОСЬ РЕЖИМА (Изделия / Компоненты). Заводится вместе с сущностью в том
            режиме, где нажали «＋ Новое», и дальше не переключается. */}
        {/* Порядок — от модели (§13.4a, Ф17): `uom`, затем `temperature`. */}
        <TextField label="Единицы" value={d.uom} locked={metaLocked} busy={busy}
          onCommit={v => run(api.updateItem(d.id, { uom: v }))} />
        <TextField label="Температура" value={d.temperature} locked={metaLocked} busy={busy}
          onCommit={v => run(api.updateItem(d.id, { temperature: v }))} />
        {/* «Оценка» без «₽» в подписи: рубль приезжает со значением в просмотре. */}
        <TextField label="Оценка" locked={priceLocked} busy={busy}
          value={d.estimated_cost != null ? String(d.estimated_cost) : ''}
          view={d.estimated_cost != null ? money(d.estimated_cost) : ''}
          onCommit={v => run(api.updateItem(d.id, { estimated_cost: v.trim() === '' ? null : Number(v) }))}
          validate={v => v.trim() === '' || Number(v) >= 0} />
      </>}
      extra={<ItemMoneyBlock m={d.money} />}
      tabs={tabs}
    />
  )
}

// Тело «Состава» — аккордеон с динамическим Парето (2026-10-20, как «Приборы» проекта).
// Свой компонент раскрывается в своё поддерево (только чтение: правится собственный
// состав, чужой — в форме компонента). Подсветка — по ФРОНТУ раскрытия: видимые строки,
// которые сами не раскрыты; раскрытая строка гаснет, её место занимают дети. Кол-во во
// вложенных строках — накопленное (штук на одно это изделие), поэтому сумма фронта всегда
// равна оценке изделия по составу. Без раскрытий подсветка совпадает с движком.
type BomLine = ItemDetail['bom'][number]
function BomBody({ lines, no, locked, busy, openItem, run }: {
  lines: BomLine[]; no: (b: BomLine) => number | undefined; locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<ItemDetail>) => void
}) {
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [expanded, setExpanded] = useState<Map<number, Set<number>>>(new Map())
  const toggleLine = (id: number) => setOpen(s => {
    const next = new Set(s)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })
  const toggleNode = (id: number, i: number) => setExpanded(m => {
    const next = new Map(m)
    const set = new Set(next.get(id) ?? [])
    if (set.has(i)) set.delete(i); else set.add(i)
    next.set(id, set)
    return next
  })
  const visible = new Map(lines.map(b => [b.id, visibleTree(b.tree, expanded.get(b.id) ?? new Set())]))
  const frontier: { key: string; cost: number | null }[] = []
  for (const b of lines) {
    if (!open.has(b.id)) { frontier.push({ key: `l${b.id}`, cost: b.cost }); continue }
    for (const v of visible.get(b.id) ?? [])
      if (!(v.hasChildren && v.isExp)) frontier.push({ key: `n${b.id}:${v.i}`, cost: v.n.cost })
  }
  const costly = paretoKeys(frontier)
  return <tbody>{lines.map(b => {
    const isOpen = open.has(b.id)
    return <Fragment key={b.id}>
      <tr className="row">
        <td className="rn">{no(b)}</td>
        <td className="gl"><ItemGlyph native={b.component_native} synced={b.component_synced} locked={b.component_locked} /></td>
        <td className="c-key"><span className="tree-cell">
          {b.tree.length > 0
            ? <button className="chev" title={isOpen ? 'свернуть' : 'раскрыть состав'}
                onClick={() => toggleLine(b.id)}><Chevron open={isOpen} /></button>
            : <span className="tree-lead" />}
          <EntityLink kind="item" id={b.component_id} open={openItem}>
            {b.component_code}</EntityLink></span></td>
        <td className="c-desc">
          <span className="cell-ellip" title={b.component_description}>{b.component_description}</span></td>
        <td className="num">
          {!locked
            ? <CommitInput value={String(b.qty)} disabled={busy}
                onCommit={v => run(api.updateBomLine(b.id, { qty: Number(v) }))}
                validate={v => Number(v) > 0} />
            : num(b.qty)}
        </td>
        <td className="uom">{b.component_uom}</td>
        <td className="num c-money">
          <Cost cost={b.cost} status={!isOpen && costly.has(`l${b.id}`) ? 'costly' : null} /></td>
        {!locked && <td className="act">
          <button className="fh-ctl icon fh-del" title="Убрать компонент из состава"
            disabled={busy} onClick={() => run(api.deleteBomLine(b.id))}>
            <span className="ci ci-trash" /></button>
        </td>}
      </tr>
      {isOpen && (visible.get(b.id) ?? []).map(({ n, i, hasChildren, isExp }) => (
        <tr key={i} className="row">
          <td className="rn" />
          <td className="gl"><ItemGlyph native={n.component_native} synced={n.component_synced} locked={n.component_locked} /></td>
          {/* Отступ — по глубине: вычисляемая инлайн-ширина, как в дереве «Приборов». */}
          <td className="c-key"><span className="tree-cell" style={{ paddingLeft: (n.depth + 1) * 18 }}>
            {hasChildren
              ? <button className="chev" title={isExp ? 'свернуть подсборку' : 'раскрыть подсборку'}
                  onClick={() => toggleNode(b.id, i)}><Chevron open={isExp} /></button>
              : <span className="tree-lead" />}
            <EntityLink kind="item" id={n.component_id} open={openItem}>
              {n.component_code}</EntityLink></span></td>
          <td className="c-desc">
            <span className="cell-ellip" title={n.component_description}>{n.component_description}</span></td>
          <td className="num" title="штук на одно это изделие">{num(n.qty)}</td>
          <td className="uom">{n.uom}</td>
          <td className="num c-money">
            <Cost cost={n.cost}
              status={!(hasChildren && isExp) && costly.has(`n${b.id}:${i}`) ? 'costly' : null} /></td>
          {!locked && <td className="act" />}
        </tr>))}
    </Fragment>
  })}</tbody>
}

// Блок «Деньги» изделия (волна 26). Главное — факт, где он есть: у покупного — последняя
// цена по счёту; у производимого (своего ещё не паяем) — живой пересчёт оценки по составу.
// Все числа и сигналы считает движок (`engine.item_money`), здесь только знак.
function ItemMoneyBlock({ m }: { m: ItemMoney }) {
  const stock = <Stat label="на складах" value={money(m.stock_value)} dim={m.stock_value === 0}
    title="Стоимость живых остатков всех партий изделия во всех проектах" />
  if (m.native) {
    const incomplete = m.incomplete ?? []
    return (
      <StatPanel>
        <Stat main label="оценка по составу" value={money(m.rollup ?? 0)}
          note="живой пересчёт" title="Σ(компонент × кол-во) по BOM до листьев — прямо сейчас" />
        <StatGroup>
          {(m.top ?? []).map(t => (
            <Stat key={t.id} label={t.code} value={money(t.cost)}
              title={`вклад компонента в оценку: ${num(t.qty)} × оценка`} />))}
          {stock}
        </StatGroup>
        {m.estimate_stale &&
          <StatWarn title="живой пересчёт разошёлся с сохранённой оценкой — нажмите «Переоценить»">
            оценка устарела: сохранена {m.estimate != null ? money(m.estimate) : '—'} — переоцените
          </StatWarn>}
        {incomplete.length > 0 &&
          <StatWarn title={'без цены: ' + incomplete.join(', ')}>
            {count(incomplete.length, 'позиция', 'позиции', 'позиций')} без цены — оценка неполна
          </StatWarn>}
      </StatPanel>
    )
  }
  const doc = m.last_doc
  const drift = m.estimate_drift ?? null
  return (
    <StatPanel>
      <Stat main label="последняя цена" value={m.last != null ? unitMoney(m.last) : '—'}
        dim={m.last == null}
        note={doc ? `${doc.date ? viewDate(doc.date) : ''} · ${doc.contractor_code || doc.contractor_name}`
          : 'счетов ещё не было'}
        title={doc ? `за штуку · ${doc.kind === 'purchase' ? 'заказ' : 'поставка без заказа'} ${doc.code ?? ''}`
          : undefined} />
      <StatGroup>
        <Stat label="средняя" value={m.avg != null ? unitMoney(m.avg) : '—'} dim={m.avg == null}
          title={`взвешенная по количеству: все деньги ÷ все штуки (${m.facts ?? 0} док., образцы с нулевой ценой не в счёт)`} />
        <Stat label="максимальная" value={m.max != null ? unitMoney(m.max) : '—'}
          dim={m.max == null} title="потолок цены за штуку — риск для плана" />
        {stock}
      </StatGroup>
      {m.last != null && m.estimate_off &&
        <StatWarn title="оценка — цена, по которой считаются планы всех проектов">
          {m.estimate == null || drift === null
            ? 'оценки нет — возьмите последнюю цену в оценку'
            : `оценка ${drift < 0 ? 'ниже' : 'выше'} последней цены на ${Math.abs(Math.round(drift * 100))}%`
              + ` — планы проектов ${drift < 0 ? 'занижены' : 'завышены'}`}
        </StatWarn>}
    </StatPanel>
  )
}

// Добавить компонент в состав: пикер изделий (кроме самого и уже добавленных) + кол-во.
// Циклы/дубли ловит бэкенд — здесь только базовый отсев для чистого списка.
// Ф3 (волна 16) сделала здесь первый type-ahead; Ф2 (волна 19) вынесла его в общий
// `ItemPicker` — этот блок стал тонкой обёрткой: отсев кандидатов + кол-во + кнопка.
// Пока компонент не выбран — кнопка заблокирована.
function AddComponent({ items, parentId, bom, busy, add }: {
  items: ItemRow[]; parentId: number; bom: ItemDetail['bom']; busy: boolean
  add: (componentId: number, qty: number) => void
}) {
  const options = useMemo(() => {
    const taken = new Set(bom.map(b => b.component_id))
    return items.filter(i => i.id !== parentId && !taken.has(i.id))
  }, [items, parentId, bom])
  const [componentId, setComponentId] = useState<number | ''>('')
  const [qty, setQty] = useState('1')

  const submit = () => {
    const n = Number(qty)
    if (!componentId || !(n > 0)) return
    add(componentId, n)
    setComponentId('')
  }

  if (options.length === 0)
    return <div className="kit-actions">
      <span className="lbl">Нет доступных изделий — добавить в состав нечего.</span></div>
  // Язык добавления — общий со строкой-призраком таблиц (правка Ивана 2026-08-11):
  // ведущая подпись «＋ компонент» снята (её работу делает заголовок поля), а команда —
  // кнопка-глиф `add`, пара корзины в строке. Панель осталась панелью: она стоит ПОД
  // таблицей, а не в ней, и колонок у неё нет — совпадают приёмы, не геометрия.
  return (
    <div className="kit-actions">
      <ItemPicker items={options} value={componentId} onPick={setComponentId}
        disabled={busy} onEnter={submit} placeholder="Компонент…"
        onClear={() => setComponentId('')}
        notFound="ничего не найдено — компонент должен быть в справочнике изделий." />
      <input className="qty-in" value={qty} disabled={busy}
        onChange={e => setQty(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && componentId) submit() }} />
      <button className="fh-ctl icon fh-add" title="Добавить компонент в состав"
        disabled={busy || !componentId} onClick={submit}>
        <span className="ci ci-add" /></button>
    </div>
  )
}
