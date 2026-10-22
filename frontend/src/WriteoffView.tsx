// Витрина волны 6: форма списания / Writeoff (записываемое ядро).
// Списание — чистое выбытие партии из проекта (`−ISSUE`, серый путь): born-лота
// нет, лот покидает учёт. Строка = списываем свою партию; добавление/правка/
// удаление автосейвом. Корректность — «списываем только своё» + пересписание в
// минус информативно (▲).
//
// Волна 19 (Ф12c): форма по канону §13 — табы Строки · Файлы, общие поля шапки
// через `OrderFields`, «Причина» — специфика вида.
import { useState } from 'react'
import { api, type AvailableLot, type WriteoffForm,
  type WriteoffFormLine } from './api'
import { CommitInput } from './CommitInput'
import { OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { MoneyBlock } from './StatPanel'
import { Dropdown } from './Dropdown'
import { TextField } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { Anomaly, LotGlyph, count, num, sumByUom } from './status'
import { EntityLink } from './EntityLink'
import { pairKey, pairLabel } from './lotPairs'

export function WriteoffView({ writeoffId, isNew, openItem, openLot, openProject, onChanged, onDeleted }: {
  writeoffId: number
  isNew: boolean
  openItem: (id: number) => void; openLot: (id: number) => void
  openProject: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [lots, setLots] = useState<AvailableLot[]>([])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    writeoffId, api.writeoff, {
      onChanged, onDeleted,
      onLoad: c => { api.projectAvailableLots(c.project_id).then(setLots) },
      remove: api.deleteWriteoff,
      confirmDelete: { noun: 'списание' },
    }, isNew)
  const att = useAttachments('writeoff', writeoffId)   // загрузка — команда шапки (§13.8)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.locked                   // проведено — read-only (единый мягкий замок)
  const locked = fixed || !unlocked

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="rn">№</th><th className="gl" /><th className="c-key">Партия</th>
              <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
              <th className="num">Кол-во</th><th className="uom">Ед.</th>
              <th className="num">Остаток</th>
              {!locked && <th className="act" />}
            </tr>
          </thead>
          <tbody>
            {c.lines.map((ln, i) => (
              <LineRow key={ln.id} no={i + 1} ln={ln} locked={locked} busy={busy} openItem={openItem} openLot={openLot} run={run} />
            ))}
            {!locked && <GhostRow writeoffId={c.id} lots={lots} busy={busy} run={run} />}
          </tbody>
        </table>
        {c.lines.length === 0 && locked && <div className="tab-empty">Акт пуст.</div>}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="списание" locked={locked} error={err}
      // Мета (§13.6): счёт по табам + итог документа в натуре (по единицам).
      meta={<>
        {count(c.lines.length, 'строка', 'строки', 'строк')}
        {sumByUom(c.lines).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockWriteoff(c.id))}
      fixateTitle="Зафиксировать акт списания"
      onUnfix={() => run(api.unlockWriteoff(c.id))}
      fixation={`writeoffs/${c.id}`}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл — появится в табе «Файлы»', disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy} numberLabel="№ акта"
          openProject={openProject}
          patch={b => run(api.updateWriteoff(c.id, b))}>
          <TextField label="Причина" value={c.reason} locked={locked} busy={busy}
            onCommit={v => run(api.updateWriteoff(c.id, { reason: v }))} />
        </OrderFields>}
      // Блок «Деньги» (волна 26): у ордера одно число — сумма его движений.
      extra={<MoneyBlock label="списали на сумму" value={c.total_cost}
        title="Потери в рублях: стоимость списанных партий — их доли по учётному канону" />}
      tabs={tabs}
    />
  )
}

// Реальная строка списания (лот): автосейв кол-ва, удаление (коррекция).
function LineRow({ no, ln, locked, busy, openItem, openLot, run }: {
  no?: number
  ln: WriteoffFormLine; locked: boolean; busy: boolean
  openItem: (id: number) => void; openLot: (id: number) => void
  run: (p: Promise<WriteoffForm>) => void
}) {
  const negative = ln.lot_live_qty < 0   // пересписали — источник в минусе
  return (
    <tr className="row">
      <td className="rn">{no}</td>
      <td className="gl"><LotGlyph native={ln.item_native} liveQty={ln.lot_live_qty} /></td>
      <td className="c-key">
        <EntityLink kind="lot" id={ln.lot_id} open={openLot}>{ln.lot_label}</EntityLink></td>
      <td className="c-fit">
        <EntityLink kind="item" id={ln.item_id} open={openItem}>{ln.item_code}</EntityLink></td>
      <td className="c-desc">
        <span className="cell-ellip" title={ln.item_description}>{ln.item_description}</span></td>
      <td className="num">
        <CommitInput value={String(ln.qty)} disabled={locked || busy}
          onCommit={v => run(api.updateWriteoffLine(ln.id, Number(v)))}
          validate={v => Number(v) > 0} />
      </td>
      <td className="uom">{ln.uom}</td>
      <td className="num">
        <span className={negative ? 'anomaly' : ''}>{num(ln.lot_live_qty)}</span>
        {negative && <Anomaly title="пересписали — источник в минусе" />}
      </td>
      {!locked && <td className="act">
        <button className="fh-ctl icon fh-del" title="Убрать строку списания"
          disabled={busy} onClick={() => run(api.deleteWriteoffLine(ln.id))}>
          <span className="ci ci-trash" /></button>
      </td>}
    </tr>
  )
}

// Призрачная строка: выбрать списываемую партию проекта (пикер live>0) + кол-во.
function GhostRow({ writeoffId, lots, busy, run }: {
  writeoffId: number; lots: AvailableLot[]; busy: boolean
  run: (p: Promise<WriteoffForm>) => void
}) {
  // Волна 27: строка пикера — пара «лот @ локация» (выбор лота = выбор места).
  const [pick, setPick] = useState('')
  const [qty, setQty] = useState('')
  const picked = lots.find(l => pairKey(l) === pick)

  const add = () => {
    const q = Number(qty)
    if (!picked || !(q > 0)) return
    run(api.addWriteoffLine(writeoffId, { lot_id: picked.lot_id, location_id: picked.location_id, qty: q }))
    setPick(''); setQty('')
  }

  return (
    <tr className="row ghost">
      <td className="rn" />
      <td className="gl" />
      <td className="c-key" colSpan={2}>
        <Dropdown value={pick} disabled={busy} placeholder="Партия…"
          onPick={v => setPick(String(v))} onClear={() => setPick('')}
          options={lots.map(l => ({ value: pairKey(l),
            label: pairLabel(l, `#${l.lot_id} ${l.item_code}`) }))} />
      </td>
      <td className="c-desc">
        {picked?.item_description ?? ''}</td>
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
        <button className="fh-ctl icon fh-add" title="Добавить строку списания"
          disabled={busy || !picked || !(Number(qty) > 0)} onClick={add}>
          <span className="ci ci-add" /></button>
      </td>
    </tr>
  )
}
