// Волна 27: форма Требования / Requisition — официальная выдача с Центрального склада
// на нашу локацию (решение Ивана 2026-10-21). УПД оформляет бухгалтерия, и в работу
// компоненты уходят только по требованию — его же потом вписывают в акт комплектации
// (акт находит требование по своим лотам, связи в схеме нет).
//
// Строка = лот проекта, лежащий на Центральном; на бэке это пара знаковых `StockLine`
// (`−q`@Центральный / `+q`@«Куда»), та же механика, что у перемещения: тотал лота и
// проект не меняются. «Куда» — поле шапки, одно на документ (только наша локация).
import { useState } from 'react'
import { api, type AvailableLot, type RequisitionForm, type RequisitionLine } from './api'
import { CommitInput } from './CommitInput'
import { LocationField, OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { MoneyBlock } from './StatPanel'
import { Dropdown } from './Dropdown'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { Anomaly, LotGlyph, count, num, sumByUom } from './status'
import { EntityLink } from './EntityLink'
import { pairKey, pairLabel } from './lotPairs'

export function RequisitionView({ requisitionId, isNew, openItem, openProject, openLot,
  openLocation, onChanged, onDeleted }: {
  requisitionId: number
  isNew: boolean
  openItem: (id: number) => void
  openProject: (id: number) => void
  openLot: (id: number) => void
  openLocation: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [lots, setLots] = useState<AvailableLot[]>([])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    requisitionId, api.requisition, {
      onChanged, onDeleted,
      onLoad: c => { api.requisitionSourceLots(c.id).then(setLots) },
      remove: api.deleteRequisition,
      confirmDelete: { noun: 'требование', lines: ['выданные партии вернутся на Центральный'] },
    }, isNew)
  const att = useAttachments('requisition', requisitionId)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.locked
  const locked = fixed || !unlocked
  const dest = c.location_code || '«Куда»'
  // Уже выданные лоты пикер не предлагает: один лот = одна строка (бэк отклонит дубль).
  const inDoc = new Set(c.lines.map(l => l.lot_id))
  const free = lots.filter(l => !inDoc.has(l.lot_id))

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="rn">№</th><th className="gl" /><th className="c-key">Партия</th>
              <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
              <th className="num">Кол-во</th><th className="uom">Ед.</th>
              <th className="num" title={`остаток партии на складе ${c.central_code}`}>
                {c.central_code}</th>
              <th className="num" title="остаток партии в локации «Куда»">{dest}</th>
              {!locked && <th className="act" />}
            </tr>
          </thead>
          <tbody>
            {c.lines.map((ln, i) => (
              <LineRow key={ln.lot_id} no={i + 1} ln={ln} requisitionId={c.id}
                locked={locked} busy={busy} openItem={openItem} openLot={openLot} run={run} />
            ))}
            {!locked && <GhostRow requisitionId={c.id} lots={free} busy={busy}
              disabled={!c.location_id} run={run} />}
          </tbody>
        </table>
        {!locked && !c.location_id &&
          <div className="tab-empty">Укажите «Куда» в шапке — на какую локацию выдаём.</div>}
        {c.lines.length === 0 && locked && <div className="tab-empty">Требование пусто.</div>}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="требование" locked={locked} error={err}
      meta={<>
        {count(c.lines.length, 'позиция', 'позиции', 'позиций')}
        {sumByUom(c.lines).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockRequisition(c.id))}
      fixateTitle="Зафиксировать требование — выдать партии с Центрального склада"
      onUnfix={() => run(api.unlockRequisition(c.id))}
      fixation={`requisitions/${c.id}`}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (скан требования) — появится в табе «Файлы»', disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy} numberLabel="№ требования"
          openProject={openProject}
          patch={b => run(api.updateRequisition(c.id, b))}
          anchors={<LocationField c={c} locked={locked} busy={busy} own onOpen={openLocation}
            onChange={id => run(api.updateRequisition(c.id, { location_id: id }))} />} />}
      extra={<MoneyBlock label="выдали на сумму" value={c.total_cost}
        title="Стоимость партий, выданных с Центрального склада: остаток партии в рублях не меняется" />}
      tabs={tabs}
    />
  )
}

// Строка требования (ключ — лот): автосейв кол-ва, удаление.
function LineRow({ no, ln, requisitionId, locked, busy, openItem, openLot, run }: {
  no: number
  ln: RequisitionLine; requisitionId: number
  locked: boolean; busy: boolean
  openItem: (id: number) => void; openLot: (id: number) => void
  run: (p: Promise<RequisitionForm>) => void
}) {
  const negative = ln.central_live_qty < 0   // выдали больше, чем лежало
  return (
    <tr className="row">
      <td className="rn">{no}</td>
      <td className="gl"><LotGlyph native={ln.item_native} liveQty={ln.dest_live_qty} /></td>
      <td className="c-key">
        <EntityLink kind="lot" id={ln.lot_id} open={openLot}>{ln.lot_label}</EntityLink></td>
      <td className="c-fit">
        <EntityLink kind="item" id={ln.item_id} open={openItem}>{ln.item_code}</EntityLink></td>
      <td className="c-desc">
        <span className="cell-ellip" title={ln.item_description}>{ln.item_description}</span></td>
      <td className="num">
        {locked ? num(ln.qty)
          : <CommitInput value={String(ln.qty)} disabled={busy}
              onCommit={v => run(api.updateRequisitionLine(requisitionId, ln.lot_id, Number(v)))}
              validate={v => Number(v) > 0} />}
      </td>
      <td className="uom">{ln.uom}</td>
      <td className="num">
        <span className={negative ? 'anomaly' : ''}>{num(ln.central_live_qty)}</span>
        {negative && <Anomaly title="на Центральном минус — выдали больше, чем лежало" />}
      </td>
      <td className="num">{num(ln.dest_live_qty)}</td>
      {!locked && <td className="act">
        <button className="fh-ctl icon fh-del" title="Убрать строку требования"
          disabled={busy} onClick={() => run(api.deleteRequisitionLine(requisitionId, ln.lot_id))}>
          <span className="ci ci-trash" /></button>
      </td>}
    </tr>
  )
}

// Призрачная строка: лот проекта, лежащий на Центральном, и кол-во (по умолчанию —
// всё, что там лежит: обычно партию забирают целиком).
function GhostRow({ requisitionId, lots, busy, disabled, run }: {
  requisitionId: number; lots: AvailableLot[]; busy: boolean; disabled: boolean
  run: (p: Promise<RequisitionForm>) => void
}) {
  const [pick, setPick] = useState('')
  const [qty, setQty] = useState('')
  const picked = lots.find(l => pairKey(l) === pick)
  const off = busy || disabled

  const choose = (key: string) => {
    setPick(key)
    const lot = lots.find(l => pairKey(l) === key)
    setQty(lot ? String(lot.live_qty) : '')
  }
  const add = () => {
    const q = Number(qty)
    if (!picked || !(q > 0)) return
    run(api.addRequisitionLine(requisitionId, { lot_id: picked.lot_id, qty: q }))
    setPick(''); setQty('')
  }

  return (
    <tr className="row ghost">
      <td className="rn" />
      <td className="gl" />
      <td className="c-key" colSpan={2}>
        <Dropdown value={pick} disabled={off}
          placeholder={lots.length ? 'Партия на Центральном…' : 'на Центральном пусто'}
          onPick={v => choose(String(v))} onClear={() => choose('')}
          options={lots.map(l => ({ value: pairKey(l),
            label: pairLabel(l, `#${l.lot_id} ${l.item_code}`) }))} />
      </td>
      <td className="c-desc">{picked?.item_description ?? ''}</td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={off || !picked} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="uom">{picked?.uom ?? ''}</td>
      <td className="num" />
      <td className="num" />
      <td className="act">
        <button className="fh-ctl icon fh-add" title="Добавить строку требования"
          disabled={off || !picked || !(Number(qty) > 0)} onClick={add}>
          <span className="ci ci-add" /></button>
      </td>
    </tr>
  )
}
