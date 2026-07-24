// Витрина волны 2: кокпит комплектации (записываемое ядро).
// BOM целевого прибора (1 уровень): реальные (пробитые) строки — зелёные,
// автосейв qty; остаток → призрачная строка, покрашенная по доступности, с
// пикером лота. Пайка = промоушн призрака в реальную KittingLine (+ ISSUE).
import { useEffect, useState } from 'react'
import { api, type Cockpit, type CockpitRow, type ItemRow } from './api'
import { CommitInput } from './ReceiptView'
import { AnchorSelect, AuthorField, FormHeader, ProjectField, useOrderCockpit } from './FormHeader'
import { Glyph, Segment, num } from './status'
import { AttachmentPanel } from './AttachmentPanel'

// Волна 19, Ф1c: словарь `wip/closed/cancelled` снят — ось та же `locked`, что у
// всех сущностей. Подпись остаётся своей: у комплектации фиксация рождает прибор.
const kitLabel = (locked: boolean) => locked ? 'зафиксирована' : 'в работе'

export function KittingView({ kittingId, isNew, openItem, onChanged, onDeleted }:
  { kittingId: number; isNew: boolean; openItem: (id: number) => void; onChanged: () => void
    onDeleted: () => void }) {
  // Справочник изделий — для якоря «целевое изделие» (Ф2k). Загружаем один раз.
  const [items, setItems] = useState<ItemRow[]>([])
  useEffect(() => { api.items().then(setItems) }, [])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderCockpit(
    kittingId, api.kitting, {
      onChanged, onDeleted,
      remove: api.deleteKitting,
      confirmDelete: 'Удалить комплектацию? Рождённый прибор будет снят. Действие необратимо.',
    }, isNew)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const wip = !c.locked
  const fixed = !wip                       // зафиксирована — read-only
  const locked = fixed || !unlocked
  return (
    <div className={unlocked && !fixed ? '' : 'form-locked'}>
      <FormHeader
        code={c.code || `Комплектация ${c.target_design_item_id}`}
        meta={<>
          <Glyph status={c.cockpit_status} /> {c.target_design_item_id} · {c.project_code} ·
          {' '}образцов {num(c.qty)} · {kitLabel(c.locked)}
        </>}
        unlocked={unlocked} onToggleLock={toggle}
        fixed={fixed}
        onFixate={() => run(api.lockKitting(c.id))}
        fixateTitle="Зафиксировать комплектацию — родить прибор"
        onUnfix={() => { if (confirm('Расфиксировать комплектацию? Рождённый прибор откатится.')) run(api.unlockKitting(c.id)) }}
        onDelete={del}
        error={err}
      >

      <dl className="props">
        <dt>Код</dt>
        <dd><CommitInput value={c.code ?? ''} width={220} disabled={locked || busy}
          onCommit={v => run(api.updateKitting(c.id, { code: v }))} /></dd>
        <dt>Описание</dt>
        <dd><CommitInput value={c.description} width={260} disabled={locked || busy}
          onCommit={v => run(api.updateKitting(c.id, { description: v }))} /></dd>
        <dt>Образцов</dt>
        <dd><CommitInput value={String(c.qty)} width={72} disabled={locked || busy}
          onCommit={v => run(api.updateKitting(c.id, { qty: Number(v) }))}
          validate={v => Number(v) > 0} /></dd>
        <dt>Дата</dt>
        <dd><CommitInput value={c.date ?? ''} width={140} type="date" disabled={locked || busy}
          onCommit={v => run(api.updateKitting(c.id, { date: v }))} /></dd>
        <AuthorField userId={c.user_id} userName={c.user_name} disabled={locked || busy}
          onChange={id => run(api.updateKitting(c.id, { user_id: id }))} />
        <ProjectField projectId={c.project_id} projectLabel={c.project_code} disabled={locked || busy}
          onChange={id => run(api.updateKitting(c.id, { project_id: id }))} />
        <AnchorSelect label="Изделие" id={c.target_id} currentLabel={c.target_design_item_id}
          options={items.map(i => ({ id: i.id, label: `${i.design_item_id} — ${i.description}` }))}
          disabled={locked || busy}
          onChange={id => run(api.updateKitting(c.id, { target_id: id }))} />
      </dl>
      </FormHeader>


      {c.born_lots.length > 0 && (
        <div className="born">
          Рождён лот-прибор:{' '}
          {c.born_lots.map(l => (
            <span key={l.id} className="seg">#{l.id} ×{num(l.qty)} · {num(l.unit_cost)} ₽/шт</span>
          ))}
        </div>
      )}

      {c.rows.map(row => (
        <Component key={row.component_id} row={row} cockpit={c} wip={!locked} busy={busy}
          openItem={openItem} run={run} />
      ))}

      <AttachmentPanel ownerType="kitting" ownerId={c.id} />
    </div>
  )
}

function Component({ row, cockpit, wip, busy, openItem, run }: {
  row: CockpitRow; cockpit: Cockpit; wip: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<Cockpit>) => void
}) {
  const g = row.ghost
  const status = g ? g.status : 'available'
  return (
    <div className="kit-comp">
      <div className="kit-comp-h">
        <Glyph status={status} />
        <span className="name">
          <a className="link" onClick={() => openItem(row.component_id)}>{row.component_design_item_id}</a>
          {' '}<span style={{ color: 'var(--fg-dim)' }}>{row.component_description}</span>
        </span>
        <span className="triple">надо {num(row.need)} {row.uom} · пробито {num(row.pierced)}
          {row.remaining > 0 && <> · остаток <span className="g-to_order">{num(row.remaining)}</span></>}
        </span>
      </div>

      <table className="grid">
        <tbody>
          {row.real_lines.map(ln => (
            <tr key={ln.id} className="row s-available">
              <td><span className="glyph g-available">✓</span> {ln.lot_label}</td>
              <td className="num">
                <QtyInput value={ln.qty} disabled={!wip || busy}
                  onCommit={q => run(api.updateLine(ln.id, q))} /> {row.uom}
              </td>
              <td style={{ color: 'var(--fg-dim)' }}>{ln.date ?? ''}</td>
              <td style={{ textAlign: 'right' }}>
                {wip && <button className="x" title="убрать строку" disabled={busy}
                  onClick={() => run(api.deleteLine(ln.id))}>×</button>}
              </td>
            </tr>
          ))}
          {wip && g && (
            <GhostRow row={row} ghost={g} cockpit={cockpit} busy={busy} run={run} />
          )}
        </tbody>
      </table>
    </div>
  )
}

// Призрачная строка: пайка (промоушн призрака в реальную KittingLine).
function GhostRow({ row, ghost, cockpit, busy, run }: {
  row: CockpitRow; ghost: NonNullable<CockpitRow['ghost']>; cockpit: Cockpit
  busy: boolean; run: (p: Promise<Cockpit>) => void
}) {
  const lots = ghost.candidate_lots
  const [lotId, setLotId] = useState<number | ''>(lots[0]?.lot_id ?? '')
  const [qty, setQty] = useState(String(row.remaining))
  useEffect(() => { setLotId(lots[0]?.lot_id ?? '') }, [lots.map(l => l.lot_id).join()])

  const pierce = () => {
    const n = Number(qty)
    if (!lotId || !(n > 0)) return
    run(api.pierce(cockpit.id, { component_id: row.component_id, lot_id: lotId, qty: n }))
  }

  return (
    <tr className={`row ghost s-${ghost.status}`}>
      <td>
        <Glyph status={ghost.status} />{' '}
        {lots.length === 0
          ? <span style={{ color: 'var(--fg-dim)' }}>
              нет своих лотов —{' '}
              <Segment status="on_order" value={ghost.on_order} />
              <Segment status="to_order" value={ghost.to_order} />
            </span>
          : <select className="lot-sel" value={lotId}
              onChange={e => setLotId(Number(e.target.value))} disabled={busy}>
              {lots.map(l => (
                <option key={l.lot_id} value={l.lot_id}>
                  #{l.lot_id} · остаток {num(l.live_qty)}{l.lot_name ? ` · ${l.lot_name}` : ''}
                </option>
              ))}
            </select>}
      </td>
      <td className="num">
        {lots.length > 0 &&
          <input className="qty-in" value={qty} disabled={busy}
            onChange={e => setQty(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') pierce() }} />} {row.uom}
      </td>
      <td colSpan={2} style={{ textAlign: 'right' }}>
        {lots.length > 0 &&
          <button className="btn sm" disabled={busy} onClick={pierce}>спаять</button>}
      </td>
    </tr>
  )
}

// Автосейв количества: коммит по blur / Enter (без кнопки «сохранить»).
function QtyInput({ value, onCommit, disabled }:
  { value: number; onCommit: (q: number) => void; disabled?: boolean }) {
  const [v, setV] = useState(String(value))
  useEffect(() => { setV(String(value)) }, [value])
  const commit = () => { const n = Number(v); if (n > 0 && n !== value) onCommit(n) }
  return (
    <input className="qty-in" value={v} disabled={disabled}
      onChange={e => setV(e.target.value)} onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
  )
}
