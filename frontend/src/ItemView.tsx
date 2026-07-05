// Витрина волны 1: экран изделия = панель свойств + окружение из связей.
// Партии на складе (по проектам, с живым остатком), where-used, состав.
// Волна 5: блок «Отгруженные партии» — куда и по какой накладной ушло заказчику.
// Эта волна: состав (BOM) — редактируемый (добавить/убрать компонент, автосейв кол-ва).
import { useEffect, useState } from 'react'
import { api, type ItemDetail, type ItemRow } from './api'
import { num } from './status'
import { FormHeader, useFormLock } from './FormHeader'
import { AttachmentPanel } from './AttachmentPanel'
import { CommitInput } from './ReceiptView'

const KIND_RU: Record<string, string> = {
  device: 'изделие', component: 'компонент', material: 'материал',
}
const KINDS = ['device', 'component', 'material'] as const
// Codicon вида изделия (§7) по kind: изделие — rocket, компонент — chip, материал — beaker.
const ITEM_ICON: Record<string, string> = {
  device: 'rocket', component: 'chip', material: 'beaker',
}
function itemIcon(d: ItemDetail): string {
  return ITEM_ICON[d.kind] ?? 'chip'
}

export function ItemView({ itemId, items, openItem, onChanged }:
  { itemId: number; items: ItemRow[]; openItem: (id: number) => void
    onChanged?: () => void }) {
  const [d, setD] = useState<ItemDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { unlocked, toggle } = useFormLock(false)   // замок §5: свойства правим открыв

  useEffect(() => {
    setD(null); setErr(null)
    api.item(itemId).then(setD).catch(e => setErr(String(e)))
  }, [itemId])

  // Обёртка мутации состава: ответ = свежий экран изделия, + пинок дереву (where-used).
  const run = (p: Promise<ItemDetail>) => {
    setBusy(true); setErr(null)
    p.then(next => { setD(next); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !d) return <div className="empty">Ошибка: {err}</div>
  if (!d) return <div className="empty">Загрузка…</div>

  // Состав правим у производимых/приборов (или если он уже задан) — у покупных BOM нет.
  const composable = d.is_manufactured || d.kind === 'device' || d.bom.length > 0

  return (
    <div>
      <FormHeader
        name={d.name}
        meta={<>
          <span className={`ci ci-${itemIcon(d)}`} style={{ fontSize: 12, marginRight: 5 }} />
          {d.code} · {KIND_RU[d.kind] ?? d.kind}{d.is_manufactured ? ' · производимое' : ''} · {d.uom}
          {d.estimated_cost != null && <> · оценка {d.estimated_cost} ₽</>}
        </>}
        unlocked={unlocked} onToggleLock={toggle} error={err}
      />
      <dl className="props">
        <dt>Артикул</dt>
        <dd>{unlocked
          ? <CommitInput value={d.code} width={160} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { code: v }))}
              validate={v => v.trim() !== ''} />
          : d.code}</dd>
        <dt>Название</dt>
        <dd>{unlocked
          ? <CommitInput value={d.name} width={260} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { name: v }))}
              validate={v => v.trim() !== ''} />
          : d.name}</dd>
        <dt>Вид</dt>
        <dd>{unlocked
          ? <select className="lot-sel" value={d.kind} disabled={busy}
              onChange={e => run(api.updateItem(d.id, { kind: e.target.value }))}>
              {KINDS.map(k => <option key={k} value={k}>{KIND_RU[k]}</option>)}
            </select>
          : (KIND_RU[d.kind] ?? d.kind)}</dd>
        <dt>Производимое</dt>
        <dd>{unlocked
          ? <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={d.is_manufactured} disabled={busy}
                onChange={e => run(api.updateItem(d.id, { is_manufactured: e.target.checked }))} />
              {d.is_manufactured ? 'да' : 'нет'}
            </label>
          : (d.is_manufactured ? 'да' : 'нет')}</dd>
        <dt>Ед. изм.</dt>
        <dd>{unlocked
          ? <CommitInput value={d.uom} width={80} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { uom: v }))} />
          : d.uom}</dd>
        <dt>Оценка</dt>
        <dd>{unlocked
          ? <><CommitInput value={d.estimated_cost != null ? String(d.estimated_cost) : ''}
              width={100} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { estimated_cost: v.trim() === '' ? null : Number(v) }))}
              validate={v => v.trim() === '' || Number(v) >= 0} /> ₽</>
          : (d.estimated_cost != null ? `${d.estimated_cost} ₽` : '—')}</dd>
      </dl>

      <div className="section-h">Где применяется
        <span className="hint">вхождений {d.where_used.length}</span></div>
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

      {composable && <>
        <div className="section-h">Состав (BOM)
          <span className="hint">компонентов {d.bom.length}</span></div>
        {d.bom.length === 0 && <div style={{ color: 'var(--fg-dim)' }}>Состав пуст — добавьте компонент ниже.</div>}
        {d.bom.length > 0 &&
          <table className="grid">
            <thead><tr><th>Компонент</th><th>Назв.</th>
              <th style={{ textAlign: 'right' }}>Кол-во</th><th /></tr></thead>
            <tbody>{d.bom.map(b => (
              <tr key={b.id} className="row">
                <td><a className="link" onClick={() => openItem(b.component_id)}>{b.component_code}</a></td>
                <td style={{ color: 'var(--fg-dim)' }}>{b.component_name}</td>
                <td className="num">
                  <CommitInput value={String(b.qty)} width={56} disabled={busy}
                    onCommit={v => run(api.updateBomLine(b.id, { qty: Number(v) }))}
                    validate={v => Number(v) > 0} /> {b.component_uom}
                </td>
                <td style={{ textAlign: 'right' }}>
                  <button className="x" title="убрать компонент из состава" disabled={busy}
                    onClick={() => run(api.deleteBomLine(b.id))}>×</button>
                </td>
              </tr>))}</tbody>
          </table>}
        <AddComponent items={items} parentId={d.id} bom={d.bom} busy={busy}
          add={(component_id, qty) => run(api.addBomLine(d.id, { component_id, qty }))} />
        {err && <div className="anomaly">{err}</div>}
      </>}

      <div className="section-h">Партии на складе
        <span className="hint">партий {d.lots.length} · живых {d.lots.filter(l => l.live_qty > 0).length}</span></div>
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
        <span className="hint">отгрузок {d.shipments.length}</span></div>
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

// Добавить компонент в состав: пикер изделий (кроме самого и уже добавленных) + кол-во.
// Циклы/дубли ловит бэкенд — здесь только базовый отсев для чистого списка.
function AddComponent({ items, parentId, bom, busy, add }: {
  items: ItemRow[]; parentId: number; bom: ItemDetail['bom']; busy: boolean
  add: (componentId: number, qty: number) => void
}) {
  const taken = new Set(bom.map(b => b.component_id))
  const options = items.filter(i => i.id !== parentId && !taken.has(i.id))
  const [componentId, setComponentId] = useState<number | ''>('')
  const [qty, setQty] = useState('1')
  useEffect(() => { setComponentId(options[0]?.id ?? '') }, [options.map(o => o.id).join()])

  const submit = () => {
    const n = Number(qty)
    if (!componentId || !(n > 0)) return
    add(componentId, n)
  }

  if (options.length === 0)
    return <div className="kit-actions" style={{ marginTop: 10, color: 'var(--fg-dim)', fontSize: 12 }}>
      ＋ компонент: нет доступных изделий.</div>
  return (
    <div className="kit-actions" style={{ marginTop: 10 }}>
      <span style={{ color: 'var(--fg-dim)', fontSize: 12 }}>＋ компонент</span>
      <select className="lot-sel" value={componentId} disabled={busy}
        onChange={e => setComponentId(Number(e.target.value))}>
        {options.map(i => <option key={i.id} value={i.id}>{i.code} — {i.name}</option>)}
      </select>
      <input className="qty-in" value={qty} disabled={busy}
        onChange={e => setQty(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit() }} />
      <button className="btn sm" disabled={busy} onClick={submit}>добавить</button>
    </div>
  )
}
