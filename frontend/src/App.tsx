// Каркас витрин (VS Code-подобный): activity-bar + дерево + рабочая область
// (одна, без вкладок) + статус-бар. Навигация по сущностям, проект — ось.
// Волна 2: третий режим «Комплектации» — записываемый кокпит сборки.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, setUnauthorizedHandler, type User, type ProjectRow, type ItemRow,
  type KittingRow, type ReceiptRow, type PurchaseRow, type SupplierRow,
  type TransferRow, type WriteoffRow, type RequisitionRow, type ProcurementRow,
  type InventoryRow } from './api'
import { Login } from './Login'
import { DeficitView } from './DeficitView'
import { ClosurePanel } from './ClosurePanel'
import { ProjectStockPanel } from './ProjectStockPanel'
import { ItemView } from './ItemView'
import { KittingView } from './KittingView'
import { ReceiptView } from './ReceiptView'
import { PurchaseView, PURCH_ST } from './PurchaseView'
import { ProcurementView } from './ProcurementView'
import { CommandDeficitView } from './CommandDeficitView'
import { TransferView } from './TransferView'
import { WriteoffView } from './WriteoffView'
import { RequisitionView } from './RequisitionView'
import { InventoryView } from './InventoryView'

type Mode = 'projects' | 'items' | 'kittings' | 'receipts' | 'purchases'
  | 'transfers' | 'writeoffs' | 'requisitions' | 'procurements' | 'inventories'
type Sel =
  | { kind: 'project'; id: number }
  | { kind: 'new-project' }
  | { kind: 'item'; id: number }
  | { kind: 'new-item' }
  | { kind: 'kitting'; id: number }
  | { kind: 'new-kitting' }
  | { kind: 'receipt'; id: number }
  | { kind: 'new-receipt' }
  | { kind: 'purchase'; id: number }
  | { kind: 'new-purchase' }
  | { kind: 'transfer'; id: number }
  | { kind: 'new-transfer' }
  | { kind: 'writeoff'; id: number }
  | { kind: 'new-writeoff' }
  | { kind: 'requisition'; id: number }
  | { kind: 'new-requisition' }
  | { kind: 'command' }
  | { kind: 'procurement'; id: number }
  | { kind: 'new-procurement' }
  | { kind: 'inventory'; id: number }
  | { kind: 'new-inventory' }
  | null

const KIT_GLYPH: Record<string, { g: string; cls: string }> = {
  wip: { g: '●', cls: 'g-on_order' },
  closed: { g: '✓', cls: 'g-available' },
  cancelled: { g: '○', cls: 'g-info' },
}

export default function App() {
  // Аутентификация (волна 12): undefined = грузим me(); null = не залогинен → Login.
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const [mode, setMode] = useState<Mode>('projects')
  const [projects, setProjects] = useState<ProjectRow[]>([])
  const [items, setItems] = useState<ItemRow[]>([])
  const [kittings, setKittings] = useState<KittingRow[]>([])
  const [receipts, setReceipts] = useState<ReceiptRow[]>([])
  const [purchases, setPurchases] = useState<PurchaseRow[]>([])
  const [transfers, setTransfers] = useState<TransferRow[]>([])
  const [writeoffs, setWriteoffs] = useState<WriteoffRow[]>([])
  const [requisitions, setRequisitions] = useState<RequisitionRow[]>([])
  const [procurements, setProcurements] = useState<ProcurementRow[]>([])
  const [inventories, setInventories] = useState<InventoryRow[]>([])
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
  const reloadTransfers = useCallback(() => api.transfers().then(setTransfers), [])
  const reloadWriteoffs = useCallback(() => api.writeoffs().then(setWriteoffs), [])
  const reloadRequisitions = useCallback(() => api.requisitions().then(setRequisitions), [])
  const reloadProcurements = useCallback(() => api.procurements().then(setProcurements), [])
  const reloadInventories = useCallback(() => api.inventories().then(setInventories), [])
  const reloadProjects = useCallback(() => api.projects().then(setProjects), [])
  const reloadItems = useCallback(() => api.items().then(setItems), [])

  // На старте: узнать «кто я» + завести хук на протухшую сессию (401 в любом
  // запросе → назад на логин). Регистрируем один раз.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    api.me().then(setUser).catch(() => setUser(null))
  }, [])

  // Данные грузим только под логином (и перезагружаем при смене пользователя).
  useEffect(() => {
    if (!user) return
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
    reloadTransfers()
    reloadWriteoffs()
    reloadRequisitions()
    reloadProcurements()
    reloadInventories()
  }, [user, reloadKittings, reloadReceipts, reloadPurchases, reloadTransfers,
      reloadWriteoffs, reloadRequisitions, reloadProcurements, reloadInventories])

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

  const openProject = (id: number) => { setMode('projects'); setSel({ kind: 'project', id }) }
  const openItem = (id: number) => { setMode('items'); setSel({ kind: 'item', id }) }
  const openKitting = (id: number) => { setMode('kittings'); setSel({ kind: 'kitting', id }) }
  const openReceipt = (id: number) => { setMode('receipts'); setSel({ kind: 'receipt', id }) }
  const openPurchase = (id: number) => { setMode('purchases'); setSel({ kind: 'purchase', id }) }
  const openTransfer = (id: number) => { setMode('transfers'); setSel({ kind: 'transfer', id }) }
  const openWriteoff = (id: number) => { setMode('writeoffs'); setSel({ kind: 'writeoff', id }) }
  const openRequisition = (id: number) => { setMode('requisitions'); setSel({ kind: 'requisition', id }) }
  const openProcurement = (id: number) => { setMode('procurements'); setSel({ kind: 'procurement', id }) }
  const openInventory = (id: number) => { setMode('inventories'); setSel({ kind: 'inventory', id }) }

  const doLogout = () => { api.logout().catch(() => {}); setUser(null) }

  // Гейт аутентификации: загрузка → логин → приложение.
  if (user === undefined)
    return <div className="login-screen"><div className="login-sub">Загрузка…</div></div>
  if (user === null)
    return <Login onSuccess={setUser} />

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
        <button className={mode === 'transfers' ? 'active' : ''}
          title="Передачи — отгрузка заказчику по накладной" onClick={() => setMode('transfers')}>📦</button>
        <button className={mode === 'writeoffs' ? 'active' : ''}
          title="Списания — выбытие из проекта (серый путь)" onClick={() => setMode('writeoffs')}>🗑</button>
        <button className={mode === 'requisitions' ? 'active' : ''}
          title="Требования — отпочкование / постановка на баланс" onClick={() => setMode('requisitions')}>⇄</button>
        <button className={mode === 'procurements' ? 'active' : ''}
          title="Закупки-план — командный свод + order.xlsx" onClick={() => setMode('procurements')}>⛁</button>
        <button className={mode === 'inventories' ? 'active' : ''}
          title="Инвентаризации — найденные партии + ре-материализация" onClick={() => setMode('inventories')}>🔍</button>
        <span className="spacer" />
        <button className="logout" title={`${user.full_name} — выйти`}
          onClick={doLogout}>⏻</button>
      </div>

      <div className="sidebar">
        {mode === 'projects' && <>
          <h2>Проекты</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-project' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-project' })}>
            <span className="code">＋ Новый проект</span>
          </div>
          {projects.map(p => (
            <div key={p.id}
              className={'tree-item' + (sel?.kind === 'project' && sel.id === p.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'project', id: p.id })}>
              {p.status === 'closed' && <span className="glyph g-lock">🔒</span>}
              <span className="code">{p.code}</span>
              <span className="sub">{p.name}</span>
            </div>
          ))}
        </>}

        {mode === 'items' && <>
          <h2>Изделия</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-item' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-item' })}>
            <span className="code">＋ Новое изделие</span>
          </div>
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

        {mode === 'transfers' && <>
          <h2>Передачи</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-transfer' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-transfer' })}>
            <span className="code">＋ Новая передача</span>
          </div>
          {transfers.map(t => (
            <div key={t.id}
              className={'tree-item' + (sel?.kind === 'transfer' && sel.id === t.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'transfer', id: t.id })}>
              <span className={`glyph ${t.posted ? 'g-lock' : 'g-info'}`}>{t.posted ? '🔒' : '📦'}</span>
              <span className="code">{t.number}</span>
              <span className="sub">{t.project_code} · {t.lines} стр.</span>
            </div>
          ))}
        </>}

        {mode === 'writeoffs' && <>
          <h2>Списания</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-writeoff' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-writeoff' })}>
            <span className="code">＋ Новое списание</span>
          </div>
          {writeoffs.map(w => (
            <div key={w.id}
              className={'tree-item' + (sel?.kind === 'writeoff' && sel.id === w.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'writeoff', id: w.id })}>
              <span className="glyph g-info">🗑</span>
              <span className="code">{w.number}</span>
              <span className="sub">{w.project_code} · {w.lines} стр.</span>
            </div>
          ))}
        </>}

        {mode === 'requisitions' && <>
          <h2>Требования</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-requisition' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-requisition' })}>
            <span className="code">＋ Новое требование</span>
          </div>
          {requisitions.map(r => (
            <div key={r.id}
              className={'tree-item' + (sel?.kind === 'requisition' && sel.id === r.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'requisition', id: r.id })}>
              <span className="glyph g-info">⇄</span>
              <span className="code">{r.number}</span>
              <span className="sub">→ {r.project_code} · {r.lines} стр.</span>
            </div>
          ))}
        </>}

        {mode === 'procurements' && <>
          <h2>Закупки-план</h2>
          <div className={'tree-item' + (sel?.kind === 'command' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'command' })}>
            <span className="glyph g-to_order">⛁</span>
            <span className="code">Командный свод</span>
          </div>
          <div className={'tree-item new' + (sel?.kind === 'new-procurement' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-procurement' })}>
            <span className="code">＋ Новая закупка</span>
          </div>
          {procurements.map(p => {
            const st = PURCH_ST[p.status] ?? PURCH_ST.draft
            return (
              <div key={p.id}
                className={'tree-item' + (sel?.kind === 'procurement' && sel.id === p.id ? ' sel' : '')}
                onClick={() => setSel({ kind: 'procurement', id: p.id })}>
                <span className={`glyph ${st.cls}`}>{st.g}</span>
                <span className="code">Закупка #{p.id}</span>
                <span className="sub">{p.lines} поз.{p.note ? ' · ' + p.note : ''}</span>
              </div>
            )
          })}
        </>}

        {mode === 'inventories' && <>
          <h2>Инвентаризации</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-inventory' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-inventory' })}>
            <span className="code">＋ Новая инвентаризация</span>
          </div>
          {inventories.map(i => (
            <div key={i.id}
              className={'tree-item' + (sel?.kind === 'inventory' && sel.id === i.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'inventory', id: i.id })}>
              <span className="glyph g-available">🔍</span>
              <span className="code">{i.number}</span>
              <span className="sub">{i.project_code} · {i.lines} стр.</span>
            </div>
          ))}
        </>}
      </div>

      <div className="work">
        <div className="crumb">
          <button className="back" disabled={history.length === 0}
            title="Назад — предыдущая форма (⌥←)"
            onClick={() => window.history.back()}>‹ Назад</button>
        </div>
        {sel?.kind === 'project' && (() => {
          const p = projects.find(pr => pr.id === sel.id)
          // Внутренние склады (белый/серый) — экран остатков; внешние — дефицит + закрытие.
          if (p && p.kind !== 'external')
            return <ProjectStockPanel key={sel.id} projectId={sel.id}
              projectName={p.name} openItem={openItem} />
          return <>
            <DeficitView projectId={sel.id} openItem={openItem}
              openPurchase={id => { reloadPurchases(); openPurchase(id) }} />
            <ClosurePanel key={sel.id} projectId={sel.id} openItem={openItem}
              onChanged={() => { reloadProjects(); reloadWriteoffs(); reloadRequisitions() }} />
          </>
        })()}
        {sel?.kind === 'new-project' &&
          <NewProject onCreated={id => { reloadProjects(); openProject(id) }} />}
        {sel?.kind === 'item' && <ItemView itemId={sel.id} openItem={openItem} />}
        {sel?.kind === 'new-item' &&
          <NewItem onCreated={id => { reloadItems(); openItem(id) }} />}
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
        {sel?.kind === 'transfer' &&
          <TransferView transferId={sel.id} openItem={openItem} onChanged={reloadTransfers} />}
        {sel?.kind === 'new-transfer' &&
          <NewTransfer projects={projects}
            onCreated={id => { reloadTransfers(); openTransfer(id) }} />}
        {sel?.kind === 'writeoff' &&
          <WriteoffView writeoffId={sel.id} openItem={openItem} onChanged={reloadWriteoffs} />}
        {sel?.kind === 'new-writeoff' &&
          <NewWriteoff projects={projects}
            onCreated={id => { reloadWriteoffs(); openWriteoff(id) }} />}
        {sel?.kind === 'requisition' &&
          <RequisitionView requisitionId={sel.id} openItem={openItem} onChanged={reloadRequisitions} />}
        {sel?.kind === 'new-requisition' &&
          <NewRequisition projects={projects}
            onCreated={id => { reloadRequisitions(); openRequisition(id) }} />}
        {sel?.kind === 'command' &&
          <CommandDeficitView openItem={openItem}
            openProcurement={id => { reloadProcurements(); openProcurement(id) }} />}
        {sel?.kind === 'procurement' &&
          <ProcurementView procurementId={sel.id} items={items} openItem={openItem}
            openPurchase={id => { reloadPurchases(); openPurchase(id) }}
            onChanged={reloadProcurements} />}
        {sel?.kind === 'new-procurement' &&
          <NewProcurement onCreated={id => { reloadProcurements(); openProcurement(id) }} />}
        {sel?.kind === 'inventory' &&
          <InventoryView inventoryId={sel.id} items={items} openItem={openItem}
            onChanged={reloadInventories} />}
        {sel?.kind === 'new-inventory' &&
          <NewInventory projects={projects}
            onCreated={id => { reloadInventories(); openInventory(id) }} />}
        {!sel && <div className="empty">Выберите объект слева</div>}
      </div>

      <div className="statusbar">
        <span>plume · волна 12 · логин / аутентификация · {user.full_name}</span>
        <span className="spacer" />
        <span>проектов {projects.length} · изделий {items.length} · комплектаций {kittings.length} · приходов {receipts.length} · заказов {purchases.length} · передач {transfers.length} · списаний {writeoffs.length} · требований {requisitions.length} · закупок {procurements.length} · инвентаризаций {inventories.length}</span>
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

// Создание нового изделия (справочник, канон «＋ Новое»): артикул + название + вид +
// производимое + ед.изм. + оценочная стоимость (опц.). BOM правится отдельно.
function NewItem({ onCreated }: { onCreated: (id: number) => void }) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [kind, setKind] = useState('component')
  const [manufactured, setManufactured] = useState(false)
  const [uom, setUom] = useState('шт')
  const [cost, setCost] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    if (!code.trim() || !name.trim()) { setErr('Заполните артикул и название'); return }
    setBusy(true); setErr(null)
    api.createItem({ code: code.trim(), name: name.trim(), kind, uom: uom.trim() || 'шт',
      is_manufactured: manufactured, estimated_cost: cost.trim() ? Number(cost) : undefined })
      .then(i => onCreated(i.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новое изделие</h1>
      <div className="subtitle">Справочник · артикул + название + вид · состав (BOM) правится отдельно</div>
      <dl className="props">
        <dt>Артикул</dt>
        <dd><input className="qty-in" style={{ width: 200 }} value={code}
          onChange={e => setCode(e.target.value)} /></dd>
        <dt>Название</dt>
        <dd><input className="qty-in" style={{ width: 300 }} value={name}
          onChange={e => setName(e.target.value)} /></dd>
        <dt>Вид</dt>
        <dd><select className="lot-sel" value={kind} onChange={e => setKind(e.target.value)}>
          <option value="device">Изделие (прибор)</option>
          <option value="component">Компонент</option>
          <option value="material">Материал</option>
        </select></dd>
        <dt>Производимое</dt>
        <dd><input type="checkbox" checked={manufactured}
          onChange={e => setManufactured(e.target.checked)} /> <span className="sub">делаем сами (цель комплектации)</span></dd>
        <dt>Ед. изм.</dt>
        <dd><input className="qty-in" style={{ width: 80 }} value={uom}
          onChange={e => setUom(e.target.value)} /></dd>
        <dt>Оценочная стоимость</dt>
        <dd><input className="qty-in" style={{ width: 120 }} value={cost}
          placeholder="необязательно" onChange={e => setCost(e.target.value)} /></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}

// Создание нового проекта (справочник, канон «＋ Новый»): код + название + бюджет (опц.).
// Только внешний (НИР/контракт); внутренние склады WHITE/GREY — синглтоны из сида.
function NewProject({ onCreated }: { onCreated: (id: number) => void }) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [budget, setBudget] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    if (!code.trim() || !name.trim()) { setErr('Заполните код и название'); return }
    setBusy(true); setErr(null)
    api.createProject({ code: code.trim(), name: name.trim(),
      budget: budget.trim() ? Number(budget) : undefined })
      .then(p => onCreated(p.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новый проект</h1>
      <div className="subtitle">Внешний (НИР/контракт) · потребности и бюджет ведутся дальше</div>
      <dl className="props">
        <dt>Код</dt>
        <dd><input className="qty-in" style={{ width: 200 }} value={code}
          onChange={e => setCode(e.target.value)} /></dd>
        <dt>Название</dt>
        <dd><input className="qty-in" style={{ width: 300 }} value={name}
          onChange={e => setName(e.target.value)} /></dd>
        <dt>Бюджет</dt>
        <dd><input className="qty-in" style={{ width: 140 }} value={budget}
          placeholder="необязательно" onChange={e => setBudget(e.target.value)} /></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}

// Создание новой закупки-плана: без проекта (командная высота), только примечание.
// Строки набираются в кокпите или мостом из командного свода.
function NewProcurement({ onCreated }: { onCreated: (id: number) => void }) {
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    setBusy(true); setErr(null)
    api.createProcurement({ note: note.trim() || undefined })
      .then(c => onCreated(c.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новая закупка-план</h1>
      <div className="subtitle">Планирование (командная высота, без проекта) · позиции — в кокпите или из свода</div>
      <dl className="props">
        <dt>Примечание</dt>
        <dd><input className="qty-in" style={{ width: 260 }} value={note}
          placeholder="контрагент / поток…" onChange={e => setNote(e.target.value)} /></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}

// Создание новой передачи (накладной): проект + № + дата. Строки — в кокпите.
function NewTransfer({ projects, onCreated }: {
  projects: ProjectRow[]; onCreated: (id: number) => void
}) {
  const externalProjects = projects.filter(p => p.kind === 'external')
  const [projectId, setProjectId] = useState<number | ''>(externalProjects[0]?.id ?? '')
  const [number, setNumber] = useState('')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    if (!projectId || !number.trim()) { setErr('Заполните проект и № накладной'); return }
    setBusy(true); setErr(null)
    api.createTransfer({ project_id: projectId, number: number.trim(), date })
      .then(c => onCreated(c.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новая передача</h1>
      <div className="subtitle">Отгрузка заказчику · проект + № накладной · строки в кокпите</div>
      <dl className="props">
        <dt>Проект</dt>
        <dd><select className="lot-sel" value={projectId}
          onChange={e => setProjectId(Number(e.target.value))}>
          {externalProjects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
        </select></dd>
        <dt>№ накладной</dt>
        <dd><input className="qty-in" style={{ width: 160 }} value={number}
          onChange={e => setNumber(e.target.value)} /></dd>
        <dt>Дата</dt>
        <dd><input className="qty-in" style={{ width: 160 }} type="date" value={date}
          onChange={e => setDate(e.target.value)} /></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}

// Создание нового списания: проект + № акта + дата + причина. Строки — в кокпите.
function NewWriteoff({ projects, onCreated }: {
  projects: ProjectRow[]; onCreated: (id: number) => void
}) {
  const externalProjects = projects.filter(p => p.kind === 'external')
  const [projectId, setProjectId] = useState<number | ''>(externalProjects[0]?.id ?? '')
  const [number, setNumber] = useState('')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [reason, setReason] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    if (!projectId || !number.trim()) { setErr('Заполните проект и № акта'); return }
    setBusy(true); setErr(null)
    api.createWriteoff({ project_id: projectId, number: number.trim(), date,
      reason: reason.trim() || undefined })
      .then(c => onCreated(c.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новое списание</h1>
      <div className="subtitle">Выбытие из проекта (серый путь) · проект + № акта · строки в кокпите</div>
      <dl className="props">
        <dt>Проект</dt>
        <dd><select className="lot-sel" value={projectId}
          onChange={e => setProjectId(Number(e.target.value))}>
          {externalProjects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
        </select></dd>
        <dt>№ акта</dt>
        <dd><input className="qty-in" style={{ width: 160 }} value={number}
          onChange={e => setNumber(e.target.value)} /></dd>
        <dt>Дата</dt>
        <dd><input className="qty-in" style={{ width: 160 }} type="date" value={date}
          onChange={e => setDate(e.target.value)} /></dd>
        <dt>Причина</dt>
        <dd><input className="qty-in" style={{ width: 260 }} value={reason}
          placeholder="необязательно" onChange={e => setReason(e.target.value)} /></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}

// Создание нового требования: проект-получатель + № + дата. Источники — в кокпите.
function NewRequisition({ projects, onCreated }: {
  projects: ProjectRow[]; onCreated: (id: number) => void
}) {
  const [projectId, setProjectId] = useState<number | ''>(
    projects.find(p => p.kind === 'internal_stock')?.id ?? projects[0]?.id ?? '')
  const [number, setNumber] = useState('')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    if (!projectId || !number.trim()) { setErr('Заполните проект-получатель и №'); return }
    setBusy(true); setErr(null)
    api.createRequisition({ project_id: projectId, number: number.trim(), date })
      .then(c => onCreated(c.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новое требование</h1>
      <div className="subtitle">Отпочкование в получатель · проект-получатель + № · источники в кокпите</div>
      <dl className="props">
        <dt>Получатель</dt>
        <dd><select className="lot-sel" value={projectId}
          onChange={e => setProjectId(Number(e.target.value))}>
          {projects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
        </select></dd>
        <dt>№ требования</dt>
        <dd><input className="qty-in" style={{ width: 160 }} value={number}
          onChange={e => setNumber(e.target.value)} /></dd>
        <dt>Дата</dt>
        <dd><input className="qty-in" style={{ width: 160 }} type="date" value={date}
          onChange={e => setDate(e.target.value)} /></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}

// Создание новой инвентаризации: проект-дом + № акта + дата + примечание.
// Найденные партии рождаются в кокпите (излишки + ре-материализация серого).
// По умолчанию — GREY «Свободные неучтённые» (флагман — ре-материализация), но
// излишек можно завести и в реальном проекте.
function NewInventory({ projects, onCreated }: {
  projects: ProjectRow[]; onCreated: (id: number) => void
}) {
  const [projectId, setProjectId] = useState<number | ''>(
    projects.find(p => p.kind === 'internal_writeoff')?.id ?? projects[0]?.id ?? '')
  const [number, setNumber] = useState('')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    if (!projectId || !number.trim()) { setErr('Заполните проект-дом и № акта'); return }
    setBusy(true); setErr(null)
    api.createInventory({ project_id: projectId, number: number.trim(), date,
      note: note.trim() || undefined })
      .then(c => onCreated(c.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новая инвентаризация</h1>
      <div className="subtitle">Рождение найденных партий · проект-дом + № акта · строки в кокпите</div>
      <dl className="props">
        <dt>Проект-дом</dt>
        <dd><select className="lot-sel" value={projectId}
          onChange={e => setProjectId(Number(e.target.value))}>
          {projects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
        </select></dd>
        <dt>№ акта</dt>
        <dd><input className="qty-in" style={{ width: 160 }} value={number}
          onChange={e => setNumber(e.target.value)} /></dd>
        <dt>Дата</dt>
        <dd><input className="qty-in" style={{ width: 160 }} type="date" value={date}
          onChange={e => setDate(e.target.value)} /></dd>
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
