// Витрина волны 3: форма поставки / УПД (записываемое ядро).
// Строки УПД = лоты (в модели отдельной ReceiptLine нет): изделие + наименование товара +
// part number + кол-во + стоимость, автосейв по blur/Enter. Добавление строки = рождение
// партии (+RECEIPT). Фиксация «сверено со сканом» делает форму read-only.
//
// 2026-10-20 (решение Ивана): строка читается как графа УПД. Колонки «Описание» (описание
// изделия из справочника) нет — на её месте «Наименование товара» (графа 1а УПД, бывшее
// «Название из УПД»): пользователь видит, что куда переписывать. Описание изделия — в
// подсказке к коду. Просмотр чист (§7): текст вместо погашенных полей, колонка команд
// строки — только в правке, как у заказа.
import { type KeyboardEvent, useEffect, useState } from 'react'
import { api, type CounterpartyRow, type ItemRow, type ProjectPurchaseRow,
  type ReceiptForm, type ReceiptLot } from './api'
import { CommitInput } from './CommitInput'
import { num, money, count, sumByUom, CounterpartyRef, LotGlyph,
  MismatchGlyph, gapMoney, moneyCol, moneyField, parseMoney, perUnitTitle, rowNumbers } from './status'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { LocationField, OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { MoneyBlock, Stat, StatGroup } from './StatPanel'
import { Field } from './FormField'
import { CounterpartyPicker, ItemPicker, PurchasePicker } from './Picker'
import { useCategoryFilter } from './ColumnFilter'
import { EntityLink, LotLink } from './EntityLink'

export function ReceiptView({ receiptId, items, isNew, openItem, openPurchase, openProject,
  openCounterparty, openLot, openLocation, onChanged, onDeleted }: {
  receiptId: number; items: ItemRow[]; isNew: boolean
  openItem: (id: number) => void; openPurchase: (id: number) => void
  openProject: (id: number) => void; openCounterparty: (id: number) => void
  openLot: (id: number) => void; openLocation: (id: number) => void
  onChanged: () => void; onDeleted: () => void
}) {
  const [purchases, setPurchases] = useState<ProjectPurchaseRow[]>([])
  // Ф12e: поставщик задавался ТОЛЬКО в форме создания и в шапке не жил — после её
  // сноса поставку было бы нечем укомплектовать до фиксации.
  const [suppliers, setSuppliers] = useState<CounterpartyRow[]>([])
  const reloadSuppliers = () => api.counterparties().then(setSuppliers)
  useEffect(() => { reloadSuppliers() }, [])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    receiptId, api.receipt, {
      onChanged, onDeleted,
      onLoad: c => { api.projectPurchases(c.project_id).then(setPurchases) },
      remove: api.deleteReceipt,
      confirmDelete: { noun: 'поставку', lines: ['рождённые партии будут сняты'] },
    }, isNew)
  const att = useAttachments('receipt', receiptId)   // загрузка — команда шапки (§13.8)
  // Фильтр строк по классу изделия — общий движок (2026-08-10): в УПД на сотню позиций
  // «покажи только конденсаторы» — тот же вопрос, что к составу прибора.
  const byCat = useCategoryFilter(c?.lots, l => l.item_category, receiptId)
  const no = rowNumbers(c?.lots)        // постоянный номер строки — по всем партиям

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.locked                 // фиксация (проведена/сверена) — read-only
  const locked = fixed || !unlocked        // + личный замок формы
  // Имя заказа для ссылки под замком: заказ известен формой по id, идентичность
  // берём из списка заказов проекта (он же кормит пикер).
  const purchaseLabel = purchases.find(p => p.id === c.purchase_id)?.code
    ?? `Заказ #${c.purchase_id}`
  // Ф17: расхождение с контрагентом заказа — предупреждение, не гейт (флаг от движка).
  const mismatch = c.contractor_mismatch
    ? <MismatchGlyph title="Не совпадает с контрагентом указанного заказа" />
    : null

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="rn">№</th><th className="gl" /><th className="c-key">Компонент{byCat.head}</th>
              <th className="c-desc c-txt" title="как в графе 1а УПД">Наименование товара</th>
              <th className="c-txt">PN</th>
              <th className="num">Кол-во</th>
              <th className="uom">Ед.</th>
              <th className="num c-money" title="стоимость всей строки — как в документе; цена штуки — под курсором">Стоимость, ₽</th>
              {!locked && <th className="act" />}
            </tr>
          </thead>
          <tbody>
            {byCat.shown.map(lot => (
              <LotRow key={lot.id} no={no.get(lot)} lot={lot} locked={locked} draft={!fixed} busy={busy}
                openItem={openItem} openLot={openLot} run={run} />
            ))}
            {!locked && <GhostRow receiptId={c.id} items={items} busy={busy} run={run} />}
          </tbody>
        </table>
        {c.lots.length === 0 && locked &&
          <div className="tab-empty">Поставка пуста.</div>}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="поставку" locked={locked} error={err}
      // Мета (§13.6): счёт по табам + то, чего в табах нет. Итог поставки — не одно
      // число: физически это «сколько чего приехало», а единицы у строк разные, и
      // складывать штуки с метрами нельзя. Поэтому кол-во сворачивается ПО ЕДИНИЦАМ
      // («10 344 шт · 50 м»); деньги — в блоке «Деньги» (волна 26).
      meta={<>
        {count(c.lots.length, 'позиция', 'позиции', 'позиций')}
        {sumByUom(c.lots).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockReceipt(c.id))}
      fixateTitle="Сверено со сканом — зафиксировать поставку"
      onUnfix={() => run(api.unlockReceipt(c.id))}
      fixation={`receipts/${c.id}`}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (скан УПД) — появится в табе «Файлы»', disabled: att.busy }]}
      // Ф17: последняя рукописная шапка в проекте переехала на общий `OrderFields`
      // (кастомных шапок не осталось). Якори вида — в слот `anchors` сразу за Проектом:
      // Проект → Заказ → Поставщик, затем № поставки, Дата, Автор (§13.4a).
      fields={
        <OrderFields c={c} locked={locked} busy={busy} numberLabel="№ поставки"
          openProject={openProject}
          patch={b => run(api.updateReceipt(c.id, b))}
          anchors={<>
            {/* Якорь-заказ переехал из тела формы в поля шапки (§13.3): это ссылка
                документа, а не список — в теле он висел отдельной строкой `.kit-actions`.
                Под замком поле = САМА ССЫЛКА на заказ (отдельная кнопка «открыть ›» не
                нужна: кликабельно то, что названо). */}
            <Field label="Заказ" locked={locked}
              view={c.purchase_id
                ? <EntityLink kind="purchase" id={c.purchase_id}
                    open={openPurchase}>{purchaseLabel}</EntityLink>
                : ''}>
              <PurchasePicker purchases={purchases} value={c.purchase_id ?? ''}
                disabled={busy}
                onPick={id => run(api.linkReceiptPurchase(c.id, id))}
                onClear={() => run(api.linkReceiptPurchase(c.id, null))} />
            </Field>
            {/* Ф12e: поставщик обязателен к ФИКСАЦИИ, а не к рождению — значит его
                место в шапке. «Завести» прямо из пикера: отдельной формы контрагента
                в продукте нет (заведётся режимом «Контрагенты», волна 20).
                Ф17: глиф расхождения — «кто привёз» ≠ «у кого купили». */}
            <Field label="Поставщик" locked={locked}
              view={c.contractor_id
                ? <><CounterpartyRef code={c.contractor_code} name={c.contractor_name}
                    id={c.contractor_id} open={openCounterparty} />{mismatch}</>
                : ''}>
              <CounterpartyPicker counterparties={suppliers} side="supply"
                value={c.contractor_id ?? ''}
                disabled={busy} placeholder="— не указан —"
                onPick={id => run(api.updateReceipt(c.id, { contractor_id: id }))}
                onClear={() => run(api.updateReceipt(c.id, { contractor_id: null }))}
                onCreate={name => api.createCounterparty({ description: name })
                  .then(cp => { reloadSuppliers()
                    run(api.updateReceipt(c.id, { contractor_id: cp.id })) })} />
              {mismatch}
            </Field>
            {/* Волна 27: «Куда» — по умолчанию Центральный склад (УПД оформляет
                бухгалтерия, в работу партии уходят Требованием). */}
            <LocationField c={c} locked={locked} busy={busy} onOpen={openLocation}
              onChange={id => run(api.updateReceipt(c.id, { location_id: id }))} />
          </>} />}
      // Блок «Деньги» (волна 26): ★ сумма по УПД; поставка из заказа сверяется с его счётом
      // (тем же правилом доли, что родило партии) — расхождение видно сразу.
      extra={<MoneyBlock label="поставка" value={c.total_cost}
        title="Сумма стоимостей строк УПД (факт)">
        {c.by_order !== null && <StatGroup>
          <Stat label="по заказу" value={money(c.by_order)}
            title="Что эти позиции стоят по счёту заказа (доля цены строки)" />
          <Stat label="расхождение" value={gapMoney(c.order_gap ?? 0)}
            title="УПД против счёта по тем же позициям; не ноль — проверьте документы" />
        </StatGroup>}
      </MoneyBlock>}
      tabs={tabs}
    />
  )
}

// Реальная строка УПД (лот): автосейв наименования/part number/кол-ва/стоимости,
// удаление до замка. `draft` — поставка ещё не сверена (Ф15): партия на складе не лежит,
// живого остатка у неё нет вовсе. Показывать «остаток 0» было бы враньём про
// израсходованную партию, поэтому в черновике остаток не показываем, а глиф гасим.
function LotRow({ no, lot, locked, draft, busy, openItem, openLot, run }: {
  no?: number
  lot: ReceiptLot; locked: boolean; draft: boolean; busy: boolean
  openItem: (id: number) => void; openLot: (id: number) => void
  run: (p: Promise<ReceiptForm>) => void
}) {
  const short = !draft && lot.live_qty !== lot.qty   // просел под пайку/расход
  const save = (b: Parameters<typeof api.updateReceiptLot>[1]) =>
    run(api.updateReceiptLot(lot.id, b))
  return (
    <tr className="row">
      <td className="rn">{no}</td>
      {/* Строка = партия, рождённая этой поставкой: глиф партии (форма — изделие/
          компонент, цвет — как дела, в27) — ссылка на форму лота. Описание изделия — в
          подсказке к коду: колонка текста у строки одна, и это наименование из документа. */}
      <td className="gl"><LotLink id={lot.id} open={openLot}>
        <LotGlyph native={lot.item_native} liveQty={lot.live_qty} draft={draft} /></LotLink></td>
      <td className="c-key">
        <EntityLink kind="item" id={lot.item_id} open={openItem} title={lot.item_description}>
          {lot.item_code}</EntityLink></td>
      <td className="c-desc c-txt">
        {locked
          ? <>
              <span className="cell-ellip" title={lot.lot_description}>{lot.lot_description}</span>
              {short && <span className="hint">остаток {num(lot.live_qty)} {lot.uom}</span>}
            </>
          : <CommitInput value={lot.lot_description} disabled={busy}
              onCommit={v => save({ lot_description: v })} />}
      </td>
      <td className="c-txt">
        {locked
          ? <span className="cell-ellip" title={lot.lot_code}>{lot.lot_code}</span>
          : <CommitInput value={lot.lot_code} disabled={busy}
              onCommit={v => save({ lot_code: v })} />}
      </td>
      <td className="num">
        {locked ? num(lot.qty)
          : <CommitInput value={String(lot.qty)} disabled={busy}
              onCommit={v => save({ qty: Number(v) })}
              validate={v => Number(v) > 0} />}
      </td>
      <td className="uom">{lot.uom}</td>
      {/* Волна 26: стоимость строки целиком (как в документе), цена штуки — под курсором.
          Пустой ввод — ноль: у партии стоимость есть всегда. В просмотре — деньгами, как
          цена строки заказа (поле с «20054,26» читается хуже «20 054,26 ₽»). */}
      <td className="num c-money" title={perUnitTitle(lot.cost, lot.qty)}>
        {locked ? moneyCol(lot.cost)
          : <CommitInput value={moneyField(lot.cost)} disabled={busy} numeric
              onCommit={v => save({ cost: parseMoney(v) ?? 0 })}
              validate={v => v.trim() === '' || (parseMoney(v) ?? -1) >= 0} />}
      </td>
      {/* Команда строки — только в правке (§7). Потреблённую партию (расфиксированная
          поставка, партия уже ушла ниже) убрать нельзя — вместо корзины объяснение. */}
      {!locked && <td className="act">
        {lot.consumed
          ? <span className="hint">потреблён</span>
          : <button className="fh-ctl icon fh-del" title="Убрать строку поставки"
              disabled={busy} onClick={() => run(api.deleteReceiptLot(lot.id))}>
              <span className="ci ci-trash" /></button>}
      </td>}
    </tr>
  )
}

// Призрачная строка: добавить строку УПД (рождается партия). Колонки — те же, что у
// данных. Наименование преднабивается описанием выбранного изделия (то же правило, что
// у поставки, рождённой из заказа) — дальше его правят под графу 1а документа.
function GhostRow({ receiptId, items, busy, run }: {
  receiptId: number; items: ItemRow[]; busy: boolean
  run: (p: Promise<ReceiptForm>) => void
}) {
  const [itemId, setItemId] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  const [cost, setCost] = useState('')
  const [pn, setPn] = useState('')
  const [name, setName] = useState('')
  const picked = items.find(i => i.id === itemId)   // единица известна сразу по выбору

  const pick = (id: number) => {
    setItemId(id)
    if (!name) setName(items.find(i => i.id === id)?.description ?? '')
  }
  const add = () => {
    const q = Number(qty)
    if (!itemId || !(q > 0)) return
    run(api.addReceiptLot(receiptId, {
      item_id: itemId, qty: q,
      cost: parseMoney(cost) ?? undefined,
      lot_code: pn || undefined,
      lot_description: name || undefined,
    }))
    setItemId(''); setQty(''); setCost(''); setPn(''); setName('')
  }
  const enter = (e: KeyboardEvent) => { if (e.key === 'Enter') add() }

  return (
    <tr className="row ghost">
      <td className="rn" />
      <td className="gl" />
      {/* Призрак — такая же строка, как данные (волна 25, Ф3): пикер в колонке кода. */}
      <td className="c-key">
        <ItemPicker items={items} value={itemId} onPick={pick} disabled={busy}
          placeholder="Компонент…" onEnter={add} onClear={() => setItemId('')} />
      </td>
      <td className="c-desc c-txt">
        <input className="qty-in" value={name} disabled={busy}
          placeholder="наименование товара" onChange={e => setName(e.target.value)}
          onKeyDown={enter} />
      </td>
      <td className="c-txt">
        <input className="qty-in" value={pn} disabled={busy}
          placeholder="PN" onChange={e => setPn(e.target.value)}
          onKeyDown={enter} />
      </td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy} placeholder="0"
          onChange={e => setQty(e.target.value)} onKeyDown={enter} />
      </td>
      <td className="uom">{picked?.uom ?? ''}</td>
      <td className="num c-money">
        <input className="qty-in" value={cost} disabled={busy} placeholder="0,00"
          onChange={e => setCost(e.target.value)} onKeyDown={enter} />
      </td>
      <td className="act">
        <button className="fh-ctl icon fh-add" title="Добавить строку поставки"
          disabled={busy || !itemId || !(Number(qty) > 0)} onClick={add}>
          <span className="ci ci-add" /></button>
      </td>
    </tr>
  )
}
