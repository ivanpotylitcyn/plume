// Витрина волны 5: форма передачи / Transfer (записываемое ядро).
// Отгрузка готового железа заказчику по накладной. Строка передачи = отдаём
// партию проекта (`−ISSUE`); добавление/правка/удаление автосейвом. Мягкого
// замка нет (у Transfer нет поля статуса) — правимо всегда; guard корректности —
// «лот не потреблён ниже» на бэке. Отображаемое имя строки печатается в накладной.
// Волна 19 (Ф12c): форма по канону §13 — табы Строки · Файлы, общие поля шапки
// через `OrderFields`, «Заказчик» — специфика вида.
import { useEffect, useState } from 'react'
import { api, type AvailableLot, type CounterpartyRow, type TransferForm,
  type TransferFormLine } from './api'
import { CommitInput } from './CommitInput'
import { OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { Dropdown } from './Dropdown'
import { Field } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { LotGlyph, count, num, sumByUom } from './status'
import { CounterpartyPicker } from './Picker'

export function TransferView({ transferId, isNew, openItem, openProject, onChanged, onDeleted }: {
  transferId: number
  isNew: boolean
  openItem: (id: number) => void
  openProject: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [lots, setLots] = useState<AvailableLot[]>([])
  const [customers, setCustomers] = useState<CounterpartyRow[]>([])
  useEffect(() => { api.counterparties().then(setCustomers) }, [])

  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    transferId, api.transfer, {
      onChanged, onDeleted,
      onLoad: c => { api.projectAvailableLots(c.project_id).then(setLots) },
      remove: api.deleteTransfer,
      confirmDelete: 'Удалить передачу (накладную)? Действие необратимо.',
    }, isNew)
  const att = useAttachments('transfer', transferId)   // загрузка — команда шапки (§13.8)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.locked                   // отгружено (проведена) — read-only
  const locked = fixed || !unlocked

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="gl" /><th className="c-key">Партия</th>
              <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
              <th className="num">Кол-во</th><th className="uom">Ед.</th>
              <th className="num">Остаток</th>
              <th className="c-fit">Имя в накладной</th>
              {!locked && <th className="act" />}
            </tr>
          </thead>
          <tbody>
            {c.lines.map(ln => (
              <LineRow key={ln.id} ln={ln} locked={locked} busy={busy}
                openItem={openItem} run={run} />
            ))}
            {!locked && <GhostRow transferId={c.id} lots={lots} busy={busy} run={run} />}
          </tbody>
        </table>
        {c.lines.length === 0 && locked && <div className="tab-empty">Накладная пуста.</div>}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="передачу" locked={locked} error={err}
      meta={<>
        {count(c.lines.length, 'строка', 'строки', 'строк')}
        {sumByUom(c.lines).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockTransfer(c.id))}
      fixateTitle="Отгружено — зафиксировать передачу"
      onUnfix={() => { if (confirm('Расфиксировать передачу? Отгрузка откатится.')) run(api.unlockTransfer(c.id)) }}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (скан накладной) — появится в табе «Файлы»', disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy} numberLabel="№ накладной"
          openProject={openProject}
          patch={b => run(api.updateTransfer(c.id, b))}
          // Ф17: «Заказчик» — это `contractor`, то есть ЯКОРЬ, а не атрибут вида:
          // его место сразу за Проектом, до номера накладной (§13.4a).
          anchors={
            <Field label="Заказчик" locked={locked} view={c.contractor_name}>
              <CounterpartyPicker counterparties={customers} side="shipment"
                value={c.contractor_id ?? ''}
                disabled={busy} placeholder="— не указан —"
                onPick={id => run(api.updateTransfer(c.id, { contractor_id: id }))}
                onClear={() => run(api.updateTransfer(c.id, { contractor_id: null }))}
                onCreate={name => api.createCounterparty({ description: name })
                  .then(cp => { api.counterparties().then(setCustomers)
                    run(api.updateTransfer(c.id, { contractor_id: cp.id })) })} />
            </Field>} />}
      tabs={tabs}
    />
  )
}

// Реальная строка передачи (лот): автосейв кол-ва/имени, удаление (коррекция).
function LineRow({ ln, locked, busy, openItem, run }: {
  ln: TransferFormLine; locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<TransferForm>) => void
}) {
  const negative = ln.lot_live_qty < 0   // переотдали — источник в минусе
  return (
    <tr className="row">
      <td className="gl"><LotGlyph origin={ln.origin} liveQty={ln.lot_live_qty} /></td>
      <td className="c-key"><span className="pn">{ln.lot_label}</span></td>
      <td className="c-fit">
        <a className="link" onClick={() => openItem(ln.item_id)}>{ln.item_code}</a></td>
      <td className="c-desc">
        <span className="cell-ellip" title={ln.item_description}>{ln.item_description}</span></td>
      <td className="num">
        <CommitInput value={String(ln.qty)} width={60} disabled={locked || busy}
          onCommit={v => run(api.updateTransferLine(ln.id, { qty: Number(v) }))}
          validate={v => Number(v) > 0} />
      </td>
      <td className="uom">{ln.uom}</td>
      <td className="num">
        <span className={negative ? 'anomaly' : ''}>{num(ln.lot_live_qty)}</span>
        {negative && <span className="anomaly" title="переотдали — источник в минусе">▲</span>}
      </td>
      <td className="c-fit">
        <CommitInput value={ln.display_name} width={200} disabled={locked || busy}
          onCommit={v => run(api.updateTransferLine(ln.id, { display_name: v }))} />
      </td>
      {!locked && <td className="act">
        <button className="fh-ctl icon fh-del" title="Убрать строку передачи"
          disabled={busy} onClick={() => run(api.deleteTransferLine(ln.id))}>
          <span className="ci ci-trash" /></button>
      </td>}
    </tr>
  )
}

// Призрачная строка: выбрать отдаваемую партию проекта (пикер live>0) + кол-во.
function GhostRow({ transferId, lots, busy, run }: {
  transferId: number; lots: AvailableLot[]; busy: boolean
  run: (p: Promise<TransferForm>) => void
}) {
  const [lotId, setLotId] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  const [name, setName] = useState('')
  const picked = lots.find(l => l.lot_id === lotId)

  const add = () => {
    const q = Number(qty)
    if (!lotId || !(q > 0)) return
    run(api.addTransferLine(transferId, {
      lot_id: lotId, qty: q, display_name: name || undefined,
    }))
    setLotId(''); setQty(''); setName('')
  }

  return (
    <tr className="row ghost">
      <td className="gl" />
      <td className="c-key" colSpan={2}>
        <Dropdown value={lotId} disabled={busy} placeholder="＋ партия…"
          onPick={v => setLotId(Number(v))}
          options={lots.map(l => ({ value: l.lot_id,
            label: `#${l.lot_id} ${l.item_code}` + (l.lot_name ? ` (${l.lot_name})` : '')
              + ` · ${num(l.live_qty)} ${l.uom}` }))} />
      </td>
      <td className="c-desc">
        {picked?.item_description ?? ''}</td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy || !lotId} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="uom">{picked?.uom ?? ''}</td>
      <td className="num">
        {picked ? num(picked.live_qty) : ''}
      </td>
      <td className="c-fit">
        <input className="qty-in" style={{ width: 200 }} value={name} disabled={busy}
          placeholder="имя в накладной (авто)" onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="act">
        <button className="btn sm" disabled={busy || !lotId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
