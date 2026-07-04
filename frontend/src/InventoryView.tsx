// Витрина волны 9: кокпит инвентаризации (записываемое ядро, 4-й origin партии).
// Строки акта = лоты (отдельной InventoryLine в модели нет): изделие + кол-во +
// цена + название, автосейв по blur/Enter. Добавление строки = рождение «найденной»
// партии (+RECEIPT). Замка нет — правимо всегда; guard'ы держат корректность.
// Payoff волны — серая ре-материализация: пикер «из списанных» рождает лот-потомок
// с provenance (predecessor → списанный, наследование item/цены/названия/зав.№).
import { useEffect, useState } from 'react'
import { api, type ItemRow, type InventoryCockpit, type InventoryCockpitLot,
  type WrittenOffLot } from './api'
import { num } from './status'
import { CommitInput } from './ReceiptView'
import { AttachmentPanel } from './AttachmentPanel'

export function InventoryView({ inventoryId, items, openItem, onChanged }: {
  inventoryId: number; items: ItemRow[]
  openItem: (id: number) => void; onChanged: () => void
}) {
  const [c, setC] = useState<InventoryCockpit | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setC(null); setErr(null)
    api.inventory(inventoryId).then(setC).catch(e => setErr(String(e)))
  }, [inventoryId])

  const run = (p: Promise<InventoryCockpit>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  return (
    <div>
      <h1 className="title">
        <span className="glyph g-available">🔍</span>{' '}
        <span className="pn">Инвентаризация {c.number}</span>{' '}
        <span className="lit">— {c.project_code}</span>
      </h1>
      <div className="subtitle">
        Кокпит инвентаризации · рождение «найденных» партий (+RECEIPT) · проект{' '}
        {c.project_name} · {c.date}
        {' · сумма '}<span className="seg">{num(c.total_cost)} ₽</span>
      </div>

      <div className="hdr-edit">
        <label>№ акта <CommitInput value={c.number} width={140} disabled={busy}
          onCommit={v => run(api.updateInventory(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></label>
        <label>дата <CommitInput value={c.date} width={140} type="date" disabled={busy}
          onCommit={v => run(api.updateInventory(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></label>
        <label>примечание <CommitInput value={c.note} width={220} disabled={busy}
          onCommit={v => run(api.updateInventory(c.id, { note: v }))} /></label>
      </div>

      {busy && <span className="hint">сохраняю…</span>}
      {err && <span className="anomaly">{err}</span>}

      <table className="grid">
        <thead>
          <tr>
            <th>изделие</th><th style={{ textAlign: 'right' }}>кол-во</th>
            <th style={{ textAlign: 'right' }}>цена, ₽</th><th>название</th>
            <th>провенанс</th><th />
          </tr>
        </thead>
        <tbody>
          {c.lots.map(lot => (
            <LotRow key={lot.id} lot={lot} busy={busy} openItem={openItem} run={run} />
          ))}
          <GhostRow inventoryId={c.id} items={items} busy={busy} run={run} />
        </tbody>
      </table>
      {c.lots.length === 0 && <div className="empty">Акт пуст — добавьте найденную партию.</div>}

      <RematerializePanel inventoryId={c.id} busy={busy} run={run} />

      <AttachmentPanel ownerType="inventory" ownerId={c.id} />
    </div>
  )
}

// Реальная строка акта (найденный лот): автосейв кол-ва/цены/названия, удаление.
function LotRow({ lot, busy, openItem, run }: {
  lot: InventoryCockpitLot; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<InventoryCockpit>) => void
}) {
  const short = lot.live_qty !== lot.qty   // просел под последующий расход
  return (
    <tr className="row s-available">
      <td>
        <span className="glyph g-available">✓</span>{' '}
        <a className="link" onClick={() => openItem(lot.item_id)}>{lot.item_code}</a>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>{lot.item_name}</span>
        {short && <span className="hint">остаток {num(lot.live_qty)} {lot.uom}</span>}
      </td>
      <td className="num">
        <CommitInput value={String(lot.qty)} width={60} disabled={busy}
          onCommit={v => run(api.updateInventoryLot(lot.id, { qty: Number(v) }))}
          validate={v => Number(v) > 0} /> {lot.uom}
      </td>
      <td className="num">
        <CommitInput value={String(lot.unit_cost)} width={72} disabled={busy}
          onCommit={v => run(api.updateInventoryLot(lot.id, { unit_cost: Number(v) }))}
          validate={v => Number(v) >= 0} />
      </td>
      <td>
        <CommitInput value={lot.received_name} width={160} disabled={busy}
          onCommit={v => run(api.updateInventoryLot(lot.id, { received_name: v }))} />
      </td>
      <td>
        {lot.predecessor_id
          ? <span className="hint" title="ре-материализовано из списанного лота">
              ← {lot.predecessor_label}</span>
          : <span style={{ color: 'var(--fg-dim)' }}>излишек</span>}
      </td>
      <td style={{ textAlign: 'right' }}>
        {!lot.consumed &&
          <button className="x" title="убрать строку" disabled={busy}
            onClick={() => run(api.deleteInventoryLot(lot.id))}>×</button>}
        {lot.consumed && <span className="hint">потреблён</span>}
      </td>
    </tr>
  )
}

// Призрачная строка: добавить найденную партию-излишек (без provenance).
function GhostRow({ inventoryId, items, busy, run }: {
  inventoryId: number; items: ItemRow[]; busy: boolean
  run: (p: Promise<InventoryCockpit>) => void
}) {
  const [itemId, setItemId] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  const [cost, setCost] = useState('')
  const [name, setName] = useState('')

  const add = () => {
    const q = Number(qty)
    if (!itemId || !(q > 0)) return
    run(api.addInventoryLot(inventoryId, {
      item_id: itemId, qty: q,
      unit_cost: cost === '' ? undefined : Number(cost),
      received_name: name || undefined,
    }))
    setItemId(''); setQty(''); setCost(''); setName('')
  }

  return (
    <tr className="row ghost">
      <td>
        <select className="lot-sel" value={itemId} disabled={busy}
          onChange={e => setItemId(e.target.value ? Number(e.target.value) : '')}>
          <option value="">＋ изделие…</option>
          {items.map(i => <option key={i.id} value={i.id}>{i.code} — {i.name}</option>)}
        </select>
      </td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="num">
        <input className="qty-in" value={cost} disabled={busy} placeholder="0"
          onChange={e => setCost(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td>
        <input className="qty-in" style={{ width: 160 }} value={name} disabled={busy}
          placeholder="название" onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td><span style={{ color: 'var(--fg-dim)' }}>излишек</span></td>
      <td style={{ textAlign: 'right' }}>
        <button className="btn sm" disabled={busy || !itemId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}

// Панель «из списанных»: серая ре-материализация — вернуть найденный физически
// списанный (серый) остаток на баланс. Порождает лот-потомок с provenance.
function RematerializePanel({ inventoryId, busy, run }: {
  inventoryId: number; busy: boolean; run: (p: Promise<InventoryCockpit>) => void
}) {
  const [lots, setLots] = useState<WrittenOffLot[]>([])
  const [open, setOpen] = useState(false)

  useEffect(() => { if (open) api.writtenOffLots().then(setLots) }, [open, inventoryId])

  const rematerialize = (lot: WrittenOffLot) => {
    run(api.addInventoryLot(inventoryId, {
      predecessor_id: lot.lot_id, qty: Number(lot.written_qty),
    }))
  }

  return (
    <div className="closure">
      <h2 className="section-h" onClick={() => setOpen(o => !o)} style={{ cursor: 'pointer' }}>
        {open ? '▾' : '▸'} Ре-материализация из списанных (серый путь → на баланс)
      </h2>
      {open && (lots.length === 0
        ? <div className="empty">Списанных лотов нет.</div>
        : <table className="grid">
            <thead>
              <tr>
                <th>изделие</th><th>проект-источник</th>
                <th style={{ textAlign: 'right' }}>списано</th>
                <th>зав.№</th><th />
              </tr>
            </thead>
            <tbody>
              {lots.map(l => (
                <tr key={l.lot_id} className="row">
                  <td>{l.item_code} <span style={{ color: 'var(--fg-dim)' }}>{l.item_name}</span></td>
                  <td>{l.project_code}</td>
                  <td className="num">{num(l.written_qty)} {l.uom}</td>
                  <td>{l.serial_number || '—'}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button className="btn sm" disabled={busy}
                      onClick={() => rematerialize(l)}>вернуть на баланс</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>)}
    </div>
  )
}
