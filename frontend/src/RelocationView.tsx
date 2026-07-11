// Витрина волны 13 Ф3: кокпит перемещения / Relocation (записываемое ядро).
// Ход = целый лот проекта переезжает из места-источника в место-приёмник (пара
// знаковых `StockLine` `−q`/`+q` на бэке, тотал лота сохранён). Комплектовщик
// собирает перемещение из живых лотов; автосейв кол-ва/мест; мягкий замок как
// у прочих ордеров (draft ⇄ posted).
import { useEffect, useState } from 'react'
import { api, type LocationRow, type RelocationCockpit, type RelocationMove,
  type RelocationSourceLot } from './api'
import { CommitInput } from './ReceiptView'
import { AuthorField, FormHeader, ProjectField, useOrderCockpit } from './FormHeader'
import { num } from './status'
import { AttachmentPanel } from './AttachmentPanel'

export function RelocationView({ relocationId, openItem, onChanged, onDeleted }: {
  relocationId: number
  openItem: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [lots, setLots] = useState<RelocationSourceLot[]>([])
  const [locs, setLocs] = useState<LocationRow[]>([])
  useEffect(() => { api.locations().then(setLocs) }, [])

  const { c, err, busy, unlocked, toggle, run, del } = useOrderCockpit(
    relocationId, api.relocation, {
      onChanged, onDeleted,
      onLoad: c => { api.relocationSourceLots(c.id).then(setLots) },
      remove: api.deleteRelocation,
      confirmDelete: 'Удалить перемещение? Ходы откатятся, действие необратимо.',
    })

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.posted                   // проведено — read-only
  const locked = fixed || !unlocked
  return (
    <div className={unlocked && !fixed ? '' : 'form-locked'}>
      <FormHeader
        name={`Перемещение ${c.number}`}
        meta={<>
          <span className={`glyph ${fixed ? 'g-lock' : 'g-on_order'}`}>{fixed ? '🔒' : '●'}</span>
          {c.project_code} · {c.project_name} · {c.date} · перемещено {num(c.total_qty)}
        </>}
        unlocked={unlocked} onToggleLock={toggle}
        fixed={fixed} fixedLabel="проведено"
        onUnfix={() => { if (confirm('Снять фиксацию перемещения? Форма станет черновиком.')) run(api.unpostRelocation(c.id)) }}
        onDelete={del}
        error={err}
      />

      <dl className="props">
        <dt>№ перемещения</dt>
        <dd><CommitInput value={c.number} width={140} disabled={locked || busy}
          onCommit={v => run(api.updateRelocation(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></dd>
        <dt>Дата</dt>
        <dd><CommitInput value={c.date} width={140} type="date" disabled={locked || busy}
          onCommit={v => run(api.updateRelocation(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></dd>
        <AuthorField userId={c.user_id} userName={c.user_name} disabled={locked || busy}
          onChange={id => run(api.updateRelocation(c.id, { user_id: id }))} />
        <ProjectField projectId={c.project_id} projectLabel={c.project_code} disabled={locked || busy}
          onChange={id => run(api.updateRelocation(c.id, { project_id: id }))} />
      </dl>

      <div className="kit-actions">
        {!fixed &&
          <button className="btn primary" disabled={busy || unlocked}
            title={unlocked ? 'Сначала закройте замок — просмотрите чистовик' : 'Зафиксировать документ'}
            onClick={() => run(api.postRelocation(c.id))}>Провести · зафиксировать</button>}
        {err && <span className="anomaly">{err}</span>}
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th>партия</th><th>изделие</th>
            <th style={{ textAlign: 'right' }}>кол-во</th>
            <th>откуда</th><th>куда</th><th />
          </tr>
        </thead>
        <tbody>
          {c.moves.map(m => (
            <MoveRow key={m.lot_id} m={m} relocationId={c.id} locs={locs}
              locked={locked} busy={busy} openItem={openItem} run={run} />
          ))}
          {!locked && <GhostRow relocationId={c.id} lots={lots} locs={locs}
            busy={busy} run={run} />}
        </tbody>
      </table>
      {c.moves.length === 0 &&
        <div className="empty">Перемещение пусто — добавьте ход (лот · откуда → куда).</div>}

      <AttachmentPanel ownerType="relocation" ownerId={c.id} />
    </div>
  )
}

// Реальный ход перемещения (ключ — лот): автосейв кол-ва/мест, удаление хода.
function MoveRow({ m, relocationId, locs, locked, busy, openItem, run }: {
  m: RelocationMove; relocationId: number; locs: LocationRow[]
  locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<RelocationCockpit>) => void
}) {
  const negative = m.from_live_qty < 0   // источник в минусе — переместили больше, чем лежало
  return (
    <tr className="row s-available">
      <td>
        <span className="glyph g-available">⇄</span>{' '}
        <span className="pn">{m.lot_label}</span>
      </td>
      <td>
        <a className="link" onClick={() => openItem(m.item_id)}>{m.item_code}</a>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>{m.item_name}</span>
      </td>
      <td className="num">
        <CommitInput value={String(m.qty)} width={60} disabled={locked || busy}
          onCommit={v => run(api.updateRelocationLine(relocationId, m.lot_id, { qty: Number(v) }))}
          validate={v => Number(v) > 0} /> {m.uom}
      </td>
      <td>
        <select className="lot-sel" value={m.from_location_id ?? ''} disabled={locked || busy}
          onChange={e => run(api.updateRelocationLine(relocationId, m.lot_id,
            { from_location_id: Number(e.target.value) }))}>
          {locs.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}
        </select>{' '}
        <span className={negative ? 'anomaly' : ''} style={{ color: 'var(--fg-dim)' }}>
          ({num(m.from_live_qty)}){negative && <span className="anomaly" title="источник в минусе">▲</span>}
        </span>
      </td>
      <td>
        <select className="lot-sel" value={m.to_location_id ?? ''} disabled={locked || busy}
          onChange={e => run(api.updateRelocationLine(relocationId, m.lot_id,
            { to_location_id: Number(e.target.value) }))}>
          {locs.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}
        </select>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>({num(m.to_live_qty)})</span>
      </td>
      <td style={{ textAlign: 'right' }}>
        {!locked &&
          <button className="x" title="убрать ход" disabled={busy}
            onClick={() => run(api.deleteRelocationLine(relocationId, m.lot_id))}>×</button>}
      </td>
    </tr>
  )
}

// Призрачная строка: выбрать лот проекта (live>0), место-источник (по разбивке
// лота), место-приёмник и кол-во. Один лот = один ход — уже перемещаемые лоты
// пикер прячет (guard на бэке всё равно отклонит дубль).
function GhostRow({ relocationId, lots, locs, busy, run }: {
  relocationId: number; lots: RelocationSourceLot[]; locs: LocationRow[]
  busy: boolean; run: (p: Promise<RelocationCockpit>) => void
}) {
  const [lotId, setLotId] = useState<number | ''>('')
  const [from, setFrom] = useState<number | ''>('')
  const [to, setTo] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  const picked = lots.find(l => l.lot_id === lotId)

  const pick = (id: number | '') => {
    setLotId(id)
    const lot = lots.find(l => l.lot_id === id)
    // источник по умолчанию — место, где у лота больше всего остатка
    const best = lot?.by_location.slice().sort((a, b) => b.qty - a.qty)[0]
    setFrom(best ? best.location_id : '')
    setTo('')
  }

  const add = () => {
    const q = Number(qty)
    if (!lotId || !from || !to || from === to || !(q > 0)) return
    run(api.addRelocationLine(relocationId, {
      lot_id: lotId, qty: q, from_location_id: from, to_location_id: to,
    }))
    setLotId(''); setFrom(''); setTo(''); setQty('')
  }

  return (
    <tr className="row ghost">
      <td>
        <select className="lot-sel" value={lotId} disabled={busy}
          onChange={e => pick(e.target.value ? Number(e.target.value) : '')}>
          <option value="">＋ лот…</option>
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
      <td>
        <select className="lot-sel" value={from} disabled={busy || !lotId}
          onChange={e => setFrom(e.target.value ? Number(e.target.value) : '')}>
          <option value="">откуда…</option>
          {locs.map(l => {
            const at = picked?.by_location.find(b => b.location_id === l.id)
            return <option key={l.id} value={l.id}>
              {l.code}{at ? ` (${num(at.qty)})` : ''}
            </option>
          })}
        </select>
      </td>
      <td>
        <select className="lot-sel" value={to} disabled={busy || !lotId}
          onChange={e => setTo(e.target.value ? Number(e.target.value) : '')}>
          <option value="">куда…</option>
          {locs.map(l => <option key={l.id} value={l.id} disabled={l.id === from}>{l.code}</option>)}
        </select>
      </td>
      <td style={{ textAlign: 'right' }}>
        <button className="btn sm"
          disabled={busy || !lotId || !from || !to || from === to || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
