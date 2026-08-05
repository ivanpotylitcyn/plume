// Табы закупки «Привязка» и «Заказы» — раскладка плана на проектные заказы.
//
// Переделано 2026-08-05. Раньше строка плана раскрывалась в ПРОЕКТЫ, а заказ выбирался
// дропдауном в каждой строке. Проект, однако, — свойство заказа, а не уровень
// закупочного контура (Закупка = ЧТО, Заказ = У КОГО, Поставка = КТО привёз), поэтому
// раскладка «из ЧТО в У КОГО» идёт по заказам напрямую: строка раскрывается в ЗАКАЗЫ
// этой закупки, ячейка = строка заказа. Матрица прямоугольная и без скрытого состояния
// (дропдаун прятал вторую строку того же проекта — «Разложено 150» могло означать
// 100+50 без следа на экране).
//
// Вместе с проектной осью ушли: дропдаун выбора заказа, «＋ новый заказ» с ленивым
// рождением, autopeg («Разрезать»), обратное разузлование внутрь проекта, а также
// тройка контролов ✓/＋кол-во/корзина. Их заменило ОДНО поле на строку: ввод —
// присвоение (0 снимает строку заказа), заказы заводятся руками в своей форме.
import { useEffect, useState } from 'react'
import { CommitInput } from './CommitInput'
import { api, type Allocation, type AllocationRow, type AllocationCell } from './api'
import { Balance, Chevron, StatusGlyph, balanceTitle, num } from './status'

// Состояние привязки: загрузка по id, обновление на `rev` (мутации формы плана) и
// обёртка мутации. Живёт у формы — оба таба смотрят в одни данные.
export function useAllocation(procurementId: number, rev: number) {
  const [p, setP] = useState<Allocation | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.allocation(procurementId).then(setP).catch(e => setErr(String(e)))
  }, [procurementId, rev])

  const run = (pr: Promise<Allocation>) => {
    setBusy(true); setErr(null)
    pr.then(setP).catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }
  return { p, err, busy, run }
}

export type AllocationState = ReturnType<typeof useAllocation>

// Таб «Привязка»: строки плана с раскрытием по заказам закупки.
//
// Вёрстка — ТА ЖЕ сетка строк, что у «Приборов» проекта (`.prow`, правка Ивана
// 2026-08-05): раскрыватель·глиф·код единым блоком слева, числа справа с глифом за
// числом, единица последней колонкой. Таблица `.grid` здесь давала другую геометрию, и
// два аккордеона одного продукта выглядели чужими друг другу.
//
// Колонки числовой части — `Баланс · Разложено · Остаток`, и каждая осмысленна ровно на
// своём уровне: у строки плана заполнены две правые (сколько разложено и сколько ещё
// нет), у строки заказа — две левые (баланс его проекта и поле ввода). «В плане» снята:
// она выводится из пары «Разложено + Остаток» и занимала место, которое нужнее балансу.
export function AllocationRows({ st, procurementId, openItem, openProject, openPurchase }: {
  st: AllocationState; procurementId: number
  openItem: (id: number) => void; openProject: (id: number) => void
  openPurchase: (id: number) => void
}) {
  const { p, err, busy, run } = st
  if (!p) return <div className="tab-empty">Загрузка…</div>
  if (p.rows.length === 0)
    return <div className="tab-empty">В плане нет строк — добавьте позиции в табе «Строки».</div>
  return (
    <>
      {err && <div className="anomaly">{err}</div>}
      <div className="pgrid pgrid--alloc">
        <div className="prow prow--head">
          <span className="tree-cell">Код</span>
          <span>Описание</span>
          <span className="pnum" title="баланс проекта заказа по этому изделию">
            Баланс</span>
          <span className="pnum" title="разложено по заказам закупки">Разложено</span>
          <span className="pnum" title="остаток строки плана: сколько ещё не разложено">
            Остаток</span>
          <span className="puom" title="единица измерения строки">Ед.</span>
        </div>
        {p.rows.map(r => (
          <LineRow key={r.line_id} r={r} busy={busy} procurementId={procurementId}
            run={run} openItem={openItem} openProject={openProject}
            openPurchase={openPurchase} />
        ))}
      </div>
    </>
  )
}

// Таб «Заказы»: веер проектных заказов, заведённых под эту закупку.
export function PurchaseFan({ st, openPurchase }: {
  st: AllocationState; openPurchase: (id: number) => void
}) {
  const { p } = st
  if (!p) return <div className="tab-empty">Загрузка…</div>
  if (p.fan.length === 0)
    return <div className="tab-empty">
      Под этой закупкой нет заказов — заведите заказ и укажите в нём эту закупку.
    </div>
  return (
    <table className="grid">
      <thead><tr>
        <th className="gl" /><th className="c-key">Заказ</th>
        <th className="c-fit">Проект</th><th className="c-desc">Описание проекта</th>
        <th className="num">Строк</th>
        <th className="num">Всего</th>
      </tr></thead>
      <tbody>
        {p.fan.map(f => (
          <tr key={f.purchase_id} className="row">
            <td className="gl"><StatusGlyph locked={f.locked} /></td>
            <td className="c-key">
              <a className="link" onClick={() => openPurchase(f.purchase_id)}>
                {f.purchase_code}</a></td>
            <td className="c-fit"><span className="code">{f.project_code}</span></td>
            <td className="c-desc">
              <span className="cell-ellip" title={f.project_name}>{f.project_name}</span></td>
            <td className="num">{f.lines}</td>
            <td className="num">{num(f.total)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// Строка плана: сколько разложено и сколько осталось + раскрытие в заказы.
// Глиф (правило Ивана 2026-08-05): разложено в ноль — зелёный check; не тронута или
// перепег — красный warning; между — оранжевый warning. Колонка «Баланс» у строки
// плана пустая ПРИНЦИПИАЛЬНО: сложить балансы разных проектов нельзя — профицит одного
// не гасит нужду другого. Баланс проявляется только в раскрытых строках заказов.
function LineRow({ r, busy, procurementId, run, openItem, openProject, openPurchase }: {
  r: AllocationRow; busy: boolean; procurementId: number
  run: (p: Promise<Allocation>) => void
  openItem: (id: number) => void; openProject: (id: number) => void
  openPurchase: (id: number) => void
}) {
  const [open, setOpen] = useState(false)
  const done = r.status === 'available'
  const tone = r.status === 'available' ? 'ok' : r.status === 'on_order' ? 'wip' : 'order'
  return (
    <>
      <div className="prow prow--device">
        <span className="tree-cell">
          <button className="chev" title={open ? 'свернуть' : 'раскладка по заказам'}
            onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
          <span className={`ci sg ci-${done ? 'check' : 'warning'} sg-${tone}`}
            title={done ? 'разложена полностью'
              : r.allocated === 0 ? 'ещё не разложена'
              : r.remaining < 0 ? 'разложено больше, чем в плане'
              : 'разложена частично'} />
          {/* Код — ссылка в форму изделия и в ОДНУ строку с многоточием, как везде
              (правило строк §7a): длинный код иначе разрывал строку на две. */}
          <a className="link" onClick={() => openItem(r.item_id)}>{r.item_code}</a>
        </span>
        <span className="name">{r.item_description}</span>
        <span className="pnum" />
        <span className="pnum">{num(r.allocated)}</span>
        {/* Перепег (остаток ушёл в минус) — «нужна работа», знак выбирает тема. */}
        <span className="pnum">
          <span className={r.remaining < 0 ? 'g-to_order' : undefined}>
            {num(r.remaining)}</span>
        </span>
        <span className="puom">{r.uom}</span>
      </div>
      {open && (r.orders.length === 0
        ? <div className="prow prow--comp prow--empty">
            <span>Под этой закупкой нет заказов — заведите заказ и укажите
              в нём эту закупку.</span>
          </div>
        : r.orders.map(c => (
            <OrderCell key={c.purchase_id} c={c} itemId={r.item_id} busy={busy}
              procurementId={procurementId} run={run} openProject={openProject}
              openPurchase={openPurchase} />
          )))}
    </>
  )
}

// Ячейка раскладки: заказ (глиф замка + кликабельный код + проект), баланс его проекта
// и поле количества — оно стоит в колонке «Разложено», потому что это она и есть, только
// в разрезе одного заказа. Ввод — присвоение: что вписал, то и стоит в строке заказа;
// `0` снимает строку. Зафиксированный заказ остаётся видимым («сюда уже заказано» —
// нужный контекст), но правится только в своей форме.
function OrderCell({ c, itemId, busy, procurementId, run, openProject, openPurchase }: {
  c: AllocationCell; itemId: number; busy: boolean; procurementId: number
  run: (p: Promise<Allocation>) => void
  openProject: (id: number) => void; openPurchase: (id: number) => void
}) {
  return (
    <div className="prow prow--comp">
      <span className="tree-cell alloc-sub">
        <span className="tree-lead" />
        <StatusGlyph locked={c.locked} />
        <a className="link" onClick={() => openPurchase(c.purchase_id)}>
          {c.purchase_code}</a>
      </span>
      {/* Проект — КОДОМ и ссылкой в его форму: код первичен, описание живёт в title
          (то же правило, что у контрагента). */}
      <span className="name">
        <a className="link" title={c.project_name}
          onClick={() => openProject(c.project_id)}>{c.project_code}</a></span>
      <Balance value={c.balance} status={c.balance_status}
        title={balanceTitle(c.project_code, c.need, c.kitted, c.in_stock, c.on_order)} />
      <span className="pnum">
        {c.locked
          ? <span className="sub" title="заказ зафиксирован — расфиксируйте в его форме">
              {num(c.qty)}</span>
          : <CommitInput value={String(c.qty)} disabled={busy}
              onCommit={v => run(api.allocate(procurementId,
                { purchase_id: c.purchase_id, item_id: itemId, qty: Number(v || 0) }))}
              validate={v => v === '' || Number(v) >= 0} />}
      </span>
      <span className="pnum" />
      <span className="puom" />
    </div>
  )
}
