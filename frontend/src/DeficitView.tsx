// Форма проекта (внешний): три секции — «Приборы» (что делаем, редактируемо + прогресс),
// «Потребность» (полная картина по компонентам на весь проект) и «Склад проекта»
// (ClosurePanel, ниже в App). Секция «Приборы» — редактор ProjectDemand: список
// приборов с инлайн-правкой кол-ва, аккордеон раскрывает дефицит по конкретному прибору.
import { useEffect, useState } from 'react'
import { api, type Budget, type Deficit, type DeficitComponent, type DeficitDemand,
  type ItemRow, type ProjectDetail } from './api'
import { Segment, money, num } from './status'
import { CommitInput } from './ReceiptView'
import { useFormLock } from './FormHeader'

export function DeficitView({ projectId, items, closed, openItem, openPurchase, onChanged }:
  { projectId: number; items: ItemRow[]; closed: boolean
    openItem: (id: number) => void; openPurchase: (id: number) => void
    onChanged?: () => void }) {
  const [data, setData] = useState<Deficit | null>(null)
  const [phead, setPhead] = useState<ProjectDetail | null>(null)  // реквизиты шапки
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rev, setRev] = useState(0)      // бюджет пересчитывается при правке потребности
  const { unlocked, toggle } = useFormLock(false)   // замок §5: реквизиты правим открыв

  useEffect(() => {
    setData(null); setPhead(null); setErr(null)
    api.deficit(projectId).then(setData).catch(e => setErr(String(e)))
    api.project(projectId).then(setPhead).catch(() => {})
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

  // Мост «дефицит → заказ»: положить ▲-позицию в черновик-заказ проекта и открыть его.
  const order = (itemId: number, qty: number) => {
    setBusy(true)
    api.addToOrder(projectId, { item_id: itemId, qty })
      .then(r => openPurchase(r.purchase_id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !data) return <div className="empty">Ошибка: {err}</div>
  if (!data) return <div className="empty">Загрузка…</div>

  const deviceTotal = data.demands.reduce((s, d) => s + d.qty, 0)
  const unitsTotal = data.components.reduce((s, c) => s + c.need, 0)
  const name = phead?.name ?? data.project_name
  return (
    <div>
      <div className="proj-head">
        <h1 className="title"><span className="pn">{data.project_code}</span> <span className="lit">— {name}</span></h1>
        <div className="fh-right">
          {err
            ? <span className="save-ind error">ошибка: {err}</span>
            : unlocked
              ? <span className="save-ind editing">● редактируется</span>
              : <span className="save-ind saved">✓ сохранено</span>}
          <button className={'lock-btn' + (unlocked ? ' open' : '')}
            title={unlocked ? 'Форма открыта — правятся реквизиты. Закрыть'
                            : 'Открыть правку реквизитов проекта (название, бюджет, старт)'}
            onClick={toggle}>{unlocked ? '🔓' : '🔒'}</button>
        </div>
      </div>
      {unlocked && phead &&
        <div className="hdr-edit">
          <label>название <CommitInput value={phead.name} width={260} disabled={busy}
            onCommit={v => runP(api.updateProject(projectId, { name: v }))}
            validate={v => v.trim() !== ''} /></label>
          <label>бюджет на материалы <CommitInput
            value={phead.budget != null ? String(phead.budget) : ''} width={120} disabled={busy}
            onCommit={v => runP(api.updateProject(projectId, { budget: v.trim() === '' ? null : Number(v) }))}
            validate={v => v.trim() === '' || Number(v) >= 0} /> ₽</label>
          <label>начат <CommitInput value={phead.started_at ?? ''} width={140} type="date"
            disabled={busy}
            onCommit={v => runP(api.updateProject(projectId, { started_at: v || null }))} /></label>
        </div>}
      <div className="subtitle">Проект · приборы, потребность, склад · дефицит = надо − склад − заказано (1 уровень BOM)</div>
      <BudgetPanel projectId={projectId} rev={rev} />

      <div className="section-h">Приборы
        <span className="hint">типов приборов {data.demands.length} · всего приборов {num(deviceTotal)}</span></div>
      {data.demands.length === 0
        ? <div style={{ color: 'var(--fg-dim)' }}>Пока ничего — добавьте прибор ниже.</div>
        : <div className="pgrid">
            <CompHead />
            {data.demands.map(d => <DeviceRow key={d.demand_id} d={d} closed={closed}
              busy={busy} openItem={openItem} order={order} run={run} />)}
          </div>}
      {!closed && <AddDevice items={items} demands={data.demands} busy={busy}
        add={(target_item_id, qty) => run(api.addDemand(projectId, { target_item_id, qty }))} />}
      {err && <div className="anomaly">{err}</div>}

      <div className="section-h">Потребность
        <span className="hint">типов компонентов {data.components.length} · всего штук {num(unitsTotal)}</span></div>
      {data.components.length === 0
        ? <div style={{ color: 'var(--fg-dim)' }}>Нет компонентов — задайте приборы и их составы.</div>
        : <div className="pgrid">
            <CompHead />
            {data.components.map(c => <CompRow key={c.component_id} ln={c}
              busy={busy} openItem={openItem} order={order} />)}
          </div>}
    </div>
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
    <div className="budget">
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
      <span />
      <span>Компонент</span>
      <span>Назв.</span>
      <span className="pnum">Надо</span>
      <span>Разбор</span>
      <span className="pnum">Склад</span>
      <span />
    </div>
  )
}

// Прибор в потребности: строка в том же шаблоне колонок, что и его состав.
// Статус — тонкой полосой слева (без ведущего глифа); название серым. Клик по
// шеврону раскрывает аккордеон с дефицитом по этому прибору.
function DeviceRow({ d, closed, busy, openItem, order, run }: {
  d: DeficitDemand; closed: boolean; busy: boolean
  openItem: (id: number) => void
  order: (itemId: number, qty: number) => void; run: (p: Promise<Deficit>) => void
}) {
  const [open, setOpen] = useState(false)
  const dev = d.device
  return (
    <>
      <div className={`prow prow--device s-${d.status}`}>
        <button className="chev" title={open ? 'свернуть' : 'раскрыть дефицит'}
          onClick={() => setOpen(o => !o)}>{open ? '▾' : '▸'}</button>
        <a className="link" onClick={() => openItem(d.target_id)}>{d.target_code}</a>
        <span className="name">{d.target_name}</span>
        <span className="pnum">
          <CommitInput value={String(d.qty)} width={56} disabled={closed || busy}
            onCommit={v => run(api.updateDemand(d.demand_id, Number(v)))}
            validate={v => Number(v) > 0} />
        </span>
        <span title="сделано / делается / осталось сделать">
          <Segment status="available" value={dev.done} />
          <Segment status="on_order" value={dev.wip} />
          <Segment status="to_order" value={dev.not_started} />
        </span>
        <span />
        <span className="act">
          {!closed &&
            <button className="x" title="убрать прибор из потребности" disabled={busy}
              onClick={() => { if (confirm(`Убрать ${d.target_code} из потребности проекта?`)) run(api.deleteDemand(d.demand_id)) }}>×</button>}
        </span>
      </div>
      {open && (d.lines.length === 0
        ? <div className="prow prow--comp" style={{ color: 'var(--fg-dim)' }}>
            <span /><span style={{ gridColumn: '2 / -1' }}>Состав пуст — задайте BOM прибора.</span>
          </div>
        : d.lines.map(ln => <CompRow key={ln.component_id} ln={ln}
            busy={busy} openItem={openItem} order={order} />))}
    </>
  )
}

// Строка компонента: разбор ✓/●/▲ + «＋ в заказ». Общая для аккордеона и сводной.
function CompRow({ ln, busy, openItem, order }: {
  ln: DeficitComponent; busy: boolean; openItem: (id: number) => void
  order: (itemId: number, qty: number) => void
}) {
  return (
    <div className={`prow prow--comp s-${ln.status}`}>
      <span />
      <a className="link" onClick={() => openItem(ln.component_id)}>{ln.component_code}</a>
      <span className="name">{ln.component_name}</span>
      <span className="pnum">{num(ln.need)} {ln.uom}</span>
      <span>
        <Segment status="available" value={ln.have} />
        <Segment status="on_order" value={ln.on_order} />
        <Segment status="to_order" value={ln.to_order} />
      </span>
      <span className="pnum">
        {num(ln.available_raw)}
        {ln.anomaly && <span className="anomaly" title="есть лот с отрицательным остатком">▲</span>}
      </span>
      <span className="act">
        {ln.to_order > 0 &&
          <button className="btn sm" disabled={busy}
            title={`положить ${num(ln.to_order)} ${ln.uom} в черновик-заказ проекта`}
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
  const options = items.filter(i => i.kind === 'device' && !taken.has(i.id))
  const [targetId, setTargetId] = useState<number | ''>('')
  const [qty, setQty] = useState('1')
  useEffect(() => { setTargetId(options[0]?.id ?? '') }, [options.map(o => o.id).join()])

  const submit = () => {
    const n = Number(qty)
    if (!targetId || !(n > 0)) return
    add(targetId, n)
  }

  if (options.length === 0)
    return <div className="kit-actions" style={{ marginTop: 10, color: 'var(--fg-dim)', fontSize: 12 }}>
      ＋ прибор: все изделия-приборы уже в потребности.</div>
  return (
    <div className="kit-actions" style={{ marginTop: 10 }}>
      <span style={{ color: 'var(--fg-dim)', fontSize: 12 }}>＋ прибор</span>
      <select className="lot-sel" value={targetId} disabled={busy}
        onChange={e => setTargetId(Number(e.target.value))}>
        {options.map(i => <option key={i.id} value={i.id}>{i.code} — {i.name}</option>)}
      </select>
      <input className="qty-in" value={qty} disabled={busy}
        onChange={e => setQty(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit() }} />
      <button className="btn sm" disabled={busy} onClick={submit}>добавить</button>
    </div>
  )
}
