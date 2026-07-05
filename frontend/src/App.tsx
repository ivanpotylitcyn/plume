// Каркас витрин (VS Code-подобный): панель режимов (Codicons) + список режима +
// рабочее поле (одно, без вкладок). Навигация по сущностям, проект — ось.
// Строки состояния нет (UI_GUIDE §11). Список режима — единый шаблон (§7).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler, type User, type ProjectRow, type ItemRow,
  type KittingRow, type ReceiptRow, type PurchaseRow, type SupplierRow,
  type TransferRow, type WriteoffRow, type RequisitionRow, type ProcurementRow,
  type InventoryRow } from './api'
import { Login } from './Login'
import { CommandPalette, type PaletteEntry } from './CommandPalette'
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
  const [paletteOpen, setPaletteOpen] = useState(false)

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

  // Палитра ⌘K (§8): глобальный поиск-переход.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault(); setPaletteOpen(o => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

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

  // Записи палитры ⌘K: проекты, изделия и документы — по коду/номеру/названию.
  const paletteEntries = useMemo<PaletteEntry[]>(() => {
    const e: PaletteEntry[] = []
    projects.forEach(p => e.push({ key: `p${p.id}`, code: p.code, name: p.name,
      kind: 'Проект', open: () => openProject(p.id) }))
    items.forEach(i => e.push({ key: `i${i.id}`, code: i.code, name: i.name,
      kind: 'Изделие', open: () => openItem(i.id) }))
    receipts.forEach(r => e.push({ key: `r${r.id}`, code: r.number, name: r.supplier_name,
      kind: 'Поставка', open: () => openReceipt(r.id) }))
    transfers.forEach(t => e.push({ key: `t${t.id}`, code: t.number, name: t.project_code,
      kind: 'Передача', open: () => openTransfer(t.id) }))
    writeoffs.forEach(w => e.push({ key: `w${w.id}`, code: w.number, name: w.project_code,
      kind: 'Списание', open: () => openWriteoff(w.id) }))
    requisitions.forEach(r => e.push({ key: `q${r.id}`, code: r.number, name: r.project_code,
      kind: 'Требование', open: () => openRequisition(r.id) }))
    inventories.forEach(i => e.push({ key: `v${i.id}`, code: i.number, name: i.project_code,
      kind: 'Инвентаризация', open: () => openInventory(i.id) }))
    purchases.forEach(p => e.push({ key: `u${p.id}`, code: `Заказ #${p.id}`, name: p.project_code,
      kind: 'Заказ', open: () => openPurchase(p.id) }))
    kittings.forEach(k => e.push({ key: `k${k.id}`, code: k.target_code, name: k.target_name,
      kind: 'Комплектация', open: () => openKitting(k.id) }))
    return e
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, items, receipts, transfers, writeoffs, requisitions, inventories, purchases, kittings])

  // Гейт аутентификации: загрузка → логин → приложение.
  if (user === undefined)
    return <div className="login-screen"><div className="login-sub">Загрузка…</div></div>
  if (user === null)
    return <Login onSuccess={setUser} />

  return (
    <div className="app">
      <div className="activity">
        {MODES.map(m => (
          <button key={m.mode} className={mode === m.mode ? 'active' : ''}
            title={m.title} onClick={() => setMode(m.mode)}>
            <span className={`ci ci-${m.icon}`} />
          </button>
        ))}
        <span className="spacer" />
        <button className="logout" title={`${user.full_name} — выйти`}
          onClick={doLogout}><span className="ci ci-sign-out" /></button>
      </div>

      <div className="sidebar">
        {mode === 'projects' &&
          <ModeList heading="Проекты" newLabel="＋ Новый проект"
            newSel={sel?.kind === 'new-project'} onNew={() => setSel({ kind: 'new-project' })}
            selId={sel?.kind === 'project' ? sel.id : null}
            onSelect={id => setSel({ kind: 'project', id })}
            rows={[...projects].map(p => ({ id: p.id, code: p.code, name: p.name,
              glyph: p.status === 'closed'
                ? <span className="glyph g-lock">🔒</span>
                : <span className="glyph g-info">○</span> }))} />}

        {mode === 'items' &&
          <ModeList heading="Изделия" newLabel="＋ Новое изделие"
            newSel={sel?.kind === 'new-item'} onNew={() => setSel({ kind: 'new-item' })}
            selId={sel?.kind === 'item' ? sel.id : null}
            onSelect={id => setSel({ kind: 'item', id })}
            rows={[...items].sort((a, b) => a.code.localeCompare(b.code)).map(i => ({
              id: i.id, code: i.code, name: i.name, glyph: <span className={`ci ci-${itemIcon(i.kind)}`} /> }))} />}

        {mode === 'kittings' &&
          <ModeList heading="Комплектации" newLabel="＋ Новая" projectFilter
            newSel={sel?.kind === 'new-kitting'} onNew={() => setSel({ kind: 'new-kitting' })}
            selId={sel?.kind === 'kitting' ? sel.id : null}
            onSelect={id => setSel({ kind: 'kitting', id })}
            rows={[...kittings].reverse().map(k => {
              const gl = KIT_GLYPH[k.status] ?? KIT_GLYPH.cancelled
              return { id: k.id, code: k.target_code, name: `${k.target_name} ${k.project_code}`,
                projectCode: k.project_code, glyph: <span className={`glyph ${gl.cls}`}>{gl.g}</span> }
            })} />}

        {mode === 'receipts' &&
          <ModeList heading="Поставки" newLabel="＋ Новая поставка (УПД)" projectFilter
            newSel={sel?.kind === 'new-receipt'} onNew={() => setSel({ kind: 'new-receipt' })}
            selId={sel?.kind === 'receipt' ? sel.id : null}
            onSelect={id => setSel({ kind: 'receipt', id })}
            rows={[...receipts].reverse().map(r => ({ id: r.id, code: r.number,
              name: `${r.supplier_name} ${r.project_code}`, projectCode: r.project_code,
              glyph: <span className={`glyph ${r.approved ? 'g-lock' : 'g-on_order'}`}>{r.approved ? '🔒' : '●'}</span> }))} />}

        {mode === 'purchases' &&
          <ModeList heading="Заказы" newLabel="＋ Новый заказ" projectFilter
            newSel={sel?.kind === 'new-purchase'} onNew={() => setSel({ kind: 'new-purchase' })}
            selId={sel?.kind === 'purchase' ? sel.id : null}
            onSelect={id => setSel({ kind: 'purchase', id })}
            rows={[...purchases].reverse().map(p => {
              const st = PURCH_ST[p.status] ?? PURCH_ST.draft
              return { id: p.id, code: `Заказ #${p.id}`, name: p.project_code,
                projectCode: p.project_code, glyph: <span className={`glyph ${st.cls}`}>{st.g}</span> }
            })} />}

        {mode === 'transfers' &&
          <ModeList heading="Передачи" newLabel="＋ Новая передача" projectFilter
            newSel={sel?.kind === 'new-transfer'} onNew={() => setSel({ kind: 'new-transfer' })}
            selId={sel?.kind === 'transfer' ? sel.id : null}
            onSelect={id => setSel({ kind: 'transfer', id })}
            rows={[...transfers].reverse().map(t => ({ id: t.id, code: t.number,
              name: t.project_code, projectCode: t.project_code,
              glyph: <span className={`glyph ${t.posted ? 'g-lock' : 'g-on_order'}`}>{t.posted ? '🔒' : '●'}</span> }))} />}

        {mode === 'writeoffs' &&
          <ModeList heading="Списания" newLabel="＋ Новое списание" projectFilter
            newSel={sel?.kind === 'new-writeoff'} onNew={() => setSel({ kind: 'new-writeoff' })}
            selId={sel?.kind === 'writeoff' ? sel.id : null}
            onSelect={id => setSel({ kind: 'writeoff', id })}
            rows={[...writeoffs].reverse().map(w => ({ id: w.id, code: w.number,
              name: `${w.project_code} ${w.reason}`, projectCode: w.project_code,
              glyph: <span className="glyph g-info">○</span> }))} />}

        {mode === 'requisitions' &&
          <ModeList heading="Требования" newLabel="＋ Новое требование" projectFilter
            newSel={sel?.kind === 'new-requisition'} onNew={() => setSel({ kind: 'new-requisition' })}
            selId={sel?.kind === 'requisition' ? sel.id : null}
            onSelect={id => setSel({ kind: 'requisition', id })}
            rows={[...requisitions].reverse().map(r => ({ id: r.id, code: r.number,
              name: r.project_code, projectCode: r.project_code,
              glyph: <span className="glyph g-info">○</span> }))} />}

        {mode === 'procurements' &&
          <ModeList heading="Закупки-план" newLabel="＋ Новая закупка"
            newSel={sel?.kind === 'new-procurement'} onNew={() => setSel({ kind: 'new-procurement' })}
            selId={sel?.kind === 'procurement' ? sel.id : null}
            onSelect={id => setSel({ kind: 'procurement', id })}
            extraTop={
              <div className={'tree-item' + (sel?.kind === 'command' ? ' sel' : '')}
                onClick={() => setSel({ kind: 'command' })}>
                <span className="ci ci-table" />
                <span className="code">Командный свод</span>
              </div>}
            rows={[...procurements].reverse().map(p => {
              const st = PURCH_ST[p.status] ?? PURCH_ST.draft
              return { id: p.id, code: `Закупка #${p.id}`, name: p.note,
                glyph: <span className={`glyph ${st.cls}`}>{st.g}</span> }
            })} />}

        {mode === 'inventories' &&
          <ModeList heading="Инвентаризации" newLabel="＋ Новая инвентаризация" projectFilter
            newSel={sel?.kind === 'new-inventory'} onNew={() => setSel({ kind: 'new-inventory' })}
            selId={sel?.kind === 'inventory' ? sel.id : null}
            onSelect={id => setSel({ kind: 'inventory', id })}
            rows={[...inventories].reverse().map(i => ({ id: i.id, code: i.number,
              name: `${i.project_code} ${i.note}`, projectCode: i.project_code,
              glyph: <span className="glyph g-info">○</span> }))} />}
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
            <DeficitView key={sel.id} projectId={sel.id} items={items}
              closed={p?.status === 'closed'} openItem={openItem}
              openPurchase={id => { reloadPurchases(); openPurchase(id) }}
              onChanged={reloadProjects} />
            <ClosurePanel key={sel.id} projectId={sel.id} openItem={openItem}
              onChanged={() => { reloadProjects(); reloadWriteoffs(); reloadRequisitions() }} />
          </>
        })()}
        {sel?.kind === 'new-project' &&
          <NewProject onCreated={id => { reloadProjects(); openProject(id) }} />}
        {sel?.kind === 'item' && <ItemView itemId={sel.id} items={items}
          openItem={openItem} onChanged={reloadItems} />}
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
        {!sel && <div className="empty">Выберите объект слева · {KBD} — быстрый переход</div>}
      </div>

      {paletteOpen &&
        <CommandPalette entries={paletteEntries} onClose={() => setPaletteOpen(false)} />}
    </div>
  )
}

// Панель режимов (§2): Codicons, монохром. Порядок = как в старой панели.
const MODES: { mode: Mode; icon: string; title: string }[] = [
  { mode: 'projects',     icon: 'project',       title: 'Проекты — дефицит, панель проекта' },
  { mode: 'items',        icon: 'circuit-board', title: 'Изделия — справочник, остатки, состав' },
  { mode: 'kittings',     icon: 'tools',         title: 'Комплектации — сборка, списание под прибор' },
  { mode: 'receipts',     icon: 'inbox',         title: 'Поставки — УПД, рождение лотов' },
  { mode: 'purchases',    icon: 'checklist',     title: 'Заказы — обязательства поставщику' },
  { mode: 'transfers',    icon: 'export',        title: 'Передачи — отгрузка заказчику' },
  { mode: 'writeoffs',    icon: 'trash',         title: 'Списания — выбытие, серый путь' },
  { mode: 'requisitions', icon: 'arrow-swap',    title: 'Требования — отпочкование, постановка на баланс' },
  { mode: 'procurements', icon: 'table',         title: 'Закупки-план — командный свод, order.xlsx' },
  { mode: 'inventories',  icon: 'search',        title: 'Инвентаризации — найденные партии' },
]

// Сочетание для палитры под ОС: мак — ⌘K, остальные — Ctrl+K (слушаем оба, см. эффект выше).
const KBD = /Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘K' : 'Ctrl+K'

// Codicon вида изделия (§7) по kind: изделие — rocket, компонент — chip, материал — beaker.
const ITEM_ICON: Record<string, string> = {
  device: 'rocket', component: 'chip', material: 'beaker',
}
function itemIcon(kind: string): string {
  return ITEM_ICON[kind] ?? 'chip'
}

// Единый список режима (§7): призрачный «＋ Новая…» первым, строка = глиф · моно-код
// (подписи нет), фильтр-строка и — где есть проект — дропдаун по проекту.
interface ListRow { id: number; code: string; name: string; glyph: ReactNode; projectCode?: string }
function ModeList({ heading, newLabel, newSel, onNew, rows, selId, onSelect, projectFilter, extraTop }: {
  heading: string; newLabel: string; newSel: boolean; onNew: () => void
  rows: ListRow[]; selId: number | null; onSelect: (id: number) => void
  projectFilter?: boolean; extraTop?: ReactNode
}) {
  const [q, setQ] = useState('')
  const [proj, setProj] = useState('')
  useEffect(() => { setQ(''); setProj('') }, [heading])

  const projOptions = useMemo(() => {
    if (!projectFilter) return []
    return [...new Set(rows.map(r => r.projectCode).filter((x): x is string => !!x))].sort()
  }, [rows, projectFilter])

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    return rows.filter(r =>
      (!proj || r.projectCode === proj) &&
      (!s || r.code.toLowerCase().includes(s) || r.name.toLowerCase().includes(s)))
  }, [rows, q, proj])

  return (
    <>
      <h2>{heading}</h2>
      <div className="list-filters">
        <input className="list-filter" value={q} placeholder="фильтр — код или название"
          onChange={e => setQ(e.target.value)} />
        {projectFilter && projOptions.length > 1 &&
          <select className="list-proj" value={proj} onChange={e => setProj(e.target.value)}>
            <option value="">все проекты</option>
            {projOptions.map(p => <option key={p} value={p}>{p}</option>)}
          </select>}
      </div>
      <div className="list-scroll">
        {extraTop}
        <div className={'tree-item new' + (newSel ? ' sel' : '')} onClick={onNew}>
          <span className="code">{newLabel}</span>
        </div>
        {shown.map(r => (
          <div key={r.id} className={'tree-item' + (selId === r.id ? ' sel' : '')}
            onClick={() => onSelect(r.id)}>
            {r.glyph}
            <span className="code">{r.code}</span>
          </div>
        ))}
        {shown.length === 0 && <div className="list-empty">ничего не найдено</div>}
      </div>
    </>
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
      <h1 className="title">Новая поставка (УПД)</h1>
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
