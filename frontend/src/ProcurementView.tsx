// Витрина волны 7: кокпит закупки-плана (Procurement) — записываемое ядро.
// Самостоятельный план без проекта (маркер командной высоты). Строки (item + qty,
// автосейв в черновике). Мягкий замок = отправка (draft→sent): строки read-only. Кнопка
// выгрузки order.xlsx поставщику. Волна 8 — панель pegging: нарезка плана на проектные
// заказы (веер Purchase под этим планом-родителем).
import { useEffect, useState } from 'react'
import { api, type ItemRow, type ProcurementCockpit, type ProcurementCockpitLine } from './api'
import { CommitInput } from './ReceiptView'
import { AuthorField, FormHeader, useFormLock } from './FormHeader'
import { PURCH_ST } from './PurchaseView'
import { PeggingPanel } from './PeggingPanel'
import { num } from './status'

export function ProcurementView({ procurementId, items, openItem, openPurchase, onChanged, onDeleted }: {
  procurementId: number; items: ItemRow[]
  openItem: (id: number) => void; openPurchase: (id: number) => void; onChanged: () => void
  onDeleted?: () => void
}) {
  const [c, setC] = useState<ProcurementCockpit | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rev, setRev] = useState(0)     // растёт на мутациях — освежает панель pegging
  const { unlocked, toggle } = useFormLock(true)

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

  // Удаление закупки-плана (WAVE14 Ф2) под замком: только черновик (posted → fix-chip);
  // friendly-guard бэка держит привязанные заказы.
  const del = () => {
    if (!c || !confirm('Удалить закупку-план? Строки будут сняты. Действие необратимо.')) return
    setBusy(true); setErr(null)
    api.deleteProcurement(c.id).then(() => { onChanged(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const st = PURCH_ST[c.status] ?? PURCH_ST.draft
  const editable = c.editable
  const fixed = !editable                  // отправлен/отменён — read-only (фиксация)
  return (
    <div className={unlocked && editable ? '' : 'form-locked'}>
      <FormHeader
        name={`Закупка #${c.id} · план (командная высота)`}
        meta={<>
          <span className={`glyph ${st.cls}`}>{st.g}</span> {st.label}
          {c.date && <> · {c.date}</>} · позиций {c.lines.length} · всего {num(c.total_qty)}
          {c.note && <> · {c.note}</>}
        </>}
        unlocked={unlocked} onToggleLock={toggle}
        onDelete={unlocked ? del : undefined}
        fixed={fixed} fixedLabel={st.label}
        onUnfix={() => {
          if (c.status === 'sent' && confirm('Вернуть закупку в черновик?')) run(api.unsendProcurement(c.id))
          else if (c.status === 'cancelled' && confirm('Восстановить закупку из отменённых?')) run(api.restoreProcurement(c.id))
        }}
        error={err}
      />

      <dl className="props">
        <dt>Дата</dt>
        <dd><CommitInput value={c.date ?? ''} width={140} type="date" disabled={!editable || busy}
          onCommit={v => run(api.updateProcurement(c.id, { date: v }))} /></dd>
        <dt>Примечание</dt>
        <dd><CommitInput value={c.note} width={240} disabled={!editable || busy}
          onCommit={v => run(api.updateProcurement(c.id, { note: v }))} /></dd>
        <AuthorField userId={c.user_id} userName={c.user_name} disabled={!editable || busy}
          onChange={id => run(api.updateProcurement(c.id, { user_id: id }))} />
      </dl>

      <div className="kit-actions">
        {c.status === 'draft' && <>
          <button className="btn primary" disabled={busy || unlocked}
            title={unlocked ? 'Сначала закройте замок — просмотрите чистовик' : 'Зафиксировать документ'}
            onClick={() => run(api.sendProcurement(c.id))}>Отправить · зафиксировать</button>
          <button className="btn" disabled={busy}
            onClick={() => run(api.cancelProcurement(c.id))}>Отменить</button>
        </>}
        {c.status === 'sent' &&
          <button className="btn" disabled={busy}
            onClick={() => run(api.cancelProcurement(c.id))}>Отменить</button>}
        <a className="btn" href={api.orderXlsxUrl(c.id)} download
          title="выгрузить order.xlsx для поставщика">Скачать order.xlsx</a>
        {err && <span className="anomaly">{err}</span>}
      </div>

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

      {c.status !== 'cancelled' &&
        <PeggingPanel procurementId={c.id} rev={rev} openPurchase={openPurchase} />}
    </div>
  )
}

// Строка плана: изделие + кол-во (автосейв в черновике).
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

// Призрачная строка: добавить позицию в план (только в черновике).
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
