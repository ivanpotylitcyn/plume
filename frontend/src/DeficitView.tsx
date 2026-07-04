// Витрина волны 1: проектный дашборд дефицита (ось Project).
// Тройной разбор ✓/●/▲, цвет шапки прибора = worst-of + бейдж лучшего прогресса.
import { useEffect, useState } from 'react'
import { api, type Budget, type Deficit, type DeficitDemand } from './api'
import { GLYPH, Glyph, Segment, money, num } from './status'

export function DeficitView({ projectId, openItem, openPurchase }:
  { projectId: number; openItem: (id: number) => void
    openPurchase: (id: number) => void }) {
  const [data, setData] = useState<Deficit | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setData(null); setErr(null)
    api.deficit(projectId).then(setData).catch(e => setErr(String(e)))
  }, [projectId])

  // Мост «дефицит → заказ»: положить ▲-позицию в черновик-заказ проекта и открыть его.
  const order = (itemId: number, qty: number) => {
    setBusy(true)
    api.addToOrder(projectId, { item_id: itemId, qty })
      .then(r => openPurchase(r.purchase_id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err) return <div className="empty">Ошибка: {err}</div>
  if (!data) return <div className="empty">Загрузка…</div>

  return (
    <div>
      <h1 className="title"><span className="pn">{data.project_code}</span> <span className="lit">— {data.project_name}</span></h1>
      <div className="subtitle">Дефицит проекта · надо − склад − заказано · 1 уровень BOM</div>
      <BudgetPanel projectId={projectId} />
      {data.demands.length === 0 && <div className="empty">Нет потребностей (ProjectDemand)</div>}
      {data.demands.map(d => <Demand key={d.demand_id} d={d} openItem={openItem}
        order={order} busy={busy} />)}
    </div>
  )
}

// Панель бюджета (north-star окупаемости): два числа денег (потрачено/план) +
// компас против бюджета, и справа окупаемость — себестоимость/экономия заёма.
function BudgetPanel({ projectId }: { projectId: number }) {
  const [b, setB] = useState<Budget | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setB(null); setErr(null)
    api.budget(projectId).then(setB).catch(e => setErr(String(e)))
  }, [projectId])

  if (err) return <div className="empty">Бюджет: ошибка {err}</div>
  if (!b) return null

  const over = b.compass !== null && b.compass < 0   // перерасход
  return (
    <div className="budget">
      <div className="bgroup">
        <Stat label="потрачено (факт)" value={money(b.spent)} />
        <Stat label="план (прогноз)" value={money(b.plan)} />
        {b.budget !== null
          ? <Stat label="бюджет на материалы" value={money(b.budget)} />
          : <Stat label="бюджет на материалы" value="— не задан" dim />}
        {b.compass !== null &&
          <Stat label={over ? 'перерасход' : 'запас бюджета'}
            value={money(Math.abs(b.compass))} tone={over ? 'bad' : 'ok'} />}
      </div>
      <div className="bgroup okup">
        <Stat label="себестоимость (для КП)" value={money(b.cost)} />
        <Stat label="экономия (польза заёма)" value={money(b.economy)}
          tone={b.economy > 0 ? 'ok' : b.economy < 0 ? 'bad' : undefined} />
      </div>
      {b.unestimated.length > 0 &&
        <div className="bwarn" title={`нет estimated_cost: ${b.unestimated.join(', ')}`}>
          ▲ {b.unestimated.length} поз. без оценки — план неполон
        </div>}
    </div>
  )
}

function Stat({ label, value, tone, dim }: {
  label: string; value: string; tone?: 'ok' | 'bad'; dim?: boolean
}) {
  return (
    <div className="bstat">
      <div className="blabel">{label}</div>
      <div className={'bval' + (tone ? ` t-${tone}` : '') + (dim ? ' dim' : '')}>{value}</div>
    </div>
  )
}

function Demand({ d, openItem, order, busy }: {
  d: DeficitDemand; openItem: (id: number) => void
  order: (itemId: number, qty: number) => void; busy: boolean
}) {
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
            <th>Разбор</th><th style={{ textAlign: 'right' }}>Склад</th><th /></tr>
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
              <td style={{ textAlign: 'right' }}>
                {ln.to_order > 0 &&
                  <button className="btn sm" disabled={busy}
                    title={`положить ${num(ln.to_order)} ${ln.uom} в черновик-заказ проекта`}
                    onClick={() => order(ln.component_id, ln.to_order)}>＋ в заказ</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
