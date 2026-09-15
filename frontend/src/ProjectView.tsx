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
import { useEffect, useState } from 'react'
import { api, type Budget, type Deficit, type DeficitDemand,
  type DeficitTreeNode, type ItemRow, type ProjectClosure, type ProjectDetail,
  type ProjectSupply, type ResidualLot } from './api'
import { Balance, Chevron, LotGlyph, count, money, num, ItemGlyph } from './status'
import { ORDER_LABEL, type OrderKind } from './orders'
import { CommitInput } from './CommitInput'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { TextField } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { PurchaseFeed, ReceiptFeed } from './FeedTables'
import { BalanceCells, Member, NeedHead, NeedRow, needPass,
  useNeedFilters } from './NeedTable'
import { useCategoryFilter } from './ColumnFilter'
import { ItemPicker } from './Picker'
import { Stat, StatGroup, StatPanel, StatWarn } from './StatPanel'
import { EntityLink } from './EntityLink'

export function ProjectView({ projectId, items, isNew, openItem, openOrder, openPurchase,
  openCounterparty, onChanged, onDeleted }:
  { projectId: number; items: ItemRow[]; isNew: boolean
    openItem: (id: number) => void
    openOrder: (kind: OrderKind, id: number) => void   // Ф15: черновики закрытия кликабельны
    openPurchase: (id: number) => void                 // лента «Заказы» — свой режим
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
  const del = () => {
    if (!confirm('Удалить проект? Возможно только для пустого проекта. Действие необратимо.')) return
    setBusy(true); setErr(null)
    api.deleteProject(projectId).then(() => { onChanged?.(); onDeleted?.() })
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
  const shown = byCat.shown.filter(c => needPass(c, filters))
  const residuals = closure?.residuals ?? []
  const drafts = closure?.closing_drafts ?? []   // Ф15: закрывающие документы-черновики

  const tabs: FormTab[] = []
  if (external) tabs.push(
    { key: 'devices', label: 'Приборы', icon: 'rocket',
      content: <>
        {data.demands.length === 0
          ? <div className="tab-empty">
              {locked ? 'Приборов нет.' : 'Пока ничего — добавьте прибор ниже.'}</div>
          : <div className="pgrid pgrid--acts">
              <NeedHead lead="Прибор" tree acts />
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
            <NeedHead f={filters} catHead={byCat.head} />
            {shown.length === 0
              ? <div className="prow prow--comp prow--empty">
                  <span>Ни одна строка не подходит под фильтры колонок.</span>
                </div>
              : shown.map(c => <NeedRow key={c.component_id} ln={c}
                  openItem={openItem} />)}
          </div> },
  )
  // Закупочный контур проекта — двумя лентами того же вида, что в форме контрагента
  // (`FeedTables`): разрез другой, строка та же. Стоят между «Потребностью» и «Складом»
  // по потоку жизни: что надо → что заказали → что приехало → что лежит. Табы есть у
  // ЛЮБОГО проекта, включая внутренние склады (решение Ивана 2026-08-28): набор табов
  // предсказуем, у склада они просто пусты. Ленты только читают — заказ и поставку
  // заводят в своих режимах.
  tabs.push(
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
                <th className="gl" /><th className="c-key">Партия</th>
                <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
                <th className="num">Остаток</th><th className="uom">Ед.</th>
                {!locked && <th className="act" />}
              </tr></thead>
              <tbody>
                {residuals.map(r => (
                  <ResidualRow key={r.lot_id} r={r} projectId={projectId} locked={locked}
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
        {external && <>
          {/* Приборы считаем ШТУКАМИ, а не строками потребности (2026-08-28): проект
              делает 8 образцов, и это число, которым живёт НИР. Наименования идут
              ВТОРЫМ числом и в родительном падеже — «8 образцов 4 приборов» читается
              одной фразой, тогда как «4 прибора · 8 шт» было двумя сегментами про одно
              и то же, да ещё и менее важным вперёд. Родительный: 1 → «прибора»,
              остальные → «приборов» (21 прибора, 11 приборов). */}
          {count(deviceTotal, 'образец', 'образца', 'образцов')}
          {' '}{count(data.demands.length, 'прибора', 'приборов', 'приборов')}
          {' · '}{count(data.components.length, 'компонент', 'компонента', 'компонентов')}
          {' · '}
        </>}
        {count(supply?.purchases.length ?? 0, 'заказ', 'заказа', 'заказов')}
        {' · '}{count(supply?.receipts.length ?? 0, 'поставка', 'поставки', 'поставок')}
        {' · '}{count(residuals.length, 'партия', 'партии', 'партий')}
        {(closure?.anomaly_count ?? 0) > 0 &&
          <span className="anomaly"> · {closure!.anomaly_count} в минусе</span>}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
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
        <TextField label="Код" value={phead?.code ?? code} locked={locked}
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
function ResidualRow({ r, projectId, locked, busy, openItem, run }: {
  r: ResidualLot; projectId: number; locked: boolean; busy: boolean
  openItem: (id: number) => void; run: (p: Promise<ProjectClosure>) => void
}) {
  const positive = r.live_qty > 0
  return (
    <tr className="row">
      <td className="gl"><LotGlyph origin={r.origin} liveQty={r.live_qty} /></td>
      <td className="c-key"><span className="code">{r.lot_label}</span></td>
      <td className="c-fit">
        <EntityLink kind="item" id={r.item_id} open={openItem}>{r.item_code}</EntityLink></td>
      <td className="c-desc">
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
// Волна 20: вёрстка статов уехала в общий `StatPanel` (её взяла вторая форма) — здесь
// осталась только начинка, то есть сам смысл панели.
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
    <StatPanel>
      <StatGroup>
        <Stat label="потрачено (факт)" value={money(b.spent)} />
        <Stat label="план (прогноз)" value={money(b.plan)} />
        {b.budget !== null
          ? <Stat label="бюджет на материалы" value={money(b.budget)} />
          : <Stat label="бюджет на материалы" value="— не задан" dim />}
        {b.compass !== null &&
          <Stat label={over ? 'перерасход' : 'запас бюджета'}
            value={money(Math.abs(b.compass))} tone={over ? 'bad' : 'ok'} />}
      </StatGroup>
      <StatGroup aside>
        <Stat label="себестоимость (для КП)" value={money(b.cost)} />
        <Stat label="экономия (польза заёма)" value={money(b.economy)}
          tone={b.economy > 0 ? 'ok' : b.economy < 0 ? 'bad' : undefined} />
      </StatGroup>
      {b.unestimated.length > 0 &&
        <StatWarn title={`нет estimated_cost: ${b.unestimated.join(', ')}`}>
          ▲ {b.unestimated.length} поз. без оценки — план неполон
        </StatWarn>}
    </StatPanel>
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
      <div className="prow prow--device">
        <span className="tree-cell">
          <button className="chev" title={open ? 'свернуть' : 'раскрыть состав'}
            onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
          <ItemGlyph native={d.target_native} synced={d.target_synced} locked={d.target_locked} />
          <EntityLink kind="item" id={d.target_id} open={openItem}>{d.target_code}</EntityLink>
        </span>
        <span className="name">{d.target_description}</span>
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
        <span className="puom">шт</span>
        <span className="act">
          {editable &&
            <button className="fh-ctl icon fh-del" title="Убрать прибор из потребности"
              disabled={busy}
              onClick={() => { if (confirm(`Убрать ${d.target_code} из потребности проекта?`)) run(api.deleteDemand(d.demand_id)) }}>
              <span className="ci ci-trash" /></button>}
        </span>
      </div>
      {open && (d.tree.length === 0
        ? <div className="prow prow--comp prow--empty">
            <span>Состав пуст — задайте BOM прибора.</span>
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

// Строка дерева. Отступ = глубина. Узел-подсборка: кликабельный шеврон, чисел покрытия
// нет (купить нельзя — деньги и заказ живут на листьях). Лист: баланс, read-only.
function TreeRow({ n, hasChildren, expanded, onToggle, openItem }: {
  n: DeficitTreeNode; hasChildren: boolean; expanded: boolean
  onToggle: () => void; openItem: (id: number) => void
}) {
  // +1: дерево живёт под строкой прибора-цели (стаж-ступень). Единственная законная
  // инлайн-ширина во всех вью (Б2а, 2026-07-30): значение ВЫЧИСЛЯЕТСЯ из глубины узла,
  // классом такое не выразить — правил под каждый уровень не заводим.
  const indent = (n.depth + 1) * 18
  return (
    <div className="prow prow--comp">
      <span className="tree-cell" style={{ paddingLeft: indent }}>
        {hasChildren
          ? <button className="chev" title={expanded ? 'свернуть подсборку' : 'раскрыть подсборку'}
              onClick={onToggle}><Chevron open={expanded} /></button>
          : <span className="tree-lead" />}
        <ItemGlyph native={n.component_native} synced={n.component_synced} locked={n.component_locked} />
        <EntityLink kind="item" id={n.component_id} open={openItem}>{n.component_code}</EntityLink>
      </span>
      <span className="name">{n.component_description}</span>
      <span className="pnum">{num(n.need)}</span>
      {n.is_leaf
        ? <BalanceCells code={n.component_code} need={n.need} kitted={n.kitted ?? 0}
            inStock={n.in_stock ?? 0} onOrder={n.on_order ?? 0} balance={n.balance ?? 0}
            status={n.status ?? 'available'} anomaly={n.anomaly} />
        : <>
            <span className="lbl">подсборка</span>
            <span /><span /><span />
          </>}
      <span className="puom">{n.uom}</span>
      <span className="act" />
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
