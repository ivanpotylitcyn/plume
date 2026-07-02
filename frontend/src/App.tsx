// Каркас витрин (VS Code-подобный): activity-bar + дерево + рабочая область
// (одна, без вкладок) + статус-бар. Навигация по сущностям, проект — ось.
// Волна 2: третий режим «Комплектации» — записываемый кокпит сборки.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type ProjectRow, type ItemRow, type KittingRow, type ReceiptRow,
  type PurchaseRow, type SupplierRow } from './api'
import { DeficitView } from './DeficitView'
import { ItemView } from './ItemView'
import { KittingView } from './KittingView'
import { ReceiptView } from './ReceiptView'
import { PurchaseView, PURCH_ST } from './PurchaseView'

type Mode = 'projects' | 'items' | 'kittings' | 'receipts' | 'purchases'
type Sel =
  | { kind: 'project'; id: number }
  | { kind: 'item'; id: number }
  | { kind: 'kitting'; id: number }
  | { kind: 'new-kitting' }
  | { kind: 'receipt'; id: number }
  | { kind: 'new-receipt' }
  | { kind: 'purchase'; id: number }
  | { kind: 'new-purchase' }
  | null

const KIT_GLYPH: Record<string, { g: string; cls: string }> = {
  wip: { g: '●', cls: 'g-on_order' },
  closed: { g: '✓', cls: 'g-available' },
  cancelled: { g: '○', cls: 'g-info' },
}

export default function App() {
  const [mode, setMode] = useState<Mode>('projects')
  const [projects, setProjects] = useState<ProjectRow[]>([])
  const [items, setItems] = useState<ItemRow[]>([])
  const [kittings, setKittings] = useState<KittingRow[]>([])
  const [receipts, setReceipts] = useState<ReceiptRow[]>([])
  const [purchases, setPurchases] = useState<PurchaseRow[]>([])
  const [sel, setSel] = useState<Sel>(null)

  // История навигации («предыдущая форма»). Пишем сюда любую смену mode/sel
  // единым эффектом (не трогая десятки call-sites); back() восстанавливает. Всё
  // ведётся через window.history.back() → popstate, поэтому браузерный «Назад» и
  // жест Cmd+[ тоже возвращают на предыдущую форму, а не уводят с сайта.
  const [history, setHistory] = useState<{ mode: Mode; sel: Sel }[]>([])
  const prevRef = useRef<{ mode: Mode; sel: Sel } | null>(null)
  const skipRef = useRef(false)   // не записывать эту смену (back / автовыбор)

  const reloadKittings = useCallback(() => api.kittings().then(setKittings), [])
  const reloadReceipts = useCallback(() => api.receipts().then(setReceipts), [])
  const reloadPurchases = useCallback(() => api.purchases().then(setPurchases), [])

  useEffect(() => {
    api.projects().then(ps => {
      setProjects(ps)
      const ext = ps.find(p => p.kind === 'external') ?? ps[0]
      setSel(s => {
        if (s) return s
        skipRef.current = true   // стартовый автовыбор — не пункт истории
        return ext ? { kind: 'project', id: ext.id } : s
      })
    })
    api.items().then(setItems)
    reloadKittings()
    reloadReceipts()
    reloadPurchases()
  }, [reloadKittings, reloadReceipts, reloadPurchases])

  // Записать предыдущее состояние в историю при смене mode/sel + завести запись в
  // браузерной истории (чтобы её «Назад» пришёл к нам через popstate).
  useEffect(() => {
    const cur = { mode, sel }
    if (skipRef.current) { skipRef.current = false; prevRef.current = cur; return }
    const prev = prevRef.current
    if (prev && (prev.mode !== mode || prev.sel !== sel)) {
      setHistory(h => [...h, prev])
      window.history.pushState(null, '')
    }
    prevRef.current = cur
  }, [mode, sel])

  const back = useCallback(() => {
    setHistory(h => {
      if (h.length === 0) return h
      const last = h[h.length - 1]
      skipRef.current = true
      setMode(last.mode)
      setSel(last.sel)
      return h.slice(0, -1)
    })
  }, [])

  // Браузерный «Назад» / Cmd+[ → popstate → откат на предыдущую форму.
  useEffect(() => {
    const onPop = () => back()
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [back])

  // Клавиатурное сокращение: Alt+← (идёт через браузерную историю, синхронно).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key === 'ArrowLeft' && history.length > 0) {
        e.preventDefault()
        window.history.back()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [history.length])

  const openItem = (id: number) => { setMode('items'); setSel({ kind: 'item', id }) }
  const openKitting = (id: number) => { setMode('kittings'); setSel({ kind: 'kitting', id }) }
  const openReceipt = (id: number) => { setMode('receipts'); setSel({ kind: 'receipt', id }) }
  const openPurchase = (id: number) => { setMode('purchases'); setSel({ kind: 'purchase', id }) }

  return (
    <div className="app">
      <div className="activity">
        <button className={mode === 'projects' ? 'active' : ''}
          title="Проекты — дефицит" onClick={() => setMode('projects')}>▣</button>
        <button className={mode === 'items' ? 'active' : ''}
          title="Изделия — остатки" onClick={() => setMode('items')}>≡</button>
        <button className={mode === 'kittings' ? 'active' : ''}
          title="Комплектации — кокпит сборки" onClick={() => setMode('kittings')}>⛭</button>
        <button className={mode === 'receipts' ? 'active' : ''}
          title="Приходы — УПД, рождение лотов" onClick={() => setMode('receipts')}>📥</button>
        <button className={mode === 'purchases' ? 'active' : ''}
          title="Заказы — обязательства, закрытие приходом" onClick={() => setMode('purchases')}>🛒</button>
      </div>

      <div className="sidebar">
        {mode === 'projects' && <>
          <h2>Проекты</h2>
          {projects.map(p => (
            <div key={p.id}
              className={'tree-item' + (sel?.kind === 'project' && sel.id === p.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'project', id: p.id })}>
              <span className="code">{p.code}</span>
              <span className="sub">{p.name}</span>
            </div>
          ))}
        </>}

        {mode === 'items' && <>
          <h2>Изделия</h2>
          {items.map(i => (
            <div key={i.id}
              className={'tree-item' + (sel?.kind === 'item' && sel.id === i.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'item', id: i.id })}>
              <span className="code">{i.code}</span>
              <span className="sub">{i.name}</span>
            </div>
          ))}
        </>}

        {mode === 'kittings' && <>
          <h2>Комплектации</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-kitting' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-kitting' })}>
            <span className="code">＋ Новая</span>
          </div>
          {kittings.map(k => {
            const gl = KIT_GLYPH[k.status] ?? KIT_GLYPH.cancelled
            return (
              <div key={k.id}
                className={'tree-item' + (sel?.kind === 'kitting' && sel.id === k.id ? ' sel' : '')}
                onClick={() => setSel({ kind: 'kitting', id: k.id })}>
                <span className={`glyph ${gl.cls}`}>{gl.g}</span>
                <span className="code">{k.target_code}</span>
                <span className="sub">{k.project_code} ×{k.qty}</span>
              </div>
            )
          })}
        </>}

        {mode === 'receipts' && <>
          <h2>Приходы</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-receipt' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-receipt' })}>
            <span className="code">＋ Новый УПД</span>
          </div>
          {receipts.map(r => (
            <div key={r.id}
              className={'tree-item' + (sel?.kind === 'receipt' && sel.id === r.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'receipt', id: r.id })}>
              <span className={`glyph ${r.approved ? 'g-lock' : 'g-on_order'}`}>{r.approved ? '🔒' : '●'}</span>
              <span className="code">{r.number}</span>
              <span className="sub">{r.project_code} · {r.lines} стр.</span>
            </div>
          ))}
        </>}

        {mode === 'purchases' && <>
          <h2>Заказы</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-purchase' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-purchase' })}>
            <span className="code">＋ Новый заказ</span>
          </div>
          {purchases.map(p => {
            const st = PURCH_ST[p.status] ?? PURCH_ST.draft
            return (
              <div key={p.id}
                className={'tree-item' + (sel?.kind === 'purchase' && sel.id === p.id ? ' sel' : '')}
                onClick={() => setSel({ kind: 'purchase', id: p.id })}>
                <span className={`glyph ${st.cls}`}>{st.g}</span>
                <span className="code">Заказ #{p.id}</span>
                <span className="sub">{p.project_code} · {p.lines} стр.</span>
              </div>
            )
          })}
        </>}
      </div>

      <div className="work">
        <div className="crumb">
          <button className="back" disabled={history.length === 0}
            title="Назад — предыдущая форма (⌥←)"
            onClick={() => window.history.back()}>‹ Назад</button>
        </div>
        {sel?.kind === 'project' &&
          <DeficitView projectId={sel.id} openItem={openItem}
            openPurchase={id => { reloadPurchases(); openPurchase(id) }} />}
        {sel?.kind === 'item' && <ItemView itemId={sel.id} openItem={openItem} />}
        {sel?.kind === 'kitting' &&
          <KittingView kittingId={sel.id} openItem={openItem} onChanged={reloadKittings} />}
        {sel?.kind === 'new-kitting' &&
          <NewKitting projects={projects} items={items}
            onCreated={id => { reloadKittings(); openKitting(id) }} />}
        {sel?.kind === 'receipt' &&
          <ReceiptView receiptId={sel.id} items={items} openItem={openItem}
            openPurchase={openPurchase} onChanged={reloadReceipts} />}
        {sel?.kind === 'new-receipt' &&
          <NewReceipt projects={projects}
            onCreated={id => { reloadReceipts(); openReceipt(id) }} />}
        {sel?.kind === 'purchase' &&
          <PurchaseView purchaseId={sel.id} items={items} openItem={openItem}
            openReceipt={openReceipt} onChanged={reloadPurchases} />}
        {sel?.kind === 'new-purchase' &&
          <NewPurchase projects={projects}
            onCreated={id => { reloadPurchases(); openPurchase(id) }} />}
        {!sel && <div className="empty">Выберите объект слева</div>}
      </div>

      <div className="statusbar">
        <span>plume · волна 4 · записываемый заказ (Purchase)</span>
        <span className="spacer" />
        <span>проектов {projects.length} · изделий {items.length} · комплектаций {kittings.length} · приходов {receipts.length} · заказов {purchases.length}</span>
      </div>
    </div>
  )
}

// Создание новой комплектации: проект + производимый прибор + кол-во образцов.
function NewKitting({ projects, items, onCreated }: {
  projects: ProjectRow[]; items: ItemRow[]; onCreated: (id: number) => void
}) {
  const externalProjects = projects.filter(p => p.kind === 'external')
  const targets = items.filter(i => i.is_manufactured)
  const [projectId, setProjectId] = useState<number | ''>(externalProjects[0]?.id ?? '')
  const [targetId, setTargetId] = useState<number | ''>(targets[0]?.id ?? '')
  const [qty, setQty] = useState('1')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    const n = Number(qty)
    if (!projectId || !targetId || !(n > 0)) { setErr('Заполните проект, прибор и кол-во'); return }
    setBusy(true); setErr(null)
    api.createKitting({ project_id: projectId, target_item_id: targetId, qty: n })
      .then(c => onCreated(c.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новая комплектация</h1>
      <div className="subtitle">Проект + производимый прибор + количество образцов</div>
      <dl className="props">
        <dt>Проект</dt>
        <dd><select className="lot-sel" value={projectId}
          onChange={e => setProjectId(Number(e.target.value))}>
          {externalProjects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
        </select></dd>
        <dt>Прибор</dt>
        <dd><select className="lot-sel" value={targetId}
          onChange={e => setTargetId(Number(e.target.value))}>
          {targets.map(i => <option key={i.id} value={i.id}>{i.code} — {i.name}</option>)}
        </select></dd>
        <dt>Образцов</dt>
        <dd><input className="qty-in" value={qty} onChange={e => setQty(e.target.value)} /></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}

// Создание нового заказа: проект (+ примечание). Строки добавляются в кокпите.
function NewPurchase({ projects, onCreated }: {
  projects: ProjectRow[]; onCreated: (id: number) => void
}) {
  const externalProjects = projects.filter(p => p.kind === 'external')
  const [projectId, setProjectId] = useState<number | ''>(externalProjects[0]?.id ?? '')
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    if (!projectId) { setErr('Выберите проект'); return }
    setBusy(true); setErr(null)
    api.createPurchase({ project_id: projectId, note: note.trim() || undefined })
      .then(c => onCreated(c.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новый заказ</h1>
      <div className="subtitle">Проект-исполнение · строки добавляются в кокпите заказа</div>
      <dl className="props">
        <dt>Проект</dt>
        <dd><select className="lot-sel" value={projectId}
          onChange={e => setProjectId(Number(e.target.value))}>
          {externalProjects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
        </select></dd>
        <dt>Примечание</dt>
        <dd><input className="qty-in" style={{ width: 260 }} value={note}
          placeholder="необязательно" onChange={e => setNote(e.target.value)} /></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}

// Создание нового УПД: поставщик (пикер + быстрое создание) + № + дата + проект.
function NewReceipt({ projects, onCreated }: {
  projects: ProjectRow[]; onCreated: (id: number) => void
}) {
  const [suppliers, setSuppliers] = useState<SupplierRow[]>([])
  const [supplierId, setSupplierId] = useState<number | ''>('')
  const [newSupplier, setNewSupplier] = useState('')
  const [projectId, setProjectId] = useState<number | ''>(
    projects.find(p => p.kind === 'external')?.id ?? '')
  const [number, setNumber] = useState('')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.suppliers().then(ss => {
      setSuppliers(ss)
      setSupplierId(s => s || (ss[0]?.id ?? ''))
    })
  }, [])

  const addSupplier = () => {
    const name = newSupplier.trim()
    if (!name) return
    setBusy(true); setErr(null)
    api.createSupplier({ name })
      .then(s => { setSuppliers(ss => [...ss, s]); setSupplierId(s.id); setNewSupplier('') })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  const create = () => {
    if (!supplierId || !projectId || !number.trim()) {
      setErr('Заполните поставщика, № УПД и проект'); return
    }
    setBusy(true); setErr(null)
    api.createReceipt({ supplier_id: supplierId, project_id: projectId,
      number: number.trim(), date })
      .then(c => onCreated(c.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новый приход (УПД)</h1>
      <div className="subtitle">Поставщик + № УПД + дата + проект-получатель</div>
      <dl className="props">
        <dt>Поставщик</dt>
        <dd>
          <select className="lot-sel" value={supplierId} disabled={busy}
            onChange={e => setSupplierId(e.target.value ? Number(e.target.value) : '')}>
            {suppliers.length === 0 && <option value="">— нет, создайте ниже —</option>}
            {suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          {' '}
          <input className="qty-in" style={{ width: 160 }} value={newSupplier}
            placeholder="новый поставщик…" disabled={busy}
            onChange={e => setNewSupplier(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addSupplier() }} />
          <button className="btn sm" disabled={busy || !newSupplier.trim()}
            onClick={addSupplier}>＋</button>
        </dd>
        <dt>№ УПД</dt>
        <dd><input className="qty-in" style={{ width: 160 }} value={number}
          onChange={e => setNumber(e.target.value)} /></dd>
        <dt>Дата</dt>
        <dd><input className="qty-in" style={{ width: 160 }} type="date" value={date}
          onChange={e => setDate(e.target.value)} /></dd>
        <dt>Проект</dt>
        <dd><select className="lot-sel" value={projectId}
          onChange={e => setProjectId(e.target.value ? Number(e.target.value) : '')}>
          {projects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
        </select></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}
