// Витрина волны 6: кокпит требования / Requisition (записываемое ядро).
// Отпочкование: строка тянет из лота-источника (`−ISSUE`) и рождает лот-потомок
// в проекте-получателе (`+RECEIPT`, наследует item/цену/провенанс). Источник — из
// любого проекта (постановка своего на баланс → белый, заём у соседнего B→A).
// Замка нет — правимо всегда; корректность — источник ≠ получатель, один лот = одна
// строка, потомок не потреблён ниже (guard на бэке).
import { useEffect, useState } from 'react'
import { api, type AllAvailableLot, type RequisitionCockpit,
  type RequisitionCockpitLine } from './api'
import { CommitInput } from './ReceiptView'
import { num } from './status'
import { AttachmentPanel } from './AttachmentPanel'

export function RequisitionView({ requisitionId, openItem, onChanged }: {
  requisitionId: number
  openItem: (id: number) => void
  onChanged: () => void
}) {
  const [c, setC] = useState<RequisitionCockpit | null>(null)
  const [lots, setLots] = useState<AllAvailableLot[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reloadLots = () => api.allAvailableLots().then(setLots)

  useEffect(() => {
    setC(null); setErr(null)
    api.requisition(requisitionId).then(c => { setC(c); reloadLots() })
      .catch(e => setErr(String(e)))
  }, [requisitionId])

  const run = (p: Promise<RequisitionCockpit>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); reloadLots(); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  // Источник ≠ получатель: прячем из пикера лоты самого проекта-получателя.
  const pickable = lots.filter(l => l.project_id !== c.project_id)
  return (
    <div>
      <h1 className="title">
        <span className="glyph g-info">⇄</span>{' '}
        <span className="pn">Требование {c.number}</span>{' '}
        <span className="lit">→ {c.project_name}</span>
      </h1>
      <div className="subtitle">
        Кокпит требования · отпочкование в получатель {c.project_code} · {c.date} ·{' '}
        поставлено <span className="seg">{num(c.total_qty)}</span>
      </div>

      <div className="hdr-edit">
        <label>№ требования <CommitInput value={c.number} width={140} disabled={busy}
          onCommit={v => run(api.updateRequisition(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></label>
        <label>дата <CommitInput value={c.date} width={140} type="date" disabled={busy}
          onCommit={v => run(api.updateRequisition(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></label>
      </div>

      <div className="kit-actions">
        {busy && <span className="hint">сохраняю…</span>}
        {err && <span className="anomaly">{err}</span>}
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th>источник</th><th>изделие</th><th>откуда</th>
            <th style={{ textAlign: 'right' }}>кол-во</th>
            <th style={{ textAlign: 'right' }}>остаток ист.</th><th />
          </tr>
        </thead>
        <tbody>
          {c.lines.map(ln => (
            <LineRow key={ln.id} ln={ln} busy={busy} openItem={openItem} run={run} />
          ))}
          <GhostRow requisitionId={c.id} lots={pickable} busy={busy} run={run} />
        </tbody>
      </table>
      {c.lines.length === 0 &&
        <div className="empty">Требование пусто — выберите лот-источник.</div>}

      <AttachmentPanel ownerType="requisition" ownerId={c.id} />
    </div>
  )
}

// Реальная строка требования: автосейв кол-ва (синхронит источник и потомок), удаление.
function LineRow({ ln, busy, openItem, run }: {
  ln: RequisitionCockpitLine; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<RequisitionCockpit>) => void
}) {
  const negative = ln.source_live_qty < 0
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
      <td style={{ color: 'var(--fg-dim)' }}>{ln.source_project_code}</td>
      <td className="num">
        <CommitInput value={String(ln.qty)} width={60} disabled={busy}
          onCommit={v => run(api.updateRequisitionLine(ln.id, Number(v)))}
          validate={v => Number(v) > 0} /> {ln.uom}
      </td>
      <td className="num">
        <span className={negative ? 'anomaly' : ''}>{num(ln.source_live_qty)}</span>
        {negative && <span className="anomaly" title="перетянули — источник в минусе">▲</span>}
      </td>
      <td style={{ textAlign: 'right' }}>
        <button className="x" title="убрать строку" disabled={busy}
          onClick={() => run(api.deleteRequisitionLine(ln.id))}>×</button>
      </td>
    </tr>
  )
}

// Призрачная строка: выбрать лот-источник (сквозной пикер, кроме получателя) + кол-во.
function GhostRow({ requisitionId, lots, busy, run }: {
  requisitionId: number; lots: AllAvailableLot[]; busy: boolean
  run: (p: Promise<RequisitionCockpit>) => void
}) {
  const [lotId, setLotId] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  const picked = lots.find(l => l.lot_id === lotId)

  const add = () => {
    const q = Number(qty)
    if (!lotId || !(q > 0)) return
    run(api.addRequisitionLine(requisitionId, { source_lot_id: lotId, qty: q }))
    setLotId(''); setQty('')
  }

  return (
    <tr className="row ghost">
      <td>
        <select className="lot-sel" value={lotId} disabled={busy}
          onChange={e => setLotId(e.target.value ? Number(e.target.value) : '')}>
          <option value="">＋ лот-источник…</option>
          {lots.map(l => (
            <option key={l.lot_id} value={l.lot_id}>
              {l.project_code} · #{l.lot_id} {l.item_code}{l.serial_number ? ` (${l.serial_number})` : ''} · {num(l.live_qty)} {l.uom}
            </option>
          ))}
        </select>
      </td>
      <td style={{ color: 'var(--fg-dim)' }}>{picked?.item_name ?? ''}</td>
      <td style={{ color: 'var(--fg-dim)' }}>{picked?.project_code ?? ''}</td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy || !lotId} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="num" style={{ color: 'var(--fg-dim)' }}>
        {picked ? num(picked.live_qty) : ''}
      </td>
      <td style={{ textAlign: 'right' }}>
        <button className="btn sm" disabled={busy || !lotId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
