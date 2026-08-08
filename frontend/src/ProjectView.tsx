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
  type ResidualLot, type Status } from './api'
import { Balance, Chevron, LotGlyph, balanceTitle, count, money, num,
  ItemGlyph } from './status'
import { ORDER_LABEL, type OrderKind } from './orders'
import { CommitInput } from './CommitInput'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { TextField } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { ColumnFilter } from './ColumnFilter'
import { ItemPicker } from './Picker'
import { Stat, StatGroup, StatPanel, StatWarn } from './StatPanel'

export function ProjectView({ projectId, items, isNew, openItem, openOrder,
  onChanged, onDeleted }:
  { projectId: number; items: ItemRow[]; isNew: boolean
    openItem: (id: number) => void
    openOrder: (kind: OrderKind, id: number) => void   // Ф15: черновики закрытия кликабельны
    onChanged?: () => void; onDeleted?: () => void }) {
  const [data, setData] = useState<Deficit | null>(null)
  const [phead, setPhead] = useState<ProjectDetail | null>(null)  // реквизиты шапки
  const [closure, setClosure] = useState<ProjectClosure | null>(null)   // таб «Склад»
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rev, setRev] = useState(0)      // бюджет пересчитывается при правке потребности
  // Фильтры свода «Потребность» — состояние вью, на сервер не ходят: строки уже все
  // здесь, а вопрос («что не заказано?») меняется чаще, чем данные.
  const [filters, setFilters] = useState<NeedFilters>(NO_FILTERS)
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

  if (err && !data) return <div className="empty">Ошибка: {err}</div>
  if (!data) return <div className="empty">Загрузка…</div>

  const deviceTotal = data.demands.reduce((s, d) => s + d.qty, 0)
  const code = phead?.code ?? data.project_code   // после правки кода — из phead (живо)
  const closed = phead?.locked ?? false           // зафиксирован = закрыт (§5)
  const locked = closed || !unlocked
  // Внешний проект (НИР/контракт) делает приборы; внутренние склады — только хранят.
  const external = phead ? phead.kind === 'external' : true
  const shown = data.components.filter(c => needPass(c, filters))
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
              <CompHead tree />
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
            <CompHead f={{ ...filters,
              set: (k, v) => setFilters(f => ({ ...f, [k]: v })) }} />
            {shown.length === 0
              ? <div className="prow prow--comp prow--empty">
                  <span>Ни одна строка не подходит под фильтры колонок.</span>
                </div>
              : shown.map(c => <CompRow key={c.component_id} ln={c}
                  openItem={openItem} />)}
          </div> },
  )
  tabs.push(
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
                <a className="link" onClick={() => openOrder(d.kind as OrderKind, d.document_id)}>
                  {ORDER_LABEL[d.kind as OrderKind]} {d.code || d.number || `#${d.document_id}`}
                </a>{` (${num(d.qty)})`}
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
        <a className="link" onClick={() => openItem(r.item_id)}>{r.item_code}</a></td>
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

// Шапка колонок (общая для «Приборов» в раскрытии и «Потребности»). Совпадает по
// сетке со строкой прибора: код↔Компонент, потребность↔Потребность.
//
// Пять чисел вместо трёх сегментов разбора (2026-08-05). Разбор клампован потребностью,
// поэтому перебор в нём невидим: заказали 10 при нужде 6 — сегмент всё равно 6. Здесь
// все члены сырые, а «Баланс» — их невязка со знаком: минус не хватает, плюс запас.
// Порядок колонок = убывающая готовность (впаяно → лежит → едет → нет), то есть прежняя
// ось ✓●▲, разложенная на четыре члена.
//
// «Ед.» стоит ПЕРЕД числами: единица квалифицирует всю строку — все пять чисел в ней
// одной размерности, — а не примыкает к одному числу (отступление от §7a, решение
// Ивана 2026-08-05; раскатка на остальные таблицы отложена в бэклог).
// Заголовки сокращены до 4–6 знаков (2026-08-05): полное «Скомплектовано» распирало
// колонку под слово, которое ни одно число не заполняет. Полная версия — под курсором.
// ─── Фильтры колонок свода «Потребность» (2026-08-05) ───
//
// Свод — это весь закупочный состав проекта, сотни строк; вопросы к нему всегда узкие:
// «что не заказано», «что уже лежит», «где перебор». Поэтому фильтр живёт в ЗАГОЛОВКЕ
// колонки — там же, где число, к которому он относится, — и не заводит отдельной
// панели над таблицей. Знак — тот же раскрыватель, что везде в продукте.
//
// Словарь значений: у членов «есть/пусто» (наличие), у баланса — три его состояния,
// названные тем же языком, каким мы говорим о них в подсказках и журнале: не хватает /
// впритык / запас.
type MemberFilter = 'any' | 'zero' | 'some'
type BalanceFilter = 'any' | 'short' | 'even' | 'surplus'

const MEMBER_OPTS: [string, string][] = [
  ['any', 'все'], ['some', 'есть'], ['zero', 'пусто'],
]
const BALANCE_OPTS: [string, string][] = [
  ['any', 'все'], ['short', 'не хватает'], ['even', 'впритык'], ['surplus', 'запас'],
]

export interface NeedFilters {
  kitted: MemberFilter; in_stock: MemberFilter; on_order: MemberFilter
  balance: BalanceFilter
}
const NO_FILTERS: NeedFilters = {
  kitted: 'any', in_stock: 'any', on_order: 'any', balance: 'any',
}
interface FilterBar extends NeedFilters {
  set: (key: keyof NeedFilters, value: string) => void
}

function memberPass(v: number, f: MemberFilter) {
  return f === 'any' || (f === 'zero' ? v === 0 : v !== 0)
}

function needPass(c: DeficitComponent, f: NeedFilters) {
  return memberPass(c.kitted, f.kitted)
    && memberPass(c.in_stock, f.in_stock)
    && memberPass(c.on_order, f.on_order)
    && (f.balance === 'any'
      || (f.balance === 'short' ? c.balance < 0
        : f.balance === 'even' ? c.balance === 0 : c.balance > 0))
}

// `filters` — только у свода «Потребность»: в аккордеоне прибора фильтровать нечего
// (там состав одного изделия, и дыры в дереве читались бы как ошибка состава).
function CompHead({ f, tree }: { f?: FilterBar; tree?: boolean }) {
  return (
    <div className={'prow prow--head' + (tree ? ' head--tree' : '')}>
      <span className="tree-cell">Код</span>
      <span>Описание</span>
      <span className="pnum" title="потребность: разузлование BOM на все приборы проекта">
        Потр.</span>
      <span className="pnum" title="скомплектовано: впаяно в изделия проекта">
        Компл.{f && <ColumnFilter opts={MEMBER_OPTS} value={f.kitted}
          onPick={v => f.set('kitted', v)} />}</span>
      <span className="pnum" title="на складе: остаток лотов проекта">
        Склад{f && <ColumnFilter opts={MEMBER_OPTS} value={f.in_stock}
          onPick={v => f.set('in_stock', v)} />}</span>
      <span className="pnum" title="в заказе: ещё не приехало по зафиксированным заказам">
        Заказ{f && <ColumnFilter opts={MEMBER_OPTS} value={f.on_order}
          onPick={v => f.set('on_order', v)} />}</span>
      <span className="pnum" title="баланс: (компл. + склад + заказ) − потребность">
        Баланс{f && <ColumnFilter opts={BALANCE_OPTS} value={f.balance}
          onPick={v => f.set('balance', v)} />}</span>
      <span className="puom" title="единица измерения строки">Ед.</span>
      {tree && <span />}
    </div>
  )
}

// Число члена баланса с глифом ПОСЛЕ него (правка Ивана 2026-08-05). Глиф впереди
// плясал по горизонтали: числа разной ширины при выключке вправо сдвигали его на
// каждой строке, и колонка глифов шла зигзагом. За числом он встаёт на правую кромку —
// вертикальный строй ровный, а числа по-прежнему выключены вправо.
//
// Форма глифа — вид члена (что это), цвет — его роль в покрытии: впаяно и склад
// зелёные (нужда закрыта), заказ оранжевый (закрыта обещанием). НОЛЬ гасим до
// нейтрального: глиф светит, когда за ним что-то есть, иначе колонка нулей шумит.
function Member({ glyph, tone, value, title }: {
  glyph: string; tone: string; value: number; title: string
}) {
  return (
    <span className="pnum" title={title}>
      {num(value)}<span className={`ci sg ci-${glyph} sg-${value ? tone : 'none'}`} />
    </span>
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
          <a className="link" onClick={() => openItem(d.target_id)}>{d.target_code}</a>
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

// Числовой хвост строки-листа: четыре члена + баланс. Один и тот же в дереве прибора и
// в сводной «Потребности» — колонки обязаны совпадать, поэтому и разметка одна.
function BalanceCells({ code, need, kitted, inStock, onOrder, balance, status, anomaly }: {
  code: string; need: number; kitted: number; inStock: number; onOrder: number
  balance: number; status: Status; anomaly?: boolean
}) {
  return (
    <>
      <Member glyph="notebook" tone="ok" value={kitted}
        title="впаяно в изделия проекта (зафиксированные комплектации)" />
      <span className="pnum" title="остаток лотов проекта на складах">
        {num(inStock)}
        {anomaly && <span className="anomaly" title="есть лот с отрицательным остатком">▲</span>}
        <span className={`ci sg ci-layers sg-${inStock ? 'ok' : 'none'}`} />
      </span>
      <Member glyph="package" tone="wip" value={onOrder}
        title="ещё не приехало по зафиксированным заказам проекта" />
      <span className="pnum">
        <Balance value={balance} status={status}
          title={balanceTitle(code, need, kitted, inStock, onOrder)} />
      </span>
    </>
  )
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
        <a className="link" onClick={() => openItem(n.component_id)}>{n.component_code}</a>
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

// Строка компонента в сводной «Потребности»: те же пять чисел, read-only. Кнопки
// «＋ в заказ» здесь больше нет (2026-08-05) — набивка заказов живёт в «Привязке»
// закупки, где рядом стоит остаток плана; вкладки проекта кнопками не засоряем.
function CompRow({ ln, openItem }: {
  ln: DeficitComponent; openItem: (id: number) => void
}) {
  return (
    <div className="prow prow--comp">
      <span className="tree-cell">
        <ItemGlyph native={ln.component_native} synced={ln.component_synced} locked={ln.component_locked} />
        <a className="link" onClick={() => openItem(ln.component_id)}>{ln.component_code}</a>
      </span>
      <span className="name">{ln.component_description}</span>
      <span className="pnum">{num(ln.need)}</span>
      <BalanceCells code={ln.component_code} need={ln.need} kitted={ln.kitted}
        inStock={ln.in_stock} onOrder={ln.on_order} balance={ln.balance}
        status={ln.status} anomaly={ln.anomaly} />
      <span className="puom">{ln.uom}</span>
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
      <span className="lbl">＋ прибор: все изделия-приборы уже в потребности.</span></div>
  return (
    <div className="kit-actions">
      <span className="lbl">＋ прибор</span>
      <ItemPicker items={options} value={targetId} onPick={setTargetId} disabled={busy}
        onEnter={submit}
        notFound="ничего не найдено — прибор должен быть изделием (не компонентом)." />
      <input className="qty-in" value={qty} disabled={busy}
        onChange={e => setQty(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit() }} />
      <button className="btn sm" disabled={busy || !targetId} onClick={submit}>добавить</button>
    </div>
  )
}
