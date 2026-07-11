// Витрина волны 6: кокпит списания / Writeoff (записываемое ядро).
// Списание — чистое выбытие партии из проекта (`−ISSUE`, серый путь): born-лота
// нет, лот покидает учёт. Строка = списываем свою партию; добавление/правка/
// удаление автосейвом. Замка нет (у Writeoff нет поля статуса) — правимо всегда;
// корректность — «списываем только своё» + пересписание в минус информативно (▲).
import { useState } from 'react'
import { api, type AvailableLot, type WriteoffCockpit,
  type WriteoffCockpitLine } from './api'
import { CommitInput } from './ReceiptView'
import { AuthorField, FormHeader, ProjectField, useOrderCockpit } from './FormHeader'
import { num } from './status'
import { AttachmentPanel } from './AttachmentPanel'

export function WriteoffView({ writeoffId, openItem, onChanged, onDeleted }: {
  writeoffId: number
  openItem: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [lots, setLots] = useState<AvailableLot[]>([])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderCockpit(
    writeoffId, api.writeoff, {
      onChanged, onDeleted,
      onLoad: c => { api.projectAvailableLots(c.project_id).then(setLots) },
      remove: api.deleteWriteoff,
      confirmDelete: 'Удалить списание? Действие необратимо.',
    })

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.posted                   // проведено — read-only (единый мягкий замок)
  const locked = fixed || !unlocked
  return (
    <div className={unlocked && !fixed ? '' : 'form-locked'}>
      <FormHeader
        name={`Списание ${c.number}`}
        meta={<>
          <span className={`glyph ${fixed ? 'g-lock' : 'g-info'}`}>{fixed ? '🔒' : '○'}</span>
          {c.project_code} · {c.project_name} · {c.date}
          {c.reason && <> · {c.reason}</>} · списано {num(c.total_qty)}
        </>}
        unlocked={unlocked} onToggleLock={toggle}
        fixed={fixed} fixedLabel="проведено"
        onUnfix={() => { if (confirm('Снять фиксацию списания? Форма станет черновиком.')) run(api.unpostWriteoff(c.id)) }}
        onDelete={del}
        error={err}
      />

      <dl className="props">
        <dt>№ акта</dt>
        <dd><CommitInput value={c.number} width={140} disabled={locked || busy}
          onCommit={v => run(api.updateWriteoff(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></dd>
        <dt>Дата</dt>
        <dd><CommitInput value={c.date} width={140} type="date" disabled={locked || busy}
          onCommit={v => run(api.updateWriteoff(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></dd>
        <dt>Причина</dt>
        <dd><CommitInput value={c.reason} width={220} disabled={locked || busy}
          onCommit={v => run(api.updateWriteoff(c.id, { reason: v }))} /></dd>
        <AuthorField userId={c.user_id} userName={c.user_name} disabled={locked || busy}
          onChange={id => run(api.updateWriteoff(c.id, { user_id: id }))} />
        <ProjectField projectId={c.project_id} projectLabel={c.project_code} disabled={locked || busy}
          onChange={id => run(api.updateWriteoff(c.id, { project_id: id }))} />
      </dl>

      {!fixed &&
        <div className="kit-actions">
          <button className="btn primary" disabled={busy || unlocked}
            title={unlocked ? 'Сначала закройте замок — просмотрите чистовик' : 'Зафиксировать документ'}
            onClick={() => run(api.postWriteoff(c.id))}>Провести · зафиксировать</button>
          {err && <span className="anomaly">{err}</span>}
        </div>}

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
            <LineRow key={ln.id} ln={ln} locked={locked} busy={busy} openItem={openItem} run={run} />
          ))}
          {!locked && <GhostRow writeoffId={c.id} lots={lots} busy={busy} run={run} />}
        </tbody>
      </table>
      {c.lines.length === 0 &&
        <div className="empty">Акт пуст — добавьте партию к списанию.</div>}

      <AttachmentPanel ownerType="writeoff" ownerId={c.id} />
    </div>
  )
}

// Реальная строка списания (лот): автосейв кол-ва, удаление (коррекция).
function LineRow({ ln, locked, busy, openItem, run }: {
  ln: WriteoffCockpitLine; locked: boolean; busy: boolean
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
        <CommitInput value={String(ln.qty)} width={60} disabled={locked || busy}
          onCommit={v => run(api.updateWriteoffLine(ln.id, Number(v)))}
          validate={v => Number(v) > 0} /> {ln.uom}
      </td>
      <td className="num">
        <span className={negative ? 'anomaly' : ''}>{num(ln.lot_live_qty)}</span>
        {negative && <span className="anomaly" title="пересписали — источник в минусе">▲</span>}
      </td>
      <td style={{ textAlign: 'right' }}>
        {!locked &&
          <button className="x" title="убрать строку" disabled={busy}
            onClick={() => run(api.deleteWriteoffLine(ln.id))}>×</button>}
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
      <td style={{ textAlign: 'right' }}>
        <button className="btn sm" disabled={busy || !lotId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
