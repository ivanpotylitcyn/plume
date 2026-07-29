// Волна 8 — pegging: нарезка плана-закупки (Procurement) на проектные заказы.
// По каждой строке плана — распределение по проектам (наводка из командного свода +
// фактически пегнутое) с ручным пегом/снятием; «разрезать по проектам» (autopeg) кладёт
// по наводке в один клик. Веер проектных заказов — ссылки в их формы.
// Пег рождает проектный Purchase под этим планом-родителем (ломает 1:1-заглушку).
//
// Волна 19 (Ф12c): панель разобрана на части канона §13 — состояние в хук `usePegging`,
// два списка стали двумя ТАБАМИ формы закупки («Привязка», «Заказы»), а команда
// «Разрезать по проектам» уехала в колонку команд шапки (была `.kit-actions` в теле).
//
// Волна 19 (Ф5+Ф13). Три уровня вместо двух:
//   строка плана → проекты ОХВАТА (наводка + пегнутое) → применения (обратное
//   разузлование: в какие изделия проекта эта позиция идёт и по сколько штук).
// Наводка сузилась до охвата закупки — раньше сюда лезли проекты всей организации.
// Пег кладётся в ЯВНО выбранный заказ (Р2): под проектом их может быть несколько.
import { useEffect, useState } from 'react'
import { Dropdown } from './Dropdown'
import { api, type Pegging, type PeggingRow, type PeggingProject } from './api'
import { Chevron, Glyph, StatusGlyph, num } from './status'

// Состояние pegging: загрузка по id, обновление на `rev` (мутации формы плана) и
// обёртка мутации. Живёт у формы — оба таба смотрят в одни данные.
export function usePegging(procurementId: number, rev: number) {
  const [p, setP] = useState<Pegging | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.pegging(procurementId).then(setP).catch(e => setErr(String(e)))
  }, [procurementId, rev])

  const run = (pr: Promise<Pegging>) => {
    setBusy(true); setErr(null)
    pr.then(setP).catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }
  return { p, err, busy, run, autopeg: () => run(api.autopeg(procurementId)) }
}

export type PeggingState = ReturnType<typeof usePegging>

// Таб «Привязка»: строки плана с раскрытием по проектам.
export function PeggingRows({ st, procurementId }: {
  st: PeggingState; procurementId: number
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
            <th style={{ textAlign: 'right' }}>В плане</th><th className="uom">Ед.</th>
            <th style={{ textAlign: 'right' }}>Разложено</th>
            <th style={{ textAlign: 'right' }}>Остаток</th>
            <th className="act" />
          </tr>
        </thead>
        <tbody>
          {p.rows.map(r => (
            <LineRow key={r.line_id} r={r} editable={p.editable} busy={busy}
              procurementId={procurementId} run={run} />
          ))}
        </tbody>
      </table>
    </>
  )
}

// Таб «Заказы»: веер проектных заказов, рождённых из этого плана.
export function PurchaseFan({ st, openPurchase }: {
  st: PeggingState; openPurchase: (id: number) => void
}) {
  const { p } = st
  if (!p) return <div className="tab-empty">Загрузка…</div>
  if (p.fan.length === 0)
    return <div className="tab-empty">План ещё не разложен на проектные заказы.</div>
  return (
    <table className="grid">
      <thead><tr>
        <th className="gl" /><th className="c-key">Заказ</th>
        <th className="c-fit">Проект</th><th className="c-desc">Описание проекта</th>
        <th style={{ textAlign: 'right' }}>Строк</th>
        <th style={{ textAlign: 'right' }}>Всего</th>
      </tr></thead>
      <tbody>
        {p.fan.map(f => (
          <tr key={f.purchase_id} className="row">
            <td className="gl"><StatusGlyph locked={f.locked} /></td>
            <td className="c-key">
              <a className="link" onClick={() => openPurchase(f.purchase_id)}>
                Заказ #{f.purchase_id}</a></td>
            <td className="c-fit"><span className="code">{f.project_code}</span></td>
            <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
              <span className="cell-ellip" title={f.project_name}>{f.project_name}</span></td>
            <td className="num">{f.lines}</td>
            <td className="num">{num(f.total)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// Строка плана: итог разложенного + раскрытие по проектам (наводка + пег/снятие).
function LineRow({ r, editable, busy, procurementId, run }: {
  r: PeggingRow; editable: boolean; busy: boolean
  procurementId: number; run: (p: Promise<Pegging>) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <tr className={`row s-${r.status}`}>
        <td className="gl"><Glyph status={r.status} /></td>
        <td className="c-key"><span className="code">{r.item_code}</span></td>
        <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
          <span className="cell-ellip" title={r.item_description}>{r.item_description}</span></td>
        <td className="num">{num(r.qty)}</td>
        <td className="uom">{r.uom}</td>
        <td className="num">{num(r.pegged)}</td>
        <td className="num" style={{ color: r.remaining < 0 ? 'var(--st-order)' : undefined }}>
          {num(r.remaining)}
        </td>
        <td className="act">
          <button className="fh-ctl icon" title="Распределение по проектам"
            onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
          {r.by_project.length === 0 &&
            <span className="sub" style={{ marginLeft: 6 }}>нет нужды по проектам</span>}
        </td>
      </tr>
      {open && r.by_project.map(bp => (
        <ProjectRow key={bp.project_id} bp={bp} item_id={r.item_id} editable={editable}
          busy={busy} procurementId={procurementId} run={run} />
      ))}
    </>
  )
}

// Проект под строкой плана: наводка + пегнуто + пег (в выбранный заказ) / снятие.
// Раскрытие — применения: зачем эта позиция проекту (обратное разузлование).
function ProjectRow({ bp, item_id, editable, busy, procurementId, run }: {
  bp: PeggingProject; item_id: number; editable: boolean; busy: boolean
  procurementId: number; run: (p: Promise<Pegging>) => void
}) {
  const [qty, setQty] = useState('')
  const [open, setOpen] = useState(false)
  // Куда пегать (Р2). Зафиксированный заказ — не мишень (движок откажет), поэтому в
  // выборе только черновики. Пока не выбрали руками — первый черновик проекта, то есть
  // прежнее поведение; «＋ новый заказ» только по явному выбору, иначе каждый пег
  // плодил бы отдельное обязательство. Исчез выбранный (зафиксировали) — падаем на
  // тот же дефолт, а не пегаем молча не туда.
  const drafts = bp.purchases.filter(p => !p.locked)
  const [into, setInto] = useState<number | 'new' | null>(null)
  const chosen = into === 'new' || (into !== null && drafts.some(p => p.id === into))
  const target = chosen ? into as number | 'new' : (drafts[0]?.id ?? 'new')

  const peg = (q: number) => {
    if (!(q > 0)) return
    run(api.peg(procurementId,
      { item_id, project_id: bp.project_id, qty: q, purchase_id: target }))
    setQty('')
  }
  return (
    <>
      <tr className="row ghost">
        <td className="gl" />
        <td className="c-key">
          <button className="fh-ctl icon" title="Зачем это проекту (применения)"
            onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
          <span className="code">{bp.project_code}</span></td>
        <td className="c-desc"><span className="sub">{bp.project_name}</span></td>
        <td className="num sub" title="наводка по охвату (сколько проекту ещё надо)">
          {bp.suggest > 0 ? num(bp.suggest) : '—'}
        </td>
        <td className="uom" />
        <td className="num">{num(bp.pegged)}</td>
        <td className="num">
          {bp.pegged > 0 && editable &&
            <button className="fh-ctl icon fh-del" title="Отвязать от проекта" disabled={busy}
              onClick={() => run(api.unpeg(procurementId,
                { item_id, project_id: bp.project_id }))}>
              <span className="ci ci-trash" /></button>}
        </td>
        <td className="act">
          {editable && <>
            {/* Куда лечь — раньше «сколько»: заказ рождается лениво (пустых призраков
                не заводим), поэтому «＋ новый заказ» — выбор на будущий пег, а не
                создание сейчас. */}
            <Dropdown className="peg-into" value={target} disabled={busy}
              title="В какой заказ проекта класть привязку"
              options={[...drafts.map(pu => ({ value: pu.id, label: pu.code ?? `Заказ #${pu.id}` })),
                { value: 'new', label: '＋ новый заказ' }]}
              onPick={v => setInto(v === 'new' ? 'new' : Number(v))} />
            <input className="qty-in" value={qty} disabled={busy} placeholder="+кол-во"
              style={{ marginLeft: 6 }}
              onChange={e => setQty(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') peg(Number(qty)) }} />
            {/* Команды строки — одними глифами (§7a): текстовые «привязать» и
                «＋наводку» вместе с выбором заказа не влезали в строку. */}
            <button className="fh-ctl icon" disabled={busy || !(Number(qty) > 0)}
              title="Привязать введённое количество"
              onClick={() => peg(Number(qty))}><span className="ci ci-check" /></button>
            {bp.suggest > 0 &&
              <button className="fh-ctl icon" disabled={busy}
                title={`Привязать наводку — ${num(bp.suggest)}`}
                onClick={() => peg(bp.suggest)}><span className="ci ci-add" /></button>}
          </>}
        </td>
      </tr>
      {open && (bp.usage.length === 0
        ? <tr className="row ghost"><td className="gl" />
            <td colSpan={7}><span className="sub">
              Позиция не входит в изделия проекта — привязка ручная.</span></td></tr>
        : bp.usage.map(u => (
          <tr key={u.target_item_id} className="row ghost">
            <td className="gl" />
            <td className="c-key" style={{ paddingLeft: 28 }}>
              <span className="code">{u.target_code}</span></td>
            <td className="c-desc"><span className="sub">{u.target_description}</span></td>
            <td className="num sub"
              title={`${num(u.per_unit)} на изделие × ${num(u.demand_qty)} изделий`}>
              {num(u.total)}</td>
            <td className="uom" />
            <td className="num sub">×{num(u.per_unit)}</td>
            <td /><td className="act" />
          </tr>
        )))}
    </>
  )
}
