// Секция «Склад проекта» (форма проекта, внешний): живые лоты проекта, за которыми
// следим каждый день. По каждому лоту — быстрый выход: «списать» (→ серый,
// `−ISSUE`) или «на баланс» (→ белый «Собственный склад», отпочкование). Отгрузка
// заказчику — через режим «Передачи». Закрытие проекта (свод остатков в 0 + замок-веха)
// — редкое действие, тихой строкой внизу; переоткрытие свободно.
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

  const closed = c.locked
  const lots = c.residuals.length
  return (
    <div className="closure">
      <h2 className="section-h">Склад проекта
        <span className="hint">
          {closed
            ? <>зафиксирован · остатков нет</>
            : lots === 0
              ? <>склад пуст · живых остатков нет</>
              : <>живых лотов {lots}
                 {c.anomaly_count > 0 && <> · аномалий {c.anomaly_count} ▲</>}</>}
        </span>
      </h2>

      {busy && <div className="hint">сохраняю…</div>}
      {err && <div className="anomaly">{err}</div>}

      {lots > 0 && !closed &&
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

      {/* Закрытие проекта — редкое действие (свод остатков в 0 + замок-веха), тихой строкой. */}
      <div className="closure-foot">
        {closed
          ? <>
              <span className="hint">Проект зафиксирован{c.closed && <> · закрыт {c.closed}</>}.</span>
              <button className="btn sm" disabled={busy}
                onClick={() => run(api.unlockProject(c.project_id))}>Расфиксировать проект</button>
            </>
          : <>
              <button className="btn sm" disabled={busy || !c.can_close}
                title={c.can_close ? 'свести остатки в 0 и закрыть проект' : c.blocker}
                onClick={() => { if (confirm('Зафиксировать проект? Остатков быть не должно.')) run(api.lockProject(c.project_id)) }}>
                Закрыть проект</button>
              <span className="hint">{c.can_close ? 'остатков нет — можно закрыть' : c.blocker}</span>
            </>}
      </div>
    </div>
  )
}

// Живой лот проекта: один клик сводит его в 0 (списать → серый / на баланс → белый).
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
        <a className="link" onClick={() => openItem(r.item_id)}>{r.item_design_item_id}</a>{' '}
        <span style={{ color: 'var(--fg-dim)' }}>{r.item_description}</span>
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
