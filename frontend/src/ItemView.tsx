// Витрина волны 1: экран изделия = панель свойств + окружение из связей.
// Партии на складе (по проектам, с живым остатком), where-used, состав.
// Волна 19 (Ф12a): форма по канону §13 — табы Состав · Применение · Склад ·
// Движения · Файлы. «Движения» пришли на смену узкому «Отгружено»: вся лента
// ордеров, коснувшихся изделия (рождение партий + расходы), `engine.item_movements`.
import { useEffect, useMemo, useState } from 'react'
import { api, type ItemDetail, type ItemRow, type Category, type RollupResult } from './api'
import { num, money, count, ItemGlyph, LotGlyph, StatusGlyph } from './status'
import { ORDER_LABEL, type OrderKind } from './orders'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { ItemPicker } from './Picker'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { CommitInput } from './CommitInput'
import { Field, TextField } from './FormField'
import { Dropdown } from './Dropdown'

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
          <thead><tr><th className="gl" /><th className="c-key">Компонент</th><th className="c-desc">Описание</th>
            <th className="num">Кол-во</th><th className="uom">Ед.</th>
            {!locked && <th className="act" />}</tr></thead>
          <tbody>{d.bom.map(b => (
            <tr key={b.id} className="row">
              <td className="gl"><ItemGlyph native={b.component_native} synced={b.component_synced} locked={b.component_locked} /></td>
              <td className="c-key">
                <a className="link" onClick={() => openItem(b.component_id)}>{b.component_code}</a></td>
              <td className="c-desc">
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
          <thead><tr><th className="gl" /><th className="c-key">Изделие</th><th className="c-desc">Описание</th>
            <th className="num">Кол-во</th>
            <th className="uom">Ед.</th></tr></thead>
          <tbody>{d.where_used.map(w => (
            <tr key={w.parent_id} className="row">
              {/* Глиф родителя — по его собственным осям (Ф3a: ровно один по режиму). */}
              <td className="gl"><ItemGlyph native={w.parent_native} synced={w.parent_synced}
                locked={w.parent_locked} /></td>
              <td className="c-key">
                <a className="link" onClick={() => openItem(w.parent_id)}>{w.parent_code}</a></td>
              <td className="c-desc">
                <span className="cell-ellip" title={w.parent_description}>{w.parent_description}</span></td>
              <td className="num">{num(w.qty)}</td>
              <td className="uom">{d.uom}</td>
            </tr>))}</tbody>
        </table>,
  })
  tabs.push({
    key: 'lots', label: 'Склад', icon: 'layers',
    content: d.lots.length === 0
      ? <div className="tab-empty">Нет партий</div>
      // Глиф партии (Ф12c): форма = откуда родилась, цвет = живость остатка. Текстовый
      // чип «origin» снят — вид рождения теперь несёт сам глиф (§7a: одна строка —
      // один знак). Ф15: партия расфиксированного origin остаётся в списке (видно
      // входящий поток), но идёт нейтральным тоном — она не «исчерпана», а не принята.
      : <table className="grid">
          <thead><tr><th className="gl" /><th className="c-key">Партия</th>
            <th className="c-fit">Проект</th>
            <th className="num">Рожд.</th>
            <th className="num">Остаток</th>
            <th className="uom">Ед.</th>
            <th className="c-fit">Part number</th><th className="c-desc">Название</th>
          </tr></thead>
          <tbody>{d.lots.map(l => (
            <tr key={l.id} className="row">
              <td className="gl"><LotGlyph origin={l.origin} liveQty={l.live_qty}
                draft={!l.origin_locked} /></td>
              <td className="c-key">#{l.id}</td>
              <td className="c-fit code">{l.project_code}</td>
              <td className="num">{num(l.qty_born)}</td>
              {/* Ф15: у партии черновика остатка нет вовсе — прочерк, а не 0 (ноль
                  здесь читался бы как «израсходована»). Рождённое кол-во остаётся:
                  это и есть входящий поток «едет, ещё не принято». */}
              <td className="num" title={l.origin_locked ? undefined
                : 'Партия ещё не на складе — зафиксируйте документ-origin'}>
                {l.origin_locked ? num(l.live_qty) : '—'}</td>
              <td className="uom">{d.uom}</td>
              <td className="c-fit">{l.part_number || '—'}</td>
              <td className="c-desc">{l.lot_name || '—'}</td>
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
            <th className="num">Кол-во</th>
            <th className="uom">Ед.</th></tr></thead>
          <tbody>{d.movements.map((m, i) => (
            <tr key={`${m.kind}-${m.document_id}-${m.lot_id}-${i}`}
              className={'row ' + (m.qty < 0 ? 's-to_order' : 's-available')}>
              <td className="gl"><StatusGlyph locked={m.locked} /></td>
              <td className="c-key"><a className="link" onClick={() => openOrder(m.kind as OrderKind, m.document_id)}>
                {m.code || m.number || `${ORDER_LABEL[m.kind as OrderKind]} #${m.document_id}`}</a></td>
              <td>
                {ORDER_LABEL[m.kind as OrderKind] ?? m.kind}
                {m.event === 'born' && <span className="hint">партия рождена</span>}</td>
              <td>{m.date ?? '—'}</td>
              <td className="code">{m.project_code}</td>
              <td>#{m.lot_id}{m.lot_name && ` · ${m.lot_name}`}</td>
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
      /* Выгрузка (2026-07-30) — ВСЕГДА, в отличие от бланка закупки: состав нужен и
         черновиком, а покупной компонент не фиксируется вовсе (synced ⟹ not locked),
         и правило «только у запертого» оставило бы его без кнопки навсегда. Две цели
         → меню; глиф пункта — глиф вкладки, которую он выгружает (§2). */
      download={{
        title: 'Скачать xlsx (имя файла = код изделия)',
        options: [
          { label: 'Только состав', icon: 'chip', href: api.itemXlsxUrl(d.id, 'bom'),
            title: 'Один лист «Состав» — прямые компоненты, один уровень' },
          { label: 'Все вкладки', icon: 'table', href: api.itemXlsxUrl(d.id, 'all'),
            title: 'Листы по вкладкам формы, кроме «Файлов»' },
        ],
      }}
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
        <TextField label="Код" value={d.code} locked={metaLocked} busy={busy}
          onCommit={v => run(api.updateItem(d.id, { code: v }))}
          validate={v => v.trim() !== ''} />
        {/* Единственное длинное поле шапки (§13.3) — описание бывает в строку и больше. */}
        <TextField label="Описание" wide value={d.description} locked={metaLocked} busy={busy}
          onCommit={v => run(api.updateItem(d.id, { description: v }))}
          validate={v => v.trim() !== ''} />
        <Field label="Категория" locked={metaLocked} view={d.category?.code}>
          {/* Ф12e: изделие рождается по клику без категории — пустое поле честно
              говорит «ещё не выбрана» (фиксация без неё не пройдёт). */}
          <Dropdown options={categories.map(c => ({ value: c.id, label: c.code }))}
            value={d.category?.id ?? ''} disabled={busy} placeholder="— не выбрана —"
            onPick={v => run(api.updateItem(d.id, { category_id: Number(v) }))} />
        </Field>
        {/* Поля «Производимое» нет (снято 2026-07-26): `native` — не свойство на правку,
            а ОСЬ РЕЖИМА (Изделия / Компоненты). Заводится вместе с сущностью в том
            режиме, где нажали «＋ Новое», и дальше не переключается. */}
        {/* Порядок — от модели (§13.4a, Ф17): `uom`, затем `temperature`. */}
        <TextField label="Единицы" value={d.uom} locked={metaLocked} busy={busy}
          onCommit={v => run(api.updateItem(d.id, { uom: v }))} />
        <TextField label="Температура" value={d.temperature} locked={metaLocked} busy={busy}
          onCommit={v => run(api.updateItem(d.id, { temperature: v }))} />
        {/* «Оценка» без «₽» в подписи: рубль приезжает со значением в просмотре. */}
        <TextField label="Оценка" locked={locked} busy={busy}
          value={d.estimated_cost != null ? String(d.estimated_cost) : ''}
          view={d.estimated_cost != null ? money(d.estimated_cost) : ''}
          onCommit={v => run(api.updateItem(d.id, { estimated_cost: v.trim() === '' ? null : Number(v) }))}
          validate={v => v.trim() === '' || Number(v) >= 0} />
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
