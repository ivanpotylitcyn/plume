// Витрина волны 5: кокпит передачи / Transfer (записываемое ядро).
// Отгрузка готового железа заказчику по накладной. Строка передачи = отдаём
// партию проекта (`−ISSUE`); добавление/правка/удаление автосейвом. Мягкого
// замка нет (у Transfer нет поля статуса) — правимо всегда; guard корректности —
// «лот не потреблён ниже» на бэке. Отображаемое имя строки печатается в накладной.
import { useEffect, useState } from 'react'
import { api, type AvailableLot, type CounterpartyRow, type TransferCockpit,
  type TransferCockpitLine } from './api'
import { CommitInput } from './ReceiptView'
import { AuthorField, FormHeader, ProjectField, useOrderCockpit } from './FormHeader'
import { StatusGlyph, num } from './status'
import { AttachmentPanel } from './AttachmentPanel'

export function TransferView({ transferId, isNew, openItem, onChanged, onDeleted }: {
  transferId: number
  isNew: boolean
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
    }, isNew)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.locked                   // отгружено (проведена) — read-only
  const locked = fixed || !unlocked
  return (
    <div className={unlocked && !fixed ? '' : 'form-locked'}>
      <FormHeader
        code={c.code || `Накладная ${c.number}`}
        meta={<>
          <StatusGlyph locked={c.locked} />
          {c.project_code} · {c.project_name}
          {c.contractor_name && <> · {c.contractor_name}</>} · {c.date} · отдано {num(c.total_qty)}
        </>}
        unlocked={unlocked} onToggleLock={toggle}
        fixed={fixed}
        onFixate={() => run(api.lockTransfer(c.id))}
        fixateTitle="Отгружено — зафиксировать передачу"
        onUnfix={() => { if (confirm('Расфиксировать передачу? Отгрузка откатится.')) run(api.unlockTransfer(c.id)) }}
        onDelete={del}
        error={err}
      >

      <dl className="props">
        <dt>Код</dt>
        <dd><CommitInput value={c.code ?? ''} width={220} disabled={locked || busy}
          onCommit={v => run(api.updateTransfer(c.id, { code: v }))} /></dd>
        <dt>Описание</dt>
        <dd><CommitInput value={c.description} width={260} disabled={locked || busy}
          onCommit={v => run(api.updateTransfer(c.id, { description: v }))} /></dd>
        <dt>№ накладной</dt>
        <dd><CommitInput value={c.number} width={140} disabled={locked || busy}
          onCommit={v => run(api.updateTransfer(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></dd>
        <dt>Дата</dt>
        <dd><CommitInput value={c.date} width={140} type="date" disabled={locked || busy}
          onCommit={v => run(api.updateTransfer(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></dd>
        <dt>Заказчик</dt>
        <dd>
          <select className="lot-sel" value={c.contractor_id ?? ''} disabled={locked || busy}
            onChange={e => run(api.updateTransfer(c.id, {
              contractor_id: e.target.value ? Number(e.target.value) : null }))}>
            <option value="">— не указан —</option>
            {customers.map(cp => <option key={cp.id} value={cp.id}>{cp.description}</option>)}
          </select>
        </dd>
        <AuthorField userId={c.user_id} userName={c.user_name} disabled={locked || busy}
          onChange={id => run(api.updateTransfer(c.id, { user_id: id }))} />
        <ProjectField projectId={c.project_id} projectLabel={c.project_code} disabled={locked || busy}
          onChange={id => run(api.updateTransfer(c.id, { project_id: id }))} />
      </dl>
      </FormHeader>

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
        <a className="link" onClick={() => openItem(ln.item_id)}>{ln.item_design_item_id}</a>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>{ln.item_description}</span>
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
              #{l.lot_id} {l.item_design_item_id}{l.lot_name ? ` (${l.lot_name})` : ''} · {num(l.live_qty)} {l.uom}
            </option>
          ))}
        </select>
      </td>
      <td style={{ color: 'var(--fg-dim)' }}>{picked?.item_description ?? ''}</td>
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
