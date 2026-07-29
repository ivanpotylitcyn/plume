// Витрина волны 3: форма прихода / УПД (записываемое ядро).
// Строки УПД = лоты (в модели отдельной ReceiptLine нет): изделие + кол-во +
// цена + название, автосейв по blur/Enter. Добавление строки = рождение партии
// (+RECEIPT). Замок «сверено со сканом» (approved) делает форму read-only.
import { useEffect, useState } from 'react'
import { api, type CounterpartyRow, type ItemRow, type ProjectPurchaseRow,
  type ReceiptForm, type ReceiptLot } from './api'
import { CommitInput } from './CommitInput'
import { num, money, count, sumByUom, LotGlyph } from './status'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { AuthorField, ProjectField, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { CounterpartyPicker, ItemPicker, PurchasePicker } from './Picker'

export function ReceiptView({ receiptId, items, isNew, openItem, openPurchase, openProject,
  onChanged, onDeleted }: {
  receiptId: number; items: ItemRow[]; isNew: boolean
  openItem: (id: number) => void; openPurchase: (id: number) => void
  openProject: (id: number) => void
  onChanged: () => void; onDeleted: () => void
}) {
  const [purchases, setPurchases] = useState<ProjectPurchaseRow[]>([])
  // Ф12e: поставщик задавался ТОЛЬКО в форме создания и в шапке не жил — после её
  // сноса поставку было бы нечем укомплектовать до фиксации.
  const [suppliers, setSuppliers] = useState<CounterpartyRow[]>([])
  const reloadSuppliers = () => api.counterparties('supplier').then(setSuppliers)
  useEffect(() => { api.counterparties('supplier').then(setSuppliers) }, [])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    receiptId, api.receipt, {
      onChanged, onDeleted,
      onLoad: c => { api.projectPurchases(c.project_id).then(setPurchases) },
      remove: api.deleteReceipt,
      confirmDelete: 'Удалить поставку (УПД)? Рождённые партии будут сняты. Действие необратимо.',
    }, isNew)
  const att = useAttachments('receipt', receiptId)   // загрузка — команда шапки (§13.8)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const fixed = c.locked                 // фиксация (проведена/сверена) — read-only
  const locked = fixed || !unlocked        // + личный замок формы
  // Имя заказа для ссылки под замком: заказ известен формой по id, идентичность
  // берём из списка заказов проекта (он же кормит пикер).
  const purchaseLabel = purchases.find(p => p.id === c.purchase_id)?.code
    ?? `Заказ #${c.purchase_id}`

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="gl" /><th className="c-key">Изделие</th>
              <th className="c-desc">Описание</th>
              <th style={{ textAlign: 'right' }}>Кол-во</th>
              <th className="uom">Ед.</th>
              <th style={{ textAlign: 'right' }}>Цена, ₽</th>
              <th className="c-fit">Part number</th>
              <th className="c-fit">Название из УПД</th><th className="act" />
            </tr>
          </thead>
          <tbody>
            {c.lots.map(lot => (
              <LotRow key={lot.id} lot={lot} locked={locked} draft={!fixed} busy={busy}
                openItem={openItem} run={run} />
            ))}
            {!locked && <GhostRow receiptId={c.id} items={items} busy={busy} run={run} />}
          </tbody>
        </table>
        {c.lots.length === 0 && locked &&
          <div className="tab-empty">Поставка пуста.</div>}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="поставку" locked={locked} error={err}
      // Мета (§13.6): счёт по табам + то, чего в табах нет. Итог поставки — не одно
      // число: физически это «сколько чего приехало», а единицы у строк разные, и
      // складывать штуки с метрами нельзя. Поэтому кол-во сворачивается ПО ЕДИНИЦАМ
      // («10 344 шт · 50 м»), деньги — отдельным итогом.
      meta={<>
        {count(c.lots.length, 'позиция', 'позиции', 'позиций')}
        {sumByUom(c.lots).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{money(c.total_cost)}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockReceipt(c.id))}
      fixateTitle="Сверено со сканом — зафиксировать поставку"
      onUnfix={() => { if (confirm('Расфиксировать поставки?')) run(api.unlockReceipt(c.id)) }}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (скан УПД) — появится в табе «Файлы»', disabled: att.busy }]}
      fields={<>
        <dt>Код</dt>
        <dd><CommitInput value={c.code ?? ''} disabled={locked || busy}
          onCommit={v => run(api.updateReceipt(c.id, { code: v }))} /></dd>
        <dt>Описание</dt>
        {/* Единственное длинное поле шапки (§13.3). */}
        <dd className="wide"><CommitInput value={c.description} disabled={locked || busy}
          onCommit={v => run(api.updateReceipt(c.id, { description: v }))} /></dd>
        <dt>№ УПД</dt>
        <dd><CommitInput value={c.number} disabled={locked || busy}
          onCommit={v => run(api.updateReceipt(c.id, { number: v }))}
          validate={v => v.trim().length > 0} /></dd>
        {/* Ф12e: поставщик обязателен к ФИКСАЦИИ, а не к рождению — значит его
            место в шапке. «Завести» прямо из пикера: отдельной формы контрагента
            в продукте нет (заведётся режимом «Контрагенты», волна 20). */}
        <dt>Поставщик</dt>
        <dd><CounterpartyPicker counterparties={suppliers} value={c.contractor_id ?? ''}
          disabled={locked || busy} placeholder="— не указан —"
          onPick={id => run(api.updateReceipt(c.id, { contractor_id: id }))}
          onClear={() => run(api.updateReceipt(c.id, { contractor_id: null }))}
          onCreate={name => api.createCounterparty({ description: name, role: 'supplier' })
            .then(cp => { reloadSuppliers()
              run(api.updateReceipt(c.id, { contractor_id: cp.id })) })} /></dd>
        <dt>Дата</dt>
        <dd><CommitInput value={c.date} type="date" disabled={locked || busy}
          onCommit={v => run(api.updateReceipt(c.id, { date: v }))}
          validate={v => v.trim().length > 0} /></dd>
        <AuthorField userId={c.user_id} userName={c.user_name} disabled={locked || busy}
          onChange={id => run(api.updateReceipt(c.id, { user_id: id }))} />
        <ProjectField projectId={c.project_id} projectLabel={c.project_code}
          disabled={locked || busy} onOpen={openProject}
          onChange={id => run(api.updateReceipt(c.id, { project_id: id }))} />
        {/* Якорь-заказ переехал из тела формы в поля шапки (§13.3): это ссылка
            документа, а не список — в теле он висел отдельной строкой `.kit-actions`.
            Под замком поле = САМА ССЫЛКА на заказ (отдельная кнопка «открыть ›» не
            нужна: кликабельно то, что названо). */}
        <dt>Заказ</dt>
        <dd>{locked
          ? (c.purchase_id
              ? <a className="link" onClick={() => openPurchase(c.purchase_id!)}>{purchaseLabel}</a>
              : '—')
          : <PurchasePicker purchases={purchases} value={c.purchase_id ?? ''}
              disabled={busy}
              onPick={id => run(api.linkReceiptPurchase(c.id, id))}
              onClear={() => run(api.linkReceiptPurchase(c.id, null))} />}</dd>
      </>}
      tabs={tabs}
    />
  )
}

// Реальная строка УПД (лот): автосейв кол-ва/цены/названия, удаление до замка.
// `draft` — поставка ещё не сверена (Ф15): партия на складе не лежит, живого остатка
// у неё нет вовсе. Показывать «остаток 0» было бы враньём про израсходованную партию,
// поэтому в черновике остаток не показываем, а глиф гасим в нейтральный.
function LotRow({ lot, locked, draft, busy, openItem, run }: {
  lot: ReceiptLot; locked: boolean; draft: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<ReceiptForm>) => void
}) {
  const short = !draft && lot.live_qty !== lot.qty   // просел под пайку/расход
  return (
    <tr className="row">
      {/* Строка = партия, рождённая этой поставкой: глиф партии (форма — origin,
          цвет — живость остатка, §7a), код и описание — РАЗНЫМИ колонками. */}
      <td className="gl"><LotGlyph origin="receipt" liveQty={lot.live_qty} draft={draft} /></td>
      <td className="c-key">
        <a className="link" onClick={() => openItem(lot.item_id)}>{lot.item_code}</a></td>
      <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
        <span className="cell-ellip" title={lot.item_description}>{lot.item_description}</span>
        {short && <span className="hint">остаток {num(lot.live_qty)} {lot.uom}</span>}
      </td>
      <td className="num">
        <CommitInput value={String(lot.qty)} width={60} disabled={locked || busy}
          onCommit={v => run(api.updateReceiptLot(lot.id, { qty: Number(v) }))}
          validate={v => Number(v) > 0} />
      </td>
      <td className="uom">{lot.uom}</td>
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
      <td className="act">
        {!locked && !lot.consumed &&
          <button className="fh-ctl icon fh-del" title="Убрать строку поставки"
            disabled={busy} onClick={() => run(api.deleteReceiptLot(lot.id))}>
            <span className="ci ci-trash" /></button>}
        {lot.consumed && <span className="hint">потреблён</span>}
      </td>
    </tr>
  )
}

// Призрачная строка: добавить строку УПД (рождается партия).
function GhostRow({ receiptId, items, busy, run }: {
  receiptId: number; items: ItemRow[]; busy: boolean
  run: (p: Promise<ReceiptForm>) => void
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
      <td className="gl" />
      {/* Пикер занимает пару «код + описание»: ищет по обоим, и ширину берёт по ним
          (inline-`width` контрола не задаём — §7a). */}
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
      <td className="act">
        <button className="btn sm" disabled={busy || !itemId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}

