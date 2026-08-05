// Витрина волны 2: форма комплектации (записываемое ядро).
// BOM целевого прибора (1 уровень): реальные (пробитые) строки — зелёные,
// автосейв qty; остаток → призрачная строка, покрашенная по доступности, с
// пикером лота. Пайка = промоушн призрака в реальную KittingLine (+ ISSUE).
//
// Волна 19 (Ф12c): на канон §13 переведён ТОЛЬКО скелет формы (титул/шапка/мета/табы
// Строки · Файлы). Тело пробивки намеренно не трогаем: комплектация ждёт своего
// глубокого прохода отдельной волной (BACKLOG «форма комплектации»), и открывать
// второй фронт внутри Ф12c мы не стали.
import { useEffect, useState } from 'react'
import { api, type KittingForm, type KittingFormRow, type ItemRow } from './api'
import { OrderFields, useOrderForm } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { Field, TextField } from './FormField'
import { CommitInput } from './CommitInput'
import { ItemPicker } from './Picker'
import { Dropdown } from './Dropdown'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { Glyph, ItemGlyph, Segment, count, num, statusTone } from './status'

export function KittingView({ kittingId, isNew, openItem, openProject, onChanged, onDeleted }:
  { kittingId: number; isNew: boolean; openItem: (id: number) => void
    openProject: (id: number) => void; onChanged: () => void
    onDeleted: () => void }) {
  // Справочник изделий — для якоря «целевое изделие» (Ф2k). Загружаем один раз.
  const [items, setItems] = useState<ItemRow[]>([])
  useEffect(() => { api.items().then(setItems) }, [])
  const { c, err, busy, unlocked, toggle, run, del } = useOrderForm(
    kittingId, api.kitting, {
      onChanged, onDeleted,
      remove: api.deleteKitting,
      confirmDelete: 'Удалить комплектацию? Рождённый прибор будет снят. Действие необратимо.',
    }, isNew)
  const att = useAttachments('kitting', kittingId)   // загрузка — команда шапки (§13.8)

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const wip = !c.locked
  const fixed = !wip                       // зафиксирована — read-only
  const locked = fixed || !unlocked

  const tabs: FormTab[] = [
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <>
        {c.born_lots.length > 0 && (
          <div className="born">
            Рождён лот-прибор:{' '}
            {c.born_lots.map(l => (
              <span key={l.id} className="seg">#{l.id} ×{num(l.qty)} · {num(l.unit_cost)} ₽/шт</span>
            ))}
          </div>
        )}
        {c.rows.length === 0
          ? <div className="tab-empty">У целевого изделия нет состава — пробивать нечего.</div>
          : <table className="grid">
              <thead>
                <tr>
                  <th className="gl" /><th className="c-key">Компонент</th>
                  <th className="c-desc">Описание</th>
                  <th className="num">Надо</th><th className="uom">Ед.</th>
                  <th className="num">Пробито</th>
                  <th className="num">Остаток</th>
                  {!locked && <th className="act" />}
                </tr>
              </thead>
              <tbody>
                {c.rows.map(row => (
                  <Component key={row.component_id} row={row} form={c} wip={!locked}
                    busy={busy} openItem={openItem} run={run} />
                ))}
              </tbody>
            </table>}
      </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="комплектацию" locked={locked} error={err}
      // Мета (§13.6): счёт по табам + разбор пайки. Прибор/образцы/проект не
      // повторяем — они в полях шапки.
      meta={<>
        {count(c.rows.length, 'компонент', 'компонента', 'компонентов')}
        {' · '}{count(c.rows.filter(r => r.remaining <= 0).length, 'пробит', 'пробито', 'пробито')}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      fixed={fixed}
      onFixate={() => run(api.lockKitting(c.id))}
      fixateTitle="Зафиксировать комплектацию — родить прибор"
      onUnfix={() => { if (confirm('Расфиксировать комплектацию? Рождённый прибор откатится.')) run(api.unlockKitting(c.id)) }}
      onDelete={del}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (акт комплектации) — появится в табе «Файлы»', disabled: att.busy }]}
      fields={
        <OrderFields c={c} locked={locked} busy={busy}
          openProject={openProject}
          patch={b => run(api.updateKitting(c.id, b))}>
          {/* Атрибуты вида — хвостом, в порядке модели (§13.4a): `target_item`, затем
              `qty`. Ширина поля — токеном темы, не пикселями в JSX (Ф12d: инлайн-стиль
              сильнее любого класса и выбивал поле из общей сетки шапки). */}
          {/* Под замком поле = САМА ССЫЛКА на прибор-цель (§8: кликабельно то, что
              названо) — как якори «Проект» здесь же, «Заказ» поставки и «Закупка»
              заказа. Последний якорь формы, который ею не был.
              Выбор — общий `ItemPicker` (type-ahead), а не дропдаун: справочник
              изделий — тысячи строк, и «пролистай до своего» здесь не работает нигде
              больше в продукте. Кандидаты — только НАШИ изделия: «комплектуем своё» —
              не подсказка вью, а ПРАВИЛО (решение Ивана 2026-07-31), и держат его
              движок (`_require_native_target`) с моделью (`clean`). Фильтр здесь —
              лишь его знак: показывать то, что всё равно будет отвергнуто, незачем.
              Старую цель вне фильтра не подстраховываем — таких данных больше нет
              (миграция `0019` их вычистила), а мёртвая ветка врала бы о правиле. */}
          <Field label="Изделие" locked={locked}
            view={c.target_id
              ? <a className="link" onClick={() => openItem(c.target_id!)}>{c.target_code}</a>
              : ''}>
            <ItemPicker items={items.filter(i => i.native)} value={c.target_id ?? ''}
              disabled={busy} placeholder="— не выбрано —"
              notFound="ничего не найдено — комплектуем только свои изделия."
              onPick={id => run(api.updateKitting(c.id, { target_id: id }))} />
          </Field>
          {/* Пустое кол-во показываем пустым полем, а не строкой «null»: у черновика,
              рождённого по клику, его ещё нет (Ф12e). Выбор цели проставляет 1. */}
          <TextField label="Образцов" value={c.qty == null ? '' : String(c.qty)}
            locked={locked} busy={busy}
            onCommit={v => run(api.updateKitting(c.id, { qty: Number(v) }))}
            validate={v => Number(v) > 0} />
        </OrderFields>}
      tabs={tabs}
    />
  )
}

// Компонент состава = одна строка таблицы (как строка заказа в закупочном контуре):
// глиф + код + описание + три числа. Пробитые партии и призрак — строки СТУПЕНЬЮ
// ниже (`.c-key.ind`), тем же приёмом, что дерево пеггинга. До этого каждый
// компонент был отдельным блоком `.kit-comp` со своей таблицей: колонки не
// выстраивались между компонентами, описания разливались на три строки, а «надо ·
// пробито · остаток» шло свободным текстом справа — то, что Иван назвал мусором.
function Component({ row, form, wip, busy, openItem, run }: {
  row: KittingFormRow; form: KittingForm; wip: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<KittingForm>) => void
}) {
  const g = row.ghost
  const status = g ? g.status : 'available'
  return (
    <>
      <tr className={`row s-${status}`}>
        {/* Глиф строки (§7a), как в заказе: ФОРМА = изделие/компонент (оси компонента),
            ЦВЕТ = покрытие строки складом проекта. Одна строка — один глиф. */}
        <td className="gl"><ItemGlyph native={row.component_native}
          synced={row.component_synced} locked={row.component_locked}
          tone={statusTone(status)} /></td>
        <td className="c-key">
          <a className="link" onClick={() => openItem(row.component_id)}>{row.component_code}</a></td>
        <td className="c-desc">
          <span className="cell-ellip" title={row.component_description}>
            {row.component_description}</span></td>
        <td className="num">{num(row.need)}</td>
        <td className="uom">{row.uom}</td>
        <td className="num">{num(row.pierced)}</td>
        <td className="num">{num(row.remaining)}</td>
        {wip && <td className="act" />}
      </tr>
      {/* Пробитая партия: чем именно закрыт компонент. Кол-во стоит в колонке
          «Пробито» — строка пайки в неё и складывается. */}
      {row.real_lines.map(ln => (
        <tr key={ln.id} className="row">
          <td className="gl" />
          <td className="c-key ind">{ln.lot_label}</td>
          <td className="c-desc">{ln.date ?? ''}</td>
          <td className="num" />
          <td className="uom">{row.uom}</td>
          <td className="num">
            {wip
              ? <CommitInput value={String(ln.qty)} disabled={busy}
                  onCommit={v => run(api.updateLine(ln.id, Number(v)))}
                  validate={v => Number(v) > 0} />
              : num(ln.qty)}
          </td>
          <td className="num" />
          {wip && <td className="act">
            <button className="fh-ctl icon fh-del" title="Убрать пробитую строку"
              disabled={busy} onClick={() => run(api.deleteLine(ln.id))}>
              <span className="ci ci-trash" /></button>
          </td>}
        </tr>
      ))}
      {wip && g && <GhostRow row={row} ghost={g} form={form} busy={busy} run={run} />}
    </>
  )
}

// Призрачная строка: пайка (промоушн призрака в реальную KittingLine).
function GhostRow({ row, ghost, form, busy, run }: {
  row: KittingFormRow; ghost: NonNullable<KittingFormRow['ghost']>; form: KittingForm
  busy: boolean; run: (p: Promise<KittingForm>) => void
}) {
  const lots = ghost.candidate_lots
  const [lotId, setLotId] = useState<number | ''>(lots[0]?.lot_id ?? '')
  const [qty, setQty] = useState(String(row.remaining))
  // Кандидаты пересобираются на каждый ответ формы, а выбор живёт в локальном
  // стейте — и мог пережить исчезновение своего лота (пробили, расфиксировали,
  // кончился): пайка ушла бы по несуществующему lot_id. Сверяем выбор со свежим
  // списком: свой остаётся, пропавший откатывается на первый (аудит-1, Б1а-7).
  useEffect(() => {
    setLotId(prev => (lots.some(l => l.lot_id === prev) ? prev : lots[0]?.lot_id ?? ''))
  }, [lots])

  const pierce = () => {
    const n = Number(qty)
    if (!lotId || !(n > 0)) return
    run(api.pierce(form.id, { component_id: row.component_id, lot_id: lotId, qty: n }))
  }

  const empty = lots.length === 0
  return (
    <tr className={`row ghost s-${ghost.status}`}>
      <td className="gl"><Glyph status={ghost.status} /></td>
      {/* Пикер занимает колонки идентичности и описания — канон призрачной строки
          (`.c-key colSpan={2}`, тот же в девяти формах). */}
      <td className="c-key ind" colSpan={2}>
        {empty
          ? <>
              нет своих лотов —{' '}
              <Segment status="on_order" value={ghost.on_order} />
              <Segment status="to_order" value={ghost.to_order} />
            </>
          : <Dropdown value={lotId} disabled={busy} onPick={v => setLotId(Number(v))}
              options={lots.map(l => ({ value: l.lot_id,
                label: `#${l.lot_id} · остаток ${num(l.live_qty)}`
                  + (l.lot_name ? ` · ${l.lot_name}` : '') }))} />}
      </td>
      <td className="num" />
      <td className="uom">{empty ? '' : row.uom}</td>
      <td className="num">
        {!empty &&
          <input className="qty-in" value={qty} disabled={busy}
            onChange={e => setQty(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') pierce() }} />}
      </td>
      <td className="num" />
      <td className="act">
        {!empty &&
          <button className="btn sm" disabled={busy} onClick={pierce}>спаять</button>}
      </td>
    </tr>
  )
}
