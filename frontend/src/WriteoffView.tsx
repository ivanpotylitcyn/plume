// Витрина волны 6: кокпит списания / Writeoff (записываемое ядро).
// Списание — чистое выбытие партии из проекта (`−ISSUE`, серый путь): born-лота
// нет, лот покидает учёт. Строка = списываем свою партию; добавление/правка/
// удаление автосейвом. Замка нет (у Writeoff нет поля статуса) — правимо всегда;
// корректность — «списываем только своё» + пересписание в минус информативно (▲).
import { useEffect, useState } from 'react'
import { api, type AvailableLot, type WriteoffCockpit,
  type WriteoffCockpitLine } from './api'
import { CommitInput } from './ReceiptView'
import { num } from './status'

export function WriteoffView({ writeoffId, openItem, onChanged }: {
  writeoffId: number
  openItem: (id: number) => void
  onChanged: () => void
}) {
  const [c, setC] = useState<WriteoffCockpit | null>(null)
  const [lots, setLots] = useState<AvailableLot[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reloadLots = (projectId: number) =>
    api.projectAvailableLots(projectId).then(setLots)

  useEffect(() => {
    setC(null); setErr(null)
    api.writeoff(writeoffId).then(c => {
      setC(c)
      reloadLots(c.project_id)
    }).catch(e => setErr(String(e)))
  }, [writeoffId])

  const run = (p: Promise<WriteoffCockpit>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); reloadLots(next.project_id); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  return (
    <div>
      <h1 className="title">
        <span className="glyph g-info">🗑</span>{' '}
        <span className="pn">Списание {c.number}</span>{' '}
        <span className="lit">— {c.project_name}</span>
      </h1>
      <div className="subtitle">
        Кокпит списания · выбытие из проекта {c.project_code} · {c.date}
        {c.reason && <> · причина: <span className="lit">{c.reason}</span></>}
        {' · списано '}<span className="seg">{num(c.total_qty)}</span>
      </div>

      <div className="hdr-edit">
        <label>№ акта <CommitInput value={c.number} width={140} disabled={busy}
          onCommit={v => run(api.updateWriteoff(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></label>
        <label>дата <CommitInput value={c.date} width={140} type="date" disabled={busy}
          onCommit={v => run(api.updateWriteoff(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></label>
        <label>причина <CommitInput value={c.reason} width={220} disabled={busy}
          onCommit={v => run(api.updateWriteoff(c.id, { reason: v }))} /></label>
      </div>

      <div className="kit-actions">
        {busy && <span className="hint">сохраняю…</span>}
        {err && <span className="anomaly">{err}</span>}
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th>партия</th><th>изделие</th>
            <th style={{ textAlign: 'right' }}>кол-во</th>
            <th style={{ textAlign: 'right' }}>остаток</th><th />
          </tr>
        </thead>
        <tbody>
          {c.lines.map(ln => (
            <LineRow key={ln.id} ln={ln} busy={busy} openItem={openItem} run={run} />
          ))}
          <GhostRow writeoffId={c.id} lots={lots} busy={busy} run={run} />
        </tbody>
      </table>
      {c.lines.length === 0 &&
        <div className="empty">Акт пуст — добавьте партию к списанию.</div>}
    </div>
  )
}

// Реальная строка списания (лот): автосейв кол-ва, удаление (коррекция).
function LineRow({ ln, busy, openItem, run }: {
  ln: WriteoffCockpitLine; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<WriteoffCockpit>) => void
}) {
  const negative = ln.lot_live_qty < 0   // пересписали — источник в минусе
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
        <CommitInput value={String(ln.qty)} width={60} disabled={busy}
          onCommit={v => run(api.updateWriteoffLine(ln.id, Number(v)))}
          validate={v => Number(v) > 0} /> {ln.uom}
      </td>
      <td className="num">
        <span className={negative ? 'anomaly' : ''}>{num(ln.lot_live_qty)}</span>
        {negative && <span className="anomaly" title="пересписали — источник в минусе">▲</span>}
      </td>
      <td style={{ textAlign: 'right' }}>
        <button className="x" title="убрать строку" disabled={busy}
          onClick={() => run(api.deleteWriteoffLine(ln.id))}>×</button>
      </td>
    </tr>
  )
}

// Призрачная строка: выбрать списываемую партию проекта (пикер live>0) + кол-во.
function GhostRow({ writeoffId, lots, busy, run }: {
  writeoffId: number; lots: AvailableLot[]; busy: boolean
  run: (p: Promise<WriteoffCockpit>) => void
}) {
  const [lotId, setLotId] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  const picked = lots.find(l => l.lot_id === lotId)

  const add = () => {
    const q = Number(qty)
    if (!lotId || !(q > 0)) return
    run(api.addWriteoffLine(writeoffId, { lot_id: lotId, qty: q }))
    setLotId(''); setQty('')
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
      <td style={{ textAlign: 'right' }}>
        <button className="btn sm" disabled={busy || !lotId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
