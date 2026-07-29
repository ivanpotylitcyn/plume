// Витрина волны 7: форма закупки-плана (Procurement) — записываемое ядро.
// Самостоятельный план без проекта (маркер командной высоты). Строки (item + qty,
// автосейв, пока расфиксирована). Замок делает строки read-only.
// Кнопка выгрузки xlsx-бланка поставщику (имя файла = код закупки). Волна 8 — панель pegging: нарезка плана на
// проектные заказы (веер Purchase под этим планом-родителем).
//
// Волна 19 (Ф12c): форма по канону §13 — табы Строки · Привязка · Заказы · Файлы.
// Панель pegging разобрана на два таба (§13.7), её команда «Разрезать по проектам»
// уехала в колонку команд шапки. Проекта у плана нет (он командный) — поэтому общий
// `OrderFields` тут неприменим, поля выписаны свои; охват проектов придёт в Ф13.
import { useEffect, useState } from 'react'
import { api, type ItemRow, type ProcurementForm, type ProcurementFormLine,
  type CounterpartyRow } from './api'
import { CommitInput } from './CommitInput'
import { AuthorField, useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { PeggingRows, PurchaseFan, usePegging } from './PeggingPanel'
import { CounterpartyPicker, ItemPicker } from './Picker'
import { ItemGlyph, count, num, sumByUom } from './status'

export function ProcurementView({ procurementId, items, isNew, openItem, openPurchase, onChanged, onDeleted }: {
  procurementId: number; items: ItemRow[]; isNew: boolean
  openItem: (id: number) => void; openPurchase: (id: number) => void; onChanged: () => void
  onDeleted?: () => void
}) {
  const [c, setC] = useState<ProcurementForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rev, setRev] = useState(0)     // растёт на мутациях — освежает панель pegging
  const [suppliers, setSuppliers] = useState<CounterpartyRow[]>([])
  const { unlocked, toggle } = useFormLock(procurementId, isNew)

  // Контрагенты-поставщики (Ф4, Р3): закупка = поток общения с поставщиком.
  useEffect(() => { api.counterparties('supplier').then(setSuppliers) }, [])
  const att = useAttachments('procurement', procurementId)   // владелец заведён Ф12b (§13.8)
  const peg = usePegging(procurementId, rev)                 // табы «Привязка» и «Заказы»

  useEffect(() => {
    setC(null); setErr(null)
    api.procurement(procurementId).then(setC).catch(e => setErr(String(e)))
  }, [procurementId])

  const run = (p: Promise<ProcurementForm>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); setRev(n => n + 1); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Удаление закупки-плана (WAVE14 Ф2): корзина в шапке только у расфиксированной
  // (§5: у запертой одна степень свободы — расфиксировать); friendly-guard бэка
  // держит привязанные заказы.
  const del = () => {
    if (!c || !confirm('Удалить закупку-план? Строки будут сняты. Действие необратимо.')) return
    setBusy(true); setErr(null)
    api.deleteProcurement(c.id).then(() => { onChanged(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const editable = c.editable
  const fixed = !editable                  // зафиксирована — read-only
  const locked = !editable || !unlocked

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="gl" /><th className="c-key">Изделие</th>
              <th className="c-desc">Описание</th>
              <th style={{ textAlign: 'right' }}>Кол-во</th><th className="uom">Ед.</th>
              {editable && <th className="act" />}
            </tr>
          </thead>
          <tbody>
            {c.lines.map(ln => (
              <LineRow key={ln.id} ln={ln} editable={editable} busy={busy}
                openItem={openItem} run={run} />
            ))}
            {editable && <GhostRow procurementId={c.id} items={items} busy={busy} run={run} />}
          </tbody>
        </table>
        {c.lines.length === 0 && !editable && <div className="tab-empty">Закупка пуста.</div>}
      </> },
    { key: 'pegging', label: 'Привязка', icon: 'flag',
      content: <PeggingRows st={peg} procurementId={c.id} /> },
    { key: 'fan', label: 'Заказы', icon: 'package',
      content: <PurchaseFan st={peg} openPurchase={openPurchase} /> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="закупку" locked={locked} error={err}
      // Мета (§13.6): счёт по табам + итог плана в натуре. Контрагент и дата — в полях.
      meta={<>
        {count(c.lines.length, 'позиция', 'позиции', 'позиций')}
        {sumByUom(c.lines).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(peg.p?.fan.length ?? 0, 'заказ', 'заказа', 'заказов')}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      onDelete={del}
      fixed={fixed}
      onFixate={() => run(api.lockProcurement(c.id))}
      fixateTitle="Зафиксировать закупку — строки станут read-only"
      onUnfix={() => {
        if (confirm('Расфиксировать закупку?')) run(api.unlockProcurement(c.id))
      }}
      download={{ href: api.xlsxUrl(c.id), title: 'Скачать xlsx-бланк для поставщика (имя файла = код закупки)' }}
      actions={[
        ...(editable ? [{ onClick: peg.autopeg, label: 'Разрезать', icon: 'ci-git-branch',
          title: 'Разложить каждую строку плана по нуждающимся проектам (наводка свода)',
          disabled: peg.busy }] : []),
        { onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
          title: 'Загрузить файл (КП, счёт) — появится в табе «Файлы»', disabled: att.busy },
      ]}
      fields={<>
        <dt>Код</dt>
        <dd><CommitInput value={c.code ?? ''} disabled={!editable || busy}
          onCommit={v => run(api.updateProcurement(c.id, { code: v }))} /></dd>
        <dt>Описание</dt>
        <dd className="wide"><CommitInput value={c.description} disabled={!editable || busy}
          onCommit={v => run(api.updateProcurement(c.id, { description: v }))} /></dd>
        <dt>Дата</dt>
        <dd><CommitInput value={c.date ?? ''} type="date" disabled={!editable || busy}
          onCommit={v => run(api.updateProcurement(c.id, { date: v }))} /></dd>
        <dt>Контрагент</dt>
        <dd>
          <CounterpartyPicker counterparties={suppliers} value={c.contractor_id ?? ''}
            disabled={!editable || busy} placeholder="— не указан —"
            onPick={id => run(api.updateProcurement(c.id, { contractor_id: id }))}
            onClear={() => run(api.updateProcurement(c.id, { contractor_id: null }))}
            onCreate={name => api.createCounterparty({ description: name, role: 'supplier' })
              .then(cp => { api.counterparties('supplier').then(setSuppliers)
                run(api.updateProcurement(c.id, { contractor_id: cp.id })) })} />
        </dd>
        <AuthorField userId={c.user_id} userName={c.user_name} disabled={!editable || busy}
          onChange={id => run(api.updateProcurement(c.id, { user_id: id }))} />
      </>}
      tabs={tabs}
    />
  )
}

// Строка плана: изделие + кол-во (автосейв, пока расфиксировано).
function LineRow({ ln, editable, busy, openItem, run }: {
  ln: ProcurementFormLine; editable: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<ProcurementForm>) => void
}) {
  return (
    <tr className="row">
      <td className="gl">
        <ItemGlyph native={ln.item_native} synced={ln.item_synced} locked={ln.item_locked} /></td>
      <td className="c-key">
        <a className="link" onClick={() => openItem(ln.item_id)}>{ln.item_code}</a></td>
      <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
        <span className="cell-ellip" title={ln.item_description}>{ln.item_description}</span></td>
      <td className="num">
        {editable
          ? <CommitInput value={String(ln.qty)} width={72} disabled={busy}
              onCommit={v => run(api.updateProcurementLine(ln.id, Number(v)))}
              validate={v => Number(v) > 0} />
          : num(ln.qty)}
      </td>
      <td className="uom">{ln.uom}</td>
      {editable && <td className="act">
        <button className="fh-ctl icon fh-del" title="Убрать строку плана"
          disabled={busy} onClick={() => run(api.deleteProcurementLine(ln.id))}>
          <span className="ci ci-trash" /></button>
      </td>}
    </tr>
  )
}

// Призрачная строка: добавить позицию в план (только пока расфиксировано).
function GhostRow({ procurementId, items, busy, run }: {
  procurementId: number; items: ItemRow[]; busy: boolean
  run: (p: Promise<ProcurementForm>) => void
}) {
  const [itemId, setItemId] = useState<number | ''>('')
  const [qty, setQty] = useState('')

  const add = () => {
    const q = Number(qty)
    if (!itemId || !(q > 0)) return
    run(api.addProcurementLine(procurementId, { item_id: itemId, qty: q }))
    setItemId(''); setQty('')
  }

  return (
    <tr className="row ghost">
      <td className="gl" />
      <td className="c-key" colSpan={2}>
        <ItemPicker items={items} value={itemId} onPick={setItemId} disabled={busy}
          placeholder="＋ изделие…" onEnter={add} />
      </td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      {/* Ед. приезжает вместе с изделием — в призрачной строке её ещё нет. */}
      <td className="uom" />
      <td className="act">
        <button className="btn sm" disabled={busy || !itemId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
