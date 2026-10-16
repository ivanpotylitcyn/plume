// Витрина волны 4: форма заказа (Purchase) — записываемое ядро.
// Строки-обязательства: заказано (автосейв, пока расфиксировано), поступило по связанным
// приходам (Receipt.purchase), остаток. Закрытость строки красится тем же словарём
// ✓/●/▲. Мягкий замок = утверждение (draft→posted): строки read-only, заказ считается
// в члене «заказано» дашборда дефицита. Отмены нет — отмена = удаление (волна 19, Р1).
//
// Волна 19 (Ф12c): форма по канону §13 — общие поля шапки через `OrderFields`, якорь
// «Закупка» — специфика вида. Заодно снят антипринцип §7a: код и описание изделия
// разъехались по своим колонкам (эта форма была его последним живым примером).
//
// Табы: Строки · Поставки · Файлы. Волна 24 (2026-10-16): заказ — следствие работы с
// закупкой. Рождается только из неё («Новый заказ»), проект выводит через неё, строки
// берёт только из её позиций. Таб «Потребность» (2026-08-19) снят: планируют в закупке,
// а не в заказе (решение Ивана — «отучить планировать в Заказе»).
import { useEffect, useMemo, useState } from 'react'
import { api, type CounterpartyRow, type ItemRow, type PurchaseCandidate, type PurchaseForm,
  type PurchaseFormLine } from './api'
import { CommitInput } from './CommitInput'
import { OrderFields, useFormLock } from './FormHeader'
import { Stat, StatGroup, StatPanel, StatWarn } from './StatPanel'
import { FormShell, type FormTab } from './FormShell'
import { Field } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { CounterpartyRef, ItemGlyph, MismatchGlyph, StatusGlyph,
  count, money, num } from './status'
import { ColumnFilter, useCategoryFilter } from './ColumnFilter'
import { CounterpartyPicker, ItemPicker } from './Picker'
import { EntityLink } from './EntityLink'
import { ask } from './dialog'

// Фильтр поступления: главный вопрос к заказу — «что ещё не приехало». Словарь тот же по
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
  const [rev, setRev] = useState(0)     // растёт на мутациях — освежает кандидатов строки
  const [rest, setRest] = useState<RestFilter>('any')        // фильтр колонки «Поступило»
  // Ф17: контрагент заказа («у кого купили») — своё поле, обязательное к фиксации.
  const [suppliers, setSuppliers] = useState<CounterpartyRow[]>([])
  const reloadSuppliers = () => api.counterparties().then(setSuppliers)
  const { unlocked, toggle } = useFormLock(purchaseId, isNew)

  useEffect(() => {
    setC(null); setErr(null)
    api.purchase(purchaseId).then(setC).catch(e => setErr(String(e)))
  }, [purchaseId])
  useEffect(() => { reloadSuppliers() }, [])
  const att = useAttachments('purchase', purchaseId)   // владелец заведён Ф12b (§13.8)
  // Два фильтра на одной таблице и порядок между ними: сперва остаток («что ещё не
  // приехало»), потом класс. Категории собираются уже по отобранному — меню не обещает
  // строк, которых первый фильтр не покажет.
  const byRest = useMemo(() => (c?.rows ?? []).filter(ln => rest === 'any'
    || (rest === 'open' ? ln.remaining > 0 : ln.remaining <= 0)), [c, rest])
  const byCat = useCategoryFilter(byRest, ln => ln.item_category, purchaseId)

  const run = (p: Promise<PurchaseForm>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); setRev(n => n + 1); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Удаление заказа (WAVE14 Ф2): корзина в шапке живёт только у расфиксированного
  // (§5: у запертого одна степень свободы — расфиксировать); friendly-guard бэка
  // держит привязанный приход.
  const del = async () => {
    if (!c || !(await ask({ title: `Удалить заказ «${c.code ?? `#${c.id}`}»?`,
      lines: ['строки заказа будут сняты'], verb: 'Удалить', icon: 'ci-trash', danger: true }))) return
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
  // Цвет «поступило» в мете — тот же, что у колонки «Поступило» (волна 24): ничего не
  // пришло — серое, частично — оранжевое, полностью — зелёное. Красного нет.
  const coverage = c.total_received === 0 ? 'sub'
    : c.rows.every(r => r.remaining <= 0) ? 'g-available' : 'g-on_order'
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


  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        <table className="grid">
          <thead>
            <tr>
              <th className="gl" /><th className="c-key">Компонент{byCat.head}</th>
              <th className="c-desc">Описание</th>
              {/* Баланса проекта здесь нет (волна 24, решение Ивана): «сколько надо» —
                  вопрос закупки. «Остаток» тоже снят: он повторял соседние числа и шумел;
                  закрытость строки говорит цветом само «Поступило». */}
              <th className="num">Заказано</th>
              {/* Фильтр — тот же приём, что в «Потребности» проекта: раскрыватель сразу
                  за подписью, внутри её ячейки. Главный вопрос к заказу — «что ещё не
                  приехало», поэтому фильтр висит на поступлении. */}
              <th className="num">Поступило
                <ColumnFilter opts={REST_OPTS} value={rest}
                  onPick={v => setRest(v as RestFilter)} /></th>
              {/* Колонка «Поставки» снята 2026-08-05 (решение Ивана: «забудем о них,
                  пока не заболит»). Чем строка закрыта — видно в табе «Поставки»
                  и в самой накладной; в строке это распирало таблицу ссылками. */}
              <th className="uom">Ед.</th>
              {/* Деньги — за границей единицы измерения: «Ед.» квалифицирует количества
                  слева от себя, а цена другой размерности. Волна 24 (решения Ивана):
                  ОДНА денежная колонка — цена всей строки, как в счёте: рубли и копейки
                  за строку сходятся со счётом до копейки, цена штуки выводится делением
                  (в подсказке). Стоимость-по-оценке снята: в заказе оценки нет. */}
              <th className="num c-money" title="цена всей строки по счёту / КП">Цена</th>
              {!locked && <th className="act" />}
            </tr>
          </thead>
          <tbody>
            {byCat.shown.map(ln => (
              <LineRow key={ln.id} ln={ln} editable={!locked} busy={busy}
                openItem={openItem} run={run} />
            ))}
            {/* Правочные ручки строк — и корзина, и строка-призрак — по ПОЛНОМУ замку
                (`locked` = зафиксирован ИЛИ форма в просмотре), как в шести остальных
                формах-ордерах. Раньше здесь стоял один `editable` (только фиксация):
                в просмотре расфиксированного заказа призрак оставался на месте, а если
                изделие в нём было уже выбрано — застывал строкой-обманкой, которая
                выглядит как содержимое заказа, но им не является (боль Ивана
                2026-08-11). Уход из правки теперь СНИМАЕТ призрака вместе с набранным:
                состояние живёт в нём самом и умирает с ним. */}
            {!locked && <GhostRow purchaseId={c.id} items={items} rev={rev} busy={busy}
              run={run} />}
          </tbody>
        </table>
        {c.rows.length === 0 && locked && <div className="tab-empty">Заказ пуст.</div>}
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
                    <EntityLink kind="receipt" id={r.id} open={openReceipt}>
                      {r.code || `Поставка #${r.id}`}</EntityLink></td>
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
        {' · поступило '}<span className={coverage}>{num(c.total_received)}</span>
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      onDelete={del}
      /* Бланк наружу — как у закупки: только у ЗАФИКСИРОВАННОГО заказа (черновик ещё
         не обязательство). Один и тот же документ у двух форм контура: шапка запроса
         (поставщик · заказчик · дата · автор с контактами) + нумерованные позиции. */
      download={fixed
        ? { href: api.purchaseXlsxUrl(c.id),
            title: 'Скачать xlsx-бланк для поставщика (имя файла = код заказа и дата)' }
        : undefined}
      fixed={fixed}
      onFixate={() => run(api.lockPurchase(c.id))}
      fixateTitle="Зафиксировать заказ — строки станут read-only"
      onUnfix={() => run(api.unlockPurchase(c.id))}
      fixation={`purchases/${c.id}`}
      actions={[
        { onClick: makeReceipt, label: 'Создать поставку', icon: 'ci-inbox',
          title: receiptWhy, disabled: busy || !fixed || !open },
        { onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
          title: 'Загрузить файл (счёт, скан накладной) — появится в табе «Файлы»',
          disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy} openProject={openProject}
          // Волна 24: проект заказа — проект его закупки, правится там (пока у неё
          // нет заказов), а здесь только ссылка.
          projectLocked
          patch={b => run(api.updatePurchase(c.id, b))}
          // Якори вида — сразу за Проектом (§13.4a): Проект → Закупка → Контрагент,
          // затем внешние атрибуты и автор. Порядок один на все три уровня контура.
          anchors={<>
            {/* Закупка — источник заказа (волна 24): задана при рождении и не
                меняется, поэтому поле — всегда ссылка (§8: кликабельно то, что названо). */}
            <Field label="Закупка" locked
              view={<EntityLink kind="procurement" id={c.procurement_id}
                open={openProcurement}>{c.procurement_code || `Закупка #${c.procurement_id}`}
              </EntityLink>} />
            {/* Ф17: «у кого купили» — своё поле заказа, а не чтение сквозь план.
                Обязательно к ФИКСАЦИИ (движок откажет внятно), не к рождению. */}
            <Field label="Контрагент" locked={locked}
              view={c.contractor_id
                ? <><CounterpartyRef code={c.contractor_code} name={c.contractor_name}
                    id={c.contractor_id} open={openCounterparty} />{mismatch}</>
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
      // Деньги заказа (волна 24, решение Ивана): заказ — онлайн-зеркало оффлайн-счёта,
      // поэтому в панели ОДНА сумма — сухой факт по счёту, прижатая вправо, над ценами
      // строк. «Потребность» и «Переплата» сняты: это язык оценки, он живёт в закупке.
      extra={<StatPanel>
        <StatGroup aside>
          <Stat label="Заказ" value={money(c.estimate)}
            title="Сумма цен строк по счёту — сходится со счётом до копейки" />
        </StatGroup>
        {c.unestimated.length > 0 &&
          <StatWarn title={'без цены: ' + c.unestimated.join(', ')}>
            ▲ {c.unestimated.length} поз. без цены — сумма неполна
          </StatWarn>}
      </StatPanel>}
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
          приехало ли — и так видно цветом «Поступило» и фильтром на нём,
          а вот статус компонента (библиотечный / ручной / наш под замком) в строке
          заказа больше взять негде. */}
      <td className="gl">
        <ItemGlyph native={ln.item_native} synced={ln.item_synced} locked={ln.item_locked} />
      </td>
      <td className="c-key">
        <EntityLink kind="item" id={ln.item_id} open={openItem}>{ln.item_code}</EntityLink></td>
      <td className="c-desc">
        <span className="cell-ellip" title={ln.item_description}>{ln.item_description}</span></td>
      <td className="num">
        {editable
          /* Ноль допустим (2026-08-19): строку рождает витрина «Потребность» именно
             нулём («позицию беру, количество думаю»), и вернуться в это состояние так
             же законно, как в него прийти. Убрать позицию совсем — корзиной строки. */
          ? <CommitInput value={String(ln.qty)} disabled={busy}
              onCommit={v => run(api.updatePurchaseLine(ln.id, { qty: Number(v) }))}
              validate={v => Number(v) >= 0} />
          : num(ln.qty)}
      </td>
      {/* Поступило — цветом закрытости строки (решение Ивана, волна 24): ничего не
          пришло — серое (`.sub`), частично — оранжевое, полностью — зелёное. */}
      <td className="num">
        <span className={ln.status === 'available' ? 'g-available'
          : ln.status === 'on_order' ? 'g-on_order' : 'sub'}>{num(ln.received)}</span>
      </td>
      <td className="uom">{ln.uom}</td>
      {/* Цена всей строки по счёту: пусто — ещё не известна; пустой ввод стирает цену.
          Запятая — как десятичный разделитель счёта. Цена штуки — в подсказке. */}
      <td className="num c-money"
        title={ln.unit_price === null ? undefined
          : `за штуку ${money(Math.round(ln.unit_price * 100) / 100)}`}>
        {editable
          ? <CommitInput value={ln.price === null ? '' : String(ln.price)}
              disabled={busy}
              onCommit={v => run(api.updatePurchaseLine(ln.id,
                { price: v.trim() === '' ? null : Number(v.replace(',', '.')) }))}
              validate={v => v.trim() === '' || Number(v.replace(',', '.')) >= 0} />
          : ln.price === null ? <span className="sub">—</span> : money(ln.price)}
      </td>
      {editable && <td className="act">
        <button className="fh-ctl icon fh-del" title="Убрать строку заказа"
          disabled={busy} onClick={() => run(api.deletePurchaseLine(ln.id))}>
          <span className="ci ci-trash" /></button>
      </td>}
    </tr>
  )
}

// Призрачная строка: добавить позицию в заказ (только пока расфиксировано).
// Волна 24: выбор — только из позиций закупки, у которых есть остаток и которых в заказе
// ещё нет (`purchase_candidates`); список убывает по мере того, как заказы закрывают
// план. Количество преднабивается остатком — то же правило, что у окна «Новый заказ».
function GhostRow({ purchaseId, items, rev, busy, run }: {
  purchaseId: number; items: ItemRow[]; rev: number; busy: boolean
  run: (p: Promise<PurchaseForm>) => void
}) {
  const [cands, setCands] = useState<PurchaseCandidate[]>([])
  const [itemId, setItemId] = useState<number | ''>('')
  const [qty, setQty] = useState('')
  useEffect(() => {
    api.purchaseCandidates(purchaseId).then(setCands)
  }, [purchaseId, rev])
  // Пикер работает по справочнику изделий — сужаем его до кандидатов закупки.
  const offer = useMemo(() => {
    const ids = new Set(cands.map(c => c.item_id))
    return items.filter(i => ids.has(i.id))
  }, [cands, items])
  // Выбранная позиция целиком: единица измерения и остаток известны ДО добавления.
  const picked = cands.find(c => c.item_id === itemId)

  const pick = (id: number) => {
    setItemId(id)
    const c = cands.find(x => x.item_id === id)
    setQty(c ? String(c.remaining) : '')
  }
  const add = () => {
    const q = Number(qty)
    if (!itemId || !(q > 0)) return
    run(api.addPurchaseLine(purchaseId, { item_id: itemId, qty: q }))
    setItemId(''); setQty('')
  }

  return (
    <tr className="row ghost">
      <td className="gl" />
      {/* Заголовок поля — подпись его колонки («Компонент»), без «＋»: строка-призрак
          и так читается пустой строкой таблицы, а знак прибавления несёт кнопка в конце
          строки (правка Ивана 2026-08-11). */}
      <td className="c-key" colSpan={2}>
        <ItemPicker items={offer} value={itemId} onPick={pick} disabled={busy}
          placeholder={cands.length ? 'Позиция закупки…' : 'Все позиции закупки взяты'}
          onEnter={add} onClear={() => { setItemId(''); setQty('') }} />
      </td>
      <td className="num" />
      <td className="num">
        <input className="qty-in" value={qty} disabled={busy} placeholder="0"
          onChange={e => setQty(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }} />
      </td>
      {/* «Поступило» у ненабитой строки пусто — считать ещё нечего. Ячейка обязана
          БЫТЬ на своём месте, иначе правый блок колонок отлипает от края (правка Ивана
          2026-08-06). */}
      <td className="num" />
      <td className="uom">{picked?.uom ?? ''}</td>
      <td className="num c-money" />
      <td className="act">
        <button className="fh-ctl icon fh-add" title="Добавить строку заказа"
          disabled={busy || !itemId || !(Number(qty) > 0)} onClick={add}>
          <span className="ci ci-add" /></button>
      </td>
    </tr>
  )
}
