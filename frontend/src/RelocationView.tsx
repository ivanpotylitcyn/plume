// Витрина волны 13 Ф3: форма перемещения / Relocation (записываемое ядро).
// Ход = целый лот проекта переезжает из места-источника в место-приёмник (пара
// знаковых `StockLine` `−q`/`+q` на бэке, тотал лота сохранён). Комплектовщик
// собирает перемещение из живых лотов; автосейв кол-ва/мест; мягкий замок как
// у прочих ордеров (draft ⇄ posted).
//
// Волна 19 (Ф12c): форма по канону §13 — табы Строки · Файлы, общие поля шапки
// через `OrderFields` (своих полей у перемещения нет).
import { useEffect, useState } from 'react'
import { api, type LocationRow, type RelocationForm, type RelocationMove,
  type RelocationSourceLot } from './api'
import { CommitInput } from './CommitInput'
import { OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { LotGlyph, count, num, sumByUom } from './status'

export function RelocationView({ relocationId, isNew, openItem, openProject, onChanged, onDeleted }: {
  relocationId: number
  isNew: boolean
  openItem: (id: number) => void
  openProject: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [lots, setLots] = useState<RelocationSourceLot[]>([])
  const [locs, setLocs] = useState<LocationRow[]>([])
  useEffect(() => { api.locations().then(setLocs) }, [])

  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    relocationId, api.relocation, {
      onChanged, onDeleted,
      onLoad: c => { api.relocationSourceLots(c.id).then(setLots) },
      remove: api.deleteRelocation,
      confirmDelete: 'Удалить перемещение? Ходы откатятся, действие необратимо.',
    }, isNew)
  const att = useAttachments('relocation', relocationId)   // загрузка — команда шапки (§13.8)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.locked                   // проведено — read-only
  const locked = fixed || !unlocked

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="gl" /><th className="c-key">Партия</th>
              <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
              <th style={{ textAlign: 'right' }}>Кол-во</th><th className="uom">Ед.</th>
              <th className="c-fit">Откуда</th><th className="c-fit">Куда</th>
              {!locked && <th className="act" />}
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
        {c.moves.length === 0 && locked && <div className="tab-empty">Перемещение пусто.</div>}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="перемещение" locked={locked} error={err}
      meta={<>
        {count(c.moves.length, 'ход', 'хода', 'ходов')}
        {sumByUom(c.moves).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockRelocation(c.id))}
      fixateTitle="Зафиксировать перемещение"
      onUnfix={() => { if (confirm('Расфиксировать перемещения?')) run(api.unlockRelocation(c.id)) }}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл — появится в табе «Файлы»', disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy} numberLabel="№ перемещения"
          openProject={openProject}
          patch={b => run(api.updateRelocation(c.id, b))} />}
      tabs={tabs}
    />
  )
}

// Реальный ход перемещения (ключ — лот): автосейв кол-ва/мест, удаление хода.
function MoveRow({ m, relocationId, locs, locked, busy, openItem, run }: {
  m: RelocationMove; relocationId: number; locs: LocationRow[]
  locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<RelocationForm>) => void
}) {
  const negative = m.from_live_qty < 0   // источник в минусе — переместили больше, чем лежало
  return (
    <tr className="row">
      <td className="gl"><LotGlyph origin={m.origin} liveQty={m.from_live_qty} /></td>
      <td className="c-key"><span className="pn">{m.lot_label}</span></td>
      <td className="c-fit">
        <a className="link" onClick={() => openItem(m.item_id)}>{m.item_code}</a></td>
      <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
        <span className="cell-ellip" title={m.item_description}>{m.item_description}</span></td>
      <td className="num">
        <CommitInput value={String(m.qty)} width={60} disabled={locked || busy}
          onCommit={v => run(api.updateRelocationLine(relocationId, m.lot_id, { qty: Number(v) }))}
          validate={v => Number(v) > 0} />
      </td>
      <td className="uom">{m.uom}</td>
      <td className="c-fit">
        <select className="lot-sel" value={m.from_location_id ?? ''} disabled={locked || busy}
          onChange={e => run(api.updateRelocationLine(relocationId, m.lot_id,
            { from_location_id: Number(e.target.value) }))}>
          {locs.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}
        </select>{' '}
        <span className={negative ? 'anomaly' : ''} style={{ color: 'var(--fg-dim)' }}>
          ({num(m.from_live_qty)}){negative && <span className="anomaly" title="источник в минусе">▲</span>}
        </span>
      </td>
      <td className="c-fit">
        <select className="lot-sel" value={m.to_location_id ?? ''} disabled={locked || busy}
          onChange={e => run(api.updateRelocationLine(relocationId, m.lot_id,
            { to_location_id: Number(e.target.value) }))}>
          {locs.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}
        </select>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>({num(m.to_live_qty)})</span>
      </td>
      {!locked && <td className="act">
        <button className="fh-ctl icon fh-del" title="Убрать ход перемещения"
          disabled={busy} onClick={() => run(api.deleteRelocationLine(relocationId, m.lot_id))}>
          <span className="ci ci-trash" /></button>
      </td>}
    </tr>
  )
}

// Призрачная строка: выбрать лот проекта (live>0), место-источник (по разбивке
// лота), место-приёмник и кол-во. Один лот = один ход — уже перемещаемые лоты
// пикер прячет (guard на бэке всё равно отклонит дубль).
function GhostRow({ relocationId, lots, locs, busy, run }: {
  relocationId: number; lots: RelocationSourceLot[]; locs: LocationRow[]
  busy: boolean; run: (p: Promise<RelocationForm>) => void
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
      <td className="gl" />
      <td className="c-key" colSpan={2}>
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
      <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
        {picked?.item_description ?? ''}</td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy || !lotId} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="uom">{picked?.uom ?? ''}</td>
      <td className="c-fit">
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
      <td className="c-fit">
        <select className="lot-sel" value={to} disabled={busy || !lotId}
          onChange={e => setTo(e.target.value ? Number(e.target.value) : '')}>
          <option value="">куда…</option>
          {locs.map(l => <option key={l.id} value={l.id} disabled={l.id === from}>{l.code}</option>)}
        </select>
      </td>
      <td className="act">
        <button className="btn sm"
          disabled={busy || !lotId || !from || !to || from === to || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
