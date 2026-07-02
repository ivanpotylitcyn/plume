// Витрина волны 4: кокпит заказа (Purchase) — записываемое ядро.
// Строки-обязательства: заказано (автосейв в черновике), поступило по связанным
// приходам (Receipt.purchase), остаток. Закрытость строки красится тем же словарём
// ✓/●/▲. Мягкий замок = отправка (draft→sent): строки read-only, заказ считается в
// члене «заказано» дашборда дефицита. cancel/restore — выход из счёта и возврат.
import { useEffect, useState } from 'react'
import { api, type ItemRow, type PurchaseCockpit, type PurchaseCockpitLine } from './api'
import { CommitInput } from './ReceiptView'
import { Glyph, num } from './status'

// Статус заказа → значок/цвет: draft ▲ (твой ход), sent ● (ждём), cancelled ○.
export const PURCH_ST: Record<string, { label: string; cls: string; g: string }> = {
  draft: { label: 'черновик', cls: 'g-to_order', g: '▲' },
  sent: { label: 'отправлен', cls: 'g-on_order', g: '●' },
  cancelled: { label: 'отменён', cls: 'g-info', g: '○' },
}

export function PurchaseView({ purchaseId, items, openItem, openReceipt, onChanged }: {
  purchaseId: number; items: ItemRow[]
  openItem: (id: number) => void; openReceipt: (id: number) => void
  onChanged: () => void
}) {
  const [c, setC] = useState<PurchaseCockpit | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setC(null); setErr(null)
    api.purchase(purchaseId).then(setC).catch(e => setErr(String(e)))
  }, [purchaseId])

  const run = (p: Promise<PurchaseCockpit>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const st = PURCH_ST[c.status] ?? PURCH_ST.draft
  const editable = c.editable
  return (
    <div>
      <h1 className="title">
        <span className={`glyph ${st.cls}`}>{st.g}</span>{' '}
        <span className="pn">Заказ #{c.id}</span>{' '}
        <span className="lit">— {c.project_code} {c.project_name}</span>
      </h1>
      <div className="subtitle">
        Кокпит заказа · <span className={st.cls}>{st.label}</span>
        {c.date && <> · {c.date}</>}
        {' · заказано '}<span className="seg">{num(c.total_ordered)}</span>
        {' · поступило '}<span className="seg">{num(c.total_received)}</span>
        {c.note && <> · {c.note}</>}
      </div>

      <div className="kit-actions">
        {c.status === 'draft' && <>
          <button className="btn" disabled={busy}
            onClick={() => run(api.sendPurchase(c.id))}>Отправить</button>
          <button className="btn" disabled={busy}
            onClick={() => run(api.cancelPurchase(c.id))}>Отменить</button>
        </>}
        {c.status === 'sent' && <>
          <button className="btn" disabled={busy}
            onClick={() => run(api.unsendPurchase(c.id))}>Вернуть в черновик</button>
          <button className="btn" disabled={busy}
            onClick={() => run(api.cancelPurchase(c.id))}>Отменить</button>
        </>}
        {c.status === 'cancelled' &&
          <button className="btn" disabled={busy}
            onClick={() => run(api.restorePurchase(c.id))}>Восстановить</button>}
        {busy && <span className="hint">сохраняю…</span>}
        {err && <span className="anomaly">{err}</span>}
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th>изделие</th><th style={{ textAlign: 'right' }}>заказано</th>
            <th style={{ textAlign: 'right' }}>поступило</th>
            <th style={{ textAlign: 'right' }}>остаток</th><th /><th />
          </tr>
        </thead>
        <tbody>
          {c.rows.map(ln => (
            <LineRow key={ln.id} ln={ln} editable={editable} busy={busy}
              openItem={openItem} run={run} />
          ))}
          {editable && <GhostRow purchaseId={c.id} items={items} busy={busy} run={run} />}
        </tbody>
      </table>
      {c.rows.length === 0 && !editable &&
        <div className="empty">Заказ пуст.</div>}

      {c.receipts.length > 0 && <>
        <div className="subtitle" style={{ marginTop: 16 }}>Приходы, закрывающие заказ</div>
        <table className="grid">
          <thead><tr><th>УПД</th><th>дата</th><th>поставщик</th>
            <th style={{ textAlign: 'right' }}>строк</th></tr></thead>
          <tbody>
            {c.receipts.map(r => (
              <tr key={r.id} className="row s-available">
                <td><a className="link" onClick={() => openReceipt(r.id)}>{r.number}</a></td>
                <td style={{ color: 'var(--fg-dim)' }}>{r.date}</td>
                <td>{r.supplier_name}</td>
                <td className="num">{r.lines}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </>}
    </div>
  )
}

// Строка заказа: заказано (автосейв в черновике) + поступило/остаток + закрытость.
function LineRow({ ln, editable, busy, openItem, run }: {
  ln: PurchaseCockpitLine; editable: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<PurchaseCockpit>) => void
}) {
  return (
    <tr className={`row s-${ln.status}`}>
      <td>
        <Glyph status={ln.status} />{' '}
        <a className="link" onClick={() => openItem(ln.item_id)}>{ln.item_code}</a>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>{ln.item_name}</span>
      </td>
      <td className="num">
        {editable
          ? <CommitInput value={String(ln.qty)} width={72} disabled={busy}
              onCommit={v => run(api.updatePurchaseLine(ln.id, Number(v)))}
              validate={v => Number(v) > 0} />
          : num(ln.qty)} {ln.uom}
      </td>
      <td className="num">{num(ln.received)}</td>
      <td className="num">{num(ln.remaining)}</td>
      <td />
      <td style={{ textAlign: 'right' }}>
        {editable &&
          <button className="x" title="убрать строку" disabled={busy}
            onClick={() => run(api.deletePurchaseLine(ln.id))}>×</button>}
      </td>
    </tr>
  )
}

// Призрачная строка: добавить позицию в заказ (только в черновике).
function GhostRow({ purchaseId, items, busy, run }: {
  purchaseId: number; items: ItemRow[]; busy: boolean
  run: (p: Promise<PurchaseCockpit>) => void
}) {
  const [itemId, setItemId] = useState<number | ''>('')
  const [qty, setQty] = useState('')

  const add = () => {
    const q = Number(qty)
    if (!itemId || !(q > 0)) return
    run(api.addPurchaseLine(purchaseId, { item_id: itemId, qty: q }))
    setItemId(''); setQty('')
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
      <td /><td /><td />
      <td style={{ textAlign: 'right' }}>
        <button className="btn sm" disabled={busy || !itemId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
