// Витрина волны 1: экран изделия = панель свойств + окружение из связей.
// Партии на складе (по проектам, с живым остатком), where-used, состав.
// Волна 19 (Ф12a): форма по канону §13 — табы Состав · Применение · Склад ·
// Движения · Файлы. «Движения» пришли на смену узкому «Отгружено»: вся лента
// ордеров, коснувшихся изделия (рождение партий + расходы), `engine.item_movements`.
import { useEffect, useMemo, useState } from 'react'
import { api, type ItemDetail, type ItemRow, type Category, type RollupResult } from './api'
import { num, money, count, ItemGlyph, StatusGlyph } from './status'
import { ORDER_LABEL, type OrderKind } from './orders'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { ItemPicker } from './Picker'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { CommitInput } from './ReceiptView'

export function ItemView({ itemId, items, isNew, openItem, openOrder, onChanged, onDeleted }:
  { itemId: number; items: ItemRow[]; isNew: boolean; openItem: (id: number) => void
    openOrder: (kind: OrderKind, id: number) => void   // лента движений кликабельна (§8)
    onChanged?: () => void; onDeleted?: () => void }) {
  const [d, setD] = useState<ItemDetail | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rollup, setRollup] = useState<RollupResult | null>(null)
  const { unlocked, toggle } = useFormLock(itemId, isNew)   // §5: существующее — в просмотре
  const att = useAttachments('item', itemId)   // загрузка — команда шапки (§13.8)

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

  // Табы (§13.7): порядок — от сути изделия к его следам на складе. Глифы взяты у
  // РЕЖИМОВ навигации (§2): состав = `chip` (Компоненты), применение = `rocket`
  // (Изделия), склад = `layers` (Склады), отгружено = `notebook` (Ордера) — одна
  // сущность носит один знак, где бы ни встретилась. Счётчиков в табах нет: числа
  // ушли в мету. «Состав» появляется только там, где состав вообще бывает.
  const tabs: FormTab[] = []
  if (composable) tabs.push({
    key: 'bom', label: 'Состав', icon: 'chip',
    content: <>
      {d.bom.length === 0 && <div className="tab-empty">
        {locked ? 'Состав пуст.' : 'Состав пуст — добавьте компонент ниже.'}</div>}
      {d.bom.length > 0 &&
        <table className="grid">
          <thead><tr><th className="gl" /><th className="c-key">Компонент</th><th>Описание</th>
            <th style={{ textAlign: 'right' }}>Кол-во</th><th className="uom">Ед.</th>
            {!locked && <th className="act" />}</tr></thead>
          <tbody>{d.bom.map(b => (
            <tr key={b.id} className="row">
              <td className="gl"><ItemGlyph native={b.component_native} synced={b.component_synced} locked={b.component_locked} /></td>
              <td className="c-key">
                <a className="link" onClick={() => openItem(b.component_id)}>{b.component_code}</a></td>
              <td style={{ color: 'var(--fg-dim)' }}>
                <span className="cell-ellip" title={b.component_description}>{b.component_description}</span></td>
              <td className="num">
                {!locked
                  ? <CommitInput value={String(b.qty)} width={56} disabled={busy}
                      onCommit={v => run(api.updateBomLine(b.id, { qty: Number(v) }))}
                      validate={v => Number(v) > 0} />
                  : num(b.qty)}
              </td>
              <td className="uom">{b.component_uom}</td>
              {!locked && <td className="act">
                <button className="fh-ctl icon fh-del" title="Убрать компонент из состава"
                  disabled={busy} onClick={() => run(api.deleteBomLine(b.id))}>
                  <span className="ci ci-trash" /></button>
              </td>}
            </tr>))}</tbody>
        </table>}
      {/* Добавление компонента — только когда форма редактируема (мягкий замок открыт
          и не зафиксировано). Под замком/фиксацией состав = read-only список. */}
      {!locked && <AddComponent items={items} parentId={d.id} bom={d.bom} busy={busy}
        add={(component_id, qty) => run(api.addBomLine(d.id, { component_id, qty }))} />}
    </>,
  })
  tabs.push({
    key: 'where', label: 'Применение', icon: 'rocket',
    content: d.where_used.length === 0
      ? <div className="tab-empty">Нигде (не входит в BOM)</div>
      : <table className="grid">
          <thead><tr><th className="gl" /><th className="c-key">Изделие</th><th>Описание</th>
            <th style={{ textAlign: 'right' }}>Кол-во</th>
            <th className="uom">Ед.</th></tr></thead>
          <tbody>{d.where_used.map(w => (
            <tr key={w.parent_id} className="row">
              {/* Глиф родителя — по его собственным осям (Ф3a: ровно один по режиму). */}
              <td className="gl"><ItemGlyph native={w.parent_native} synced={w.parent_synced}
                locked={w.parent_locked} /></td>
              <td className="c-key">
                <a className="link" onClick={() => openItem(w.parent_id)}>{w.parent_code}</a></td>
              <td style={{ color: 'var(--fg-dim)' }}>{w.parent_description}</td>
              <td className="num">{num(w.qty)}</td>
              <td className="uom">{d.uom}</td>
            </tr>))}</tbody>
        </table>,
  })
  tabs.push({
    key: 'lots', label: 'Склад', icon: 'layers',
    content: d.lots.length === 0
      ? <div className="tab-empty">Нет партий</div>
      : <table className="grid">
          <thead><tr><th>Lot</th><th>Проект</th><th>Origin</th>
            <th style={{ textAlign: 'right' }}>Рожд.</th>
            <th style={{ textAlign: 'right' }}>Остаток</th>
            <th>Part number</th><th>Название</th>
            <th className="uom">Ед.</th></tr></thead>
          <tbody>{d.lots.map(l => (
            <tr key={l.id} className={'row' + (l.live_qty > 0 ? ' s-available' : '')}>
              <td>#{l.id}</td><td>{l.project_code}</td><td className="kind-chip">{l.origin}</td>
              <td className="num">{num(l.qty_born)}</td>
              <td className="num">{num(l.live_qty)}</td>
              <td style={{ color: 'var(--fg-dim)' }}>{l.part_number || '—'}</td>
              <td style={{ color: 'var(--fg-dim)' }}>{l.lot_name || '—'}</td>
              <td className="uom">{d.uom}</td>
            </tr>))}</tbody>
        </table>,
  })
  // «Движения» (2026-07-26, вместо узкого «Отгружено»): ВСЕ ордера, коснувшиеся
  // изделия — рождение партии (поставка/комплектация/инвентаризация/требование) и её
  // движения (пайка, передача, списание, перемещение). Знак сохраняем: расход виден
  // расходом. Ордер кликабелен (§8), глиф — ось фиксации документа.
  tabs.push({
    key: 'moves', label: 'Движения', icon: 'notebook',
    content: d.movements.length === 0
      ? <div className="tab-empty">Изделие ещё не двигалось по складу</div>
      : <table className="grid">
          <thead><tr><th className="gl" /><th className="c-key">Ордер</th><th>Вид</th><th>Дата</th><th>Проект</th>
            <th>Партия</th>
            <th style={{ textAlign: 'right' }}>Кол-во</th>
            <th className="uom">Ед.</th></tr></thead>
          <tbody>{d.movements.map((m, i) => (
            <tr key={`${m.kind}-${m.document_id}-${m.lot_id}-${i}`}
              className={'row ' + (m.qty < 0 ? 's-to_order' : 's-available')}>
              <td className="gl"><StatusGlyph locked={m.locked} /></td>
              <td className="c-key"><a className="link" onClick={() => openOrder(m.kind as OrderKind, m.document_id)}>
                {m.code || m.number || `${ORDER_LABEL[m.kind as OrderKind]} #${m.document_id}`}</a></td>
              <td style={{ color: 'var(--fg-dim)' }}>
                {ORDER_LABEL[m.kind as OrderKind] ?? m.kind}
                {m.event === 'born' && <span className="hint">партия рождена</span>}</td>
              <td style={{ color: 'var(--fg-dim)' }}>{m.date ?? '—'}</td>
              <td>{m.project_code}</td>
              <td style={{ color: 'var(--fg-dim)' }}>#{m.lot_id}{m.lot_name && ` · ${m.lot_name}`}</td>
              <td className="num">{m.qty > 0 ? `+${num(m.qty)}` : num(m.qty)}</td>
              <td className="uom">{d.uom}</td>
            </tr>))}</tbody>
        </table>,
  })
  tabs.push({
    key: 'files', label: 'Файлы', icon: 'files',
    content: <AttachmentList att={att} locked={locked} />,
  })

  return (
    <FormShell
      id={d.id} code={d.code} entity="изделие" locked={locked} error={err}
      // Мета (§13.6) — СЧЁТ ПО ТАБАМ в их порядке, число впереди подписи («17
      // компонентов · 2 вхождения»): читается фразой. Поля не повторяет, глифа нет
      // (он есть в списке и однозначно читается по доступным командам).
      // «Спящий» — не счётчик: это «ни одной живой ссылки, можно удалять» (шире
      // вхождений — сюда же лоты, строки заказов, потребность, комплектации).
      // Обратное («используется») молчит: об этом говорят сами счётчики.
      meta={<>
        {composable && <>{count(d.bom.length, 'компонент', 'компонента', 'компонентов')} · </>}
        {count(d.where_used.length, 'вхождение', 'вхождения', 'вхождений')} ·{' '}
        {count(d.lots.length, 'партия', 'партии', 'партий')} ·{' '}
        {count(d.movements.length, 'движение', 'движения', 'движений')} ·{' '}
        {count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
        {!d.used && <span className="sub"> · спящий</span>}
        {d.synced && !locked && <span className="sub"> · правится только цена</span>}
        {d.native && rollup && <span className="sub">
          {' · '}переоценено узлов {rollup.updated.length}
          {rollup.incomplete.length > 0 &&
            <span className="anomaly"> · без цены: {rollup.incomplete.join(', ')}</span>}
        </span>}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={d.native ? () => run(api.lockItem(d.id)) : undefined}
      fixateTitle="Зафиксировать: заморозить состав (BOM) и свойства изделия"
      onUnfix={() => { if (confirm('Расфиксировать изделие? Форма снова станет редактируемой.')) run(api.unlockItem(d.id)) }}
      onDelete={del}
      // Фиксация — только у Изделий (native): у Компонентов замок из UI недостижим,
      // синк держит их расфиксированными (инвариант `synced ⟹ not locked`).
      actions={[
        ...(d.native ? [{ onClick: recalc, label: 'Переоценить', icon: 'ci-symbol-operator',
          title: 'Пересчитать стоимость: оценка = Σ(компонент × кол-во), рекурсивно по BOM до листьев',
          disabled: busy }] : []),
        { onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
          title: 'Загрузить файл (datasheet, КД) — появится в табе «Файлы»',
          disabled: att.busy },
      ]}
      fields={<>
        <dt>Код</dt>
        <dd>{!metaLocked
          ? <CommitInput value={d.code} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { code: v }))}
              validate={v => v.trim() !== ''} />
          : d.code}</dd>
        <dt>Описание</dt>
        {/* Единственное длинное поле шапки (§13.3) — описание бывает в строку и больше. */}
        <dd className="wide">{!metaLocked
          ? <CommitInput value={d.description} disabled={busy}
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
        {/* Поля «Производимое» нет (снято 2026-07-26): `native` — не свойство на правку,
            а ОСЬ РЕЖИМА (Изделия / Компоненты). Заводится вместе с сущностью в том
            режиме, где нажали «＋ Новое», и дальше не переключается. */}
        <dt>Температура</dt>
        <dd>{!metaLocked
          ? <CommitInput value={d.temperature} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { temperature: v }))} />
          : (d.temperature || '—')}</dd>
        <dt>Единицы</dt>
        <dd>{!metaLocked
          ? <CommitInput value={d.uom} disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { uom: v }))} />
          : d.uom}</dd>
        {/* «Оценка» без «₽» в подписи: рубль приезжает со значением в просмотре. */}
        <dt>Оценка</dt>
        <dd>{!locked
          ? <CommitInput value={d.estimated_cost != null ? String(d.estimated_cost) : ''}
              disabled={busy}
              onCommit={v => run(api.updateItem(d.id, { estimated_cost: v.trim() === '' ? null : Number(v) }))}
              validate={v => v.trim() === '' || Number(v) >= 0} />
          : (d.estimated_cost != null ? money(d.estimated_cost) : '—')}</dd>
      </>}
      tabs={tabs}
    />
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
