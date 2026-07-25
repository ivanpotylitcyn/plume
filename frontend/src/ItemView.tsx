// Витрина волны 1: экран изделия = панель свойств + окружение из связей.
// Партии на складе (по проектам, с живым остатком), where-used, состав.
// Волна 5: блок «Отгруженные партии» — куда и по какой накладной ушло заказчику.
// Эта волна: состав (BOM) — редактируемый (добавить/убрать компонент, автосейв кол-ва).
import { useEffect, useMemo, useState } from 'react'
import { api, type ItemDetail, type ItemRow, type Category, type RollupResult } from './api'
import { num, ItemGlyph } from './status'
import { FormHeader, useFormLock } from './FormHeader'
import { ItemPicker } from './Picker'
import { AttachmentPanel } from './AttachmentPanel'
import { CommitInput } from './ReceiptView'

export function ItemView({ itemId, items, isNew, openItem, onChanged, onDeleted }:
  { itemId: number; items: ItemRow[]; isNew: boolean; openItem: (id: number) => void
    onChanged?: () => void; onDeleted?: () => void }) {
  const [d, setD] = useState<ItemDetail | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rollup, setRollup] = useState<RollupResult | null>(null)
  const { unlocked, toggle } = useFormLock(itemId, isNew)   // §5: существующее — в просмотре

  useEffect(() => {
    setD(null); setErr(null); setRollup(null)
    api.item(itemId).then(setD).catch(e => setErr(String(e)))
  }, [itemId])
  useEffect(() => { api.categories().then(setCategories).catch(() => {}) }, [])

  // Обёртка мутации состава: ответ = свежий экран изделия, + пинок дереву (where-used).
  const run = (p: Promise<ItemDetail>) => {
    setBusy(true); setErr(null)
    p.then(next => { setD(next); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Пересчёт оценочной стоимости роллапом по BOM (волна 15). Ответ = свежий экран
  // изделия + сводка `updated`/`incomplete` — показываем под кнопкой.
  const recalc = () => {
    setBusy(true); setErr(null); setRollup(null)
    api.recalcCost(itemId)
      .then(next => { const { rollup, ...det } = next; setD(det); setRollup(rollup); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Удаление изделия (WAVE14 Ф2) под замком: confirm + friendly-guard бэка → сброс выбора.
  const del = () => {
    if (!d || !confirm('Удалить изделие из справочника? Действие необратимо.')) return
    setBusy(true); setErr(null)
    api.deleteItem(d.id).then(() => { onChanged?.(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !d) return <div className="empty">Ошибка: {err}</div>
  if (!d) return <div className="empty">Загрузка…</div>

  // Состав правим у производимых (или если он уже задан) — у покупных BOM нет.
  const composable = d.native || d.bom.length > 0

  // Фиксация (волна 17) — ровно как у StockDocument (см. ReceiptView): `d.locked` =
  // изделие зафиксировано (форма read-only, бэк гейтит мутации), чип вместо замка.
  // `locked` = фиксация ИЛИ закрытый личный мягкий замок → всё в форме read-only.
  const fixed = d.locked
  const locked = fixed || !unlocked
  // Матрица synced×locked (Ф3a): библиотечное (`synced`) расфиксированное — правится
  // ТОЛЬКО оценочная стоимость; остальные поля приходят из библиотеки (read-only).
  // `metaLocked` запирает «библиотечные» свойства; Оценка гейтится обычным `locked`.
  const metaLocked = locked || d.synced

  return (
    <div className={unlocked && !fixed ? '' : 'form-locked'}>
      <FormHeader
        code={d.code}
        meta={<>
          {d.category.description}{d.native ? ' · производимое' : ''} · {d.uom}
          {!d.native && <> · {d.synced ? 'библиотечное' : 'ручное'}</>}
          {d.synced && !locked && <span className="sub"> (правится только цена)</span>}
          {d.temperature && <> · {d.temperature}</>}
          {' · '}<span className={d.used ? 's-available' : ''}>{d.used ? 'используется' : 'спящий'}</span>
          {d.estimated_cost != null && <> · оценка {d.estimated_cost} ₽</>}
        </>}
        unlocked={unlocked} onToggleLock={toggle} error={err}
        fixed={fixed}
        onFixate={d.native ? () => run(api.lockItem(d.id)) : undefined}
        fixateTitle="Зафиксировать: заморозить состав (BOM) и свойства изделия"
        onUnfix={() => { if (confirm('Расфиксировать изделие? Форма снова станет редактируемой.')) run(api.unlockItem(d.id)) }}
        onDelete={del}
        action={d.native ? { onClick: recalc, label: 'Пересчитать', icon: 'ci-credit-card',
          title: 'Пересчитать стоимость: оценка = Σ(компонент × кол-во), рекурсивно по BOM до листьев',
          disabled: busy } : undefined}
      >
      <dl className="props">
        <dt>Код</dt>
        <dd>{!metaLocked
          ? <CommitInput value={d.code} width={160} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { code: v }))}
              validate={v => v.trim() !== ''} />
          : d.code}</dd>
        <dt>Описание</dt>
        <dd>{!metaLocked
          ? <CommitInput value={d.description} width={260} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { description: v }))}
              validate={v => v.trim() !== ''} />
          : d.description}</dd>
        <dt>Категория</dt>
        <dd>{!metaLocked
          ? <select className="lot-sel" value={d.category.id} disabled={busy}
              onChange={e => run(api.updateItem(d.id, { category_id: Number(e.target.value) }))}>
              {categories.map(c => <option key={c.id} value={c.id}>{c.description}</option>)}
            </select>
          : d.category.description}</dd>
        <dt>Производимое</dt>
        <dd>{!metaLocked
          ? <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={d.native} disabled={busy}
                onChange={e => run(api.updateItem(d.id, { native: e.target.checked }))} />
              {d.native ? 'да' : 'нет'}
            </label>
          : (d.native ? 'да' : 'нет')}</dd>
        <dt>Температурный диапазон</dt>
        <dd>{!metaLocked
          ? <CommitInput value={d.temperature} width={160} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { temperature: v }))} />
          : (d.temperature || '—')}</dd>
        <dt>Ед. изм.</dt>
        <dd>{!metaLocked
          ? <CommitInput value={d.uom} width={80} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { uom: v }))} />
          : d.uom}</dd>
        <dt>Оценка</dt>
        <dd>{!locked
          ? <><CommitInput value={d.estimated_cost != null ? String(d.estimated_cost) : ''}
              width={100} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { estimated_cost: v.trim() === '' ? null : Number(v) }))}
              validate={v => v.trim() === '' || Number(v) >= 0} /> ₽</>
          : (d.estimated_cost != null ? `${d.estimated_cost} ₽` : '—')}</dd>
      </dl>
      </FormHeader>

      {/* Фиксация Изделия вернулась в шапку (единый контрол, как у закупок/документов):
          «Зафиксировать»/«Расфиксировать» через onFixate/onUnfix FormHeader — только у
          Изделий (native). У Компонентов кнопки фиксации нет: их замок из UI недостижим,
          синк держит их расфиксированными (инвариант `synced ⟹ not locked`). Правка
          библиотечного (synced) — только цена (матрица `metaLocked`); `synced` руками не
          снять. Кнопка «Пересчитать стоимость» переехала в правую колонку шапки (action);
          здесь остаётся только сводка результата после клика. */}

      {d.native && rollup && <div className="kit-actions" style={{ marginBottom: 4 }}>
        <span style={{ color: 'var(--fg-dim)', fontSize: 12 }}>
          оценка {rollup.estimated_cost != null ? `${rollup.estimated_cost} ₽` : '—'} ·
          переоценено узлов {rollup.updated.length}
          {rollup.incomplete.length > 0 &&
            <span className="anomaly"> · без цены: {rollup.incomplete.join(', ')}</span>}
        </span>
      </div>}

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
                <td style={{ color: 'var(--fg-dim)' }}>{w.parent_description}</td>
                <td className="num">{num(w.qty)}</td>
              </tr>))}</tbody>
          </table>}

      {composable && <>
        <div className="section-h">Состав (BOM)
          <span className="hint">компонентов {d.bom.length}</span></div>
        {d.bom.length === 0 && <div style={{ color: 'var(--fg-dim)' }}>
          {locked ? 'Состав пуст.' : 'Состав пуст — добавьте компонент ниже.'}</div>}
        {d.bom.length > 0 &&
          <table className="grid">
            <thead><tr><th /><th>Компонент</th><th>Описание</th>
              <th style={{ textAlign: 'right' }}>Кол-во</th>{!locked && <th />}</tr></thead>
            <tbody>{d.bom.map(b => (
              <tr key={b.id} className="row">
                <td><ItemGlyph native={b.component_native} synced={b.component_synced} locked={b.component_locked} /></td>
                <td><a className="link" onClick={() => openItem(b.component_id)}>{b.component_code}</a></td>
                <td style={{ color: 'var(--fg-dim)' }}>
                  <span className="cell-ellip" title={b.component_description}>{b.component_description}</span></td>
                <td className="num">
                  {!locked
                    ? <><CommitInput value={String(b.qty)} width={56} disabled={busy}
                        onCommit={v => run(api.updateBomLine(b.id, { qty: Number(v) }))}
                        validate={v => Number(v) > 0} /> {b.component_uom}</>
                    : <>{num(b.qty)} {b.component_uom}</>}
                </td>
                {!locked && <td style={{ textAlign: 'right' }}>
                  <button className="x" title="убрать компонент из состава" disabled={busy}
                    onClick={() => run(api.deleteBomLine(b.id))}>×</button>
                </td>}
              </tr>))}</tbody>
          </table>}
        {/* Добавление компонента — только когда форма редактируема (мягкий замок открыт
            и не зафиксировано). Под замком/фиксацией состав = read-only список. */}
        {!locked && <AddComponent items={items} parentId={d.id} bom={d.bom} busy={busy}
          add={(component_id, qty) => run(api.addBomLine(d.id, { component_id, qty }))} />}
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
              <th>Part number</th><th>Название</th></tr></thead>
            <tbody>{d.lots.map(l => (
              <tr key={l.id} className={'row' + (l.live_qty > 0 ? ' s-available' : '')}>
                <td>#{l.id}</td><td>{l.project_code}</td><td className="kind-chip">{l.origin}</td>
                <td className="num">{num(l.qty_born)}</td>
                <td className="num">{num(l.live_qty)}</td>
                <td style={{ color: 'var(--fg-dim)' }}>{l.part_number || '—'}</td>
                <td style={{ color: 'var(--fg-dim)' }}>{l.lot_name || '—'}</td>
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
                  <span className={`glyph ${s.locked ? 'g-lock' : 'g-on_order'}`}>{s.locked ? '🔒' : '●'}</span>{' '}
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
// Ф3 (волна 16) сделала здесь первый type-ahead; Ф2 (волна 19) вынесла его в общий
// `ItemPicker` — этот блок стал тонкой обёрткой: отсев кандидатов + кол-во + кнопка.
// Пока компонент не выбран — кнопка заблокирована.
function AddComponent({ items, parentId, bom, busy, add }: {
  items: ItemRow[]; parentId: number; bom: ItemDetail['bom']; busy: boolean
  add: (componentId: number, qty: number) => void
}) {
  const options = useMemo(() => {
    const taken = new Set(bom.map(b => b.component_id))
    return items.filter(i => i.id !== parentId && !taken.has(i.id))
  }, [items, parentId, bom])
  const [componentId, setComponentId] = useState<number | ''>('')
  const [qty, setQty] = useState('1')

  const submit = () => {
    const n = Number(qty)
    if (!componentId || !(n > 0)) return
    add(componentId, n)
    setComponentId('')
  }

  if (options.length === 0)
    return <div className="kit-actions" style={{ marginTop: 10, color: 'var(--fg-dim)', fontSize: 12 }}>
      ＋ компонент: нет доступных изделий.</div>
  return (
    <div className="kit-actions" style={{ marginTop: 10 }}>
      <span style={{ color: 'var(--fg-dim)', fontSize: 12 }}>＋ компонент</span>
      <ItemPicker items={options} value={componentId} onPick={setComponentId}
        disabled={busy} width={240} onEnter={submit}
        notFound="ничего не найдено — компонент должен быть в справочнике изделий." />
      <input className="qty-in" value={qty} disabled={busy}
        onChange={e => setQty(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && componentId) submit() }} />
      <button className="btn sm" disabled={busy || !componentId} onClick={submit}>добавить</button>
    </div>
  )
}
