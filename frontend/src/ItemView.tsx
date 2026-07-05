// Витрина волны 1: экран изделия = панель свойств + окружение из связей.
// Партии на складе (по проектам, с живым остатком), where-used, состав. Read-only.
// Волна 5: блок «Отгруженные партии» — куда и по какой накладной ушло заказчику.
import { useEffect, useState } from 'react'
import { api, type ItemDetail } from './api'
import { num } from './status'
import { FormHeader } from './FormHeader'
import { AttachmentPanel } from './AttachmentPanel'

const KIND_RU: Record<string, string> = {
  device: 'изделие', component: 'компонент', material: 'материал',
}
// Codicon вида изделия (§7): tools — производимое, package — прибор, circuit-board — прочее.
function itemIcon(d: ItemDetail): string {
  return d.is_manufactured ? 'tools' : d.kind === 'device' ? 'package' : 'circuit-board'
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
      <FormHeader
        name={d.name}
        meta={<>
          <span className={`ci ci-${itemIcon(d)}`} style={{ fontSize: 12, marginRight: 5 }} />
          {d.code} · {KIND_RU[d.kind] ?? d.kind}{d.is_manufactured ? ' · производимое' : ''} · {d.uom}
          {d.estimated_cost != null && <> · оценка {d.estimated_cost} ₽</>}
        </>}
      />
      <dl className="props">
        <dt>Вид</dt><dd>{KIND_RU[d.kind] ?? d.kind}{d.is_manufactured ? ' · производимое' : ''}</dd>
        <dt>Ед. изм.</dt><dd>{d.uom}</dd>
        <dt>Оценка</dt><dd>{d.estimated_cost != null ? `${d.estimated_cost} ₽` : '—'}</dd>
      </dl>

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

      <div className="section-h">Партии на складе
        <span className="hint">где лежит по проектам · рождённое / живой остаток</span></div>
      {d.lots.length === 0
        ? <div style={{ color: 'var(--fg-dim)' }}>Нет партий</div>
        : <table className="grid">
            <thead><tr><th>Lot</th><th>Проект</th><th>Origin</th>
              <th style={{ textAlign: 'right' }}>Рожд.</th>
              <th style={{ textAlign: 'right' }}>Остаток</th>
              <th>Зав. №</th></tr></thead>
            <tbody>{d.lots.map(l => (
              <tr key={l.id} className={'row' + (l.live_qty > 0 ? ' s-available' : '')}>
                <td>#{l.id}</td><td>{l.project_code}</td><td className="kind-chip">{l.origin}</td>
                <td className="num">{num(l.qty_born)}</td>
                <td className="num">{num(l.live_qty)}</td>
                <td style={{ color: 'var(--fg-dim)' }}>{l.serial_number || '—'}</td>
              </tr>))}</tbody>
          </table>}

      <div className="section-h">Отгруженные партии
        <span className="hint">куда ушло заказчику · по накладным</span></div>
      {d.shipments.length === 0
        ? <div style={{ color: 'var(--fg-dim)' }}>Пока ничего не отгружено</div>
        : <table className="grid">
            <thead><tr><th>Накладная</th><th>Дата</th><th>Проект</th><th>Lot</th>
              <th style={{ textAlign: 'right' }}>Кол-во</th>
              <th>Имя в накладной</th></tr></thead>
            <tbody>{d.shipments.map((s, i) => (
              <tr key={`${s.transfer_id}-${s.lot_id}-${i}`} className="row">
                <td>
                  <span className={`glyph ${s.posted ? 'g-lock' : 'g-on_order'}`}>{s.posted ? '🔒' : '●'}</span>{' '}
                  {s.number}
                </td>
                <td style={{ color: 'var(--fg-dim)' }}>{s.date}</td>
                <td>{s.project_code}</td>
                <td>#{s.lot_id}</td>
                <td className="num">{num(s.qty)} {d.uom}</td>
                <td style={{ color: 'var(--fg-dim)' }}>{s.display_name || '—'}</td>
              </tr>))}</tbody>
          </table>}

      <AttachmentPanel ownerType="item" ownerId={d.id} />
    </div>
  )
}
