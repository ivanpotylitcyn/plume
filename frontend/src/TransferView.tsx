// Витрина волны 5: кокпит передачи / Transfer (записываемое ядро).
// Отгрузка готового железа заказчику по накладной. Строка передачи = отдаём
// партию проекта (`−ISSUE`); добавление/правка/удаление автосейвом. Мягкого
// замка нет (у Transfer нет поля статуса) — правимо всегда; guard корректности —
// «лот не потреблён ниже» на бэке. Отображаемое имя строки печатается в накладной.
import { useEffect, useState } from 'react'
import { api, type AvailableLot, type CounterpartyRow, type TransferCockpit,
  type TransferCockpitLine } from './api'
import { CommitInput } from './ReceiptView'
import { FormHeader, useOrderCockpit } from './FormHeader'
import { num } from './status'
import { AttachmentPanel } from './AttachmentPanel'

export function TransferView({ transferId, openItem, onChanged, onDeleted }: {
  transferId: number
  openItem: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [lots, setLots] = useState<AvailableLot[]>([])
  const [customers, setCustomers] = useState<CounterpartyRow[]>([])
  useEffect(() => { api.counterparties('customer').then(setCustomers) }, [])

  const { c, err, busy, unlocked, toggle, run, del } = useOrderCockpit(
    transferId, api.transfer, {
      onChanged, onDeleted,
      onLoad: c => { api.projectAvailableLots(c.project_id).then(setLots) },
      remove: api.deleteTransfer,
      confirmDelete: 'Удалить передачу (накладную)? Действие необратимо.',
    })

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.posted                   // отгружено (проведена) — read-only
  const locked = fixed || !unlocked
  return (
    <div className={unlocked && !fixed ? '' : 'form-locked'}>
      <FormHeader
        name={`Накладная ${c.number}`}
        meta={<>
          <span className={`glyph ${fixed ? 'g-lock' : 'g-on_order'}`}>{fixed ? '🔒' : '●'}</span>
          {c.project_code} · {c.project_name}
          {c.contractor_name && <> · {c.contractor_name}</>} · {c.date} · отдано {num(c.total_qty)}
        </>}
        unlocked={unlocked} onToggleLock={toggle}
        fixed={fixed} fixedLabel="отгружена"
        onUnfix={() => { if (confirm('Снять фиксацию передачи? Отгрузка откатится, форма станет черновиком.')) run(api.unpostTransfer(c.id)) }}
        onDelete={del}
        error={err}
      />

      <div className="hdr-edit">
        <label>№ накладной <CommitInput value={c.number} width={140} disabled={locked || busy}
          onCommit={v => run(api.updateTransfer(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></label>
        <label>дата <CommitInput value={c.date} width={140} type="date" disabled={locked || busy}
          onCommit={v => run(api.updateTransfer(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></label>
        <label>заказчик{' '}
          <select className="lot-sel" value={c.contractor_id ?? ''} disabled={locked || busy}
            onChange={e => run(api.updateTransfer(c.id, {
              contractor_id: e.target.value ? Number(e.target.value) : null }))}>
            <option value="">— не указан —</option>
            {customers.map(cp => <option key={cp.id} value={cp.id}>{cp.name}</option>)}
          </select>
        </label>
      </div>

      <div className="kit-actions">
        {!fixed &&
          <button className="btn primary" disabled={busy || unlocked}
            title={unlocked ? 'Сначала закройте замок — просмотрите чистовик' : 'Зафиксировать документ'}
            onClick={() => run(api.postTransfer(c.id))}>Отгружено · зафиксировать</button>}
        {err && <span className="anomaly">{err}</span>}
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th>партия</th><th>изделие</th>
            <th style={{ textAlign: 'right' }}>кол-во</th>
            <th style={{ textAlign: 'right' }}>остаток</th>
            <th>имя в накладной</th><th />
          </tr>
        </thead>
        <tbody>
          {c.lines.map(ln => (
            <LineRow key={ln.id} ln={ln} locked={locked} busy={busy}
              openItem={openItem} run={run} />
          ))}
          {!locked && <GhostRow transferId={c.id} lots={lots} busy={busy} run={run} />}
        </tbody>
      </table>
      {c.lines.length === 0 &&
        <div className="empty">Накладная пуста — добавьте партию к отгрузке.</div>}

      <AttachmentPanel ownerType="transfer" ownerId={c.id} />
    </div>
  )
}

// Реальная строка передачи (лот): автосейв кол-ва/имени, удаление (коррекция).
function LineRow({ ln, locked, busy, openItem, run }: {
  ln: TransferCockpitLine; locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<TransferCockpit>) => void
}) {
  const negative = ln.lot_live_qty < 0   // переотдали — источник в минусе
  return (
    <tr className="row s-available">
      <td>
        <span className="glyph g-available">✓</span>{' '}
        <span className="pn">{ln.lot_label}</span>
      </td>
      <td>
        <a className="link" onClick={() => openItem(ln.item_id)}>{ln.item_code}</a>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>{ln.item_name}</span>
      </td>
      <td className="num">
        <CommitInput value={String(ln.qty)} width={60} disabled={locked || busy}
          onCommit={v => run(api.updateTransferLine(ln.id, { qty: Number(v) }))}
          validate={v => Number(v) > 0} /> {ln.uom}
      </td>
      <td className="num">
        <span className={negative ? 'anomaly' : ''}>{num(ln.lot_live_qty)}</span>
        {negative && <span className="anomaly" title="переотдали — источник в минусе">▲</span>}
      </td>
      <td>
        <CommitInput value={ln.display_name} width={200} disabled={locked || busy}
          onCommit={v => run(api.updateTransferLine(ln.id, { display_name: v }))} />
      </td>
      <td style={{ textAlign: 'right' }}>
        {!locked &&
          <button className="x" title="убрать строку" disabled={busy}
            onClick={() => run(api.deleteTransferLine(ln.id))}>×</button>}
      </td>
    </tr>
  )
}

// Призрачная строка: выбрать отдаваемую партию проекта (пикер live>0) + кол-во.
function GhostRow({ transferId, lots, busy, run }: {
  transferId: number; lots: AvailableLot[]; busy: boolean
  run: (p: Promise<TransferCockpit>) => void
}) {
  const [lotId, setLotId] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  const [name, setName] = useState('')
  const picked = lots.find(l => l.lot_id === lotId)

  const add = () => {
    const q = Number(qty)
    if (!lotId || !(q > 0)) return
    run(api.addTransferLine(transferId, {
      lot_id: lotId, qty: q, display_name: name || undefined,
    }))
    setLotId(''); setQty(''); setName('')
  }

  return (
    <tr className="row ghost">
      <td>
        <select className="lot-sel" value={lotId} disabled={busy}
          onChange={e => setLotId(e.target.value ? Number(e.target.value) : '')}>
          <option value="">＋ партия…</option>
          {lots.map(l => (
            <option key={l.lot_id} value={l.lot_id}>
              #{l.lot_id} {l.item_code}{l.lot_name ? ` (${l.lot_name})` : ''} · {num(l.live_qty)} {l.uom}
            </option>
          ))}
        </select>
      </td>
      <td style={{ color: 'var(--fg-dim)' }}>{picked?.item_name ?? ''}</td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy || !lotId} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="num" style={{ color: 'var(--fg-dim)' }}>
        {picked ? num(picked.live_qty) : ''}
      </td>
      <td>
        <input className="qty-in" style={{ width: 200 }} value={name} disabled={busy}
          placeholder="имя в накладной (авто)" onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td style={{ textAlign: 'right' }}>
        <button className="btn sm" disabled={busy || !lotId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
