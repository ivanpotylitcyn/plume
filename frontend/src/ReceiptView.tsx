// Витрина волны 3: кокпит прихода / УПД (записываемое ядро).
// Строки УПД = лоты (в модели отдельной ReceiptLine нет): изделие + кол-во +
// цена + название, автосейв по blur/Enter. Добавление строки = рождение партии
// (+RECEIPT). Замок «сверено со сканом» (approved) делает форму read-only.
import { useEffect, useState } from 'react'
import { api, type ItemRow, type ProjectPurchaseRow, type ReceiptCockpit,
  type ReceiptLot } from './api'
import { num } from './status'
import { AttachmentPanel } from './AttachmentPanel'
import { FormHeader, useFormLock } from './FormHeader'

export function ReceiptView({ receiptId, items, openItem, openPurchase, onChanged, onDeleted }: {
  receiptId: number; items: ItemRow[]
  openItem: (id: number) => void; openPurchase: (id: number) => void
  onChanged: () => void; onDeleted: () => void
}) {
  const [c, setC] = useState<ReceiptCockpit | null>(null)
  const [purchases, setPurchases] = useState<ProjectPurchaseRow[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { unlocked, toggle } = useFormLock(true)

  useEffect(() => {
    setC(null); setErr(null)
    api.receipt(receiptId).then(c => {
      setC(c)
      api.projectPurchases(c.project_id).then(setPurchases)
    }).catch(e => setErr(String(e)))
  }, [receiptId])

  const run = (p: Promise<ReceiptCockpit>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  const del = () => {
    if (!c || !confirm('Удалить поставку (УПД)? Рождённые партии будут сняты. Действие необратимо.')) return
    setBusy(true); setErr(null)
    api.deleteReceipt(c.id).then(() => onDeleted())
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.approved                 // фиксация (проведена/сверена) — read-only
  const locked = fixed || !unlocked        // + личный замок формы
  return (
    <div className={unlocked && !fixed ? '' : 'form-locked'}>
      <FormHeader
        name={c.supplier_name}
        meta={<>
          <span className={`glyph ${fixed ? 'g-lock' : 'g-on_order'}`}>{fixed ? '🔒' : '●'}</span>
          УПД {c.number} · {c.date} · {c.project_code} · сумма {num(c.total_cost)} ₽
        </>}
        unlocked={unlocked} onToggleLock={toggle}
        fixed={fixed} fixedLabel="сверена"
        onUnfix={() => { if (confirm('Снять фиксацию поставки? Форма станет черновиком.')) run(api.unapproveReceipt(c.id)) }}
        onDelete={del}
        error={err}
      />

      <div className="hdr-edit">
        <label>№ УПД <CommitInput value={c.number} width={140} disabled={locked || busy}
          onCommit={v => run(api.updateReceipt(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></label>
        <label>дата <CommitInput value={c.date} width={140} type="date" disabled={locked || busy}
          onCommit={v => run(api.updateReceipt(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></label>
      </div>

      <div className="kit-actions">
        {!fixed &&
          <button className="btn primary" disabled={busy || unlocked}
            title={unlocked ? 'Сначала закройте замок — просмотрите чистовик' : 'Зафиксировать документ'}
            onClick={() => run(api.approveReceipt(c.id))}>Сверено со сканом · зафиксировать</button>}
        <span className="hint">Заказ (закрывает):</span>
        <select className="lot-sel" value={c.purchase_id ?? ''} disabled={locked || busy}
          onChange={e => run(api.linkReceiptPurchase(
            c.id, e.target.value ? Number(e.target.value) : null))}>
          <option value="">— не связан —</option>
          {purchases.map(p => (
            <option key={p.id} value={p.id}>Заказ #{p.id} · {p.status} · {p.lines} стр.</option>
          ))}
        </select>
        {c.purchase_id &&
          <a className="link" onClick={() => openPurchase(c.purchase_id!)}>открыть заказ ›</a>}
        {err && <span className="anomaly">{err}</span>}
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th>изделие</th><th style={{ textAlign: 'right' }}>кол-во</th>
            <th style={{ textAlign: 'right' }}>цена, ₽</th>
            <th>part number</th><th>название из УПД</th><th />
          </tr>
        </thead>
        <tbody>
          {c.lots.map(lot => (
            <LotRow key={lot.id} lot={lot} locked={locked} busy={busy}
              openItem={openItem} run={run} />
          ))}
          {!locked && <GhostRow receiptId={c.id} items={items} busy={busy} run={run} />}
        </tbody>
      </table>
      {c.lots.length === 0 && locked &&
        <div className="empty">Приход пуст.</div>}

      <AttachmentPanel ownerType="receipt" ownerId={c.id} />
    </div>
  )
}

// Реальная строка УПД (лот): автосейв кол-ва/цены/названия, удаление до замка.
function LotRow({ lot, locked, busy, openItem, run }: {
  lot: ReceiptLot; locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<ReceiptCockpit>) => void
}) {
  const short = lot.live_qty !== lot.qty   // просел под пайку/расход
  return (
    <tr className="row s-available">
      <td>
        <span className="glyph g-available">✓</span>{' '}
        <a className="link" onClick={() => openItem(lot.item_id)}>{lot.item_code}</a>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>{lot.item_name}</span>
        {short && <span className="hint">остаток {num(lot.live_qty)} {lot.uom}</span>}
      </td>
      <td className="num">
        <CommitInput value={String(lot.qty)} width={60} disabled={locked || busy}
          onCommit={v => run(api.updateReceiptLot(lot.id, { qty: Number(v) }))}
          validate={v => Number(v) > 0} /> {lot.uom}
      </td>
      <td className="num">
        <CommitInput value={String(lot.unit_cost)} width={72} disabled={locked || busy}
          onCommit={v => run(api.updateReceiptLot(lot.id, { unit_cost: Number(v) }))}
          validate={v => Number(v) >= 0} />
      </td>
      <td>
        <CommitInput value={lot.part_number} width={140} disabled={locked || busy}
          onCommit={v => run(api.updateReceiptLot(lot.id, { part_number: v }))} />
      </td>
      <td>
        <CommitInput value={lot.lot_name} width={160} disabled={locked || busy}
          onCommit={v => run(api.updateReceiptLot(lot.id, { lot_name: v }))} />
      </td>
      <td style={{ textAlign: 'right' }}>
        {!locked && !lot.consumed &&
          <button className="x" title="убрать строку" disabled={busy}
            onClick={() => run(api.deleteReceiptLot(lot.id))}>×</button>}
        {lot.consumed && <span className="hint">потреблён</span>}
      </td>
    </tr>
  )
}

// Призрачная строка: добавить строку УПД (рождается партия).
function GhostRow({ receiptId, items, busy, run }: {
  receiptId: number; items: ItemRow[]; busy: boolean
  run: (p: Promise<ReceiptCockpit>) => void
}) {
  const [itemId, setItemId] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  const [cost, setCost] = useState('')
  const [pn, setPn] = useState('')
  const [name, setName] = useState('')

  const add = () => {
    const q = Number(qty)
    if (!itemId || !(q > 0)) return
    run(api.addReceiptLot(receiptId, {
      item_id: itemId, qty: q,
      unit_cost: cost === '' ? undefined : Number(cost),
      part_number: pn || undefined,
      lot_name: name || undefined,
    }))
    setItemId(''); setQty(''); setCost(''); setPn(''); setName('')
  }

  return (
    <tr className="row ghost">
      <td>
        <select className="lot-sel" value={itemId} disabled={busy}
          onChange={e => setItemId(e.target.value ? Number(e.target.value) : '')}>
          <option value="">＋ изделие…</option>
          {items.map(i => <option key={i.id} value={i.id}>{i.code} — {i.name}</option>)}
        </select>
      </td>
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td className="num">
        <input className="qty-in" value={cost} disabled={busy} placeholder="0"
          onChange={e => setCost(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td>
        <input className="qty-in" style={{ width: 140 }} value={pn} disabled={busy}
          placeholder="part number" onChange={e => setPn(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td>
        <input className="qty-in" style={{ width: 160 }} value={name} disabled={busy}
          placeholder="название из УПД" onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      <td style={{ textAlign: 'right' }}>
        <button className="btn sm" disabled={busy || !itemId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}

// Автосейв текстового/числового поля: коммит по blur / Enter (без кнопки).
// Переиспуемый компонент (кокпиты прихода/заказа).
export function CommitInput({ value, onCommit, disabled, width = 60, validate, type }: {
  value: string; onCommit: (v: string) => void; disabled?: boolean
  width?: number; validate?: (v: string) => boolean; type?: string
}) {
  const [v, setV] = useState(value)
  useEffect(() => { setV(value) }, [value])
  const commit = () => {
    if (v === value) return
    if (validate && !validate(v)) { setV(value); return }
    onCommit(v)
  }
  return (
    <input className="qty-in" style={{ width }} value={v} disabled={disabled} type={type}
      onChange={e => setV(e.target.value)} onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
  )
}
