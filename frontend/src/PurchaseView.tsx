// Витрина волны 4: форма заказа (Purchase) — записываемое ядро.
// Строки-обязательства: заказано (автосейв, пока расфиксировано), поступило по связанным
// приходам (Receipt.purchase), остаток. Закрытость строки красится тем же словарём
// ✓/●/▲. Мягкий замок = утверждение (draft→posted): строки read-only, заказ считается
// в члене «заказано» дашборда дефицита. Отмены нет — отмена = удаление (волна 19, Р1).
//
// Волна 19 (Ф12c): форма по канону §13 — табы Строки · Поставки · Файлы, общие поля
// шапки через `OrderFields`, якорь «Закупка» — специфика вида. Заодно снят антипринцип
// §7a: код и описание изделия разъехались по своим колонкам (эта форма была его
// последним живым примером).
import { useEffect, useState } from 'react'
import { api, type ItemRow, type ProcurementRow, type PurchaseForm,
  type PurchaseFormLine, type Status } from './api'
import { CommitInput } from './CommitInput'
import { AnchorSelect, OrderFields, useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { ItemGlyph, count, num, statusTone } from './status'
import { ItemPicker } from './Picker'

export function PurchaseView({ purchaseId, items, isNew, openItem, openReceipt, openProject,
  onChanged, onDeleted }: {
  purchaseId: number; items: ItemRow[]; isNew: boolean
  openItem: (id: number) => void; openReceipt: (id: number) => void
  openProject: (id: number) => void
  onChanged: () => void; onDeleted?: () => void
}) {
  const [c, setC] = useState<PurchaseForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [procs, setProcs] = useState<ProcurementRow[]>([])   // якорь «закупка-план» (Ф2k)
  const { unlocked, toggle } = useFormLock(purchaseId, isNew)

  useEffect(() => {
    setC(null); setErr(null)
    api.purchase(purchaseId).then(setC).catch(e => setErr(String(e)))
  }, [purchaseId])
  useEffect(() => { api.procurements().then(setProcs) }, [])
  const att = useAttachments('purchase', purchaseId)   // владелец заведён Ф12b (§13.8)

  const run = (p: Promise<PurchaseForm>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Удаление заказа (WAVE14 Ф2): корзина в шапке живёт только у расфиксированного
  // (§5: у запертого одна степень свободы — расфиксировать); friendly-guard бэка
  // держит привязанный приход.
  const del = () => {
    if (!c || !confirm('Удалить заказ? Строки заказа будут сняты. Действие необратимо.')) return
    setBusy(true); setErr(null)
    api.deletePurchase(c.id).then(() => { onChanged(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const editable = c.editable
  const fixed = !editable                  // зафиксирован — read-only
  // Ф1b: цвет строки/меты = покрытие лотами — как в списке Заказов.
  const coverage: Status = c.total_received === 0 ? 'to_order'
    : c.rows.every(r => r.remaining <= 0) ? 'available' : 'on_order'

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="gl" /><th className="c-key">Изделие</th>
              <th className="c-desc">Описание</th>
              <th style={{ textAlign: 'right' }}>Заказано</th><th className="uom">Ед.</th>
              <th style={{ textAlign: 'right' }}>Поступило</th>
              <th style={{ textAlign: 'right' }}>Остаток</th>
              {editable && <th className="act" />}
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
        {c.rows.length === 0 && !editable && <div className="tab-empty">Заказ пуст.</div>}
      </> },
    { key: 'receipts', label: 'Поставки', icon: 'inbox',
      content: c.receipts.length === 0
        ? <div className="tab-empty">Заказ ещё не закрыт ни одной поставкой.</div>
        : <table className="grid">
            <thead><tr>
              <th className="c-key">УПД</th><th className="c-fit">Дата</th>
              <th className="c-desc">Поставщик</th>
              <th style={{ textAlign: 'right' }}>Строк</th>
            </tr></thead>
            <tbody>
              {c.receipts.map(r => (
                <tr key={r.id} className="row">
                  <td className="c-key">
                    <a className="link" onClick={() => openReceipt(r.id)}>{r.number}</a></td>
                  <td className="c-fit" style={{ color: 'var(--fg-dim)' }}>{r.date}</td>
                  <td className="c-desc">{r.contractor_name}</td>
                  <td className="num">{r.lines}</td>
                </tr>
              ))}
            </tbody>
          </table> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={!editable || !unlocked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="заказ" locked={!editable || !unlocked} error={err}
      // Мета (§13.6): счёт по табам + закрытость заказа числами (проект/дата — в полях).
      meta={<>
        {count(c.rows.length, 'строка', 'строки', 'строк')}
        {' · '}{count(c.receipts.length, 'поставка', 'поставки', 'поставок')}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
        {' · заказано '}{num(c.total_ordered)}
        {' · поступило '}<span className={'g-' + coverage}>{num(c.total_received)}</span>
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      onDelete={del}
      fixed={fixed}
      onFixate={() => run(api.lockPurchase(c.id))}
      fixateTitle="Зафиксировать заказ — строки станут read-only"
      onUnfix={() => {
        if (confirm('Расфиксировать заказ?')) run(api.unlockPurchase(c.id))
      }}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (счёт, скан накладной) — появится в табе «Файлы»',
        disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={!editable} busy={busy} openProject={openProject}
          patch={b => run(api.updatePurchase(c.id, b))}>
          <AnchorSelect label="Закупка" id={c.procurement_id} currentLabel={`#${c.procurement_id}`}
            options={procs.map(p => ({ id: p.id, label: p.code || `Закупка #${p.id}` }))}
            disabled={!editable || busy}
            onChange={id => run(api.updatePurchase(c.id, { procurement_id: id }))} />
        </OrderFields>}
      tabs={tabs}
    />
  )
}

// Строка заказа: заказано (автосейв, пока расфиксировано) + поступило/остаток + закрытость.
function LineRow({ ln, editable, busy, openItem, run }: {
  ln: PurchaseFormLine; editable: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<PurchaseForm>) => void
}) {
  return (
    <tr className={`row s-${ln.status}`}>
      {/* Глиф строки (§7a): форма = изделие/компонент, ЦВЕТ = закрытость строки
          (▲ ждём → ● частично → ✓ получено). Одна строка — один глиф. */}
      <td className="gl"><ItemGlyph native={ln.item_native} synced={ln.item_synced}
        locked={ln.item_locked} tone={statusTone(ln.status)} /></td>
      <td className="c-key">
        <a className="link" onClick={() => openItem(ln.item_id)}>{ln.item_code}</a></td>
      <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
        <span className="cell-ellip" title={ln.item_description}>{ln.item_description}</span></td>
      <td className="num">
        {editable
          ? <CommitInput value={String(ln.qty)} width={72} disabled={busy}
              onCommit={v => run(api.updatePurchaseLine(ln.id, Number(v)))}
              validate={v => Number(v) > 0} />
          : num(ln.qty)}
      </td>
      <td className="uom">{ln.uom}</td>
      <td className="num">{num(ln.received)}</td>
      <td className="num">{num(ln.remaining)}</td>
      {editable && <td className="act">
        <button className="fh-ctl icon fh-del" title="Убрать строку заказа"
          disabled={busy} onClick={() => run(api.deletePurchaseLine(ln.id))}>
          <span className="ci ci-trash" /></button>
      </td>}
    </tr>
  )
}

// Призрачная строка: добавить позицию в заказ (только пока расфиксировано).
function GhostRow({ purchaseId, items, busy, run }: {
  purchaseId: number; items: ItemRow[]; busy: boolean
  run: (p: Promise<PurchaseForm>) => void
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
      <td className="uom" /><td /><td />
      <td className="act">
        <button className="btn sm" disabled={busy || !itemId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
