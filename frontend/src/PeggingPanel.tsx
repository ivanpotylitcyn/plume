// Волна 8 — панель pegging: нарезка плана-закупки (Procurement) на проектные заказы.
// По каждой строке плана — распределение по проектам (наводка из командного свода +
// фактически пегнутое) с ручным пегом/снятием; «разрезать по проектам» (autopeg) кладёт
// по наводке в один клик. Внизу — веер проектных заказов со ссылками в их кокпиты.
// Пег рождает проектный Purchase под этим планом-родителем (ломает 1:1-заглушку).
import { useEffect, useState } from 'react'
import { api, type Pegging, type PeggingRow, type PeggingProject } from './api'
import { PURCH_ST } from './PurchaseView'
import { Glyph, num } from './status'

export function PeggingPanel({ procurementId, rev, openPurchase }: {
  procurementId: number; rev: number; openPurchase: (id: number) => void
}) {
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

  if (!p) return null
  const editable = p.editable
  return (
    <div style={{ marginTop: 20 }}>
      <div className="section-h">Привязка к проектам{' '}
        <span className="lit">— из плана в проектные заказы</span></div>
      <div className="kit-actions">
        {editable &&
          <button className="btn" disabled={busy}
            title="разложить каждую строку плана по нуждающимся проектам (наводка свода)"
            onClick={() => run(api.autopeg(procurementId))}>Разрезать по проектам</button>}
        {busy && <span className="hint">сохраняю…</span>}
        {err && <span className="anomaly">{err}</span>}
      </div>

      {p.rows.length === 0 &&
        <div className="empty">В плане нет строк — добавьте позиции выше.</div>}
      {p.rows.length > 0 &&
        <table className="grid">
          <thead>
            <tr>
              <th>Изделие</th><th style={{ textAlign: 'right' }}>В плане</th>
              <th style={{ textAlign: 'right' }}>Разложено</th>
              <th style={{ textAlign: 'right' }}>Остаток</th><th>Проекты</th>
            </tr>
          </thead>
          <tbody>
            {p.rows.map(r => (
              <LineRow key={r.line_id} r={r} editable={editable} busy={busy}
                procurementId={procurementId} run={run} />
            ))}
          </tbody>
        </table>}

      {p.fan.length > 0 && <>
        <div className="subtitle" style={{ marginTop: 16 }}>Проектные заказы (веер плана)</div>
        <table className="grid">
          <thead><tr><th>Заказ</th><th>Проект</th>
            <th style={{ textAlign: 'right' }}>строк</th>
            <th style={{ textAlign: 'right' }}>всего</th></tr></thead>
          <tbody>
            {p.fan.map(f => {
              const st = PURCH_ST[f.status] ?? PURCH_ST.draft
              return (
                <tr key={f.purchase_id} className="row s-available">
                  <td>
                    <span className={`glyph ${st.cls}`}>{st.g}</span>{' '}
                    <a className="link" onClick={() => openPurchase(f.purchase_id)}>
                      Заказ #{f.purchase_id}</a>{' '}
                    <span className={st.cls} style={{ fontSize: 11 }}>{st.label}</span>
                  </td>
                  <td><span className="code">{f.project_code}</span>{' '}
                    <span style={{ color: 'var(--fg-dim)' }}>{f.project_name}</span></td>
                  <td className="num">{f.lines}</td>
                  <td className="num">{num(f.total)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </>}
    </div>
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
        <td>
          <Glyph status={r.status} />{' '}
          <span className="code">{r.item_design_item_id}</span>{' '}
          <span style={{ color: 'var(--fg-dim)' }}>{r.item_description}</span>
        </td>
        <td className="num">{num(r.qty)} {r.uom}</td>
        <td className="num">{num(r.pegged)}</td>
        <td className="num" style={{ color: r.remaining < 0 ? 'var(--st-order)' : undefined }}>
          {num(r.remaining)}
        </td>
        <td>
          <button className="x" title="распределение по проектам"
            onClick={() => setOpen(o => !o)}>{open ? '▾' : '▸'}</button>
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

// Проект под строкой плана: наводка + пегнуто + пег (ввод) / снятие.
function ProjectRow({ bp, item_id, editable, busy, procurementId, run }: {
  bp: PeggingProject; item_id: number; editable: boolean; busy: boolean
  procurementId: number; run: (p: Promise<Pegging>) => void
}) {
  const [qty, setQty] = useState('')
  const peg = () => {
    const q = Number(qty)
    if (!(q > 0)) return
    run(api.peg(procurementId, { item_id, project_id: bp.project_id, qty: q }))
    setQty('')
  }
  return (
    <tr className="row ghost">
      <td style={{ paddingLeft: 24 }}>
        <span className="code">{bp.project_code}</span>{' '}
        <span className="sub">{bp.project_name}</span>
      </td>
      <td className="num sub" title="наводка свода (сколько проекту ещё надо)">
        {bp.suggest > 0 ? num(bp.suggest) : '—'}
      </td>
      <td className="num">{num(bp.pegged)}</td>
      <td className="num">
        {bp.pegged > 0 && editable &&
          <button className="x" title="отвязать" disabled={busy}
            onClick={() => run(api.unpeg(procurementId,
              { item_id, project_id: bp.project_id }))}>×</button>}
      </td>
      <td>
        {editable && <>
          <input className="qty-in" value={qty} disabled={busy} placeholder="+кол-во"
            onChange={e => setQty(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') peg() }} />
          <button className="btn sm" disabled={busy || !(Number(qty) > 0)}
            style={{ marginLeft: 6 }} onClick={peg}>привязать</button>
          {bp.suggest > 0 &&
            <button className="btn sm" disabled={busy} style={{ marginLeft: 6 }}
              title={`привязать наводку ${num(bp.suggest)}`}
              onClick={() => run(api.peg(procurementId,
                { item_id, project_id: bp.project_id, qty: bp.suggest }))}>
              ＋наводку</button>}
        </>}
      </td>
    </tr>
  )
}
