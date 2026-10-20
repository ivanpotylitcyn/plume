// Табы закупки «Строки» и «Заказы» — план и его распределение по заказам.
//
// Волна 24 (решение Ивана 2026-10-16): закупка — источник правды, и в ней ОДНО поле
// ввода — «сколько хотим». Аккордеон строки показывает, какие заказы и сколько взяли, —
// только для чтения: количество в заказе правится в форме заказа, а заказ рождается
// кнопкой «Новый заказ» (остатком). Матрица с полями в ячейках (2026-08-05, присвоение
// `set_allocation`) снята: форму пилили под нарезку, и она вышла сложной.
//
// Закупка однопроектная, поэтому у строки плана наконец есть честный баланс проекта —
// то же число, что в его «Потребности» (раньше балансы разных проектов охвата сложить
// было нельзя, и колонка у строки плана пустовала).
import { useEffect, useState } from 'react'
import { CommitInput } from './CommitInput'
import { api, type Allocation, type AllocationRow, type AllocationCell } from './api'
import { useCategoryFilter } from './ColumnFilter'
import { Balance, Chevron, Cost, CounterpartyRef, PurchaseGlyph, balanceTitle, num,
  rowNumbers } from './status'
import { EntityLink } from './EntityLink'

// Состояние распределения: загрузка по id и обновление на `rev` (мутации формы
// закупки). Живёт у формы — табы «Строки», «Заказы» и окно «Новый заказ» смотрят в одни
// данные. Мутаций своих нет: распределение только читается (волна 24).
export function useAllocation(procurementId: number, rev: number) {
  const [p, setP] = useState<Allocation | null>(null)
  const [err, setErr] = useState<string | null>(null)

  // Сменилась закупка — прежние данные и ошибка ей не принадлежат (форма переиспользуется
  // между закупками, и без сброса ошибка чужого id висела над чужими строками).
  useEffect(() => { setP(null); setErr(null) }, [procurementId])
  useEffect(() => {
    api.allocation(procurementId)
      .then(next => { setP(next); setErr(null) })
      .catch(e => setErr(String(e)))
  }, [procurementId, rev])

  return { p, err }
}

export type AllocationState = ReturnType<typeof useAllocation>

// Таб «Строки»: строки плана с раскрытием по заказам закупки.
//
// Вёрстка — ТА ЖЕ сетка строк, что у «Приборов» проекта (`.prow`, правка Ивана
// 2026-08-05): раскрыватель·глиф·код единым блоком слева, числа справа, единица
// последней колонкой. Колонки числовой части — `Баланс · Кол-во · Остаток`: «Кол-во» на
// обоих уровнях значит «сколько в ЭТОМ документе», но поле ввода — только у строки
// плана («хочу»), у строки заказа это число для чтения.
export function AllocationRows({ st, procurementId, editable, onQty, onDelete,
  openItem, openPurchase, openCounterparty }: {
  st: AllocationState; procurementId: number
  editable: boolean                            // закупка расфиксирована — план правится
  onQty: (lineId: number, qty: number) => void // правка строки ПЛАНА (мимо st: ответ
                                               // сервера — форма закупки, не распределение)
  onDelete: (lineId: number) => void           // убрать строку плана (корзина строки)
  openItem: (id: number) => void
  openPurchase: (id: number) => void; openCounterparty: (id: number) => void
}) {
  const { p, err } = st
  // Фильтр по классу изделия — общий движок (2026-08-10), тот же, что в остальном контуре.
  const byCat = useCategoryFilter(p?.rows, r => r.item_category, procurementId)
  const no = rowNumbers(p?.rows)        // постоянный номер строки плана
  if (!p) return <div className="tab-empty">Загрузка…</div>
  if (p.rows.length === 0)
    return <div className="tab-empty">
      В плане нет строк — возьмите позиции в табе «Потребность».
    </div>
  return (
    <>
      {err && <div className="anomaly">{err}</div>}
      <div className={'pgrid pgrid--alloc' + (editable ? ' pgrid--acts' : '')}>
        {/* Заголовок ведущей колонки отступает на раскрыватель и глиф (`head--tree`,
            §7a): подпись начинается ровно над первым символом кода. */}
        <div className="prow prow--head head--tree">
          <span className="rn" title="номер строки — постоянный, фильтр его не меняет">№</span>
          <span className="tree-cell">Компонент{byCat.head}</span>
          <span className="name">Описание</span>
          <span className="pnum" title="баланс проекта закупки по этому изделию">
            Баланс</span>
          <span className="pnum"
            title="у строки плана — сколько хотим, у заказа — сколько он взял">
            Кол-во</span>
          <span className="pnum" title="остаток строки плана: сколько ещё не взяли заказы">
            Остаток</span>
          <span className="puom" title="единица измерения строки">Ед.</span>
          {/* Деньги — за границей единицы: она квалифицирует количества слева. */}
          <span className="pnum" title="стоимость строки: кол-во × оценка изделия">
            Стоимость, ₽</span>
          {editable && <span />}
        </div>
        {byCat.shown.map(r => (
          <LineRow key={r.line_id} r={r} no={no.get(r)} editable={editable} onQty={onQty}
            onDelete={onDelete} openItem={openItem} openPurchase={openPurchase}
            openCounterparty={openCounterparty} />
        ))}
      </div>
    </>
  )
}

// Таб «Заказы»: веер заказов, рождённых из этой закупки.
export function PurchaseFan({ st, openPurchase, openCounterparty }: {
  st: AllocationState; openPurchase: (id: number) => void
  openCounterparty: (id: number) => void
}) {
  const { p } = st
  if (!p) return <div className="tab-empty">Загрузка…</div>
  if (p.fan.length === 0)
    return <div className="tab-empty">
      Заказов ещё нет — заведите заказ кнопкой «Новый заказ».
    </div>
  return (
    <table className="grid">
      <thead><tr>
        <th className="rn">№</th><th className="gl" /><th className="c-key">Заказ</th>
        <th className="c-desc">Контрагент</th>
        <th className="num">Строк</th>
        <th className="num">Всего</th>
      </tr></thead>
      <tbody>
        {p.fan.map((f, i) => (
          <tr key={f.purchase_id} className="row">
            <td className="rn">{i + 1}</td>
            <td className="gl"><PurchaseGlyph locked={f.locked} files={f.files} coverage={f.coverage} /></td>
            <td className="c-key">
              <EntityLink kind="purchase" id={f.purchase_id} open={openPurchase}>
                {f.purchase_code}</EntityLink></td>
            <td className="c-desc">
              <CounterpartyRef code={f.contractor_code} name={f.contractor_name}
                id={f.contractor_id} open={openCounterparty} /></td>
            <td className="num">{f.lines}</td>
            <td className="num">{num(f.total)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// Строка плана: сколько взяли заказы и сколько осталось + раскрытие в заказы.
// Глиф (правило Ивана 2026-08-05): взята в ноль — зелёный check; не тронута или
// перебор — красный warning; между — оранжевый warning.
function LineRow({ r, no, editable, onQty, onDelete, openItem, openPurchase,
  openCounterparty }: {
  r: AllocationRow; no?: number
  editable: boolean; onQty: (lineId: number, qty: number) => void
  onDelete: (lineId: number) => void
  openItem: (id: number) => void
  openPurchase: (id: number) => void; openCounterparty: (id: number) => void
}) {
  const [open, setOpen] = useState(false)
  const done = r.status === 'available'
  const tone = r.status === 'available' ? 'ok' : r.status === 'on_order' ? 'wip' : 'order'
  return (
    <>
      <div className="prow prow--device">
        <span className="rn">{no}</span>
        <span className="tree-cell">
          <button className="chev" title={open ? 'свернуть' : 'распределение по заказам'}
            onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
          <span className={`ci sg ci-${done ? 'check' : 'warning'} sg-${tone}`}
            title={done ? 'взята заказами полностью'
              : r.allocated === 0 ? 'ещё не взята заказами'
              : r.remaining < 0 ? 'заказы взяли больше, чем в плане'
              : 'взята заказами частично'} />
          {/* Код — ссылка в форму изделия и в ОДНУ строку с многоточием (§7a). */}
          <EntityLink kind="item" id={r.item_id} open={openItem}>{r.item_code}</EntityLink>
        </span>
        <span className="name">{r.item_description}</span>
        <span className="pnum">
          <Balance value={r.balance} status={r.balance_status}
            title={balanceTitle(r.item_code, r.need, r.kitted, r.in_stock, r.on_order,
              r.planned)} />
        </span>
        {/* «Хочу» — единственное поле ввода закупки; под замком план read-only. Ответ
            приходит формой закупки, поэтому правку ведёт вьюха-хозяйка (`onQty`). */}
        <span className="pnum">
          {editable
            /* Ноль допустим (2026-08-11): строку рождает «Потребность» именно нулём
               — «позицию беру, количество думаю». Убрать позицию совсем — корзиной. */
            ? <CommitInput value={String(r.qty)}
                onCommit={v => onQty(r.line_id, Number(v))}
                validate={v => Number(v) >= 0} />
            : num(r.qty)}
        </span>
        {/* Перебор (остаток ушёл в минус) — «нужна работа», знак выбирает тема. */}
        <span className="pnum">
          <span className={r.remaining < 0 ? 'g-to_order' : undefined}>
            {num(r.remaining)}</span>
        </span>
        <span className="puom">{r.uom}</span>
        <span className="pnum"><Cost cost={r.cost} status={r.cost_status}
          overpayAt={r.overpay_at} uom={r.uom} /></span>
        {/* Корзина строки — крайняя колонка, только в правке (§9). */}
        {editable && <span className="act">
          <button className="fh-ctl icon fh-del" title="Убрать строку плана"
            onClick={() => onDelete(r.line_id)}>
            <span className="ci ci-trash" /></button>
        </span>}
      </div>
      {open && (r.orders.length === 0
        ? <div className="prow prow--comp prow--empty">
            <span>Позицию ещё не взял ни один заказ.</span>
          </div>
        : r.orders.map(c => (
            <OrderCell key={c.purchase_id} c={c} uom={r.uom} editable={editable}
              openPurchase={openPurchase} openCounterparty={openCounterparty} />
          )))}
    </>
  )
}

// Строка заказа под строкой плана: глиф замка + код заказа, контрагент, сколько взял.
// Только чтение — правится в форме заказа (волна 24).
function OrderCell({ c, uom, editable, openPurchase, openCounterparty }: {
  c: AllocationCell; uom: string
  editable: boolean                              // держит колонку команд строки плана
  openPurchase: (id: number) => void; openCounterparty: (id: number) => void
}) {
  return (
    <div className="prow prow--comp">
      <span className="rn" />
      <span className="tree-cell alloc-sub">
        <span className="tree-lead" />
        <PurchaseGlyph locked={c.locked} files={c.files} coverage={c.coverage} />
        <EntityLink kind="purchase" id={c.purchase_id} open={openPurchase}>
          {c.purchase_code}</EntityLink>
      </span>
      {/* Контрагент — КОДОМ и ссылкой в его форму (код первичен, имя — в title). */}
      <span className="name">
        <CounterpartyRef code={c.contractor_code} name={c.contractor_name}
          id={c.contractor_id} open={openCounterparty} /></span>
      <span className="pnum" />
      <span className="pnum">{num(c.qty)}</span>
      <span className="pnum" />
      <span className="puom">{uom}</span>
      <span className="pnum"><Cost cost={c.cost} status={null} /></span>
      {/* Колонка команд есть у строки плана — без пустой ячейки сетка съедет. */}
      {editable && <span className="act" />}
    </div>
  )
}
