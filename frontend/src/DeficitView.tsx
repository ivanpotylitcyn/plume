// Витрина волны 1: проектный дашборд дефицита (ось Project).
// Тройной разбор ✓/●/▲, цвет шапки прибора = worst-of + бейдж лучшего прогресса.
import { useEffect, useState } from 'react'
import { api, type Deficit, type DeficitDemand } from './api'
import { GLYPH, Glyph, Segment, num } from './status'

export function DeficitView({ projectId, openItem }:
  { projectId: number; openItem: (id: number) => void }) {
  const [data, setData] = useState<Deficit | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setData(null); setErr(null)
    api.deficit(projectId).then(setData).catch(e => setErr(String(e)))
  }, [projectId])

  if (err) return <div className="empty">Ошибка: {err}</div>
  if (!data) return <div className="empty">Загрузка…</div>

  return (
    <div>
      <h1 className="title">{data.project_code} — {data.project_name}</h1>
      <div className="subtitle">Дефицит проекта · надо − склад − заказано · 1 уровень BOM</div>
      {data.demands.length === 0 && <div className="empty">Нет потребностей (ProjectDemand)</div>}
      {data.demands.map(d => <Demand key={d.demand_id} d={d} openItem={openItem} />)}
    </div>
  )
}

function Demand({ d, openItem }: { d: DeficitDemand; openItem: (id: number) => void }) {
  const dev = d.device
  return (
    <div>
      <div className="device">
        <span className={`glyph g-${d.status}`}>{GLYPH[d.status]}</span>
        <span className="name">
          <a className="link" onClick={() => openItem(d.target_id)}>{d.target_code}</a>
          {' '}{d.target_name}
        </span>
        <span className="triple">потребность {num(d.qty)} ·{' '}
          <Segment status="available" value={dev.done} />{' '}
          <Segment status="on_order" value={dev.wip} />{' '}
          <Segment status="to_order" value={dev.not_started} />
        </span>
        {d.status !== d.badge &&
          <span className="triple">прогресс: <Glyph status={d.badge} /></span>}
      </div>
      <table className="grid">
        <thead>
          <tr><th>Компонент</th><th>Назв.</th><th style={{ textAlign: 'right' }}>Надо</th>
            <th>Разбор</th><th style={{ textAlign: 'right' }}>Склад</th></tr>
        </thead>
        <tbody>
          {d.lines.map(ln => (
            <tr key={ln.component_id} className={`row s-${ln.status}`}>
              <td><a className="link" onClick={() => openItem(ln.component_id)}>
                {ln.component_code}</a></td>
              <td style={{ color: 'var(--fg-dim)' }}>{ln.component_name}</td>
              <td className="num">{num(ln.need)} {ln.uom}</td>
              <td>
                <Segment status="available" value={ln.have} />
                <Segment status="on_order" value={ln.on_order} />
                <Segment status="to_order" value={ln.to_order} />
              </td>
              <td className="num">
                {num(ln.available_raw)}
                {ln.anomaly && <span className="anomaly" title="есть лот с отрицательным остатком">▲ подбей лоты</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
