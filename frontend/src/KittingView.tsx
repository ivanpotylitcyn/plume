// Витрина волны 2: форма комплектации (записываемое ядро).
// BOM целевого прибора (1 уровень): реальные (пробитые) строки — зелёные,
// автосейв qty; остаток → призрачная строка, покрашенная по доступности, с
// пикером лота. Пайка = промоушн призрака в реальную KittingLine (+ ISSUE).
//
// Волна 19 (Ф12c): на канон §13 переведён ТОЛЬКО скелет формы (титул/шапка/мета/табы
// Строки · Файлы). Тело пробивки намеренно не трогаем: комплектация ждёт своего
// глубокого прохода отдельной волной (BACKLOG «форма комплектации»), и открывать
// второй фронт внутри Ф12c мы не стали.
import { useEffect, useState } from 'react'
import { api, type KittingForm, type KittingFormRow, type ItemRow } from './api'
import { AnchorSelect, OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { TextField } from './FormField'
import { Dropdown } from './Dropdown'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { Glyph, Segment, count, num } from './status'

export function KittingView({ kittingId, isNew, openItem, openProject, onChanged, onDeleted }:
  { kittingId: number; isNew: boolean; openItem: (id: number) => void
    openProject: (id: number) => void; onChanged: () => void
    onDeleted: () => void }) {
  // Справочник изделий — для якоря «целевое изделие» (Ф2k). Загружаем один раз.
  const [items, setItems] = useState<ItemRow[]>([])
  useEffect(() => { api.items().then(setItems) }, [])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    kittingId, api.kitting, {
      onChanged, onDeleted,
      remove: api.deleteKitting,
      confirmDelete: 'Удалить комплектацию? Рождённый прибор будет снят. Действие необратимо.',
    }, isNew)
  const att = useAttachments('kitting', kittingId)   // загрузка — команда шапки (§13.8)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const wip = !c.locked
  const fixed = !wip                       // зафиксирована — read-only
  const locked = fixed || !unlocked

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        {c.born_lots.length > 0 && (
          <div className="born">
            Рождён лот-прибор:{' '}
            {c.born_lots.map(l => (
              <span key={l.id} className="seg">#{l.id} ×{num(l.qty)} · {num(l.unit_cost)} ₽/шт</span>
            ))}
          </div>
        )}
        {c.rows.length === 0 && <div className="tab-empty">
          У целевого изделия нет состава — пробивать нечего.</div>}
        {c.rows.map(row => (
          <Component key={row.component_id} row={row} form={c} wip={!locked} busy={busy}
            openItem={openItem} run={run} />
        ))}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="комплектацию" locked={locked} error={err}
      // Мета (§13.6): счёт по табам + разбор пайки. Прибор/образцы/проект не
      // повторяем — они в полях шапки.
      meta={<>
        {count(c.rows.length, 'компонент', 'компонента', 'компонентов')}
        {' · '}{count(c.rows.filter(r => r.remaining <= 0).length, 'пробит', 'пробито', 'пробито')}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockKitting(c.id))}
      fixateTitle="Зафиксировать комплектацию — родить прибор"
      onUnfix={() => { if (confirm('Расфиксировать комплектацию? Рождённый прибор откатится.')) run(api.unlockKitting(c.id)) }}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (акт комплектации) — появится в табе «Файлы»', disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy}
          openProject={openProject}
          patch={b => run(api.updateKitting(c.id, b))}>
          {/* Ширина поля — токеном темы, не пикселями в JSX (Ф12d: инлайн-стиль
              сильнее любого класса и выбивал поле из общей сетки шапки). */}
          <TextField label="Образцов" value={String(c.qty)} locked={locked} busy={busy}
            onCommit={v => run(api.updateKitting(c.id, { qty: Number(v) }))}
            validate={v => Number(v) > 0} />
          <AnchorSelect label="Изделие" id={c.target_id} currentLabel={c.target_code}
            options={items.map(i => ({ id: i.id, label: i.code }))}
            locked={locked} busy={busy}
            onChange={id => run(api.updateKitting(c.id, { target_id: id }))} />
        </OrderFields>}
      tabs={tabs}
    />
  )
}

function Component({ row, form, wip, busy, openItem, run }: {
  row: KittingFormRow; form: KittingForm; wip: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<KittingForm>) => void
}) {
  const g = row.ghost
  const status = g ? g.status : 'available'
  return (
    <div className="kit-comp">
      <div className="kit-comp-h">
        <Glyph status={status} />
        <span className="name">
          <a className="link" onClick={() => openItem(row.component_id)}>{row.component_code}</a>
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
              <td className="act">
                {wip && <button className="fh-ctl icon fh-del" title="Убрать пробитую строку"
                  disabled={busy} onClick={() => run(api.deleteLine(ln.id))}>
                  <span className="ci ci-trash" /></button>}
              </td>
            </tr>
          ))}
          {wip && g && (
            <GhostRow row={row} ghost={g} form={form} busy={busy} run={run} />
          )}
        </tbody>
      </table>
    </div>
  )
}

// Призрачная строка: пайка (промоушн призрака в реальную KittingLine).
function GhostRow({ row, ghost, form, busy, run }: {
  row: KittingFormRow; ghost: NonNullable<KittingFormRow['ghost']>; form: KittingForm
  busy: boolean; run: (p: Promise<KittingForm>) => void
}) {
  const lots = ghost.candidate_lots
  const [lotId, setLotId] = useState<number | ''>(lots[0]?.lot_id ?? '')
  const [qty, setQty] = useState(String(row.remaining))
  useEffect(() => { setLotId(lots[0]?.lot_id ?? '') }, [lots.map(l => l.lot_id).join()])

  const pierce = () => {
    const n = Number(qty)
    if (!lotId || !(n > 0)) return
    run(api.pierce(form.id, { component_id: row.component_id, lot_id: lotId, qty: n }))
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
          : <Dropdown value={lotId} disabled={busy} onPick={v => setLotId(Number(v))}
              options={lots.map(l => ({ value: l.lot_id,
                label: `#${l.lot_id} · остаток ${num(l.live_qty)}`
                  + (l.lot_name ? ` · ${l.lot_name}` : '') }))} />}
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
