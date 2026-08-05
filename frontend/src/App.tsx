// Каркас витрин (VS Code-подобный): панель режимов (Codicons) + список режима +
// рабочее поле (одно, без вкладок). Навигация по сущностям, проект — ось.
// Строки состояния нет (UI_GUIDE §11). Список режима — единый шаблон (§7).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler, type User, type ProjectRow, type ItemRow,
  type KittingRow, type ReceiptRow, type PurchaseRow,
  type TransferRow, type WriteoffRow, type RequisitionRow, type ProcurementRow,
  type InventoryRow, type RelocationRow, type LocationRow,
  type CounterpartyRow } from './api'
import { Login } from './Login'
import { Dropdown } from './Dropdown'
import { CommandPalette, type PaletteEntry } from './CommandPalette'
import { ProjectView } from './ProjectView'
import { ItemView } from './ItemView'
import { LibraryImportView } from './LibraryImportView'
import { PurchaseView } from './PurchaseView'
import { ProcurementView } from './ProcurementView'
import { OrderForm } from './OrderForm'
import { ORDER_KINDS, ORDER_LABEL, type OrderKind } from './orders'
import { LocationView } from './LocationView'
import { CounterpartyView } from './CounterpartyView'
import { AccountView } from './AccountView'
import { applyTheme } from './core/theme'
import { StatusGlyph, SyncGlyph, statusTone } from './status'
import { AnchoredMenu } from './AnchoredMenu'

// Волна 13, Ф1b (флагман): 6 складских документов свёрнуты в один режим «Ордера».
// Их detail-вьюхи остаются раздельными (диспетчер по kind), но список/иконка/форма
// создания — единые. Procurement/Purchase — вне (лотов не трогают).
// Волна 17: справочник изделий разделён на два режима — по оси `native`, ровно как
// её описывает модель ([models.py] «режимы Изделия (native) / Компоненты (not native)»)
// и UI_GUIDE §7. `products` — «Изделия»: наше авторское (`native=true`), без фильтра
// категорий и синка; NewItem там по умолчанию `native=true`. `items` — «Компоненты»:
// покупное (`native=false`), фильтр по категории, синк с библиотекой.
// В волну 17 второй фильтр не поставили («оставить как есть»), и «Компоненты» год
// показывали ВЕСЬ справочник — наши приборы дублировались в оба режима, да ещё с
// глифом синка (`sync-ignored`), который для авторского изделия ничего не значит.
// Замечено Иваном 2026-07-30, поправлено тем же днём: режим = ровно своя половина оси.
// Волна 20: режим «Контрагенты» — внешняя сторона документооборота (поставщик/заказчик)
// стала полноценной сущностью со своей формой, а не только записью в пикерах.
type Mode = 'projects' | 'products' | 'items' | 'orders' | 'locations' | 'procurements'
  | 'purchases' | 'counterparties'
// Волна 19, Ф12e: тринадцати вариантов `new-*` больше нет. «＋ Новый» не открывает
// форму создания (второй, параллельный скелет формы), а РОЖДАЕТ сущность и уводит в
// её обычную каноничную форму — выбирать тут нечего.
type Sel =
  | { kind: 'project'; id: number }
  | { kind: 'item'; id: number }
  | { kind: 'library-sync' }
  | { kind: 'kitting'; id: number }
  | { kind: 'receipt'; id: number }
  | { kind: 'purchase'; id: number }
  | { kind: 'transfer'; id: number }
  | { kind: 'writeoff'; id: number }
  | { kind: 'requisition'; id: number }
  | { kind: 'procurement'; id: number }
  | { kind: 'inventory'; id: number }
  | { kind: 'relocation'; id: number }
  | { kind: 'location'; id: number }
  | { kind: 'counterparty'; id: number }
  // Волна 21: аккаунт — это `Sel` БЕЗ `Mode` (как `library-sync`), а не режим. `mode` и
  // `sel` в этом компоненте независимы, поэтому сайдбар держит последний открытый
  // список: аккаунт — «я сам», а не режим работы, и он не должен стоить человеку места
  // в работе. Даром работают и `Alt+←`, и браузерный «Назад» — история пишет пару
  // `{mode, sel}`.
  | { kind: 'account' }
  | null

// Виды ордера и их подписи живут рядом с типом (`./OrderForm`) — их читает и этот
// список, и ленты, где вид приходит данными (движения изделия).
// Ключи detail-выбора, относящиеся к ордеру (для подсветки строки в едином списке).
const ORDER_SEL_KINDS = new Set(ORDER_KINDS.map(k => k.kind as string))

// Нормализованная строка единого списка ордеров (собирается клиентски из 6 фидов).
interface OrderEntry {
  kind: OrderKind; id: number; code: string; name: string
  projectCode: string; locked: boolean; date: string | null
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
  const [relocations, setRelocations] = useState<RelocationRow[]>([])
  const [locationRows, setLocationRows] = useState<LocationRow[]>([])
  const [counterparties, setCounterparties] = useState<CounterpartyRow[]>([])
  const [sel, setSel] = useState<Sel>(null)
  // §5 (Ф9): «только что создан» — единственный документ, что открывается в правке.
  // Помечается в onCreated-потоках, гаснет как только выбор ушёл с него (эффект ниже).
  const [justCreated, setJustCreated] = useState<{ kind: string; id: number } | null>(null)
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
  const reloadRelocations = useCallback(() => api.relocations().then(setRelocations), [])
  const reloadLocations = useCallback(() => api.locations().then(setLocationRows), [])
  const reloadCounterparties = useCallback(
    () => api.counterparties().then(setCounterparties), [])
  const reloadProjects = useCallback(() => api.projects().then(setProjects), [])
  const reloadItems = useCallback(() => api.items().then(setItems), [])

  // На старте: узнать «кто я» + завести хук на протухшую сессию (401 в любом
  // запросе → назад на логин). Регистрируем один раз.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    // Волна 21: тема приезжает этим же ответом (без второго round-trip) и применяется
    // до первого рендера приложения. Экран логина темы не знает и остаётся на
    // дефолтной — у входа нет владельца, показывать чей-то вкус там неоткуда.
    api.me().then(u => { if (u) applyTheme(u.theme); setUser(u) }).catch(() => setUser(null))
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
    reloadRelocations()
    reloadLocations()
    reloadCounterparties()
  }, [user, reloadKittings, reloadReceipts, reloadPurchases, reloadTransfers,
      reloadWriteoffs, reloadRequisitions, reloadProcurements, reloadInventories,
      reloadRelocations, reloadLocations, reloadCounterparties])

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

  // Метка «только что создан» гаснет, как только выбор ушёл с этого документа —
  // повторный заход в него уже откроется в просмотре, как любой существующий.
  useEffect(() => {
    if (justCreated && !(sel && 'id' in sel &&
        sel.kind === justCreated.kind && sel.id === justCreated.id))
      setJustCreated(null)
  }, [sel, justCreated])
  const isFresh = (kind: string, id: number) =>
    justCreated?.kind === kind && justCreated.id === id

  // Ф12e: «＋ Новый» = POST пустым телом → пометить «только что создан» (Ф9 откроет
  // в правке) → перезагрузить список → открыть форму. Один сценарий на 13 кнопок:
  // раньше у каждой была своя форма создания со своими полями и своим `onCreated`.
  const born = (path: string, kind: string, reload: () => void,
                open: (id: number) => void, body: object = {}) =>
    api.born(path, body).then(({ id }) => {
      reload()
      setJustCreated({ kind, id })
      open(id)
    })

  const openProject = (id: number) => { setMode('projects'); setSel({ kind: 'project', id }) }
  // Переход на форму изделия ведёт в ТОТ режим, которому эта строка принадлежит по оси
  // `native` (2026-07-30, вместе с фильтром «Компонентов»): раньше любая ссылка кидала
  // в «Компоненты», и это сходило с рук, пока там лежал весь справочник. Теперь наш
  // прибор в списке компонентов не значится — открытый из BOM, он оказался бы выбранным
  // в режиме, где его строки нет. Неизвестный id (список ещё не доехал) → «Компоненты»,
  // как было: покупных подавляющее большинство.
  const openItem = (id: number) => {
    setMode(items.find(i => i.id === id)?.native ? 'products' : 'items')
    setSel({ kind: 'item', id })
  }
  // 6 складских документов открываются в едином режиме «Ордера» (Ф1b-флагман).
  // Общий вход по виду — для лент, где вид приходит данными (движения изделия).
  const openOrder = (kind: OrderKind, id: number) => { setMode('orders'); setSel({ kind, id }) }
  const openKitting = (id: number) => { setMode('orders'); setSel({ kind: 'kitting', id }) }
  const openReceipt = (id: number) => { setMode('orders'); setSel({ kind: 'receipt', id }) }
  const openTransfer = (id: number) => { setMode('orders'); setSel({ kind: 'transfer', id }) }
  const openWriteoff = (id: number) => { setMode('orders'); setSel({ kind: 'writeoff', id }) }
  const openRequisition = (id: number) => { setMode('orders'); setSel({ kind: 'requisition', id }) }
  const openInventory = (id: number) => { setMode('orders'); setSel({ kind: 'inventory', id }) }
  const openRelocation = (id: number) => { setMode('orders'); setSel({ kind: 'relocation', id }) }
  const openLocation = (id: number) => { setMode('locations'); setSel({ kind: 'location', id }) }
  const openPurchase = (id: number) => { setMode('purchases'); setSel({ kind: 'purchase', id }) }
  const openProcurement = (id: number) => { setMode('procurements'); setSel({ kind: 'procurement', id }) }
  const openCounterparty = (id: number) => { setMode('counterparties'); setSel({ kind: 'counterparty', id }) }

  // Единый фид ордеров: 6 списков нормализуются в общую строку. Новейшие сверху
  // (по дате, null — вниз, tiebreak id). Диспетчер открытия — по kind.
  const orderEntries = useMemo<OrderEntry[]>(() => {
    const es: OrderEntry[] = []
    receipts.forEach(r => es.push({ kind: 'receipt', id: r.id, code: r.code || r.number,
      name: r.contractor_name, projectCode: r.project_code, locked: r.locked, date: r.date }))
    kittings.forEach(k => es.push({ kind: 'kitting', id: k.id, code: k.code || k.target_code,
      name: k.target_description, projectCode: k.project_code, locked: k.locked, date: k.date }))
    transfers.forEach(t => es.push({ kind: 'transfer', id: t.id, code: t.code || t.number,
      name: t.project_code, projectCode: t.project_code, locked: t.locked, date: t.date }))
    requisitions.forEach(r => es.push({ kind: 'requisition', id: r.id, code: r.code || r.number,
      name: r.project_code, projectCode: r.project_code, locked: r.locked, date: r.date }))
    writeoffs.forEach(w => es.push({ kind: 'writeoff', id: w.id, code: w.code || w.number,
      name: w.reason, projectCode: w.project_code, locked: w.locked, date: w.date }))
    inventories.forEach(i => es.push({ kind: 'inventory', id: i.id, code: i.code || i.number,
      name: i.description, projectCode: i.project_code, locked: i.locked, date: i.date }))
    relocations.forEach(r => es.push({ kind: 'relocation', id: r.id, code: r.code || r.number,
      name: r.project_code, projectCode: r.project_code, locked: r.locked, date: r.date }))
    return es.sort((a, b) => (b.date ?? '').localeCompare(a.date ?? '') || b.id - a.id)
  }, [receipts, kittings, transfers, requisitions, writeoffs, inventories, relocations])

  const openOrderEntry = (e: OrderEntry) => openOrder(e.kind, e.id)
  // Ф2i: перезагрузить фид нужного вида ордера — единый колбэк для <OrderForm>.
  const reloadOrderKind = (k: OrderKind) => ({
    receipt: reloadReceipts, kitting: reloadKittings, transfer: reloadTransfers,
    requisition: reloadRequisitions, writeoff: reloadWriteoffs, inventory: reloadInventories,
    relocation: reloadRelocations,
  }[k])()
  // Ф12e: рождение ордера выбранного вида. Маршруты множественные — словарь один
  // на семь видов (`kind` ↔ путь API), сценарий общий (`born`).
  const ORDER_PATH: Record<OrderKind, string> = {
    receipt: 'receipts', kitting: 'kittings', transfer: 'transfers',
    requisition: 'requisitions', writeoff: 'writeoffs', inventory: 'inventories',
    relocation: 'relocations',
  }
  const bornOrder = (k: OrderKind) =>
    born(ORDER_PATH[k], k, () => reloadOrderKind(k), id => openOrder(k, id))
  // Ключ выбранного ордера для подсветки строки (id пересекаются между таблицами).
  const orderSelKey = sel && ORDER_SEL_KINDS.has(sel.kind) && 'id' in sel
    ? `${sel.kind}:${sel.id}` : null

  const doLogout = () => { api.logout().catch(() => {}); setUser(null) }

  // Записи палитры ⌘K: проекты, изделия и документы — по коду/номеру/названию.
  const paletteEntries = useMemo<PaletteEntry[]>(() => {
    const e: PaletteEntry[] = []
    projects.forEach(p => e.push({ key: `p${p.id}`, code: p.code, name: p.description,
      kind: 'Проект', open: () => openProject(p.id) }))
    items.forEach(i => e.push({ key: `i${i.id}`, code: i.code, name: i.description,
      kind: 'Изделие', open: () => openItem(i.id) }))
    receipts.forEach(r => e.push({ key: `r${r.id}`, code: r.code || r.number, name: r.contractor_name,
      kind: 'Поставка', open: () => openReceipt(r.id) }))
    transfers.forEach(t => e.push({ key: `t${t.id}`, code: t.code || t.number, name: t.project_code,
      kind: 'Передача', open: () => openTransfer(t.id) }))
    writeoffs.forEach(w => e.push({ key: `w${w.id}`, code: w.code || w.number, name: w.project_code,
      kind: 'Списание', open: () => openWriteoff(w.id) }))
    requisitions.forEach(r => e.push({ key: `q${r.id}`, code: r.code || r.number, name: r.project_code,
      kind: 'Требование', open: () => openRequisition(r.id) }))
    inventories.forEach(i => e.push({ key: `v${i.id}`, code: i.code || i.number, name: i.project_code,
      kind: 'Инвентаризация', open: () => openInventory(i.id) }))
    purchases.forEach(p => e.push({ key: `u${p.id}`, code: p.code || `Заказ #${p.id}`, name: p.project_code,
      kind: 'Заказ', open: () => openPurchase(p.id) }))
    kittings.forEach(k => e.push({ key: `k${k.id}`, code: k.code || k.target_code, name: k.target_description,
      kind: 'Комплектация', open: () => openKitting(k.id) }))
    relocations.forEach(r => e.push({ key: `l${r.id}`, code: r.code || r.number, name: r.project_code,
      kind: 'Перемещение', open: () => openRelocation(r.id) }))
    locationRows.forEach(l => e.push({ key: `loc${l.id}`, code: l.code, name: l.description,
      kind: 'Склад', open: () => openLocation(l.id) }))
    // Волна 20: контрагент ищется по коду-жаргону («КОМПЭЛ»), как и всё остальное;
    // у старых записей кода может не быть — тогда в палитру идёт описание.
    counterparties.forEach(cp => e.push({ key: `cp${cp.id}`, code: cp.code || cp.description,
      name: cp.description, kind: 'Контрагент', open: () => openCounterparty(cp.id) }))
    return e
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, items, receipts, transfers, writeoffs, requisitions, inventories,
      purchases, kittings, relocations, locationRows, counterparties])

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
        {/* Волна 21: здесь стоял «Выход» — теперь «Аккаунт», а выход переехал в команды
            его формы. Кнопка получает `.active` по `sel` (аккаунт — не режим), и строка
            в списке подсветку теряет: это уже валидное состояние (так же после удаления
            сущности). */}
        <button className={sel?.kind === 'account' ? 'active' : ''}
          title={`${user.full_name} — аккаунт, тема интерфейса, выход`}
          onClick={() => setSel({ kind: 'account' })}>
          <span className="ci ci-account" /></button>
      </div>

      <div className="sidebar">
        {mode === 'projects' &&
          <ModeList heading="Проекты" newLabel="＋ Новый проект"
            onNew={() => born('projects', 'project', reloadProjects, openProject)}
            selId={sel?.kind === 'project' ? sel.id : null}
            onSelect={id => setSel({ kind: 'project', id })}
            rows={[...projects].map(p => ({ id: p.id, code: p.code, name: p.description,
              // Ф1b: замок-проекция (unlock=активный / lock=архивный); цвет=worst-of
              // здоровья проекта (`_project_health`), null → нейтральный.
              glyph: <StatusGlyph locked={p.locked} tone={p.health ? statusTone(p.health) : 'none'}
                title={p.locked ? 'архивный (закрыт)' : 'активный'} /> }))} />}

        {/* Режим «Изделия» (волна 17): только производимые; без фильтра категорий и
            синка. Открывает ту же форму изделия (sel.kind='item'). */}
        {mode === 'products' &&
          <ModeList heading="Изделия" newLabel="＋ Новое изделие"
            onNew={() => born('items', 'item', reloadItems,
              id => { setMode('products'); setSel({ kind: 'item', id }) }, { native: true })}
            selId={sel?.kind === 'item' ? sel.id : null}
            onSelect={id => setSel({ kind: 'item', id })}
            rows={[...items].filter(i => i.native)
              .sort((a, b) => a.code.localeCompare(b.code)).map(i => ({
                id: i.id, code: i.code, name: i.description, category: i.category?.description,
                glyph: <StatusGlyph locked={i.locked} /> }))} />}

        {mode === 'items' &&
          <ModeList heading="Компоненты" newLabel="＋ Новое изделие" categoryFilter
            onNew={() => born('items', 'item', reloadItems, openItem)}
            selId={sel?.kind === 'item' ? sel.id : null}
            onSelect={id => setSel({ kind: 'item', id })}
            extraTop={
              <div className={'tree-item' + (sel?.kind === 'library-sync' ? ' sel' : '')}
                onClick={() => setSel({ kind: 'library-sync' })}>
                <span className="ci ci-sync" />
                <span className="code">Синхронизация с библиотекой</span>
              </div>}
            rows={[...items].filter(i => !i.native)
              .sort((a, b) => a.code.localeCompare(b.code)).map(i => ({
                id: i.id, code: i.code, name: i.description, category: i.category?.description,
                glyph: <SyncGlyph synced={i.synced} /> }))} />}

        {/* Волна 20: глиф строки = СТОРОНА контрагента по фактам документооборота
            (своей оси фиксации у справочника нет) — семейство `fold-*`, см. `SideGlyph`. */}
        {mode === 'counterparties' &&
          <ModeList heading="Контрагенты" newLabel="＋ Новый контрагент"
            onNew={() => born('counterparties', 'counterparty', reloadCounterparties,
              openCounterparty)}
            selId={sel?.kind === 'counterparty' ? sel.id : null}
            onSelect={id => setSel({ kind: 'counterparty', id })}
            rows={[...counterparties].map(cp => ({
              id: cp.id, code: cp.code || cp.description, name: cp.description,
              glyph: <SideGlyph supply={cp.has_supply} shipment={cp.has_shipment} />,
            }))} />}

        {mode === 'orders' &&
          <OrderList entries={orderEntries} selKey={orderSelKey}
            onNew={bornOrder} onSelect={openOrderEntry} />}

        {mode === 'locations' &&
          <ModeList heading="Склады" newLabel="＋ Новый склад"
            onNew={() => born('locations', 'location', reloadLocations, openLocation)}
            selId={sel?.kind === 'location' ? sel.id : null}
            onSelect={id => setSel({ kind: 'location', id })}
            rows={[...locationRows].map(l => ({ id: l.id, code: l.code, name: l.description,
              glyph: <span className="ci ci-database" /> }))} />}

        {mode === 'purchases' &&
          <ModeList heading="Заказы" newLabel="＋ Новый заказ" projectFilter
            onNew={() => born('purchases', 'purchase', reloadPurchases, openPurchase)}
            selId={sel?.kind === 'purchase' ? sel.id : null}
            onSelect={id => setSel({ kind: 'purchase', id })}
            rows={[...purchases].reverse().map(p => ({
              id: p.id, code: p.code || `Заказ #${p.id}`, name: p.project_code, projectCode: p.project_code,
              // Ф1b: глиф=замок (фиксация), цвет=покрытие лотами (`_purchase_coverage`).
              glyph: <StatusGlyph locked={p.locked} tone={statusTone(p.coverage)} />,
            }))} />}

        {mode === 'procurements' &&
          <ModeList heading="Закупки" newLabel="＋ Новая закупка"
            onNew={() => born('procurements', 'procurement', reloadProcurements, openProcurement)}
            selId={sel?.kind === 'procurement' ? sel.id : null}
            onSelect={id => setSel({ kind: 'procurement', id })}
            rows={[...procurements].reverse().map(p => ({
              id: p.id, code: p.code || `Закупка #${p.id}`, name: p.description,
              // Ф1b: закупка-план — ось только фиксация, цвет=фиксация (зелёный заперт).
              glyph: <StatusGlyph locked={p.locked} />,
            }))} />}
      </div>

      <div className="work">
        {/* Одна форма на ВСЕ проекты, включая внутренние склады (Ф12c): кастомный
            экран остатков и панель закрытия свёрнуты в её табы. */}
        {sel?.kind === 'project' &&
          <ProjectView key={sel.id} projectId={sel.id} items={items}
            isNew={isFresh('project', sel.id)}
            openItem={openItem}
            openOrder={openOrder}
            onChanged={() => { reloadProjects(); reloadWriteoffs(); reloadRequisitions() }}
            onDeleted={() => { reloadProjects(); setSel(null) }} />}
        {sel?.kind === 'item' && <ItemView itemId={sel.id} items={items}
          isNew={isFresh('item', sel.id)}
          openItem={openItem} openOrder={openOrder} onChanged={reloadItems}
          onDeleted={() => setSel(null)} />}
        {sel?.kind === 'library-sync' &&
          <LibraryImportView onApplied={reloadItems} openItem={openItem} />}
        {/* Ф2i: единый вход detail-формы «Ордера» вместо шести условных веток. */}
        {sel && ORDER_SEL_KINDS.has(sel.kind) && (() => {
          const o = sel as { kind: OrderKind; id: number }
          return <OrderForm kind={o.kind} id={o.id} items={items}
            isNew={isFresh(o.kind, o.id)}
            openItem={openItem} openPurchase={openPurchase} openProject={openProject}
            openCounterparty={openCounterparty}
            onChanged={() => reloadOrderKind(o.kind)}
            onDeleted={() => { reloadOrderKind(o.kind); setSel(null) }} />
        })()}
        {sel?.kind === 'purchase' &&
          <PurchaseView purchaseId={sel.id} items={items} openItem={openItem}
            isNew={isFresh('purchase', sel.id)}
            openReceipt={openReceipt} openProject={openProject}
            openCounterparty={openCounterparty}
            openProcurement={id => { reloadProcurements(); openProcurement(id) }}
            onChanged={reloadPurchases}
            onDeleted={() => { reloadPurchases(); setSel(null) }} />}
        {sel?.kind === 'procurement' &&
          <ProcurementView procurementId={sel.id} items={items}
            openItem={openItem} openProject={openProject}
            openCounterparty={openCounterparty}
            isNew={isFresh('procurement', sel.id)}
            openPurchase={id => { reloadPurchases(); openPurchase(id) }}
            onChanged={reloadProcurements}
            onDeleted={() => { reloadProcurements(); setSel(null) }} />}
        {sel?.kind === 'location' &&
          <LocationView locationId={sel.id} openItem={openItem}
            isNew={isFresh('location', sel.id)} onChanged={reloadLocations}
            onDeleted={() => { reloadLocations(); setSel(null) }} />}
        {sel?.kind === 'counterparty' &&
          <CounterpartyView counterpartyId={sel.id}
            isNew={isFresh('counterparty', sel.id)}
            openProcurement={openProcurement} openPurchase={openPurchase}
            openOrder={openOrder}
            onChanged={reloadCounterparties}
            onDeleted={() => { reloadCounterparties(); setSel(null) }} />}
        {/* Аккаунт (волна 21): форма «я сам» — фиксации и корзины у неё нет, зато есть
            тема интерфейса и выход. Смена имени тут же обновляет подпись в панели
            режимов (и сбрасывает кэш справочника авторов — внутри вьюхи). */}
        {sel?.kind === 'account' &&
          <AccountView
            openProcurement={openProcurement} openPurchase={openPurchase}
            openOrder={openOrder} onLogout={doLogout}
            onChanged={full_name => setUser(u => u && { ...u, full_name })} />}
        {!sel && <div className="empty">Выберите объект слева · {KBD} — быстрый переход</div>}
      </div>

      {paletteOpen &&
        <CommandPalette entries={paletteEntries} onClose={() => setPaletteOpen(false)} />}
    </div>
  )
}

// Панель режимов (§2): Codicons, монохром. Порядок = поток жизненного цикла изделия
// (планирование → исполнение → приёмка → сборка → выбытие → сверка).
// Волна 20: «Контрагенты» стоят на СТЫКЕ справочников и закупочного контура (решение
// Ивана 2026-07-30) — это последний справочник «что и с кем», после которого начинается
// поток денег и документов (Закупки → Заказы → Ордера).
const MODES: { mode: Mode; icon: string; title: string }[] = [
  { mode: 'projects',     icon: 'flag',          title: 'Проекты — дефицит, панель проекта' },
  { mode: 'products',     icon: 'rocket',        title: 'Изделия — производимые (приборы/сборки), состав, остатки' },
  { mode: 'items',        icon: 'chip',          title: 'Компоненты — весь справочник, категории, синк с библиотекой' },
  { mode: 'counterparties', icon: 'call-outgoing', title: 'Контрагенты — поставщики и заказчики, что привезли и что им передали' },
  { mode: 'procurements', icon: 'law',           title: 'Закупки — командный свод, xlsx-бланк' },
  { mode: 'purchases',    icon: 'package',       title: 'Заказы — обязательства поставщику' },
  { mode: 'orders',       icon: 'notebook',      title: 'Ордера — поставки, комплектации, передачи, требования, списания, инвентаризации, перемещения' },
  { mode: 'locations',    icon: 'layers',        title: 'Склады — места хранения, что на них лежит' },
]

// Глиф строки контрагента: ось СТОРОНЫ (единственная его ось — замка у справочника
// нет). Семейство `fold-*` (решение Ивана 2026-07-30): одна форма с направлением
// внутри — `fold-down` (к нам едет), `fold-up` (от нас уходит), `fold` (в обе
// стороны). Направление читается СРАВНЕНИЕМ строк списка, а не припоминанием иконки,
// и глифы не занимают формы, уже говорящие о другом (`inbox`/`export` — виды ордера,
// `arrow-swap` — требование).
//
// Ф3: сторона — ФАКТ (движок считает по документам), а не заявленная роль. Пустой
// контрагент — нейтральный `fold`: он заведён, но с ним ещё ничего не было, и это
// нормальная строка справочника, а не ошибка заполнения.
function SideGlyph({ supply, shipment }: { supply: boolean; shipment: boolean }) {
  const [icon, tone, title] = supply && shipment
    ? ['fold', 'sg-ok', 'и привозит нам, и принимает от нас']
    : supply ? ['fold-down', 'sg-ok', 'привозит нам — закупки, заказы, поставки']
    : shipment ? ['fold-up', 'sg-ok', 'ему передаём — накладные']
    : ['fold', 'sg-none', 'документов с ним ещё не было']
  return <span className={`ci sg ci-${icon} ${tone}`} title={title} />
}

// Сочетание для палитры под ОС: мак — ⌘K, остальные — Ctrl+K (слушаем оба, см. эффект выше).
const KBD = /Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘K' : 'Ctrl+K'

// Единый список режима (§7): призрачный «＋ Новая…» первым, строка = глиф · моно-код
// (подписи нет), фильтр-строка и — где есть проект — дропдаун по проекту.
interface ListRow { id: number; code: string; name: string; glyph: ReactNode; projectCode?: string; category?: string }
// Ф12e: `newSel` больше нет — «＋ Новый» не выбирает форму создания, а рождает
// сущность и уводит в её каноничную форму, так что подсвечивать нечего.
function ModeList({ heading, newLabel, onNew, rows, selId, onSelect, projectFilter, categoryFilter, extraTop }: {
  heading: string; newLabel: string; onNew: () => void
  rows: ListRow[]; selId: number | null; onSelect: (id: number) => void
  projectFilter?: boolean; categoryFilter?: boolean; extraTop?: ReactNode
}) {
  const [q, setQ] = useState('')
  const [proj, setProj] = useState('')
  const [cat, setCat] = useState('')
  useEffect(() => { setQ(''); setProj(''); setCat('') }, [heading])

  const projOptions = useMemo(() => {
    if (!projectFilter) return []
    return [...new Set(rows.map(r => r.projectCode).filter((x): x is string => !!x))].sort()
  }, [rows, projectFilter])

  const catOptions = useMemo(() => {
    if (!categoryFilter) return []
    return [...new Set(rows.map(r => r.category).filter((x): x is string => !!x))].sort()
  }, [rows, categoryFilter])

  // Фильтр показываем, только когда выбирать есть из чего (одно значение на весь
  // список — не выбор): признак нужен и разметке строки, и решению её рисовать.
  const projFilterOn = projectFilter && projOptions.length > 1
  const catFilterOn = categoryFilter && catOptions.length > 1

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    return rows.filter(r =>
      (!proj || r.projectCode === proj) &&
      (!cat || r.category === cat) &&
      (!s || r.code.toLowerCase().includes(s) || r.name.toLowerCase().includes(s)))
  }, [rows, q, proj, cat])

  return (
    <>
      <h2>{heading}</h2>
      <div className="list-filters">
        <input className="list-filter" value={q} placeholder="фильтр — код или название"
          onChange={e => setQ(e.target.value)} />
        {/* Выпадающие — своей строкой, как у ордеров: один занимает её целиком, два
            делят пополам. Пустая строка не рисуется (фильтр появляется, только когда
            есть из чего выбирать). */}
        {(projFilterOn || catFilterOn) &&
          <div className="list-filter-row">
            {projFilterOn &&
              <Dropdown className="list-proj" value={proj} onPick={v => setProj(String(v))}
                options={[{ value: '', label: 'все проекты' },
                  ...projOptions.map(p => ({ value: p, label: p }))]} />}
            {catFilterOn &&
              <Dropdown className="list-proj" value={cat} onPick={v => setCat(String(v))}
                options={[{ value: '', label: 'все категории' },
                  ...catOptions.map(c => ({ value: c, label: c }))]} />}
          </div>}
      </div>
      <div className="list-scroll">
        {extraTop}
        <div className="tree-item new" onClick={onNew}>
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

// Единый список ордеров (Ф1b-флагман): смешанный фид 6 типов, два фильтра — по типу
// (kind) и проекту. Строка = статусный глиф · моно-№ · подпись типа справа. Ключ
// строки — `kind:id` (id пересекаются между таблицами документов).
function OrderList({ entries, selKey, onSelect, onNew }: {
  entries: OrderEntry[]; selKey: string | null
  onSelect: (e: OrderEntry) => void; onNew: (kind: OrderKind) => void
}) {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const [proj, setProj] = useState('')
  // Ф12e: вид ордера — единственное, что нельзя добрать фолбэком (это КОД, не
  // данные: по нему фильтруют proxy-менеджеры и стерегут CHECK). Поэтому вместо
  // преформы — меню на кнопке: клик по виду сразу рождает документ.
  const [menu, setMenu] = useState(false)
  const newBtn = useRef<HTMLDivElement>(null)
  const menuBox = useRef<HTMLDivElement>(null)
  // Клик мимо / Esc закрывают меню. Мимо — это мимо ОБОИХ: и кнопки, и самого меню.
  // Меню — портал в `body` (`AnchoredMenu`), поэтому для документа его строка лежит
  // «вне кнопки»: без проверки по `menuBox` этот обработчик успевал закрыть меню на
  // `mousedown`, React снимал строку с DOM, и `click` до неё уже не доходил — вид
  // выбрать было нельзя. `preventDefault` на строке тут не спасает: он не гасит
  // всплытие. Кнопку тоже пропускаем — иначе она закрывала бы меню здесь и тут же
  // открывала в своём `onClick`.
  useEffect(() => {
    if (!menu) return
    const off = (e: MouseEvent) => {
      const t = e.target as Node
      if (!newBtn.current?.contains(t) && !menuBox.current?.contains(t))
        setMenu(false)
    }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false) }
    document.addEventListener('mousedown', off)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', off)
      document.removeEventListener('keydown', esc)
    }
  }, [menu])

  const kindOptions = useMemo(() =>
    ORDER_KINDS.filter(k => entries.some(e => e.kind === k.kind)), [entries])
  const projOptions = useMemo(() =>
    [...new Set(entries.map(e => e.projectCode).filter(Boolean))].sort(), [entries])

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    return entries.filter(e =>
      (!kind || e.kind === kind) &&
      (!proj || e.projectCode === proj) &&
      (!s || e.code.toLowerCase().includes(s) || e.name.toLowerCase().includes(s)))
  }, [entries, q, kind, proj])

  return (
    <>
      <h2>Ордера</h2>
      <div className="list-filters">
        <input className="list-filter" value={q} placeholder="фильтр — № или название"
          onChange={e => setQ(e.target.value)} />
        <div className="list-filter-row">
          <Dropdown className="list-proj" value={kind} onPick={v => setKind(String(v))}
            options={[{ value: '', label: 'все типы' },
              ...kindOptions.map(k => ({ value: k.kind, label: k.label }))]} />
          {projOptions.length > 1 &&
            <Dropdown className="list-proj" value={proj} onPick={v => setProj(String(v))}
              options={[{ value: '', label: 'все проекты' },
                ...projOptions.map(p => ({ value: p, label: p }))]} />}
        </div>
      </div>
      <div className="list-scroll">
        <div ref={newBtn} className="tree-item new" onClick={() => setMenu(m => !m)}>
          <span className="code">＋ Новый ордер</span>
          <span className="ci ci-chevron-down" />
        </div>
        {menu &&
          <AnchoredMenu anchor={newBtn} boxRef={menuBox} className="typeahead-menu">
            {ORDER_KINDS.map(k => (
              <div key={k.kind} className="typeahead-item"
                onClick={() => { setMenu(false); onNew(k.kind) }}>
                <span className="code">{k.label}</span>
              </div>
            ))}
          </AnchoredMenu>}
        {shown.map(e => {
          const key = `${e.kind}:${e.id}`
          return (
            <div key={key} className={'tree-item' + (selKey === key ? ' sel' : '')}
              onClick={() => onSelect(e)} title={ORDER_LABEL[e.kind]}>
              <StatusGlyph locked={e.locked} />
              <span className="code">{e.code}</span>
              <span className="row-tag">{ORDER_LABEL[e.kind]}</span>
            </div>
          )
        })}
        {shown.length === 0 && <div className="list-empty">ничего не найдено</div>}
      </div>
    </>
  )
}

