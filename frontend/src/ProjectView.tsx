// Форма ПРОЕКТА (волна 19, Ф12c) — канон §13: табы «Приборы» (что делаем, редактируемо
// + прогресс), «Потребность» (полная картина по компонентам на весь проект), «Склад»
// (живые лоты + сведение остатков к нулю, бывш. ClosurePanel) и «Файлы» (владелец
// заведён Ф12b). Панель бюджета — органичное дополнение стека (§13.1), между метой и
// табами. Внутренние склады (белый/серый) идут ЧЕРЕЗ ЭТУ ЖЕ форму (решение Ивана
// 2026-07-26: «это обычные проекты, унифицируем») — у них просто нет приборов и
// потребности, поэтому набор табов сужается, как у покупного изделия нет «Состава».
// Фиксация проекта (бывш. «Закрыть проект») — обычная команда шапки (§5).
import { useEffect, useState } from 'react'
import { api, type Budget, type Deficit, type DeficitComponent, type DeficitDemand,
  type DeficitTreeNode, type ItemRow, type ProjectClosure, type ProjectDetail,
  type ResidualLot } from './api'
import { Chevron, LayerSeg, LotGlyph, count, money, num, ItemGlyph } from './status'
import { CommitInput } from './CommitInput'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { ItemPicker } from './Picker'

export function ProjectView({ projectId, items, isNew, openItem, openPurchase, onChanged, onDeleted }:
  { projectId: number; items: ItemRow[]; isNew: boolean
    openItem: (id: number) => void; openPurchase: (id: number) => void
    onChanged?: () => void; onDeleted?: () => void }) {
  const [data, setData] = useState<Deficit | null>(null)
  const [phead, setPhead] = useState<ProjectDetail | null>(null)  // реквизиты шапки
  const [closure, setClosure] = useState<ProjectClosure | null>(null)   // таб «Склад»
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rev, setRev] = useState(0)      // бюджет пересчитывается при правке потребности
  const { unlocked, toggle } = useFormLock(projectId, isNew)   // §5: существующее — в просмотре
  const att = useAttachments('project', projectId)   // владелец заведён Ф12b (§13.8)

  useEffect(() => {
    setData(null); setPhead(null); setClosure(null); setErr(null)
    api.deficit(projectId).then(setData).catch(e => setErr(String(e)))
    api.project(projectId).then(setPhead).catch(() => {})
    api.closure(projectId).then(setClosure).catch(() => {})
  }, [projectId])

  // Обёртка мутации потребности: ответ = свежий дефицит (обе секции), + пинок бюджету.
  const run = (p: Promise<Deficit>) => {
    setBusy(true); setErr(null)
    p.then(next => { setData(next); setRev(r => r + 1); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Обёртка правки реквизитов шапки (название/бюджет/старт): обновляет шапку + бюджет.
  const runP = (p: Promise<ProjectDetail>) => {
    setBusy(true); setErr(null)
    p.then(next => { setPhead(next); setRev(r => r + 1); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Обёртка мутаций склада проекта (списать / на баланс / фиксация проекта): ответ —
  // свежая панель закрытия; шапку тоже освежаем, в ней живёт замок проекта.
  const runC = (p: Promise<ProjectClosure>) => {
    setBusy(true); setErr(null)
    p.then(next => {
      setClosure(next); setRev(r => r + 1)
      api.project(projectId).then(setPhead).catch(() => {})
      onChanged?.()
    })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Удаление проекта (WAVE14 Ф2) под замком: только пустой (guard бэка), иначе — закрытие.
  const del = () => {
    if (!confirm('Удалить проект? Возможно только для пустого проекта. Действие необратимо.')) return
    setBusy(true); setErr(null)
    api.deleteProject(projectId).then(() => { onChanged?.(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Мост «дефицит → заказ»: положить ▲-позицию в расфиксированный заказ проекта и открыть его.
  const order = (itemId: number, qty: number) => {
    setBusy(true)
    api.addToPurchase(projectId, { item_id: itemId, qty })
      .then(r => openPurchase(r.purchase_id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !data) return <div className="empty">Ошибка: {err}</div>
  if (!data) return <div className="empty">Загрузка…</div>

  const deviceTotal = data.demands.reduce((s, d) => s + d.qty, 0)
  const code = phead?.code ?? data.project_code   // после правки кода — из phead (живо)
  const closed = phead?.locked ?? false           // зафиксирован = закрыт (§5)
  const locked = closed || !unlocked
  // Внешний проект (НИР/контракт) делает приборы; внутренние склады — только хранят.
  const external = phead ? phead.kind === 'external' : true
  const residuals = closure?.residuals ?? []

  const tabs: FormTab[] = []
  if (external) tabs.push(
    { key: 'devices', label: 'Приборы', icon: 'rocket',
      content: <>
        {data.demands.length === 0
          ? <div className="tab-empty">
              {locked ? 'Приборов нет.' : 'Пока ничего — добавьте прибор ниже.'}</div>
          : <div className="pgrid">
              <CompHead />
              {data.demands.map(d => <DeviceRow key={d.demand_id} d={d}
                editable={!locked}
                busy={busy} openItem={openItem} run={run} />)}
            </div>}
        {/* §5 (Ф9): контролы правки приборов только в режиме правки — просмотр чище. */}
        {!locked && <AddDevice items={items} demands={data.demands} busy={busy}
          add={(target_item_id, qty) => run(api.addDemand(projectId, { target_item_id, qty }))} />}
      </> },
    { key: 'need', label: 'Потребность', icon: 'chip',
      content: data.components.length === 0
        ? <div className="tab-empty">Нет компонентов — задайте приборы и их составы.</div>
        : <div className="pgrid">
            <CompHead />
            {data.components.map(c => <CompRow key={c.component_id} ln={c}
              busy={busy} openItem={openItem} order={order} />)}
          </div> },
  )
  tabs.push(
    { key: 'stock', label: 'Склад', icon: 'layers',
      content: residuals.length === 0
        ? <div className="tab-empty">Склад проекта пуст — живых остатков нет.</div>
        : <table className="grid">
            <thead><tr>
              <th className="gl" /><th className="c-key">Партия</th>
              <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
              <th style={{ textAlign: 'right' }}>Остаток</th><th className="uom">Ед.</th>
              {!locked && <th className="act" />}
            </tr></thead>
            <tbody>
              {residuals.map(r => (
                <ResidualRow key={r.lot_id} r={r} projectId={projectId} locked={locked}
                  busy={busy} openItem={openItem} run={runC} />
              ))}
            </tbody>
          </table> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  )

  return (
    <FormShell
      id={projectId} code={code} entity="проект" locked={locked} error={err}
      // Мета (§13.6): счёт по табам в их порядке + приборы штуками. Описание и бюджет
      // не повторяем — они в полях; аномалии остатков всплывают отдельным сегментом.
      meta={<>
        {external && <>
          {count(data.demands.length, 'прибор', 'прибора', 'приборов')}
          {' · '}{num(deviceTotal)} шт
          {' · '}{count(data.components.length, 'компонент', 'компонента', 'компонентов')}
          {' · '}
        </>}
        {count(residuals.length, 'партия', 'партии', 'партий')}
        {(closure?.anomaly_count ?? 0) > 0 &&
          <span className="anomaly"> · {closure!.anomaly_count} в минусе</span>}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      onDelete={del}
      // Фиксация проекта = закрытие (свод остатков в 0 + веха). Гейт бэка тот же,
      // подсказка несёт причину отказа (`blocker`).
      fixed={closed}
      onFixate={closure?.is_external
        ? () => {
            if (!closure.can_close) { setErr(closure.blocker); return }
            if (confirm('Зафиксировать проект? Остатков быть не должно.'))
              runC(api.lockProject(projectId))
          }
        : undefined}
      fixateTitle={closure?.can_close
        ? 'Остатков нет — закрыть проект (веха)'
        : closure?.blocker || 'Зафиксировать проект'}
      onUnfix={closure?.is_external ? () => runC(api.unlockProject(projectId)) : undefined}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (договор, ТЗ) — появится в табе «Файлы»', disabled: att.busy }]}
      fields={<>
        <dt>Код</dt>
        <dd><CommitInput value={phead?.code ?? code} disabled={locked || busy || !phead}
          onCommit={v => runP(api.updateProject(projectId, { code: v }))}
          validate={v => v.trim() !== ''} /></dd>
        <dt>Описание</dt>
        <dd className="wide"><CommitInput value={phead?.description ?? data.project_name}
          disabled={locked || busy || !phead}
          onCommit={v => runP(api.updateProject(projectId, { description: v }))}
          validate={v => v.trim() !== ''} /></dd>
        {external && <>
          <dt>Бюджет</dt>
          <dd><CommitInput value={phead?.budget != null ? String(phead.budget) : ''}
            disabled={locked || busy || !phead}
            onCommit={v => runP(api.updateProject(projectId, { budget: v.trim() === '' ? null : Number(v) }))}
            validate={v => v.trim() === '' || Number(v) >= 0} /></dd>
          <dt>Начат</dt>
          <dd><CommitInput value={phead?.started ?? ''} type="date" disabled={locked || busy || !phead}
            onCommit={v => runP(api.updateProject(projectId, { started: v || null }))} /></dd>
        </>}
      </>}
      extra={external ? <BudgetPanel projectId={projectId} rev={rev} /> : undefined}
      tabs={tabs}
    />
  )
}

// Живой лот проекта: один клик сводит его в 0 (списать → серый / на баланс → белый).
// Переехала сюда из `ClosurePanel` вместе со всей панелью закрытия (Ф12c).
function ResidualRow({ r, projectId, locked, busy, openItem, run }: {
  r: ResidualLot; projectId: number; locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<ProjectClosure>) => void
}) {
  const positive = r.live_qty > 0
  return (
    <tr className={'row' + (r.anomaly ? ' s-to_order' : '')}>
      <td className="gl"><LotGlyph origin={r.origin} liveQty={r.live_qty} /></td>
      <td className="c-key"><span className="pn">{r.lot_label}</span></td>
      <td className="c-fit">
        <a className="link" onClick={() => openItem(r.item_id)}>{r.item_code}</a></td>
      <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
        <span className="cell-ellip" title={r.item_description}>{r.item_description}</span></td>
      <td className="num">
        <span className={r.anomaly ? 'anomaly' : ''}>{num(r.live_qty)}</span>
        {r.anomaly && <span className="anomaly" title="недостача — подбей лоты"> ▲</span>}
      </td>
      <td className="uom">{r.uom}</td>
      {!locked && <td className="act">
        {positive && <>
          <button className="btn sm" disabled={busy}
            title="списать остаток → серый склад (Свободные неучтённые)"
            onClick={() => run(api.writeoffLot(projectId, { lot_id: r.lot_id, qty: r.live_qty }))}>
            списать</button>{' '}
          <button className="btn sm" disabled={busy}
            title="поставить на баланс → белый склад (Собственный склад)"
            onClick={() => run(api.stockLot(projectId, { lot_id: r.lot_id, qty: r.live_qty }))}>
            на баланс</button>
        </>}
      </td>}
    </tr>
  )
}

// Панель бюджета (north-star окупаемости): два числа денег + компас, себестоимость/экономия.
function BudgetPanel({ projectId, rev }: { projectId: number; rev: number }) {
  const [b, setB] = useState<Budget | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setB(null); setErr(null)
    api.budget(projectId).then(setB).catch(e => setErr(String(e)))
  }, [projectId, rev])

  if (err) return <div className="empty">Бюджет: ошибка {err}</div>
  if (!b) return null

  const over = b.compass !== null && b.compass < 0   // перерасход
  return (
    <div className="panel budget">
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

// Шапка колонок (общая для «Приборов» в раскрытии и «Потребности»). Совпадает по
// сетке со строкой прибора: код↔Компонент, потребность↔Надо, прогресс↔Разбор.
function CompHead() {
  return (
    <div className="prow prow--head">
      <span className="tree-cell">Компонент</span>
      <span>Назв.</span>
      <span className="pnum">Надо</span>
      <span className="puom">Ед.</span>
      <span>Разбор</span>
      <span className="pnum">Склад</span>
      <span />
    </div>
  )
}

// Прибор в потребности: строка в том же шаблоне колонок, что и его состав.
// Статус — тонкой полосой слева (без ведущего глифа); название серым. Клик по
// шеврону раскрывает аккордеон с дефицитом по этому прибору.
function DeviceRow({ d, editable, busy, openItem, run }: {
  d: DeficitDemand; editable: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<Deficit>) => void
}) {
  const [open, setOpen] = useState(false)
  const dev = d.device
  return (
    <>
      <div className={`prow prow--device s-${d.status}`}>
        <span className="tree-cell">
          <button className="chev" title={open ? 'свернуть' : 'раскрыть состав'}
            onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
          <ItemGlyph native={d.target_native} synced={d.target_synced} locked={d.target_locked} />
          <a className="link" onClick={() => openItem(d.target_id)}>{d.target_code}</a>
        </span>
        <span className="name">{d.target_description}</span>
        <span className="pnum">
          {editable
            ? <CommitInput value={String(d.qty)} width={56} disabled={busy}
                onCommit={v => run(api.updateDemand(d.demand_id, Number(v)))}
                validate={v => Number(v) > 0} />
            : num(d.qty)}
        </span>
        <span className="puom">шт</span>
        <span title="сделано / делается / осталось сделать">
          <LayerSeg status="available" value={dev.done} />
          <LayerSeg status="on_order" value={dev.wip} />
          <LayerSeg status="to_order" value={dev.not_started} />
        </span>
        <span />
        <span className="act">
          {editable &&
            <button className="fh-ctl icon fh-del" title="Убрать прибор из потребности"
              disabled={busy}
              onClick={() => { if (confirm(`Убрать ${d.target_code} из потребности проекта?`)) run(api.deleteDemand(d.demand_id)) }}>
              <span className="ci ci-trash" /></button>}
        </span>
      </div>
      {open && (d.tree.length === 0
        ? <div className="prow prow--comp" style={{ color: 'var(--fg-dim)' }}>
            <span style={{ gridColumn: '1 / -1' }}>Состав пуст — задайте BOM прибора.</span>
          </div>
        : <DeviceTree tree={d.tree} openItem={openItem} />)}
    </>
  )
}

// Дерево BOM в аккордеоне прибора (Ф5b) со сворачиванием подсборок. Узлы-подсборки
// свёрнуты по умолчанию (expanded — пусто): при раскрытии прибора видно только прямые
// компоненты, дальше — по шевронам. Плоский pre-order + `depth` от бэка: скрываем строки
// глубже свёрнутого узла (пока не вернёмся на его уровень).
function DeviceTree({ tree, openItem }: {
  tree: DeficitTreeNode[]; openItem: (id: number) => void
}) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const toggle = (i: number) => setExpanded(s => {
    const next = new Set(s)
    if (next.has(i)) next.delete(i); else next.add(i)
    return next
  })
  // Видимые строки: узел скрыт, если он глубже ближайшего свёрнутого предка.
  const visible: { n: DeficitTreeNode; i: number; hasChildren: boolean; isExp: boolean }[] = []
  let hideDepth = Infinity
  tree.forEach((n, i) => {
    if (n.depth > hideDepth) return       // под свёрнутым узлом — прячем
    hideDepth = Infinity                  // вернулись на уровень предка — снимаем сокрытие
    const hasChildren = !n.is_leaf
    const isExp = expanded.has(i)
    if (hasChildren && !isExp) hideDepth = n.depth   // свёрнут → прячем его поддерево
    visible.push({ n, i, hasChildren, isExp })
  })
  return <>{visible.map(({ n, i, hasChildren, isExp }) =>
    <TreeRow key={i} n={n} hasChildren={hasChildren} expanded={isExp}
      onToggle={() => toggle(i)} openItem={openItem} />)}</>
}

// Строка дерева. Отступ = глубина; статус-полоса слева (у узла — worst-of поддерева).
// Узел-подсборка: кликабельный шеврон (свернуть/раскрыть), купить нельзя — «＋ в заказ»
// живёт в своде «Потребность». Лист: разбор ✓/●/▲ + склад (read-only).
function TreeRow({ n, hasChildren, expanded, onToggle, openItem }: {
  n: DeficitTreeNode; hasChildren: boolean; expanded: boolean
  onToggle: () => void; openItem: (id: number) => void
}) {
  const indent = (n.depth + 1) * 18   // +1: дерево живёт под строкой прибора-цели (стаж-ступень)
  return (
    <div className={`prow prow--comp s-${n.status}`}>
      <span className="tree-cell" style={{ paddingLeft: indent }}>
        {hasChildren
          ? <button className="chev" title={expanded ? 'свернуть подсборку' : 'раскрыть подсборку'}
              onClick={onToggle}><Chevron open={expanded} /></button>
          : <span className="tree-lead" />}
        <ItemGlyph native={n.component_native} synced={n.component_synced} locked={n.component_locked} />
        <a className="link" onClick={() => openItem(n.component_id)}>{n.component_code}</a>
      </span>
      <span className="name">{n.component_description}</span>
      <span className="pnum">{num(n.need)}</span>
      <span className="puom">{n.uom}</span>
      {n.is_leaf ? <>
        <span>
          <LayerSeg status="available" value={n.have ?? 0} />
          <LayerSeg status="on_order" value={n.on_order ?? 0} />
          <LayerSeg status="to_order" value={n.to_order ?? 0} />
        </span>
        <span className="pnum">
          {num(n.available_raw ?? 0)}
          {n.anomaly && <span className="anomaly" title="есть лот с отрицательным остатком">▲</span>}
        </span>
      </> : <>
        <span style={{ color: 'var(--fg-dim)', fontSize: 11 }}>подсборка</span>
        <span />
      </>}
      <span className="act" />
    </div>
  )
}

// Строка компонента: разбор ✓/●/▲ + «＋ в заказ». Общая для аккордеона и сводной.
function CompRow({ ln, busy, openItem, order }: {
  ln: DeficitComponent; busy: boolean; openItem: (id: number) => void
  order: (itemId: number, qty: number) => void
}) {
  return (
    <div className={`prow prow--comp s-${ln.status}`}>
      <span className="tree-cell">
        <ItemGlyph native={ln.component_native} synced={ln.component_synced} locked={ln.component_locked} />
        <a className="link" onClick={() => openItem(ln.component_id)}>{ln.component_code}</a>
      </span>
      <span className="name">{ln.component_description}</span>
      <span className="pnum">{num(ln.need)}</span>
      <span className="puom">{ln.uom}</span>
      <span>
        <LayerSeg status="available" value={ln.have} />
        <LayerSeg status="on_order" value={ln.on_order} />
        <LayerSeg status="to_order" value={ln.to_order} />
      </span>
      <span className="pnum">
        {num(ln.available_raw)}
        {ln.anomaly && <span className="anomaly" title="есть лот с отрицательным остатком">▲</span>}
      </span>
      <span className="act">
        {ln.to_order > 0 &&
          <button className="btn sm" disabled={busy}
            title={`положить ${num(ln.to_order)} ${ln.uom} в расфиксированный заказ проекта`}
            onClick={() => order(ln.component_id, ln.to_order)}>＋ в заказ</button>}
      </span>
    </div>
  )
}

// Добавить прибор в потребность: пикер изделий-приборов (не добавленных) + кол-во.
function AddDevice({ items, demands, busy, add }: {
  items: ItemRow[]; demands: DeficitDemand[]; busy: boolean
  add: (targetItemId: number, qty: number) => void
}) {
  const taken = new Set(demands.map(d => d.target_id))
  const options = items.filter(i => i.native && !taken.has(i.id))
  // Ф2 (волна 19): автовыбора первого прибора нет — выбор прибора всегда явный
  // (молчаливый первый вариант был источником ошибочных строк потребности).
  const [targetId, setTargetId] = useState<number | ''>('')
  const [qty, setQty] = useState('1')

  const submit = () => {
    const n = Number(qty)
    if (!targetId || !(n > 0)) return
    add(targetId, n)
    setTargetId('')
  }

  if (options.length === 0)
    return <div className="kit-actions" style={{ marginTop: 10, color: 'var(--fg-dim)', fontSize: 12 }}>
      ＋ прибор: все изделия-приборы уже в потребности.</div>
  return (
    <div className="kit-actions" style={{ marginTop: 10 }}>
      <span style={{ color: 'var(--fg-dim)', fontSize: 12 }}>＋ прибор</span>
      <ItemPicker items={options} value={targetId} onPick={setTargetId} disabled={busy}
        width={240} onEnter={submit}
        notFound="ничего не найдено — прибор должен быть изделием (не компонентом)." />
      <input className="qty-in" value={qty} disabled={busy}
        onChange={e => setQty(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit() }} />
      <button className="btn sm" disabled={busy || !targetId} onClick={submit}>добавить</button>
    </div>
  )
}
