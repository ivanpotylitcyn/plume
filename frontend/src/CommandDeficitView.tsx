// Витрина волны 7: командный свод (ось Item) — суммарный дефицит по всем активным
// внешним проектам (Σ проектных, без перенеттинга). North-star линзы: «видеть всё к
// закупке разом». Красное наверху. «＋ в закупку» кладёт позицию в черновик-план и
// открывает его. Раскрытие строки показывает разбивку по проектам (откуда нужда).
import { useEffect, useState } from 'react'
import { api, type CommandDeficit, type CommandDeficitRow } from './api'
import { GLYPH, Segment, num } from './status'

export function CommandDeficitView({ openItem, openProcurement }: {
  openItem: (id: number) => void
  openProcurement: (id: number) => void
}) {
  const [data, setData] = useState<CommandDeficit | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = () => {
    setData(null); setErr(null)
    api.commandDeficit().then(setData).catch(e => setErr(String(e)))
  }
  useEffect(reload, [])

  // Мост «свод → закупка»: положить ▲-позицию в черновик-план и открыть его.
  const toProcurement = (itemId: number, qty: number) => {
    setBusy(true)
    api.addToProcurement({ item_id: itemId, qty })
      .then(r => openProcurement(r.procurement_id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err) return <div className="empty">Ошибка: {err}</div>
  if (!data) return <div className="empty">Загрузка…</div>

  const toBuy = data.rows.filter(r => r.to_order > 0).length
  return (
    <div>
      <h1 className="title"><span className="pn">Командный свод</span>{' '}
        <span className="lit">— что закупить по всем проектам</span></h1>
      <div className="subtitle">
        Ось Item · Σ проектных дефицитов (без перенеттинга) · 1 уровень BOM
        {' · к закупке '}<span className="seg">{toBuy}</span>{' поз.'}
      </div>
      {data.rows.length === 0 &&
        <div className="empty">Нет потребностей по активным внешним проектам.</div>}
      {data.rows.length > 0 &&
        <table className="grid">
          <thead>
            <tr>
              <th>Изделие</th><th>Назв.</th><th style={{ textAlign: 'right' }}>Надо</th>
              <th>Разбор</th><th style={{ textAlign: 'right' }}>Закупить</th><th />
            </tr>
          </thead>
          <tbody>
            {data.rows.map(r => (
              <Row key={r.item_id} r={r} busy={busy}
                openItem={openItem} toProcurement={toProcurement} />
            ))}
          </tbody>
        </table>}
    </div>
  )
}

function Row({ r, busy, openItem, toProcurement }: {
  r: CommandDeficitRow; busy: boolean
  openItem: (id: number) => void
  toProcurement: (itemId: number, qty: number) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <tr className={`row s-${r.status}`}>
        <td>
          <span className={`glyph g-${r.status}`}>{GLYPH[r.status]}</span>{' '}
          <a className="link" onClick={() => openItem(r.item_id)}>{r.item_design_item_id}</a>
        </td>
        <td style={{ color: 'var(--fg-dim)' }}>{r.item_description}</td>
        <td className="num">{num(r.need)} {r.uom}</td>
        <td>
          <Segment status="available" value={r.have} />
          <Segment status="on_order" value={r.on_order} />
          <Segment status="to_order" value={r.to_order} />
          {r.by_project.length > 1 &&
            <button className="x" title="разбивка по проектам"
              onClick={() => setOpen(o => !o)}>{open ? '▾' : '▸'}</button>}
        </td>
        <td className="num">{r.to_order > 0 ? num(r.to_order) : '—'}</td>
        <td style={{ textAlign: 'right' }}>
          {r.to_order > 0 &&
            <button className="btn sm" disabled={busy}
              title={`положить ${num(r.to_order)} ${r.uom} в черновик-закупку`}
              onClick={() => toProcurement(r.item_id, r.to_order)}>＋ в закупку</button>}
        </td>
      </tr>
      {open && r.by_project.map(p => (
        <tr key={p.project_id} className="row ghost">
          <td style={{ paddingLeft: 24 }} colSpan={2}>
            <span className={`glyph g-${p.status}`}>{GLYPH[p.status]}</span>{' '}
            <span className="code">{p.project_code}</span>{' '}
            <span className="sub">{p.project_name}</span>
          </td>
          <td className="num">{num(p.need)}</td>
          <td>
            <Segment status="available" value={p.have} />
            <Segment status="on_order" value={p.on_order} />
            <Segment status="to_order" value={p.to_order} />
          </td>
          <td className="num">{p.to_order > 0 ? num(p.to_order) : '—'}</td>
          <td />
        </tr>
      ))}
    </>
  )
}
