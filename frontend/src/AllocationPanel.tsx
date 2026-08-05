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
import { Chevron, StatusGlyph, num } from './status'

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
export function AllocationRows({ st, procurementId, openPurchase }: {
  st: AllocationState; procurementId: number; openPurchase: (id: number) => void
}) {
  const { p, err, busy, run } = st
  if (!p) return <div className="tab-empty">Загрузка…</div>
  if (p.rows.length === 0)
    return <div className="tab-empty">В плане нет строк — добавьте позиции в табе «Строки».</div>
  return (
    <>
      {err && <div className="anomaly">{err}</div>}
      <table className="grid">
        <thead>
          <tr>
            <th className="gl" /><th className="c-key">Изделие</th>
            <th className="c-desc">Описание</th>
            <th className="uom">Ед.</th>
            <th className="num">В плане</th>
            <th className="num">Разложено</th>
            <th className="num">Остаток</th>
            <th className="num">Баланс</th>
            <th className="act" />
          </tr>
        </thead>
        <tbody>
          {p.rows.map(r => (
            <LineRow key={r.line_id} r={r} busy={busy} procurementId={procurementId}
              run={run} openPurchase={openPurchase} />
          ))}
        </tbody>
      </table>
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
function LineRow({ r, busy, procurementId, run, openPurchase }: {
  r: AllocationRow; busy: boolean; procurementId: number
  run: (p: Promise<Allocation>) => void; openPurchase: (id: number) => void
}) {
  const [open, setOpen] = useState(false)
  const done = r.status === 'available'
  const tone = r.status === 'available' ? 'ok' : r.status === 'on_order' ? 'wip' : 'order'
  return (
    <>
      <tr className="row">
        <td className="gl">
          <span className={`ci sg ci-${done ? 'check' : 'warning'} sg-${tone}`}
            title={done ? 'разложена полностью'
              : r.allocated === 0 ? 'ещё не разложена'
              : r.remaining < 0 ? 'разложено больше, чем в плане'
              : 'разложена частично'} />
        </td>
        <td className="c-key">
          {/* Раскрыватель — первый символ строки (§7a), как в «Приборах» проекта. */}
          <button className="fh-ctl icon" title="Раскладка по заказам закупки"
            onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
          <span className="code">{r.item_code}</span></td>
        <td className="c-desc">
          <span className="cell-ellip" title={r.item_description}>{r.item_description}</span></td>
        <td className="uom">{r.uom}</td>
        <td className="num">{num(r.qty)}</td>
        <td className="num">{num(r.allocated)}</td>
        {/* Перепег (остаток ушёл в минус) — «нужна работа», знак выбирает тема. */}
        <td className="num">
          <span className={r.remaining < 0 ? 'g-to_order' : undefined}>{num(r.remaining)}</span>
        </td>
        <td className="num" />
        <td className="act" />
      </tr>
      {open && (r.orders.length === 0
        ? <tr className="row ghost"><td className="gl" />
            <td colSpan={8}><span>
              Под этой закупкой нет заказов — заведите заказ и укажите в нём эту закупку.
            </span></td></tr>
        : r.orders.map(c => (
            <OrderCell key={c.purchase_id} c={c} itemId={r.item_id} busy={busy}
              procurementId={procurementId} run={run} openPurchase={openPurchase} />
          )))}
    </>
  )
}

// Ячейка раскладки: заказ (глиф замка + кликабельный код + проект), баланс проекта и
// поле количества. Поле — присвоение: что вписал, то и стоит в строке заказа; `0`
// снимает строку. Зафиксированный заказ остаётся видимым («сюда уже заказано» — нужный
// контекст), но правится только в своей форме.
function OrderCell({ c, itemId, busy, procurementId, run, openPurchase }: {
  c: AllocationCell; itemId: number; busy: boolean; procurementId: number
  run: (p: Promise<Allocation>) => void; openPurchase: (id: number) => void
}) {
  const tone = c.balance_status === 'to_order' ? 'order'
    : c.balance_status === 'on_order' ? 'wip' : 'ok'
  return (
    <tr className="row ghost">
      <td className="gl"><StatusGlyph locked={c.locked} /></td>
      <td className="c-key ind">
        <a className="link" onClick={() => openPurchase(c.purchase_id)}>
          {c.purchase_code}</a></td>
      <td className="c-desc">
        <span className="code">{c.project_code}</span>{' '}
        <span className="cell-ellip" title={c.project_name}>{c.project_name}</span></td>
      <td className="uom" />
      <td className="num" />
      <td className="num" />
      <td className="num" />
      <td className="num" title={`${c.project_code} · надо ${num(c.need)}, `
        + `скомплектовано ${num(c.kitted)}, склад ${num(c.in_stock)}, `
        + `в заказах ${num(c.on_order)}`}>
        <span className={`ci sg ci-warning sg-${tone}`} />
        {c.balance > 0 ? `+${num(c.balance)}` : num(c.balance)}
      </td>
      <td className="act">
        {c.locked
          ? <span className="sub" title="заказ зафиксирован — расфиксируйте в его форме">
              {num(c.qty)}</span>
          : <CommitInput value={String(c.qty)} disabled={busy}
              onCommit={v => run(api.allocate(procurementId,
                { purchase_id: c.purchase_id, item_id: itemId, qty: Number(v || 0) }))}
              validate={v => v === '' || Number(v) >= 0} />}
      </td>
    </tr>
  )
}
