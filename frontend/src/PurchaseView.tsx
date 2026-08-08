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
import { api, type CounterpartyRow, type ItemRow, type ProcurementRow, type PurchaseForm,
  type PurchaseFormLine, type Status } from './api'
import { CommitInput } from './CommitInput'
import { AnchorSelect, OrderFields, useFormLock } from './FormHeader'
import { IntentBudget } from './IntentBudget'
import { FormShell, type FormTab } from './FormShell'
import { Field } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { Balance, Cost, CounterpartyRef, ItemGlyph, MismatchGlyph, StatusGlyph,
  balanceTitle, count, num } from './status'
import { ColumnFilter } from './ColumnFilter'
import { CounterpartyPicker, ItemPicker } from './Picker'

// Фильтр остатка: главный вопрос к заказу — «что ещё не приехало». Словарь тот же по
// духу, что у фильтров «Потребности»: первый вариант нейтральный, дальше — состояния
// строки на языке заказа.
type RestFilter = 'any' | 'open' | 'closed'
const REST_OPTS: [string, string][] = [
  ['any', 'все'], ['open', 'ждём'], ['closed', 'закрыто'],
]

export function PurchaseView({ purchaseId, items, isNew, openItem, openReceipt, openProject,
  openProcurement, openCounterparty, onChanged, onDeleted }: {
  purchaseId: number; items: ItemRow[]; isNew: boolean
  openItem: (id: number) => void; openReceipt: (id: number) => void
  openProject: (id: number) => void
  openProcurement: (id: number) => void   // якорь «Закупка» кликабелен под замком (§8)
  openCounterparty: (id: number) => void
  onChanged: () => void; onDeleted?: () => void
}) {
  const [c, setC] = useState<PurchaseForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [procs, setProcs] = useState<ProcurementRow[]>([])   // якорь «закупка-план» (Ф2k)
  const [rest, setRest] = useState<RestFilter>('any')        // фильтр колонки «Остаток»
  // Ф17: контрагент заказа («у кого купили») — своё поле, обязательное к фиксации.
  const [suppliers, setSuppliers] = useState<CounterpartyRow[]>([])
  const reloadSuppliers = () => api.counterparties().then(setSuppliers)
  const { unlocked, toggle } = useFormLock(purchaseId, isNew)

  useEffect(() => {
    setC(null); setErr(null)
    api.purchase(purchaseId).then(setC).catch(e => setErr(String(e)))
  }, [purchaseId])
  useEffect(() => { api.procurements().then(setProcs) }, [])
  useEffect(() => { reloadSuppliers() }, [])
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
  // Замок формы гейтит и поля шапки (Ф12d): раньше они правились в просмотре, то есть
  // «просмотр» у заказа и закупки значил не то же, что у остальных форм.
  const locked = !editable || !unlocked
  // Ф1b: цвет строки/меты = покрытие лотами — как в списке Заказов.
  const coverage: Status = c.total_received === 0 ? 'to_order'
    : c.rows.every(r => r.remaining <= 0) ? 'available' : 'on_order'
  // Идентичность закупки-якоря берём из списка планов (он же кормит меню выбора).
  const procurementLabel = procs.find(p => p.id === c.procurement_id)?.code
    || `Закупка #${c.procurement_id}`
  // Ф17: расхождение с контрагентом указанной закупки — предупреждение, не гейт.
  // Флаг считает движок ([[engine-view-seam]]), форма только выбирает знак.
  const mismatch = c.contractor_mismatch
    ? <MismatchGlyph title="Не совпадает с контрагентом указанной закупки" />
    : null

  // Ф6, поток «Заказ → УПД»: накладная повторяет заказ 1:1, набивать её заново незачем.
  // Кнопка живёт у ЗАФИКСИРОВАННОГО заказа (черновик ещё правится — поставки по
  // неутверждённому обязательству не бывает) и только пока есть остаток. Гейт
  // дублируется движком; здесь он гасит кнопку и ОБЪЯСНЯЕТ причину — молчаливо
  // отключённая команда учит хуже, чем подсказка.
  const open = c.rows.some(r => r.remaining > 0)
  const receiptWhy = !fixed ? 'Сперва зафиксируйте заказ — поставка создаётся по утверждённому'
    : !open ? 'Заказ закрыт полностью — принимать нечего'
    : 'Создать черновик поставки, преднабитый остатком заказа'
  const makeReceipt = () => {
    setBusy(true); setErr(null)
    api.receiptFromPurchase(c.id)
      .then(r => { onChanged(); openReceipt(r.id) })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  const shown = c.rows.filter(ln => rest === 'any'
    || (rest === 'open' ? ln.remaining > 0 : ln.remaining <= 0))

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="gl" /><th className="c-key">Изделие</th>
              <th className="c-desc">Описание</th>
              {/* Баланс проекта по изделию — ПЕРВЫМ числом, как в «Привязке» закупки
                  (Баланс · Кол-во · …): сперва «сколько надо вообще», потом «сколько
                  беру здесь». Два экрана одного контура читаются одинаково. */}
              <th className="num" title="баланс проекта по этому изделию">Баланс</th>
              <th className="num">Заказано</th>
              <th className="num">Поступило</th>
              {/* Фильтр — тот же приём, что в «Потребности» проекта: раскрыватель сразу
                  за подписью, внутри её ячейки. Главный вопрос к заказу — «что ещё не
                  приехало», поэтому фильтр висит именно на остатке. */}
              <th className="num">Остаток
                <ColumnFilter opts={REST_OPTS} value={rest}
                  onPick={v => setRest(v as RestFilter)} /></th>
              {/* Колонка «Поставки» снята 2026-08-05 (решение Ивана: «забудем о них,
                  пока не заболит»). Чем строка закрыта — видно в табе «Поставки»
                  и в самой накладной; в строке это распирало таблицу ссылками. */}
              <th className="uom">Ед.</th>
              {/* Деньги — за границей единицы измерения: «Ед.» квалифицирует количества
                  слева от себя, а стоимость другой размерности и к ней не относится. */}
              <th className="num c-money">Стоимость</th>
              {editable && <th className="act" />}
            </tr>
          </thead>
          <tbody>
            {shown.map(ln => (
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
              <th className="gl" /><th className="c-key">Поставка</th>
              <th className="c-fit">№ поставки</th><th className="c-fit">Дата</th>
              <th className="c-desc">Поставщик</th>
              <th className="num">Строк</th>
            </tr></thead>
            <tbody>
              {c.receipts.map(r => (
                <tr key={r.id} className="row">
                  {/* Глиф-замок: черновая накладная заказ ещё не гасит (Ф6) — видно,
                      что она заведена, но «поступило» по строкам пока ноль. */}
                  <td className="gl"><StatusGlyph locked={r.locked} /></td>
                  {/* Ссылка — по КОДУ: он есть всегда (фолбэк «Поставка 12»), а № поставки
                      у только что рождённой пуст, и ссылка на него была пустотой. */}
                  <td className="c-key">
                    <a className="link" onClick={() => openReceipt(r.id)}>
                      {r.code || `Поставка #${r.id}`}</a></td>
                  <td className="c-fit code">{r.number || <span className="hint">не задан</span>}</td>
                  <td className="c-fit">{r.date}</td>
                  <td className="c-desc">
                    <CounterpartyRef code={r.contractor_code} name={r.contractor_name} /></td>
                  <td className="num">{r.lines}</td>
                </tr>
              ))}
            </tbody>
          </table> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="заказ" locked={locked} error={err}
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
      actions={[
        { onClick: makeReceipt, label: 'Создать поставку', icon: 'ci-inbox',
          title: receiptWhy, disabled: busy || !fixed || !open },
        { onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
          title: 'Загрузить файл (счёт, скан накладной) — появится в табе «Файлы»',
          disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy} openProject={openProject}
          patch={b => run(api.updatePurchase(c.id, b))}
          // Якори вида — сразу за Проектом (§13.4a): Проект → Закупка → Контрагент,
          // затем внешние атрибуты и автор. Порядок один на все три уровня контура.
          anchors={<>
            {/* Подпись якоря — КОД закупки, а не её id ([[code-identity-principle]]):
                «#1» ничего не говорит, а в просмотре это единственное, что видно.
                Ф17: план опционален — пустой пункт меню снимает якорь. Под замком поле
                = САМА ССЫЛКА на закупку (§8: кликабельно то, что названо), как якорь
                «Проект» здесь же и якорь «Заказ» в форме поставки. */}
            <AnchorSelect label="Закупка" id={c.procurement_id}
              currentLabel={procurementLabel}
              options={procs.map(p => ({ id: p.id, label: p.code || `Закупка #${p.id}` }))}
              locked={locked} busy={busy} placeholder="— не выбрана —"
              view={c.procurement_id
                ? <a className="link"
                    onClick={() => openProcurement(c.procurement_id!)}>{procurementLabel}</a>
                : ''}
              onChange={id => run(api.updatePurchase(c.id, { procurement_id: id }))}
              onClear={() => run(api.updatePurchase(c.id, { procurement_id: null }))} />
            {/* Ф17: «у кого купили» — своё поле заказа, а не чтение сквозь план.
                Обязательно к ФИКСАЦИИ (движок откажет внятно), не к рождению. */}
            <Field label="Контрагент" locked={locked}
              view={c.contractor_id
                ? <><CounterpartyRef code={c.contractor_code} name={c.contractor_name}
                    onOpen={() => openCounterparty(c.contractor_id!)} />{mismatch}</>
                : ''}>
              <CounterpartyPicker counterparties={suppliers} side="supply"
                value={c.contractor_id ?? ''}
                disabled={busy} placeholder="— не указан —"
                onPick={id => run(api.updatePurchase(c.id, { contractor_id: id }))}
                onClear={() => run(api.updatePurchase(c.id, { contractor_id: null }))}
                onCreate={name => api.createCounterparty({ description: name })
                  .then(cp => { reloadSuppliers()
                    run(api.updatePurchase(c.id, { contractor_id: cp.id })) })} />
              {mismatch}
            </Field>
          </>} />}
      // Деньги заказа — панелью над метой (2026-08-07), как бюджет у проекта. Поле
      // «Оценка» отсюда снято: это ровно стат «Заказ», и держать его дважды незачем.
      extra={<IntentBudget demand={c.demand} total={c.estimate} totalLabel="Заказ"
        overpay={c.overpay} unestimated={c.unestimated} />}
      tabs={tabs}
    />
  )
}

// Строка заказа: заказано (автосейв, пока расфиксировано) + поступило/остаток + закрытость.
function LineRow({ ln, editable, busy, openItem, run }: {
  ln: PurchaseFormLine; editable: boolean; busy: boolean
  openItem: (id: number) => void
  run: (p: Promise<PurchaseForm>) => void
}) {
  return (
    <tr className="row">
      {/* Глиф строки — ИЗДЕЛИЕ, как в списке «Компоненты» и в форме закупки (правка
          Ивана 2026-08-08, разворот решения 2026-08-05). Циферблат «ждём поставку» снят:
          приехало ли — и так видно колонками «Поступило»/«Остаток» с фильтром на них,
          а вот статус компонента (библиотечный / ручной / наш под замком) в строке
          заказа больше взять негде. */}
      <td className="gl">
        <ItemGlyph native={ln.item_native} synced={ln.item_synced} locked={ln.item_locked} />
      </td>
      <td className="c-key">
        <a className="link" onClick={() => openItem(ln.item_id)}>{ln.item_code}</a></td>
      <td className="c-desc">
        <span className="cell-ellip" title={ln.item_description}>{ln.item_description}</span></td>
      <td className="num">
        <Balance value={ln.balance} status={ln.balance_status}
          title={balanceTitle(ln.item_code, ln.need, ln.kitted, ln.in_stock, ln.on_order)} />
      </td>
      <td className="num">
        {editable
          ? <CommitInput value={String(ln.qty)} disabled={busy}
              onCommit={v => run(api.updatePurchaseLine(ln.id, Number(v)))}
              validate={v => Number(v) > 0} />
          : num(ln.qty)}
      </td>
      <td className="num">{num(ln.received)}</td>
      <td className="num">{num(ln.remaining)}</td>
      <td className="uom">{ln.uom}</td>
      <td className="num c-money"><Cost cost={ln.cost} status={ln.cost_status}
        overpayAt={ln.overpay_at} uom={ln.uom} /></td>
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
      <td className="num" />
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      {/* «Поступило» и «Остаток» у ненабитой строки пусты — считать ещё нечего. Ячейки
          обязаны БЫТЬ и стоять на своих местах: лишний безымянный `<td>` здесь заводил
          таблице девятый столбец против восьми в шапке, и весь правый блок колонок
          отлипал от края панели на его ширину (правка Ивана 2026-08-06). */}
      <td className="num" /><td className="num" />
      {/* Ед. приезжает вместе с изделием — в призрачной строке её ещё нет. */}
      <td className="uom" />
      <td className="num c-money" />
      <td className="act">
        <button className="btn sm" disabled={busy || !itemId || !(Number(qty) > 0)}
          onClick={add}>добавить</button>
      </td>
    </tr>
  )
}
