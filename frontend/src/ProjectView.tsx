// Форма ПРОЕКТА (волна 19, Ф12c) — канон §13: табы «Приборы» (что делаем, редактируемо
// + прогресс), «Потребность» (полная картина по компонентам на весь проект), «Заказы» и
// «Поставки» (закупочный контур проекта, 2026-08-28 — ленты только на чтение), «Склад»
// (живые лоты + сведение остатков к нулю, бывш. ClosurePanel) и «Файлы» (владелец
// заведён Ф12b). Порядок табов = поток жизни: что надо → что заказали → что приехало →
// что лежит. Панель бюджета — органичное дополнение стека (§13.1), между метой и
// табами. Внутренние склады (белый/серый) идут ЧЕРЕЗ ЭТУ ЖЕ форму (решение Ивана
// 2026-07-26: «это обычные проекты, унифицируем») — у них просто нет приборов и
// потребности, поэтому набор табов сужается, как у покупного изделия нет «Состава».
// Фиксация проекта (бывш. «Закрыть проект») — обычная команда шапки (§5).
import { useEffect, useState, type ReactNode } from 'react'
import { api, type Budget, type Deficit, type DeficitDemand,
  type DeficitTreeNode, type ItemRow, type ProjectClosure, type ProjectDetail,
  type ProjectSupply, type ResidualLot } from './api'
import { Anomaly, Balance, Chevron, Cost, LotGlyph, count, money, num, ItemGlyph, paretoKeys, pct,
  rowNumbers, visibleTree, type VisibleNode,
  signedPct } from './status'
import { ORDER_LABEL, type OrderKind } from './orders'
import { CommitInput } from './CommitInput'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { TextField } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { ProcurementFeed, PurchaseFeed, ReceiptFeed } from './FeedTables'
import { BalanceCells, Member, NeedHead, NeedRow, NeedSums, needPass,
  useNeedFilters } from './NeedTable'
import { useCategoryFilter } from './ColumnFilter'
import { ItemPicker } from './Picker'
import { Stat, StatGroup, StatPanel, StatWarn } from './StatPanel'
import { EntityLink } from './EntityLink'
import { ask } from './dialog'

// Категории масштаба, которые мета показывает (коды канона): приборы и узлы печатные.
const META_SCALE = ['ПРБ', 'УП']

export function ProjectView({ projectId, items, isNew, openItem, openOrder, openPurchase,
  openProcurement, openCounterparty, onChanged, onDeleted }:
  { projectId: number; items: ItemRow[]; isNew: boolean
    openItem: (id: number) => void
    openOrder: (kind: OrderKind, id: number) => void   // Ф15: черновики закрытия кликабельны
    openPurchase: (id: number) => void                 // лента «Заказы» — свой режим
    openProcurement: (id: number) => void              // лента «Закупки» (волна 24)
    openCounterparty: (id: number) => void             // поставщик в лентах — ссылка
    onChanged?: () => void; onDeleted?: () => void }) {
  const [data, setData] = useState<Deficit | null>(null)
  const [phead, setPhead] = useState<ProjectDetail | null>(null)  // реквизиты шапки
  const [closure, setClosure] = useState<ProjectClosure | null>(null)   // таб «Склад»
  const [supply, setSupply] = useState<ProjectSupply | null>(null)  // табы «Заказы»/«Поставки»
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rev, setRev] = useState(0)      // бюджет пересчитывается при правке потребности
  const filters = useNeedFilters(projectId)     // фильтры колонок свода «Потребность»
  // Фильтр по классу изделия — общий движок (2026-08-10), тот же, что во всех колонках
  // «Компонент» продукта. Стоит ПЕРВЫМ в цепочке: сперва сужаем набор классом, потом
  // членами баланса.
  const byCat = useCategoryFilter(data?.components, c => c.component_category, projectId)
  const { unlocked, toggle } = useFormLock(projectId, isNew)   // §5: существующее — в просмотре
  const att = useAttachments('project', projectId)   // владелец заведён Ф12b (§13.8)

  useEffect(() => {
    setData(null); setPhead(null); setClosure(null); setSupply(null); setErr(null)
    api.deficit(projectId).then(setData).catch(e => setErr(String(e)))
    api.project(projectId).then(setPhead).catch(() => {})
    api.closure(projectId).then(setClosure).catch(() => {})
    api.projectSupply(projectId).then(setSupply).catch(() => {})
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
  const del = async () => {
    if (!(await ask({ title: 'Удалить проект?',
      lines: ['возможно только для пустого проекта'], verb: 'Удалить', icon: 'ci-trash', danger: true }))) return
    setBusy(true); setErr(null)
    api.deleteProject(projectId).then(() => { onChanged?.(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !data) return <div className="empty">Ошибка: {err}</div>
  if (!data) return <div className="empty">Загрузка…</div>

  const code = phead?.code ?? data.project_code   // после правки кода — из phead (живо)
  const closed = phead?.locked ?? false           // зафиксирован = закрыт (§5)
  const locked = closed || !unlocked
  // Внешний проект (НИР/контракт) делает приборы; внутренние склады — только хранят.
  const external = phead ? phead.kind === 'external' : true
  const shown = byCat.shown.filter(c => needPass(c, filters))
  const needNo = rowNumbers(data.components)   // постоянный номер строки «Потребности»
  const residuals = closure?.residuals ?? []
  const drafts = closure?.closing_drafts ?? []   // Ф15: закрывающие документы-черновики

  const tabs: FormTab[] = []
  if (external) tabs.push(
    { key: 'devices', label: 'Приборы', icon: 'rocket',
      content: <>
        {data.demands.length === 0
          ? <div className="tab-empty">
              {locked ? 'Приборов нет.' : 'Пока ничего — добавьте прибор ниже.'}</div>
          : <DevicesGrid demands={data.demands} editable={!locked} busy={busy}
              openItem={openItem} run={run} />}
        {/* §5 (Ф9): контролы правки приборов только в режиме правки — просмотр чище. */}
        {!locked && <AddDevice items={items} demands={data.demands} busy={busy}
          add={(target_item_id, qty) => run(api.addDemand(projectId, { target_item_id, qty }))} />}
      </> },
    { key: 'need', label: 'Потребность', icon: 'chip',
      content: data.components.length === 0
        ? <div className="tab-empty">Нет компонентов — задайте приборы и их составы.</div>
        : <div className="pgrid">
            <NeedSums rows={shown} outside={data.outside_spent}
              filtered={shown.length !== data.components.length} />
            <NeedHead f={filters} catHead={byCat.head} />
            {shown.length === 0
              ? <div className="prow prow--comp prow--empty">
                  <span>Ни одна строка не подходит под фильтры колонок.</span>
                </div>
              : shown.map(c => <NeedRow key={c.component_id} ln={c} no={needNo.get(c)}
                  openItem={openItem} />)}
          </div> },
  )
  // Закупочный контур проекта — тремя лентами того же вида, что в форме контрагента
  // (`FeedTables`): разрез другой, строка та же. Стоят между «Потребностью» и «Складом»
  // по потоку жизни: что надо → что решили купить (закупки, волна 24: закупка стала
  // проектной) → что заказали → что приехало → что лежит. Табы есть у
  // ЛЮБОГО проекта, включая внутренние склады (решение Ивана 2026-08-28): набор табов
  // предсказуем, у склада они просто пусты. Ленты только читают — заказ и поставку
  // заводят в своих режимах.
  tabs.push(
    { key: 'procurements', label: 'Закупки', icon: 'law',
      content: <ProcurementFeed rows={supply?.procurements ?? []} open={openProcurement}
        empty="Закупок по этому проекту нет." /> },
    { key: 'purchases', label: 'Заказы', icon: 'package',
      content: <PurchaseFeed rows={supply?.purchases ?? []} side="project"
        open={openPurchase} openCounterparty={openCounterparty}
        empty="Заказов по этому проекту нет." /> },
    { key: 'receipts', label: 'Поставки', icon: 'inbox',
      content: <ReceiptFeed rows={supply?.receipts ?? []} side="project"
        open={id => openOrder('receipt', id)} openCounterparty={openCounterparty}
        empty="В этот проект ещё ничего не привозили." /> },
    { key: 'stock', label: 'Склад', icon: 'layers',
      content: residuals.length === 0
        ? <div className="tab-empty">Склад проекта пуст — живых остатков нет.</div>
        : <>
            {/* Ф15: «списать»/«на баланс» кладут остаток в ЧЕРНОВОЙ документ, а со
                склада он уйдёт на его фиксации — иначе клик выглядит несработавшим. */}
            {drafts.length > 0 && <div className="hint-row">
              Ждут фиксации:{' '}
              {drafts.map((d, i) => <span key={d.document_id}>
                {i > 0 && ' · '}
                <EntityLink kind={d.kind as OrderKind} id={d.document_id}
                  open={id => openOrder(d.kind as OrderKind, id)}>
                  {ORDER_LABEL[d.kind as OrderKind]} {d.code || d.number || `#${d.document_id}`}
                </EntityLink>{` (${num(d.qty)})`}
              </span>)}
            </div>}
            <table className="grid">
              <thead><tr>
                <th className="rn">№</th><th className="gl" /><th className="c-key">Партия</th>
                <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
                <th className="num">Остаток</th><th className="uom">Ед.</th>
                {!locked && <th className="act" />}
              </tr></thead>
              <tbody>
                {residuals.map((r, i) => (
                  <ResidualRow key={r.lot_id} no={i + 1} r={r} projectId={projectId} locked={locked}
                    busy={busy} openItem={openItem} run={runC} />
                ))}
              </tbody>
            </table>
          </> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  )

  return (
    <FormShell
      id={projectId} code={code} entity="проект" locked={locked} error={err}
      // Мета (§13.6): счёт по табам в их порядке + приборы штуками. Описание и бюджет
      // не повторяем — они в полях; аномалии остатков всплывают отдельным сегментом.
      meta={<>
        {/* Мета расчищена (решение Ивана 2026-10-16): приборы · узлы печатные ·
            компоненты — масштаб работы, ради которого в мету и смотрят. Остальное
            (системы, кабельные сети, закупки, заказы, поставки, партии, файлы) снято —
            добавим, когда понадобится. Штуки по всему дереву — из движка (`scale`,
            волна 23 Ф4), склонение здесь. */}
        {external && [
          ...data.scale.filter(x => META_SCALE.includes(x.category ?? ''))
            .map(x => count(x.count, ...x.forms)),
          count(data.components.length, 'компонент', 'компонента', 'компонентов'),
        ].join(' · ')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      onDelete={del}
      /* План закупок (2026-09-15) — только у внешнего проекта: у складов-проектов нет
         ни приборов, ни потребности, и выгружать им нечего. Одна цель → обычная
         ссылка, без меню (меню у изделия, там целей две). */
      download={external
        ? { label: 'Скачать план закупок', href: api.projectPlanXlsxUrl(projectId),
            title: 'xlsx: «Потребность» в деньгах — кол-во, цена, стоимость и «Всего»; '
              + 'позиции без оценки красные' }
        : undefined}
      // Фиксация проекта = закрытие (свод остатков в 0 + веха). Гейт бэка тот же,
      // подсказка несёт причину отказа (`blocker`).
      fixed={closed}
      // Отказ (остатки не сведены) теперь говорит окно фиксации — пробной фиксацией в
      // движке, той же проверкой, что у кнопки (волна 23, Ф1).
      onFixate={closure?.is_external ? () => runC(api.lockProject(projectId)) : undefined}
      fixateTitle={closure?.can_close
        ? 'Остатков нет — закрыть проект (веха)'
        : closure?.blocker || 'Зафиксировать проект'}
      onUnfix={closure?.is_external ? () => runC(api.unlockProject(projectId)) : undefined}
      fixation={`projects/${projectId}`}
      actions={[{ onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
        title: 'Загрузить файл (договор, ТЗ) — появится в табе «Файлы»', disabled: att.busy }]}
      fields={<>
        <TextField label="Код" code value={phead?.code ?? code} locked={locked}
          busy={busy || !phead}
          onCommit={v => runP(api.updateProject(projectId, { code: v }))}
          validate={v => v.trim() !== ''} />
        <TextField label="Описание" wide value={phead?.description ?? data.project_name}
          locked={locked} busy={busy || !phead}
          onCommit={v => runP(api.updateProject(projectId, { description: v }))}
          validate={v => v.trim() !== ''} />
        {external && <>
          <TextField label="Бюджет" locked={locked} busy={busy || !phead}
            value={phead?.budget != null ? String(phead.budget) : ''}
            view={phead?.budget != null ? money(phead.budget) : ''}
            onCommit={v => runP(api.updateProject(projectId, { budget: v.trim() === '' ? null : Number(v) }))}
            validate={v => v.trim() === '' || Number(v) >= 0} />
          <TextField label="Начат" type="date" value={phead?.started ?? ''}
            locked={locked} busy={busy || !phead}
            onCommit={v => runP(api.updateProject(projectId, { started: v || null }))} />
        </>}
      </>}
      extra={external ? <BudgetPanel projectId={projectId} rev={rev} /> : undefined}
      tabs={tabs}
    />
  )
}

// Живой лот проекта: один клик сводит его в 0 (списать → серый / на баланс → белый).
// Переехала сюда из `ClosurePanel` вместе со всей панелью закрытия (Ф12c).
function ResidualRow({ no, r, projectId, locked, busy, openItem, run }: {
  no?: number
  r: ResidualLot; projectId: number; locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<ProjectClosure>) => void
}) {
  const positive = r.live_qty > 0
  return (
    <tr className="row">
      <td className="rn">{no}</td>
      <td className="gl"><LotGlyph origin={r.origin} liveQty={r.live_qty} /></td>
      <td className="c-key"><span className="code">{r.lot_label}</span></td>
      <td className="c-fit">
        <EntityLink kind="item" id={r.item_id} open={openItem}>{r.item_code}</EntityLink></td>
      <td className="c-desc">
        <span className="cell-ellip" title={r.item_description}>{r.item_description}</span></td>
      <td className="num">
        <span className={r.anomaly ? 'anomaly' : ''}>{num(r.live_qty)}</span>
        {r.anomaly && <Anomaly title="недостача — подбей лоты" />}
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

// Блок «Деньги» проекта (волна 26): ★ потрачено + доли освоения, план, бюджет, компас и
// «сверх потребности». Себестоимость/экономия сняты в BACKLOG. Волна 20: вёрстка статов
// живёт в общем `StatPanel` — здесь только начинка, то есть сам смысл блока.
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
  // «Сверх потребности» (волна 26): одно число честно смешивает три причины — раскладка
  // под курсором, чтобы было видно, откуда перерасход.
  const overNeedTitle = `план ${money(b.plan)} против чистой потребности ${money(b.need)}`
    + ` (нужда по BOM × оценка, без запаса):\n· запас закупок ${money(b.reserve)}`
    + `\n· куплено вне BOM ${money(b.outside)}`
    + `\n· разница цен счёта с оценкой и прочее ${money(b.price_gap)}`
  return (
    <StatPanel>
      {/* Волна 26 (решение Ивана): главное — потрачено. Освоенные рубли — маркер хода
          работы и объективный факт для отчёта; остальное — поддержка решений по затратам.
          Потрачено — обязательства, а не приход по УПД (волна 24). */}
      <Stat main label="потрачено" value={money(b.spent)}
        title="Зафиксированные заказы по счёту + поставки без заказа по УПД" />
      <StatGroup>
        <Stat label="от бюджета" value={pct(b.spent_of_budget)} dim={b.spent_of_budget === null}
          title="Освоение бюджета на материалы — для отчёта по контракту" />
        <Stat label="от плана" value={pct(b.spent_of_plan)} dim={b.spent_of_plan === null}
          title="Ход работы: 100% — план закрыт обязательствами; мало — отстаём с закупкой" />
        <Stat label="план (прогноз)" value={money(b.plan)}
          title="Потрачено + план зафиксированных закупок (с запасом) и нехватка — по оценке изделий" />
        {b.budget !== null
          ? <Stat label="бюджет на материалы" value={money(b.budget)} />
          : <Stat label="бюджет на материалы" value="— не задан" dim />}
        {b.compass !== null &&
          <Stat label={over ? 'перерасход' : 'запас бюджета'}
            value={money(Math.abs(b.compass))} tone={over ? 'bad' : 'ok'} />}
        <Stat label="сверх потребности" value={signedPct(b.over_need)}
          dim={b.over_need === null} title={overNeedTitle}
          tone={b.over_need !== null && b.over_need > 0 ? 'wip' : undefined} />
      </StatGroup>
      {b.unestimated.length > 0 &&
        <StatWarn title={`нет estimated_cost: ${b.unestimated.join(', ')}`}>
          {count(b.unestimated.length, 'позиция', 'позиции', 'позиций')} без оценки — план неполон
        </StatWarn>}
    </StatPanel>
  )
}

// Прибор в потребности: строка в том же шаблоне колонок, что и его состав.
// Статус — тонкой полосой слева (без ведущего глифа); название серым. Клик по
// шеврону раскрывает аккордеон с дефицитом по этому прибору.
// Динамический Парето (2026-10-20, идея Ивана): подсветка идёт по ФРОНТУ аккордеона —
// видимым строкам, которые сами не раскрыты. Ничего не раскрыто — по приборам; раскрыт
// прибор — он выпадает, а в счёт идут его узлы (и остальные приборы); раскрыта подсборка —
// её место занимают её дети. Сумма фронта всегда равна сумме приборов: оценка узла — это
// сумма детей (роллап), поэтому 80% считаются от одного и того же целого. Фронт зависит
// от раскрытости — состояния вью, — поэтому счёт здесь (`paretoKeys`, правило движка
// `mark_pareto`); без раскрытий он совпадает с `cost_status` приборов от движка.
function DevicesGrid({ demands, editable, busy, openItem, run }: {
  demands: DeficitDemand[]; editable: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<Deficit>) => void
}) {
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [expanded, setExpanded] = useState<Map<number, Set<number>>>(new Map())
  const toggleDevice = (id: number) => setOpen(s => {
    const next = new Set(s)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })
  const toggleNode = (id: number, i: number) => setExpanded(m => {
    const next = new Map(m)
    const set = new Set(next.get(id) ?? [])
    if (set.has(i)) set.delete(i); else set.add(i)
    next.set(id, set)
    return next
  })
  const visible = new Map(demands.map(d => [d.demand_id,
    visibleTree(d.tree, expanded.get(d.demand_id) ?? new Set())]))
  const frontier: { key: string; cost: number | null }[] = []
  for (const d of demands) {
    if (!open.has(d.demand_id)) { frontier.push({ key: `d${d.demand_id}`, cost: d.cost }); continue }
    for (const v of visible.get(d.demand_id) ?? [])
      if (!(v.hasChildren && v.isExp)) frontier.push({ key: `t${d.demand_id}:${v.i}`, cost: v.n.est_cost })
  }
  const costly = paretoKeys(frontier)
  return (
    // Колонка команд — только в правке (2026-10-20, как у «Строк» закупки): в просмотре
    // корзины нет, а пустой трек 44px поджимал «Оценку» к «Балансу».
    <div className={'pgrid' + (editable ? ' pgrid--acts' : '')}>
      <NeedHead lead="Прибор" tree acts={editable} />
      {demands.map((d, i) => <DeviceRow key={d.demand_id} d={d} no={i + 1}
        open={open.has(d.demand_id)} onToggle={() => toggleDevice(d.demand_id)}
        costly={costly.has(`d${d.demand_id}`)}
        editable={editable} busy={busy} openItem={openItem} run={run}>
        <DeviceTree rows={visible.get(d.demand_id) ?? []}
          onToggle={i => toggleNode(d.demand_id, i)}
          costly={i => costly.has(`t${d.demand_id}:${i}`)} acts={editable}
          openItem={openItem} />
      </DeviceRow>)}
    </div>
  )
}

function DeviceRow({ d, no, open, onToggle, costly, editable, busy, openItem, run, children }: {
  d: DeficitDemand; no: number; open: boolean; onToggle: () => void; costly: boolean
  editable: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<Deficit>) => void; children: ReactNode
}) {
  const dev = d.device
  return (
    <>
      <div className="prow prow--device">
        <span className="rn">{no}</span>
        <span className="tree-cell">
          <button className="chev" title={open ? 'свернуть' : 'раскрыть состав'}
            onClick={onToggle}><Chevron open={open} /></button>
          <ItemGlyph native={d.target_native} synced={d.target_synced} locked={d.target_locked} />
          <EntityLink kind="item" id={d.target_id} open={openItem}>{d.target_code}</EntityLink>
        </span>
        <span className="name">{d.target_description}</span>
        <span className="puom">шт</span>
        <span className="pnum">
          {editable
            ? <CommitInput value={String(d.qty)} disabled={busy}
                onCommit={v => run(api.updateDemand(d.demand_id, Number(v)))}
                validate={v => Number(v) > 0} />
            : num(d.qty)}
        </span>
        {/* Прибор живёт в тех же колонках, что и его состав: собрано ↔ «Скомплектовано»,
            в работе ↔ «В заказе» (черновые акты — тот же смысл «запущено, ждём»), не
            начато ↔ «Баланс» со знаком минус. «На складе» у прибора пусто намеренно:
            собранный прибор лежит теми же лотами, что породила комплектация, и показать
            его здесь значило бы посчитать дважды. */}
        <Member glyph="notebook" tone="ok" value={dev.done}
          title="собрано — зафиксированные акты комплектации" />
        <span className="pnum sub">—</span>
        <Member glyph="package" tone="wip" value={dev.wip}
          title="в работе — черновые акты комплектации" />
        <span className="pnum">
          <Balance value={-dev.not_started} status={dev.not_started > 0 ? 'to_order' : 'on_order'}
            title="сколько приборов ещё не начато" />
        </span>
        {/* 2026-10-20: кол-во × оценка прибора по составу (по оценке: счета между
            приборами не делятся); оранжевые — Парето по проекту. */}
        <span className="pnum"><Cost cost={d.cost} status={costly ? 'costly' : null} /></span>
        {editable && <span className="act">
          <button className="fh-ctl icon fh-del" title="Убрать прибор из потребности"
            disabled={busy}
            onClick={async () => {
              if (await ask({ title: `Убрать ${d.target_code} из потребности проекта?`,
                verb: 'Убрать', icon: 'ci-trash' })) run(api.deleteDemand(d.demand_id))
            }}>
            <span className="ci ci-trash" /></button>
        </span>}
      </div>
      {open && (d.tree.length === 0
        ? <div className="prow prow--comp prow--empty">
            <span>Состав пуст — задайте BOM прибора.</span>
          </div>
        : children)}
    </>
  )
}

// Дерево BOM в аккордеоне прибора (Ф5b) со сворачиванием подсборок. Узлы-подсборки
// свёрнуты по умолчанию: при раскрытии прибора видно только прямые компоненты, дальше —
// по шевронам. Видимость — общая `visibleTree`; раскрытость живёт в `DevicesGrid`
// (2026-10-20: по ней считается динамический Парето), здесь только видимые строки.
function DeviceTree({ rows, onToggle, costly, acts, openItem }: {
  rows: VisibleNode<DeficitTreeNode>[]; onToggle: (i: number) => void; costly: (i: number) => boolean
  acts: boolean; openItem: (id: number) => void
}) {
  return <>{rows.map(({ n, i, hasChildren, isExp }) =>
    <TreeRow key={i} n={n} hasChildren={hasChildren} expanded={isExp} acts={acts}
      costly={costly(i)} onToggle={() => onToggle(i)} openItem={openItem} />)}</>
}

// Строка дерева. Отступ = глубина. Узел-подсборка: кликабельный шеврон, чисел покрытия
// нет (купить нельзя — деньги и заказ живут на листьях). Лист: баланс, read-only.
function TreeRow({ n, hasChildren, expanded, costly, acts, onToggle, openItem }: {
  n: DeficitTreeNode; hasChildren: boolean; expanded: boolean; costly: boolean; acts: boolean
  onToggle: () => void; openItem: (id: number) => void
}) {
  // +1: дерево живёт под строкой прибора-цели (стаж-ступень). Единственная законная
  // инлайн-ширина во всех вью (Б2а, 2026-07-30): значение ВЫЧИСЛЯЕТСЯ из глубины узла,
  // классом такое не выразить — правил под каждый уровень не заводим.
  const indent = (n.depth + 1) * 18
  return (
    <div className="prow prow--comp">
      <span className="rn" />
      <span className="tree-cell" style={{ paddingLeft: indent }}>
        {hasChildren
          ? <button className="chev" title={expanded ? 'свернуть подсборку' : 'раскрыть подсборку'}
              onClick={onToggle}><Chevron open={expanded} /></button>
          : <span className="tree-lead" />}
        <ItemGlyph native={n.component_native} synced={n.component_synced} locked={n.component_locked} />
        <EntityLink kind="item" id={n.component_id} open={openItem}>{n.component_code}</EntityLink>
      </span>
      <span className="name">{n.component_description}</span>
      <span className="puom">{n.uom}</span>
      <span className="pnum">{num(n.need)}</span>
      {n.is_leaf
        ? <BalanceCells code={n.component_code} need={n.need} kitted={n.kitted ?? 0}
            inStock={n.in_stock ?? 0} onOrder={n.on_order ?? 0} planned={n.planned ?? 0}
            balance={n.balance ?? 0}
            status={n.status ?? 'available'} anomaly={n.anomaly} />
        : <>
            <span className="lbl">подсборка</span>
            <span /><span /><span />
          </>}
      {/* Доля узла в оценке прибора: кол-во в приборе × оценка штуки; тон — динамический
          Парето по фронту аккордеона (раскрытый узел не в счёт). */}
      <span className="pnum"><Cost cost={n.est_cost} status={costly ? 'costly' : null} /></span>
      {acts && <span className="act" />}
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
    return <div className="kit-actions">
      <span className="lbl">Все изделия-приборы уже в потребности.</span></div>
  // Тот же язык добавления, что в строке-призраке таблиц (2026-08-11): заголовок поля
  // вместо ведущей подписи, команда — кнопка-глиф `add` в пару корзине строки.
  return (
    <div className="kit-actions">
      <ItemPicker items={options} value={targetId} onPick={setTargetId} disabled={busy}
        onEnter={submit} placeholder="Прибор…" onClear={() => setTargetId('')}
        notFound="ничего не найдено — прибор должен быть изделием (не компонентом)." />
      <input className="qty-in" value={qty} disabled={busy}
        onChange={e => setQty(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit() }} />
      <button className="fh-ctl icon fh-add" title="Добавить прибор в потребность"
        disabled={busy || !targetId} onClick={submit}>
        <span className="ci ci-add" /></button>
    </div>
  )
}
