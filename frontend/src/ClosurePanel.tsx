// Витрина волны 6: панель закрытия проекта (под дашбордом дефицита).
// Сведение остаточных лотов (live≠0) в 0 закрывающими выходами + мягкий замок-веха
// статуса. Один клик на строке: «списать» (→ серый, `−ISSUE`) или «на баланс» (→
// белый «Собственный склад», отпочкование). Отгрузка заказчику — через режим
// «Передачи». Закрыть можно внешний проект, когда остатков нет; переоткрытие свободно.
import { useEffect, useState } from 'react'
import { api, type ProjectClosure, type ResidualLot } from './api'
import { num } from './status'

export function ClosurePanel({ projectId, openItem, onChanged }: {
  projectId: number; openItem: (id: number) => void; onChanged?: () => void
}) {
  const [c, setC] = useState<ProjectClosure | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setC(null); setErr(null)
    api.closure(projectId).then(setC).catch(e => setErr(String(e)))
  }, [projectId])

  const run = (p: Promise<ProjectClosure>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return null              // проект без панели (напр. ошибка) — молча
  if (!c) return null
  if (!c.is_external) return null         // внутренние склады не закрываются

  const closed = c.status === 'closed'
  return (
    <div className="closure">
      <h2 className="section-h">
        <span className={`glyph ${closed ? 'g-lock' : 'g-info'}`}>{closed ? '🔒' : '○'}</span>{' '}
        Закрытие проекта
        {closed && <span className="lit"> — закрыт {c.closed_at}</span>}
      </h2>
      <div className="subtitle">
        Свести остаточные лоты в 0 → замок-веха ·{' '}
        {c.residuals.length === 0
          ? <span className="g-available">остатков нет ✓</span>
          : <>остаточных лотов <span className="seg">{c.residuals.length}</span>
             {c.anomaly_count > 0 &&
               <span className="anomaly"> · аномалий {c.anomaly_count} ▲</span>}</>}
      </div>

      <div className="kit-actions">
        {closed
          ? <button className="btn" disabled={busy}
              onClick={() => run(api.reopenProject(c.project_id))}>Переоткрыть</button>
          : <button className="btn" disabled={busy || !c.can_close}
              title={c.can_close ? 'закрыть проект' : c.blocker}
              onClick={() => run(api.closeProject(c.project_id))}>Закрыть проект</button>}
        {!closed && !c.can_close && c.blocker &&
          <span className="hint">{c.blocker}</span>}
        {busy && <span className="hint">сохраняю…</span>}
        {err && <span className="anomaly">{err}</span>}
      </div>

      {c.residuals.length > 0 && !closed &&
        <table className="grid">
          <thead>
            <tr>
              <th>партия</th><th>изделие</th>
              <th style={{ textAlign: 'right' }}>остаток</th><th />
            </tr>
          </thead>
          <tbody>
            {c.residuals.map(r => (
              <ResidualRow key={r.lot_id} r={r} projectId={c.project_id}
                busy={busy} openItem={openItem} run={run} />
            ))}
          </tbody>
        </table>}
    </div>
  )
}

// Остаточный лот: один клик сводит его в 0 (списать → серый / на баланс → белый).
function ResidualRow({ r, projectId, busy, openItem, run }: {
  r: ResidualLot; projectId: number; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<ProjectClosure>) => void
}) {
  const positive = r.live_qty > 0
  return (
    <tr className={'row ' + (r.anomaly ? 's-to_order' : 's-available')}>
      <td>
        <span className={`glyph ${r.anomaly ? 'g-to_order' : 'g-available'}`}>
          {r.anomaly ? '▲' : '✓'}</span>{' '}
        <span className="pn">{r.lot_label}</span>
      </td>
      <td>
        <a className="link" onClick={() => openItem(r.item_id)}>{r.item_code}</a>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>{r.item_name}</span>
      </td>
      <td className="num">
        <span className={r.anomaly ? 'anomaly' : ''}>{num(r.live_qty)}</span> {r.uom}
        {r.anomaly && <span className="anomaly" title="недостача — подбей лоты"> подбей</span>}
      </td>
      <td style={{ textAlign: 'right' }}>
        {positive && <>
          <button className="btn sm" disabled={busy}
            title="списать остаток → серый склад (Свободные неучтённые)"
            onClick={() => run(api.writeoffLot(projectId, { lot_id: r.lot_id, qty: r.live_qty }))}>
            списать</button>{' '}
          <button className="btn sm" disabled={busy}
            title="поставить на баланс → белый склад (Собственный склад)"
            onClick={() => run(api.stockLot(projectId, { lot_id: r.lot_id, qty: r.live_qty }))}>
            на баланс</button>
        </>}
      </td>
    </tr>
  )
}
