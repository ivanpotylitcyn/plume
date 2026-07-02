// Витрина волны 5: кокпит передачи / Transfer (записываемое ядро).
// Отгрузка готового железа заказчику по накладной. Строка передачи = отдаём
// партию проекта (`−ISSUE`); добавление/правка/удаление автосейвом. Мягкого
// замка нет (у Transfer нет поля статуса) — правимо всегда; guard корректности —
// «лот не потреблён ниже» на бэке. Отображаемое имя строки печатается в накладной.
import { useEffect, useState } from 'react'
import { api, type AvailableLot, type TransferCockpit,
  type TransferCockpitLine } from './api'
import { CommitInput } from './ReceiptView'
import { num } from './status'

export function TransferView({ transferId, openItem, onChanged }: {
  transferId: number
  openItem: (id: number) => void
  onChanged: () => void
}) {
  const [c, setC] = useState<TransferCockpit | null>(null)
  const [lots, setLots] = useState<AvailableLot[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reloadLots = (projectId: number) =>
    api.projectAvailableLots(projectId).then(setLots)

  useEffect(() => {
    setC(null); setErr(null)
    api.transfer(transferId).then(c => {
      setC(c)
      reloadLots(c.project_id)
    }).catch(e => setErr(String(e)))
  }, [transferId])

  const run = (p: Promise<TransferCockpit>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); reloadLots(next.project_id); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const locked = c.posted
  return (
    <div>
      <h1 className="title">
        <span className={`glyph ${locked ? 'g-lock' : 'g-info'}`}>{locked ? '🔒' : '📦'}</span>{' '}
        <span className="pn">Накладная {c.number}</span>{' '}
        <span className="lit">— {c.project_name}</span>
      </h1>
      <div className="subtitle">
        Кокпит передачи · отгрузка заказчику · проект {c.project_code} · {c.date} ·{' '}
        <span className={locked ? 'g-lock' : 'g-info'}>{locked ? 'отгружено (замок)' : 'в работе'}</span>
        {' · отдано '}<span className="seg">{num(c.total_qty)}</span>
      </div>

      <div className="hdr-edit">
        <label>№ накладной <CommitInput value={c.number} width={140} disabled={locked || busy}
          onCommit={v => run(api.updateTransfer(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></label>
        <label>дата <CommitInput value={c.date} width={140} type="date" disabled={locked || busy}
          onCommit={v => run(api.updateTransfer(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></label>
      </div>

      <div className="kit-actions">
        {locked
          ? <button className="btn" disabled={busy}
              onClick={() => run(api.unpostTransfer(c.id))}>Снять замок</button>
          : <button className="btn" disabled={busy}
              onClick={() => run(api.postTransfer(c.id))}>Отгружено</button>}
        {locked && <span className="hint">подписанную накладную приложим отдельной волной (вложения)</span>}
        {busy && <span className="hint">сохраняю…</span>}
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
              #{l.lot_id} {l.item_code}{l.serial_number ? ` (${l.serial_number})` : ''} · {num(l.live_qty)} {l.uom}
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
