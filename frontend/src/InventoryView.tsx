// Витрина волны 9: форма инвентаризации (записываемое ядро, 4-й origin партии).
// Строки акта = лоты (отдельной InventoryLine в модели нет): изделие + кол-во +
// цена + название, автосейв по blur/Enter. Добавление строки = рождение «найденной»
// партии (+RECEIPT). Замка нет — правимо всегда; guard'ы держат корректность.
// Payoff волны — серая ре-материализация: пикер «из списанных» рождает лот-потомок
// с provenance (predecessor → списанный, наследование item/цены/названия/зав.№).
//
// Волна 19 (Ф12c): форма по канону §13 — табы Строки · Списанные (только в правке) ·
// Файлы. Аккордеон-секция «Ре-материализация» стала табом: несколько списков формы
// разрешаются табами, а не простынёй секций (§13.7).
import { useEffect, useState } from 'react'
import { api, type ItemRow, type InventoryForm, type InventoryFormLot,
  type WrittenOffLot } from './api'
import { LotGlyph, count, money, moneyField, num, parseMoney, perUnitTitle, sumByUom } from './status'
import { CommitInput } from './CommitInput'
import { OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { MoneyBlock } from './StatPanel'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { ItemPicker } from './Picker'
import { EntityLink } from './EntityLink'

export function InventoryView({ inventoryId, items, isNew, openItem, openProject,
  onChanged, onDeleted }: {
  inventoryId: number; items: ItemRow[]; isNew: boolean
  openItem: (id: number) => void; openProject: (id: number) => void
  onChanged: () => void; onDeleted: () => void
}) {
  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    inventoryId, api.inventory, {
      onChanged, onDeleted,
      remove: api.deleteInventory,
      confirmDelete: { noun: 'инвентаризацию' },
    }, isNew)
  const att = useAttachments('inventory', inventoryId)   // загрузка — команда шапки (§13.8)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.locked                   // проведено — read-only (единый мягкий замок)
  const locked = fixed || !unlocked

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="rn">№</th><th className="gl" /><th className="c-key">Изделие</th>
              <th className="c-desc">Описание</th>
              <th className="num">Кол-во</th><th className="uom">Ед.</th>
              <th className="num c-money" title="стоимость всей строки — как в документе; цена штуки — под курсором">Стоимость</th>
              <th className="c-txt">Part number</th><th className="c-txt">Название</th>
              <th className="c-fit">Провенанс</th><th className="act" />
            </tr>
          </thead>
          <tbody>
            {c.lots.map((lot, i) => (
              <LotRow key={lot.id} no={i + 1} lot={lot} locked={locked} draft={!fixed} busy={busy}
                openItem={openItem} run={run} />
            ))}
            {!locked && <GhostRow inventoryId={c.id} items={items} busy={busy} run={run} />}
          </tbody>
        </table>
        {c.lots.length === 0 && locked && <div className="tab-empty">Акт пуст.</div>}
      </> },
  ]
  // «Из списанных» — рабочий стол ре-материализации: показываем только в правке,
  // как и прочие контролы, меняющие данные (§5).
  if (!locked) tabs.push({
    key: 'written-off', label: 'Списанные', icon: 'archive',
    content: <RematerializeTab inventoryId={c.id} busy={busy} run={run} />,
  })
  tabs.push({ key: 'files', label: 'Файлы', icon: 'files',
    content: <AttachmentList att={att} locked={locked} /> })

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="инвентаризацию" locked={locked} error={err}
      meta={<>
        {count(c.lots.length, 'партия', 'партии', 'партий')}
        {sumByUom(c.lots).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockInventory(c.id))}
      fixateTitle="Зафиксировать акт инвентаризации"
      onUnfix={() => run(api.unlockInventory(c.id))}
      fixation={`inventories/${c.id}`}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл — появится в табе «Файлы»', disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy} numberLabel="№ акта"
          openProject={openProject}
          patch={b => run(api.updateInventory(c.id, b))} />}
      // Блок «Деньги» (волна 26): у ордера одно число — сумма его движений.
      extra={<MoneyBlock label="нашли на сумму" value={c.total_cost}
        title="Стоимость найденных партий — введённая или доля списанного предшественника" />}
      tabs={tabs}
    />
  )
}

// Реальная строка акта (найденный лот): автосейв кол-ва/цены/названия, удаление.
// `draft` — акт не проведён (Ф15): найденная партия ещё не на складе, живости у неё
// нет — остаток не показываем, глиф нейтральный (иначе «остаток 0» на каждой строке).
function LotRow({ no, lot, locked, draft, busy, openItem, run }: {
  no?: number
  lot: InventoryFormLot; locked: boolean; draft: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<InventoryForm>) => void
}) {
  const short = !draft && lot.live_qty !== lot.qty   // просел под последующий расход
  return (
    <tr className="row">
      <td className="rn">{no}</td>
      {/* Строка = партия, рождённая этим актом (origin = инвентаризация). */}
      <td className="gl"><LotGlyph origin="inventory" liveQty={lot.live_qty} draft={draft} /></td>
      <td className="c-key">
        <EntityLink kind="item" id={lot.item_id} open={openItem}>{lot.item_code}</EntityLink></td>
      <td className="c-desc">
        <span className="cell-ellip" title={lot.item_description}>{lot.item_description}</span>
        {short && <span className="hint">остаток {num(lot.live_qty)} {lot.uom}</span>}
      </td>
      <td className="num">
        <CommitInput value={String(lot.qty)} disabled={locked || busy}
          onCommit={v => run(api.updateInventoryLot(lot.id, { qty: Number(v) }))}
          validate={v => Number(v) > 0} />
      </td>
      <td className="uom">{lot.uom}</td>
      {/* Волна 26: стоимость строки целиком (как в документе), цена штуки — под курсором.
          Пустой ввод — ноль: у партии стоимость есть всегда. В просмотре — деньгами, как
          цена строки заказа (поле с «20054,26» читается хуже «20 054,26 ₽»). */}
      <td className="num c-money" title={perUnitTitle(lot.cost, lot.qty)}>
        {locked ? money(lot.cost)
          : <CommitInput value={moneyField(lot.cost)} disabled={busy} numeric
              onCommit={v => run(api.updateInventoryLot(lot.id, { cost: parseMoney(v) ?? 0 }))}
              validate={v => v.trim() === '' || (parseMoney(v) ?? -1) >= 0} />}
      </td>
      <td className="c-txt">
        <CommitInput value={lot.part_number} disabled={locked || busy}
          onCommit={v => run(api.updateInventoryLot(lot.id, { part_number: v }))} />
      </td>
      <td className="c-txt">
        <CommitInput value={lot.lot_name} disabled={locked || busy}
          onCommit={v => run(api.updateInventoryLot(lot.id, { lot_name: v }))} />
      </td>
      <td className="c-fit">
        {lot.predecessor_id
          ? <span className="hint" title="ре-материализовано из списанного лота">
              <span className="ci sg ci-arrow-left" /> {lot.predecessor_label}</span>
          : 'излишек'}
      </td>
      <td className="act">
        {!locked && !lot.consumed &&
          <button className="fh-ctl icon fh-del" title="Убрать строку акта"
            disabled={busy} onClick={() => run(api.deleteInventoryLot(lot.id))}>
            <span className="ci ci-trash" /></button>}
        {lot.consumed && <span className="hint">потреблён</span>}
      </td>
    </tr>
  )
}

// Призрачная строка: добавить найденную партию-излишек (без provenance).
function GhostRow({ inventoryId, items, busy, run }: {
  inventoryId: number; items: ItemRow[]; busy: boolean
  run: (p: Promise<InventoryForm>) => void
}) {
  const [itemId, setItemId] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  const [cost, setCost] = useState('')
  const [pn, setPn] = useState('')
  const [name, setName] = useState('')
  const picked = items.find(i => i.id === itemId)   // единица известна сразу по выбору

  const add = () => {
    const q = Number(qty)
    if (!itemId || !(q > 0)) return
    run(api.addInventoryLot(inventoryId, {
      item_id: itemId, qty: q,
      cost: parseMoney(cost) ?? undefined,
      part_number: pn || undefined,
      lot_name: name || undefined,
    }))
    setItemId(''); setQty(''); setCost(''); setPn(''); setName('')
  }

  return (
    <tr className="row ghost">
      <td className="rn" />
      <td className="gl" />
      {/* Призрак — такая же строка, как данные (волна 25, Ф3): пикер в колонке кода,
          описание выбранного — в своей. Под `colSpan` спрятанная колонка описания
          сдвигала бы всю строку. */}
      <td className="c-key">
        <ItemPicker items={items} value={itemId} onPick={setItemId} disabled={busy}
          placeholder="Изделие…" onEnter={add} onClear={() => setItemId('')} />
      </td>
      <td className="c-desc">
        <span className="cell-ellip" title={picked?.description}>
          {picked?.description ?? ''}</span></td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="uom">{picked?.uom ?? ''}</td>
      <td className="num c-money">
        <input className="qty-in" value={cost} disabled={busy} placeholder="0,00"
          onChange={e => setCost(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="c-txt">
        <input className="qty-in" value={pn} disabled={busy}
          placeholder="part number" onChange={e => setPn(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="c-txt">
        <input className="qty-in" value={name} disabled={busy}
          placeholder="название" onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="c-fit">излишек</td>
      <td className="act">
        <button className="fh-ctl icon fh-add" title="Добавить найденную партию"
          disabled={busy || !itemId || !(Number(qty) > 0)} onClick={add}>
          <span className="ci ci-add" /></button>
      </td>
    </tr>
  )
}

// Таб «Списанные»: серая ре-материализация — вернуть найденный физически списанный
// (серый) остаток на баланс. Порождает лот-потомок с provenance. Был аккордеон-секцией
// под формой; по канону §13.7 второй список формы = свой таб.
function RematerializeTab({ inventoryId, busy, run }: {
  inventoryId: number; busy: boolean; run: (p: Promise<InventoryForm>) => void
}) {
  const [lots, setLots] = useState<WrittenOffLot[]>([])

  useEffect(() => { api.writtenOffLots().then(setLots) }, [inventoryId])

  const rematerialize = (lot: WrittenOffLot) => {
    run(api.addInventoryLot(inventoryId, {
      predecessor_id: lot.lot_id, qty: Number(lot.written_qty),
    }))
  }

  if (lots.length === 0) return <div className="tab-empty">Списанных партий нет.</div>
  return (
    <table className="grid">
      <thead>
        <tr>
          <th className="rn">№</th><th className="gl" /><th className="c-key">Изделие</th>
          <th className="c-desc">Описание</th>
          <th className="c-fit">Проект-источник</th>
          <th className="num">Списано</th><th className="uom">Ед.</th>
          <th className="c-fit">Название</th><th className="act" />
        </tr>
      </thead>
      <tbody>
        {lots.map((l, i) => (
          <tr key={l.lot_id} className="row">
            <td className="rn">{i + 1}</td>
            {/* Партия списана — живого остатка нет: глиф приглушён по определению. */}
            <td className="gl"><LotGlyph origin={null} liveQty={0} /></td>
            <td className="c-key">{l.item_code}</td>
            <td className="c-desc">
              <span className="cell-ellip" title={l.item_description}>{l.item_description}</span></td>
            <td className="c-fit code">{l.project_code}</td>
            <td className="num">{num(l.written_qty)}</td>
            <td className="uom">{l.uom}</td>
            <td className="c-fit">{l.lot_name || '—'}</td>
            <td className="act">
              <button className="btn sm" disabled={busy}
                onClick={() => rematerialize(l)}>вернуть на баланс</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
