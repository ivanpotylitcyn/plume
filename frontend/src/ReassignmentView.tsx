// Витрина волны 6: форма перевода / Reassignment (записываемое ядро).
// Отпочкование: строка тянет из лота-источника (`−ISSUE`) и рождает лот-потомок
// в проекте-получателе (`+RECEIPT`, наследует item/цену/провенанс). Источник — из
// любого проекта (постановка своего на баланс → белый, заём у соседнего B→A).
// Замка нет — правимо всегда; корректность — источник ≠ получатель, один лот = одна
// строка, потомок не потреблён ниже (guard на бэке).
//
// Волна 19 (Ф12c): форма по канону §13 — табы Строки · Файлы, общие поля шапки
// через `OrderFields` (своих полей у перевода нет).
import { useState } from 'react'
import { api, type AllAvailableLot, type ReassignmentForm,
  type ReassignmentFormLine } from './api'
import { CommitInput } from './CommitInput'
import { OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { MoneyBlock } from './StatPanel'
import { Dropdown } from './Dropdown'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { Anomaly, LotGlyph, count, num, sumByUom } from './status'
import { EntityLink } from './EntityLink'
import { pairKey, pairLabel } from './lotPairs'

export function ReassignmentView({ reassignmentId, isNew, openItem, openLot, openProject, onChanged, onDeleted }: {
  reassignmentId: number
  isNew: boolean
  openItem: (id: number) => void; openLot: (id: number) => void
  openProject: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [lots, setLots] = useState<AllAvailableLot[]>([])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    reassignmentId, api.reassignment, {
      onChanged, onDeleted,
      onLoad: () => { api.allAvailableLots().then(setLots) },
      remove: api.deleteReassignment,
      confirmDelete: { noun: 'перевод' },
    }, isNew)
  const att = useAttachments('reassignment', reassignmentId)   // загрузка — команда шапки (§13.8)

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
              <th className="rn">№</th><th className="gl" /><th className="c-key">Источник</th>
              <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
              <th className="c-fit">Откуда</th>
              <th className="num">Кол-во</th><th className="uom">Ед.</th>
              <th className="num">Остаток ист.</th>
              {!locked && <th className="act" />}
            </tr>
          </thead>
          <tbody>
            {c.lines.map((ln, i) => (
              <LineRow key={ln.id} no={i + 1} ln={ln} locked={locked} busy={busy} openItem={openItem} openLot={openLot} run={run} />
            ))}
            {!locked && <GhostRow reassignmentId={c.id} lots={pickable} busy={busy} run={run} />}
          </tbody>
        </table>
        {c.lines.length === 0 && locked && <div className="tab-empty">Перевод пуст.</div>}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="перевод" locked={locked} error={err}
      meta={<>
        {count(c.lines.length, 'строка', 'строки', 'строк')}
        {sumByUom(c.lines).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockReassignment(c.id))}
      fixateTitle="Зафиксировать перевод"
      onUnfix={() => run(api.unlockReassignment(c.id))}
      fixation={`reassignments/${c.id}`}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл — появится в табе «Файлы»', disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy} numberLabel="№ перевода"
          openProject={openProject}
          patch={b => run(api.updateReassignment(c.id, b))} />}
      // Блок «Деньги» (волна 26): у ордера одно число — сумма его движений.
      extra={<MoneyBlock label="перевели на сумму" value={c.total_cost}
        title="Стоимость, переехавшая в проект-получатель: доли партий-источников" />}
      tabs={tabs}
    />
  )
}

// Реальная строка перевода: автосейв кол-ва (синхронит источник и потомок), удаление.
function LineRow({ no, ln, locked, busy, openItem, openLot, run }: {
  no?: number
  ln: ReassignmentFormLine; locked: boolean; busy: boolean
  openItem: (id: number) => void; openLot: (id: number) => void
  run: (p: Promise<ReassignmentForm>) => void
}) {
  const negative = ln.source_live_qty < 0
  return (
    <tr className="row">
      <td className="rn">{no}</td>
      <td className="gl"><LotGlyph native={ln.item_native} liveQty={ln.source_live_qty} /></td>
      <td className="c-key">
        <EntityLink kind="lot" id={ln.source_lot_id} open={openLot}>{ln.lot_label}</EntityLink></td>
      <td className="c-fit">
        <EntityLink kind="item" id={ln.item_id} open={openItem}>{ln.item_code}</EntityLink></td>
      <td className="c-desc">
        <span className="cell-ellip" title={ln.item_description}>{ln.item_description}</span></td>
      <td className="c-fit">{ln.source_project_code}</td>
      <td className="num">
        <CommitInput value={String(ln.qty)} disabled={locked || busy}
          onCommit={v => run(api.updateReassignmentLine(ln.id, Number(v)))}
          validate={v => Number(v) > 0} />
      </td>
      <td className="uom">{ln.uom}</td>
      <td className="num">
        <span className={negative ? 'anomaly' : ''}>{num(ln.source_live_qty)}</span>
        {negative && <Anomaly title="перетянули — источник в минусе" />}
      </td>
      {!locked && <td className="act">
        <button className="fh-ctl icon fh-del" title="Убрать строку перевода"
          disabled={busy} onClick={() => run(api.deleteReassignmentLine(ln.id))}>
          <span className="ci ci-trash" /></button>
      </td>}
    </tr>
  )
}

// Призрачная строка: выбрать лот-источник (сквозной пикер, кроме получателя) + кол-во.
function GhostRow({ reassignmentId, lots, busy, run }: {
  reassignmentId: number; lots: AllAvailableLot[]; busy: boolean
  run: (p: Promise<ReassignmentForm>) => void
}) {
  // Волна 27: строка пикера — пара «лот @ локация» (выбор лота = выбор места).
  const [pick, setPick] = useState('')
  const [qty, setQty] = useState('')
  const picked = lots.find(l => pairKey(l) === pick)

  const add = () => {
    const q = Number(qty)
    if (!picked || !(q > 0)) return
    run(api.addReassignmentLine(reassignmentId, { source_lot_id: picked.lot_id,
      location_id: picked.location_id, qty: q }))
    setPick(''); setQty('')
  }

  return (
    <tr className="row ghost">
      <td className="rn" />
      <td className="gl" />
      <td className="c-key" colSpan={2}>
        <Dropdown value={pick} disabled={busy} placeholder="Источник…"
          onPick={v => setPick(String(v))} onClear={() => setPick('')}
          options={lots.map(l => ({ value: pairKey(l),
            label: pairLabel(l, `${l.project_code} · #${l.lot_id} ${l.item_code}`) }))} />
      </td>
      <td className="c-desc">
        {picked?.item_description ?? ''}</td>
      <td className="c-fit">{picked?.project_code ?? ''}</td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy || !picked} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="uom">{picked?.uom ?? ''}</td>
      <td className="num">
        {picked ? num(picked.live_qty) : ''}
      </td>
      <td className="act">
        <button className="fh-ctl icon fh-add" title="Добавить строку перевода"
          disabled={busy || !picked || !(Number(qty) > 0)} onClick={add}>
          <span className="ci ci-add" /></button>
      </td>
    </tr>
  )
}
