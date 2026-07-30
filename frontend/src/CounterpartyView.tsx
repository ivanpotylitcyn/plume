// Форма КОНТРАГЕНТА (волна 20) — канон §13. Контрагент не документ контура, а его
// ВНЕШНЯЯ СТОРОНА, и форма устроена по этой оси:
//
//   ДНК (код / описание / ИНН)                ← шапка `.props`
//   [ПОСТАВКИ:  закупок · заказов · поставок · партий · привезено · сумма]  ← интеграл
//   [ПЕРЕДАЧИ:  передач · партий · передано · сумма]                        ← интеграл
//   [Закупки] [Заказы] [Поставки] [Передачи] [Файлы]                        ← табы
//
// Две панели вместо одной (решение Ивана 2026-07-30): у поставщика видна только
// закупочная, у заказчика — только передачная, у того, кто и поставляет, и принимает —
// обе. Пустую сторону движок отдаёт как `null` («движений нет» — это смысл, а не
// вёрстка), форма её просто не рисует. Ф3: поля «Роль» нет — сторона это ФАКТ, и
// свежезаведённый контрагент показывает голую ДНК с одним табом «Файлы»; заводят его
// под первый заказ, так что пустым он живёт минуты. Аккордеона «закупка → накладные» нет:
// заказ живёт без плана (Ф17), поставка — без заказа, поэтому уровни идут тремя
// РАВНЫМИ табами, а «чем строка закрыта» остаётся в форме заказа (Ф6), где связь
// однозначна.
import { useEffect, useState } from 'react'
import { api, type CounterpartyForm, type CpReceiptRow, type CpTransferRow,
  type UomQty } from './api'
import { count, money, num, StatusGlyph } from './status'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { TextField, viewDate } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { ProcurementFeed, PurchaseFeed } from './FeedTables'
import { Stat, StatGroup, StatPanel, StatWarn } from './StatPanel'
import type { OrderKind } from './orders'

// Итог в натуре — вектор по единицам, а не одно число: штуки с метрами не складываем
// (§13.6). Пустой вектор — прочерк, как у пустого поля шапки.
function uoms(rows: UomQty[]): string {
  return rows.length === 0 ? '—' : rows.map(r => `${num(r.qty)} ${r.uom}`).join(' · ')
}

export function CounterpartyView({ counterpartyId, isNew, openProcurement, openPurchase,
  openOrder, onChanged, onDeleted }: {
  counterpartyId: number
  isNew: boolean
  openProcurement: (id: number) => void
  openPurchase: (id: number) => void
  openOrder: (kind: OrderKind, id: number) => void
  onChanged?: () => void
  onDeleted?: () => void
}) {
  const [c, setC] = useState<CounterpartyForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { unlocked, toggle } = useFormLock(counterpartyId, isNew)  // §5: существующее — в просмотре
  const att = useAttachments('counterparty', counterpartyId)       // «карточка предприятия» (Ф12b)

  useEffect(() => {
    setC(null); setErr(null)
    api.counterparty(counterpartyId).then(setC).catch(e => setErr(String(e)))
  }, [counterpartyId])

  const run = (p: Promise<CounterpartyForm>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Удаление под замком: friendly-guard бэка (поставки/передачи/заказы держат наглухо,
  // закупки-планы просто потеряют контрагента — `SET_NULL`, Ф17).
  const del = () => {
    if (!c || !confirm('Удалить контрагента? Действие необратимо.')) return
    setBusy(true); setErr(null)
    api.deleteCounterparty(c.id).then(() => { onChanged?.(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const locked = !unlocked          // фиксации у справочника нет (§5) — только замок формы
  const supply = c.supply
  const shipment = c.shipment
  // Набор табов сужается по тому же правилу, что и панели: сторона без движений табов
  // не даёт (как у внутреннего склада нет «Приборов»). Ф3: других источников правды у
  // этого решения нет — раньше табы открывала ещё и заявленная роль, и «поставщик без
  // единого документа» получал три пустых таба, которые нечем было наполнить с места.
  const buying = supply !== null
  const selling = shipment !== null

  const tabs: FormTab[] = []
  if (buying) tabs.push(
    // Ленты закупок и заказов — общие с формой аккаунта (`FeedTables`, волна 21):
    // строка одна, отличается только вопрос, который к ней задают.
    { key: 'procurements', label: 'Закупки', icon: 'law',
      content: <ProcurementFeed rows={c.procurements} open={openProcurement}
        empty="Закупок-планов на этого контрагента нет." /> },
    { key: 'purchases', label: 'Заказы', icon: 'package',
      content: <PurchaseFeed rows={c.purchases} open={openPurchase}
        empty="Заказов у этого контрагента нет." /> },
    { key: 'receipts', label: 'Поставки', icon: 'inbox',
      content: c.receipts.length === 0
        ? <div className="tab-empty">Этот контрагент ещё ничего не привозил.</div>
        : <table className="grid">
            <thead><tr>
              <th className="gl" /><th className="c-key">Поставка</th>
              <th className="c-fit">№ УПД</th><th className="c-fit">Проект</th>
              <th className="c-fit">Дата</th>
              <th className="num">Партий</th>
              <th className="num">Сумма</th>
            </tr></thead>
            <tbody>{c.receipts.map(r => (
              <RecRow key={r.id} r={r} open={id => openOrder('receipt', id)} />))}</tbody>
          </table> },
  )
  if (selling) tabs.push(
    { key: 'transfers', label: 'Передачи', icon: 'export',
      content: c.transfers.length === 0
        ? <div className="tab-empty">Этому контрагенту ещё ничего не передавали.</div>
        : <table className="grid">
            <thead><tr>
              <th className="gl" /><th className="c-key">Передача</th>
              <th className="c-fit">№ накладной</th><th className="c-fit">Проект</th>
              <th className="c-fit">Дата</th>
              <th className="num">Строк</th>
              <th className="num">Кол-во</th>
              <th className="num">Сумма</th>
            </tr></thead>
            <tbody>{c.transfers.map(t => (
              <TransRow key={t.id} t={t} open={id => openOrder('transfer', id)} />))}</tbody>
          </table> },
  )
  tabs.push(
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  )

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="контрагента" locked={locked} error={err}
      // Мета (§13.6): счёт по табам в их порядке. ИНН не повторяем — он в полях;
      // деньги живут в панелях (иначе одно и то же число читалось бы дважды).
      meta={<>
        {buying && <>
          {count(c.procurements.length, 'закупка', 'закупки', 'закупок')}
          {' · '}{count(c.purchases.length, 'заказ', 'заказа', 'заказов')}
          {' · '}{count(c.receipts.length, 'поставка', 'поставки', 'поставок')}
          {' · '}
        </>}
        {selling && <>
          {count(c.transfers.length, 'передача', 'передачи', 'передач')}
          {' · '}
        </>}
        {count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (карточка предприятия, договор) — появится в табе «Файлы»',
        disabled: att.busy }]}
      // Порядок полей — от модели (§13.4a): идентичность (код + описание) → внешние
      // атрибуты (ИНН). Больше в ДНК контрагента ничего и нет (Ф3).
      fields={<>
        <TextField label="Код" value={c.code ?? ''} locked={locked} busy={busy}
          onCommit={v => run(api.updateCounterparty(c.id, { code: v }))}
          validate={v => v.trim() !== ''} />
        <TextField label="Описание" wide value={c.description} locked={locked} busy={busy}
          onCommit={v => run(api.updateCounterparty(c.id, { description: v }))} />
        <TextField label="ИНН" value={c.inn} locked={locked} busy={busy}
          onCommit={v => run(api.updateCounterparty(c.id, { inn: v }))} />
      </>}
      extra={<>
        {supply && <StatPanel caption="Поставки" icon="inbox">
          <StatGroup>
            <Stat label="закупок (план)" value={num(supply.procurements)} />
            <Stat label="заказов" value={num(supply.purchases)} />
            <Stat label="не закрыто" value={num(supply.open_purchases)}
              title="заказы, которые поставки закрыли не полностью"
              tone={supply.open_purchases > 0 ? undefined : 'ok'} />
            <Stat label="поставок (УПД)" value={num(supply.receipts)} />
          </StatGroup>
          {/* Материальный итог — только по ЗАФИКСИРОВАННЫМ поставкам (гейт Ф15), как
              «потрачено» проекта: черновой УПД ещё не факт. */}
          <StatGroup aside>
            <Stat label="привёз партий" value={num(supply.lots)} />
            <Stat label="привезено" value={uoms(supply.qty_by_uom)} />
            <Stat label="на сумму" value={money(supply.total)} />
          </StatGroup>
          {/* Иначе «поставок 4 · привёз 0 партий» читается как баг, а это Ф15. */}
          {supply.draft_receipts > 0 &&
            <StatWarn title="черновая поставка ещё не на складе — зафиксируйте её">
              ▲ {count(supply.draft_receipts, 'поставка', 'поставки', 'поставок')}
              {' в черновиках — в итог не входят'}
            </StatWarn>}
        </StatPanel>}
        {shipment && <StatPanel caption="Передачи" icon="export">
          <StatGroup>
            <Stat label="передач" value={num(shipment.transfers)} />
            <Stat label="партий" value={num(shipment.lots)} />
          </StatGroup>
          <StatGroup aside>
            <Stat label="передано" value={uoms(shipment.qty_by_uom)} />
            <Stat label="на сумму" value={money(shipment.total)}
              title="по цене партий-источников: своей цены у передачи нет" />
          </StatGroup>
          {shipment.draft_transfers > 0 &&
            <StatWarn title="черновая накладная ещё ничего не отгрузила — зафиксируйте её">
              ▲ {count(shipment.draft_transfers, 'передача', 'передачи', 'передач')}
              {' в черновиках — в итог не входят'}
            </StatWarn>}
        </StatPanel>}
      </>}
      tabs={tabs}
    />
  )
}

// Строка поставки. Ссылка — по КОДУ (он есть всегда, фолбэк «Поставка 12»); № УПД у
// только что рождённой пуст, и ссылка на него была бы пустотой (та же правка, что Ф6).
function RecRow({ r, open }: { r: CpReceiptRow; open: (id: number) => void }) {
  return (
    <tr className="row">
      <td className="gl"><StatusGlyph locked={r.locked} /></td>
      <td className="c-key">
        <a className="link" onClick={() => open(r.id)}>{r.code || `Поставка #${r.id}`}</a></td>
      <td className="c-fit code">{r.number || <span className="hint">не задан</span>}</td>
      <td className="c-fit code">{r.project_code}</td>
      <td className="c-fit">
        {r.date ? viewDate(r.date) : ''}</td>
      <td className="num">{r.lots}</td>
      <td className="num">{money(r.total)}</td>
    </tr>
  )
}

function TransRow({ t, open }: { t: CpTransferRow; open: (id: number) => void }) {
  return (
    <tr className="row">
      <td className="gl"><StatusGlyph locked={t.locked} /></td>
      <td className="c-key">
        <a className="link" onClick={() => open(t.id)}>{t.code || `Передача #${t.id}`}</a></td>
      <td className="c-fit code">{t.number || <span className="hint">не задан</span>}</td>
      <td className="c-fit code">{t.project_code}</td>
      <td className="c-fit">
        {t.date ? viewDate(t.date) : ''}</td>
      <td className="num">{t.lines}</td>
      <td className="num">{num(t.qty)}</td>
      <td className="num">{money(t.total)}</td>
    </tr>
  )
}
