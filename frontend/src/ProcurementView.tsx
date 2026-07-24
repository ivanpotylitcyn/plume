// Витрина волны 7: кокпит закупки-плана (Procurement) — записываемое ядро.
// Самостоятельный план без проекта (маркер командной высоты). Строки (item + qty,
// автосейв, пока расфиксирована). Замок делает строки read-only.
// Кнопка выгрузки order.xlsx поставщику. Волна 8 — панель pegging: нарезка плана на
// проектные заказы (веер Purchase под этим планом-родителем).
import { useEffect, useState } from 'react'
import { api, type ItemRow, type ProcurementCockpit, type ProcurementCockpitLine,
  type CounterpartyRow } from './api'
import { CommitInput } from './ReceiptView'
import { AuthorField, FormHeader, useFormLock } from './FormHeader'
import { PeggingPanel } from './PeggingPanel'
import { StatusGlyph, num } from './status'

export function ProcurementView({ procurementId, items, isNew, openItem, openPurchase, onChanged, onDeleted }: {
  procurementId: number; items: ItemRow[]; isNew: boolean
  openItem: (id: number) => void; openPurchase: (id: number) => void; onChanged: () => void
  onDeleted?: () => void
}) {
  const [c, setC] = useState<ProcurementCockpit | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rev, setRev] = useState(0)     // растёт на мутациях — освежает панель pegging
  const [suppliers, setSuppliers] = useState<CounterpartyRow[]>([])
  const { unlocked, toggle } = useFormLock(procurementId, isNew)

  // Контрагенты-поставщики (Ф4, Р3): закупка = поток общения с поставщиком.
  useEffect(() => { api.counterparties('supplier').then(setSuppliers) }, [])

  useEffect(() => {
    setC(null); setErr(null)
    api.procurement(procurementId).then(setC).catch(e => setErr(String(e)))
  }, [procurementId])

  const run = (p: Promise<ProcurementCockpit>) => {
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
  return (
    <div className={unlocked && editable ? '' : 'form-locked'}>
      <FormHeader
        code={c.code || `Закупка #${c.id}`}
        meta={<>
          <StatusGlyph locked={c.locked} />
          {c.locked ? 'зафиксирована' : 'расфиксирована'} · план
          {c.description && <> · {c.description}</>}
          {c.contractor_name && <> · {c.contractor_name}</>}
          {c.date && <> · {c.date}</>} · позиций {c.lines.length} · всего {num(c.total_qty)}
        </>}
        unlocked={unlocked} onToggleLock={toggle}
        onDelete={del}
        fixed={fixed}
        onFixate={() => run(api.lockProcurement(c.id))}
        onUnfix={() => {
          if (confirm('Расфиксировать закупку?')) run(api.unlockProcurement(c.id))
        }}
        download={{ href: api.orderXlsxUrl(c.id), title: 'Выгрузить order.xlsx для поставщика' }}
        error={err}
      >

      <dl className="props">
        <dt>Код</dt>
        <dd><CommitInput value={c.code ?? ''} width={240} disabled={!editable || busy}
          onCommit={v => run(api.updateProcurement(c.id, { code: v }))} /></dd>
        <dt>Описание</dt>
        <dd><CommitInput value={c.description} width={240} disabled={!editable || busy}
          onCommit={v => run(api.updateProcurement(c.id, { description: v }))} /></dd>
        <dt>Дата</dt>
        <dd><CommitInput value={c.date ?? ''} width={140} type="date" disabled={!editable || busy}
          onCommit={v => run(api.updateProcurement(c.id, { date: v }))} /></dd>
        <dt>Контрагент</dt>
        <dd>
          <select className="lot-sel" value={c.contractor_id ?? ''} disabled={!editable || busy}
            onChange={e => run(api.updateProcurement(c.id, {
              contractor_id: e.target.value ? Number(e.target.value) : null }))}>
            <option value="">— не указан —</option>
            {suppliers.map(cp => <option key={cp.id} value={cp.id}>{cp.description}</option>)}
          </select>
        </dd>
        <AuthorField userId={c.user_id} userName={c.user_name} disabled={!editable || busy}
          onChange={id => run(api.updateProcurement(c.id, { user_id: id }))} />
      </dl>
      </FormHeader>

      <table className="grid">
        <thead>
          <tr>
            <th>изделие</th><th>назв.</th>
            <th style={{ textAlign: 'right' }}>кол-во</th><th />
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
      {c.lines.length === 0 && !editable &&
        <div className="empty">Закупка пуста.</div>}

      {/* Гейт по «не отменённой» снят вместе со статусом (волна 19, Ф1). */}
      <PeggingPanel procurementId={c.id} rev={rev} openPurchase={openPurchase} />
    </div>
  )
}

// Строка плана: изделие + кол-во (автосейв, пока расфиксировано).
function LineRow({ ln, editable, busy, openItem, run }: {
  ln: ProcurementCockpitLine; editable: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<ProcurementCockpit>) => void
}) {
  return (
    <tr className="row s-available">
      <td>
        <a className="link" onClick={() => openItem(ln.item_id)}>{ln.item_design_item_id}</a>
      </td>
      <td style={{ color: 'var(--fg-dim)' }}>{ln.item_description}</td>
      <td className="num">
        {editable
          ? <CommitInput value={String(ln.qty)} width={72} disabled={busy}
              onCommit={v => run(api.updateProcurementLine(ln.id, Number(v)))}
              validate={v => Number(v) > 0} />
          : num(ln.qty)} {ln.uom}
      </td>
      <td style={{ textAlign: 'right' }}>
        {editable &&
          <button className="x" title="убрать строку" disabled={busy}
            onClick={() => run(api.deleteProcurementLine(ln.id))}>×</button>}
      </td>
    </tr>
  )
}

// Призрачная строка: добавить позицию в план (только пока расфиксировано).
function GhostRow({ procurementId, items, busy, run }: {
  procurementId: number; items: ItemRow[]; busy: boolean
  run: (p: Promise<ProcurementCockpit>) => void
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
      <td colSpan={2}>
        <select className="lot-sel" value={itemId} disabled={busy}
          onChange={e => setItemId(e.target.value ? Number(e.target.value) : '')}>
          <option value="">＋ изделие…</option>
          {items.map(i => <option key={i.id} value={i.id}>{i.design_item_id} — {i.description}</option>)}
        </select>
      </td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td style={{ textAlign: 'right' }}>
        <button className="btn sm" disabled={busy || !itemId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
