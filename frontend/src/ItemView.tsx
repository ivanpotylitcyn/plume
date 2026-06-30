// Витрина волны 1: экран изделия = панель свойств + окружение из связей.
// Карта остатков по складам-проектам (north-star), where-used, лоты. Read-only.
import { useEffect, useState } from 'react'
import { api, type ItemDetail } from './api'
import { num } from './status'

const KIND_RU: Record<string, string> = {
  device: 'изделие', component: 'компонент', material: 'материал',
}
const PROJ_KIND_RU: Record<string, string> = {
  external: 'проект', internal_stock: 'свой склад (белые)',
  internal_writeoff: 'неучтённые (серые)',
}

export function ItemView({ itemId, openItem }:
  { itemId: number; openItem: (id: number) => void }) {
  const [d, setD] = useState<ItemDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setD(null); setErr(null)
    api.item(itemId).then(setD).catch(e => setErr(String(e)))
  }, [itemId])

  if (err) return <div className="empty">Ошибка: {err}</div>
  if (!d) return <div className="empty">Загрузка…</div>

  return (
    <div>
      <h1 className="title">{d.code} — {d.name}</h1>
      <dl className="props">
        <dt>Вид</dt><dd>{KIND_RU[d.kind] ?? d.kind}{d.is_manufactured ? ' · производимое' : ''}</dd>
        <dt>Ед. изм.</dt><dd>{d.uom}</dd>
        <dt>Оценка</dt><dd>{d.estimated_cost != null ? `${d.estimated_cost} ₽` : '—'}</dd>
      </dl>

      <div className="section-h">Карта остатков
        <span className="hint">где этот Item лежит по всем складам-проектам</span></div>
      {d.stock_map.rows.length === 0
        ? <div style={{ color: 'var(--fg-dim)' }}>Нет доступных остатков</div>
        : <table className="grid">
            <thead><tr><th>Склад-проект</th><th>Вид</th>
              <th style={{ textAlign: 'right' }}>Доступно</th></tr></thead>
            <tbody>
              {d.stock_map.rows.map(r => (
                <tr key={r.project_id} className="row s-available">
                  <td>{r.project_code} <span style={{ color: 'var(--fg-dim)' }}>{r.project_name}</span></td>
                  <td className="kind-chip">{PROJ_KIND_RU[r.project_kind] ?? r.project_kind}</td>
                  <td className="num">{num(r.available)} {d.uom}</td>
                </tr>
              ))}
            </tbody>
          </table>}

      <div className="section-h">Где применяется
        <span className="hint">where-used по составу</span></div>
      {d.where_used.length === 0
        ? <div style={{ color: 'var(--fg-dim)' }}>Нигде (не входит в BOM)</div>
        : <table className="grid">
            <thead><tr><th>Изделие</th><th>Назв.</th>
              <th style={{ textAlign: 'right' }}>Кол-во</th></tr></thead>
            <tbody>{d.where_used.map(w => (
              <tr key={w.parent_id} className="row">
                <td><a className="link" onClick={() => openItem(w.parent_id)}>{w.parent_code}</a></td>
                <td style={{ color: 'var(--fg-dim)' }}>{w.parent_name}</td>
                <td className="num">{num(w.qty)}</td>
              </tr>))}</tbody>
          </table>}

      {d.bom.length > 0 && <>
        <div className="section-h">Состав (BOM)</div>
        <table className="grid">
          <thead><tr><th>Компонент</th><th>Назв.</th>
            <th style={{ textAlign: 'right' }}>Кол-во</th></tr></thead>
          <tbody>{d.bom.map(b => (
            <tr key={b.component_id} className="row">
              <td><a className="link" onClick={() => openItem(b.component_id)}>{b.component_code}</a></td>
              <td style={{ color: 'var(--fg-dim)' }}>{b.component_name}</td>
              <td className="num">{num(b.qty)}</td>
            </tr>))}</tbody>
        </table>
      </>}

      <div className="section-h">Партии на складе</div>
      {d.lots.length === 0
        ? <div style={{ color: 'var(--fg-dim)' }}>Нет партий</div>
        : <table className="grid">
            <thead><tr><th>Lot</th><th>Проект</th><th>Origin</th>
              <th style={{ textAlign: 'right' }}>Рожд.</th>
              <th style={{ textAlign: 'right' }}>Остаток</th>
              <th>Зав. №</th></tr></thead>
            <tbody>{d.lots.map(l => (
              <tr key={l.id} className="row">
                <td>#{l.id}</td><td>{l.project_code}</td><td className="kind-chip">{l.origin}</td>
                <td className="num">{num(l.qty_born)}</td>
                <td className="num">{num(l.live_qty)}</td>
                <td style={{ color: 'var(--fg-dim)' }}>{l.serial_number || '—'}</td>
              </tr>))}</tbody>
          </table>}
    </div>
  )
}
