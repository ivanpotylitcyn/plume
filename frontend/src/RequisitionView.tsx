// Витрина волны 6: форма требования / Requisition (записываемое ядро).
// Отпочкование: строка тянет из лота-источника (`−ISSUE`) и рождает лот-потомок
// в проекте-получателе (`+RECEIPT`, наследует item/цену/провенанс). Источник — из
// любого проекта (постановка своего на баланс → белый, заём у соседнего B→A).
// Замка нет — правимо всегда; корректность — источник ≠ получатель, один лот = одна
// строка, потомок не потреблён ниже (guard на бэке).
//
// Волна 19 (Ф12c): форма по канону §13 — табы Строки · Файлы, общие поля шапки
// через `OrderFields` (своих полей у требования нет).
import { useState } from 'react'
import { api, type AllAvailableLot, type RequisitionForm,
  type RequisitionFormLine } from './api'
import { CommitInput } from './CommitInput'
import { OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { Dropdown } from './Dropdown'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { LotGlyph, count, num, sumByUom } from './status'

export function RequisitionView({ requisitionId, isNew, openItem, openProject, onChanged, onDeleted }: {
  requisitionId: number
  isNew: boolean
  openItem: (id: number) => void
  openProject: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [lots, setLots] = useState<AllAvailableLot[]>([])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    requisitionId, api.requisition, {
      onChanged, onDeleted,
      onLoad: () => { api.allAvailableLots().then(setLots) },
      remove: api.deleteRequisition,
      confirmDelete: 'Удалить требование? Действие необратимо.',
    }, isNew)
  const att = useAttachments('requisition', requisitionId)   // загрузка — команда шапки (§13.8)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  // Источник ≠ получатель: прячем из пикера лоты самого проекта-получателя.
  const pickable = lots.filter(l => l.project_id !== c.project_id)
  const fixed = c.locked                   // проведено — read-only (единый мягкий замок)
  const locked = fixed || !unlocked

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="gl" /><th className="c-key">Источник</th>
              <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
              <th className="c-fit">Откуда</th>
              <th style={{ textAlign: 'right' }}>Кол-во</th><th className="uom">Ед.</th>
              <th style={{ textAlign: 'right' }}>Остаток ист.</th>
              {!locked && <th className="act" />}
            </tr>
          </thead>
          <tbody>
            {c.lines.map(ln => (
              <LineRow key={ln.id} ln={ln} locked={locked} busy={busy} openItem={openItem} run={run} />
            ))}
            {!locked && <GhostRow requisitionId={c.id} lots={pickable} busy={busy} run={run} />}
          </tbody>
        </table>
        {c.lines.length === 0 && locked && <div className="tab-empty">Требование пусто.</div>}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="требование" locked={locked} error={err}
      meta={<>
        {count(c.lines.length, 'строка', 'строки', 'строк')}
        {sumByUom(c.lines).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockRequisition(c.id))}
      fixateTitle="Зафиксировать требование"
      onUnfix={() => { if (confirm('Расфиксировать требования?')) run(api.unlockRequisition(c.id)) }}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл — появится в табе «Файлы»', disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy} numberLabel="№ требования"
          openProject={openProject}
          patch={b => run(api.updateRequisition(c.id, b))} />}
      tabs={tabs}
    />
  )
}

// Реальная строка требования: автосейв кол-ва (синхронит источник и потомок), удаление.
function LineRow({ ln, locked, busy, openItem, run }: {
  ln: RequisitionFormLine; locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<RequisitionForm>) => void
}) {
  const negative = ln.source_live_qty < 0
  return (
    <tr className="row">
      <td className="gl"><LotGlyph origin={ln.origin} liveQty={ln.source_live_qty} /></td>
      <td className="c-key"><span className="pn">{ln.lot_label}</span></td>
      <td className="c-fit">
        <a className="link" onClick={() => openItem(ln.item_id)}>{ln.item_code}</a></td>
      <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
        <span className="cell-ellip" title={ln.item_description}>{ln.item_description}</span></td>
      <td className="c-fit" style={{ color: 'var(--fg-dim)' }}>{ln.source_project_code}</td>
      <td className="num">
        <CommitInput value={String(ln.qty)} width={60} disabled={locked || busy}
          onCommit={v => run(api.updateRequisitionLine(ln.id, Number(v)))}
          validate={v => Number(v) > 0} />
      </td>
      <td className="uom">{ln.uom}</td>
      <td className="num">
        <span className={negative ? 'anomaly' : ''}>{num(ln.source_live_qty)}</span>
        {negative && <span className="anomaly" title="перетянули — источник в минусе">▲</span>}
      </td>
      {!locked && <td className="act">
        <button className="fh-ctl icon fh-del" title="Убрать строку требования"
          disabled={busy} onClick={() => run(api.deleteRequisitionLine(ln.id))}>
          <span className="ci ci-trash" /></button>
      </td>}
    </tr>
  )
}

// Призрачная строка: выбрать лот-источник (сквозной пикер, кроме получателя) + кол-во.
function GhostRow({ requisitionId, lots, busy, run }: {
  requisitionId: number; lots: AllAvailableLot[]; busy: boolean
  run: (p: Promise<RequisitionForm>) => void
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
      <td className="gl" />
      <td className="c-key" colSpan={2}>
        <Dropdown value={lotId} disabled={busy} placeholder="＋ лот-источник…"
          onPick={v => setLotId(Number(v))}
          options={lots.map(l => ({ value: l.lot_id,
            label: `${l.project_code} · #${l.lot_id} ${l.item_code}`
              + (l.lot_name ? ` (${l.lot_name})` : '') + ` · ${num(l.live_qty)} ${l.uom}` }))} />
      </td>
      <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
        {picked?.item_description ?? ''}</td>
      <td className="c-fit" style={{ color: 'var(--fg-dim)' }}>{picked?.project_code ?? ''}</td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy || !lotId} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="uom">{picked?.uom ?? ''}</td>
      <td className="num" style={{ color: 'var(--fg-dim)' }}>
        {picked ? num(picked.live_qty) : ''}
      </td>
      <td className="act">
        <button className="btn sm" disabled={busy || !lotId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
