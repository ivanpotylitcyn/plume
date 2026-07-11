// API-клиент витрин волны 1. Все эндпоинты — read-only проекции движка.
export type Status = 'available' | 'on_order' | 'to_order'

// ── Авторство шапки (волна 13, Ф2j) — единый пикер автора, редактируемо под
//    замком на всех ордерах/закупках. `UserRow` — справочник пикера. ──
export interface UserRow {
  id: number; username: string; full_name: string; is_superuser: boolean
}
export interface Authored { user_id: number; user_name: string }

export interface ProjectRow {
  id: number; code: string; name: string; kind: string; status: string
}
export interface ProjectDetail extends ProjectRow {
  budget: number | null; started_at: string | null
}
export interface ItemRow {
  id: number; code: string; name: string; kind: string; uom: string
  is_manufactured: boolean
}

export interface DeficitLine {
  component_id: number; component_code: string; component_name: string; uom: string
  need: number; have: number; on_order: number; to_order: number
  status: Status; available_raw: number; anomaly: boolean
}
export interface DeficitDemand {
  demand_id: number; target_id: number; target_code: string; target_name: string
  qty: number; device: { done: number; wip: number; not_started: number }
  status: Status; badge: Status; lines: DeficitLine[]
}
// Свод потребности по компонентам на весь проект (секция «Потребность»).
export interface DeficitComponent {
  component_id: number; component_code: string; component_name: string; uom: string
  need: number; have: number; on_order: number; to_order: number
  status: Status; available_raw: number; anomaly: boolean
}
export interface Deficit {
  project_id: number; project_code: string; project_name: string
  demands: DeficitDemand[]
  components: DeficitComponent[]
}

export interface Budget {
  project_id: number; project_code: string; project_name: string
  budget: number | null      // бюджет на материалы (может быть не задан)
  spent: number              // потрачено (факт по Receipt-лотам)
  plan: number               // прогноз полной стоимости («факт где есть, оценка где нет»)
  compass: number | null     // budget − plan (запас/перерасход); null без бюджета
  unestimated: string[]      // коды покупных позиций без estimated_cost
  cost: number               // себестоимость (для КП; заём по реальной цене)
  economy: number            // экономия = cost − spent (польза внутреннего заёма)
}

export interface StockMapRow {
  project_id: number; project_code: string; project_name: string
  project_kind: string; available: number
}
export interface StockMap {
  item_id: number; item_code: string; item_name: string; uom: string
  rows: StockMapRow[]
}
export interface ItemShipment {
  transfer_id: number; number: string; date: string; project_code: string
  posted: boolean; lot_id: number; qty: number; display_name: string
  lot_name: string
}
export interface ItemDetail {
  id: number; code: string; name: string; kind: string; uom: string
  is_manufactured: boolean; estimated_cost: number | null
  bom: { id: number; component_id: number; component_code: string;
         component_name: string; component_uom: string; qty: number; position: string }[]
  where_used: { parent_id: number; parent_code: string; parent_name: string; qty: number }[]
  lots: { id: number; project_code: string; origin: string; qty_born: number;
          live_qty: number; unit_cost: number; part_number: string; lot_name: string }[]
  shipments: ItemShipment[]
}

// ── Кокпит комплектации (волна 2 — записываемое ядро) ──
export interface KittingRow {
  id: number; project_code: string; target_code: string; target_name: string
  qty: number; status: string; date: string | null
}
export interface CandidateLot {
  lot_id: number; live_qty: number; unit_cost: number; part_number: string
  origin: string; lot_name: string
}
export interface RealLine {
  id: number; lot_id: number; lot_label: string; qty: number; date: string | null
}
export interface Ghost {
  status: Status; have: number; on_order: number; to_order: number
  candidate_lots: CandidateLot[]
}
export interface CockpitRow {
  component_id: number; component_code: string; component_name: string; uom: string
  need: number; pierced: number; remaining: number
  real_lines: RealLine[]; ghost: Ghost | null
}
export interface BornLot {
  id: number; qty: number; unit_cost: number; lot_name: string; part_number: string
}
export interface Cockpit extends Authored {
  id: number; status: string; project_id: number; project_code: string
  target_id: number; target_code: string; target_name: string; uom: string
  qty: number; date: string | null; cockpit_status: Status
  rows: CockpitRow[]; born_lots: BornLot[]
}

// ── Контрагенты (волна 13, Ф2f+ — единая сущность с ролями) ──
export interface CounterpartyRow {
  id: number; name: string; inn: string
  is_supplier: boolean; is_customer: boolean
}

// ── Приход / УПД (волна 3 — записываемое ядро) ──
export interface ReceiptRow {
  id: number; number: string; date: string; contractor_name: string
  project_code: string; approved: boolean; lines: number
}
export interface ReceiptLot {
  id: number; item_id: number; item_code: string; item_name: string; uom: string
  qty: number; live_qty: number; unit_cost: number; lot_name: string
  part_number: string; consumed: boolean
}
export interface ReceiptCockpit extends Authored {
  id: number; number: string; date: string
  contractor_id: number; contractor_name: string
  project_id: number; project_code: string; project_name: string
  purchase_id: number | null
  approved: boolean; total_cost: number; lots: ReceiptLot[]
}

// ── Заказ / Purchase (волна 4 — записываемое ядро) ──
export interface PurchaseRow {
  id: number; project_code: string; status: string
  date: string | null; note: string; lines: number
}
export interface PurchaseCockpitLine {
  id: number; item_id: number; item_code: string; item_name: string; uom: string
  qty: number; received: number; remaining: number; status: Status
}
export interface PurchaseReceiptRow {
  id: number; number: string; date: string; contractor_name: string; lines: number
}
export interface PurchaseCockpit extends Authored {
  id: number; status: string; project_id: number; project_code: string
  project_name: string; procurement_id: number; date: string | null; note: string
  editable: boolean; cockpit_status: Status
  total_ordered: number; total_received: number
  rows: PurchaseCockpitLine[]; receipts: PurchaseReceiptRow[]
}
export interface ProjectPurchaseRow {
  id: number; status: string; date: string | null; note: string; lines: number
}

// ── Передача / Transfer (волна 5 — записываемое ядро) ──
export interface TransferRow {
  id: number; number: string; date: string; project_code: string
  posted: boolean; lines: number
}
export interface AvailableLot {
  lot_id: number; item_id: number; item_code: string; item_name: string; uom: string
  live_qty: number; origin: string; part_number: string; lot_name: string
}
export interface TransferCockpitLine {
  id: number; lot_id: number; lot_label: string; item_id: number; item_code: string
  item_name: string; uom: string; qty: number; display_name: string
  lot_live_qty: number; lot_name: string
}
export interface TransferCockpit extends Authored {
  id: number; number: string; date: string
  contractor_id: number | null; contractor_name: string
  project_id: number; project_code: string; project_name: string; posted: boolean
  total_qty: number; lines: TransferCockpitLine[]
}

// ── Списание / Writeoff (волна 6 — записываемое ядро) ──
export interface WriteoffRow {
  id: number; number: string; date: string; project_code: string
  reason: string; posted: boolean; lines: number
}
export interface WriteoffCockpitLine {
  id: number; lot_id: number; lot_label: string; item_id: number; item_code: string
  item_name: string; uom: string; qty: number; lot_live_qty: number
  lot_name: string
}
export interface WriteoffCockpit extends Authored {
  id: number; number: string; date: string; reason: string
  project_id: number; project_code: string; project_name: string
  posted: boolean; total_qty: number; lines: WriteoffCockpitLine[]
}

// ── Требование / Requisition (волна 6 — записываемое ядро) ──
export interface RequisitionRow {
  id: number; number: string; date: string; project_code: string
  posted: boolean; lines: number
}
export interface AllAvailableLot {
  lot_id: number; item_id: number; item_code: string; item_name: string; uom: string
  live_qty: number; origin: string; project_id: number; project_code: string
  part_number: string; lot_name: string
}
export interface RequisitionCockpitLine {
  id: number; source_lot_id: number; lot_label: string; source_project_code: string
  item_id: number; item_code: string; item_name: string; uom: string
  qty: number; source_live_qty: number; born_lot_id: number | null
  lot_name: string
}
export interface RequisitionCockpit extends Authored {
  id: number; number: string; date: string
  project_id: number; project_code: string; project_name: string
  posted: boolean; total_qty: number; lines: RequisitionCockpitLine[]
}

// ── Место хранения / Location (волна 13 Ф3 пикер, Ф4 сущность «Склады») ──
export interface LocationRow { id: number; code: string; name: string; kind: string }
export interface LocationStockLot {
  lot_id: number; lot_label: string; part_number: string; lot_name: string
  item_id: number; item_code: string; item_name: string; uom: string; qty: number
  project_id: number; project_code: string; project_name: string
}
export interface LocationCockpit {
  id: number; code: string; name: string; kind: string
  stock: LocationStockLot[]
}

// ── Перемещение / Relocation (волна 13 Ф3 — записываемое ядро) ──
export interface RelocationRow {
  id: number; number: string; date: string; project_code: string
  posted: boolean; lines: number
}
export interface RelocationMove {
  lot_id: number; lot_label: string; item_id: number; item_code: string
  item_name: string; uom: string; qty: number
  from_location_id: number | null; from_location: string
  to_location_id: number | null; to_location: string
  from_live_qty: number; to_live_qty: number
}
export interface RelocationCockpit extends Authored {
  id: number; number: string; date: string
  project_id: number; project_code: string; project_name: string
  posted: boolean; total_qty: number; moves: RelocationMove[]
}
export interface LotLocation {
  location_id: number; code: string; name: string; qty: number
}
export interface RelocationSourceLot {
  lot_id: number; item_id: number; item_code: string; item_name: string; uom: string
  live_qty: number; part_number: string; lot_name: string
  by_location: LotLocation[]
}

// ── Инвентаризация / Inventory (волна 9 — записываемое ядро) ──
export interface InventoryRow {
  id: number; number: string; date: string; project_code: string
  note: string; posted: boolean; lines: number
}
export interface InventoryCockpitLot {
  id: number; item_id: number; item_code: string; item_name: string; uom: string
  qty: number; live_qty: number; unit_cost: number; lot_name: string
  part_number: string; predecessor_id: number | null; predecessor_label: string
  consumed: boolean
}
export interface InventoryCockpit extends Authored {
  id: number; number: string; date: string; note: string
  project_id: number; project_code: string; project_name: string
  posted: boolean; total_cost: number; lots: InventoryCockpitLot[]
}
export interface WrittenOffLot {
  lot_id: number; item_id: number; item_code: string; item_name: string; uom: string
  written_qty: number; project_code: string; unit_cost: number
  lot_name: string; part_number: string
}

// ── Панель закрытия проекта (волна 6) ──
export interface ResidualLot {
  lot_id: number; lot_label: string; item_id: number; item_code: string
  item_name: string; uom: string; live_qty: number; anomaly: boolean
}
export interface ProjectClosure {
  project_id: number; project_code: string; project_name: string; kind: string
  status: string; closed_at: string | null; is_external: boolean
  residuals: ResidualLot[]; residual_positive: number; anomaly_count: number
  can_close: boolean; blocker: string
}

// ── Планирование закупок (волна 7): командный свод + Procurement ──
export interface CommandDeficitProject {
  project_id: number; project_code: string; project_name: string
  need: number; have: number; on_order: number; to_order: number; status: Status
}
export interface CommandDeficitRow {
  item_id: number; item_code: string; item_name: string; uom: string
  is_manufactured: boolean
  need: number; have: number; on_order: number; to_order: number
  status: Status; by_project: CommandDeficitProject[]
}
export interface CommandDeficit { rows: CommandDeficitRow[] }

export interface ProcurementRow {
  id: number; status: string; date: string | null; note: string; lines: number
}
export interface ProcurementCockpitLine {
  id: number; item_id: number; item_code: string; item_name: string
  uom: string; qty: number
}
export interface ProcurementCockpit extends Authored {
  id: number; status: string; date: string | null; note: string; editable: boolean
  total_qty: number; lines: ProcurementCockpitLine[]
}

// ── Pegging (волна 8): нарезка плана на проектные заказы ──
export interface PeggingProject {
  project_id: number; project_code: string; project_name: string
  suggest: number; pegged: number
}
export interface PeggingRow {
  line_id: number; item_id: number; item_code: string; item_name: string
  uom: string; qty: number; pegged: number; remaining: number; status: Status
  by_project: PeggingProject[]
}
export interface PeggingFanRow {
  purchase_id: number; status: string; project_id: number
  project_code: string; project_name: string; lines: number; total: number
}
export interface Pegging {
  id: number; status: string; editable: boolean
  rows: PeggingRow[]; fan: PeggingFanRow[]
}

// ── Вложения (волна 11): PDF/сканы к документам и изделиям ──
export interface AttachmentRow {
  id: number; filename: string; size: number; content_type: string
  label: string; uploaded_at: string; user: string; url: string
}

// ── Аутентификация (волна 12) ──
export interface User {
  id: number; username: string; full_name: string; is_superuser: boolean
}

// Сессия истекла посреди работы → App перекинет на логин. get/send/upload зовут
// этот хук на 401 (кроме me(), где 401 = «просто не залогинен», ожидаемо).
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn }

function getCookie(name: string): string | null {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)')
  return m ? decodeURIComponent(m[2]) : null
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
  if (r.status === 401 || r.status === 403) { onUnauthorized?.(); throw new Error('unauthorized') }
  if (!r.ok) throw new Error(`${r.status} ${url}`)
  return r.json()
}

// Мутации: JSON + CSRF-токен из cookie (если есть). В dev фронт анонимен —
// DRF не форсит CSRF; на проде (сессия admin) токен подхватится автоматически.
async function send<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const csrf = getCookie('csrftoken')
  if (csrf) headers['X-CSRFToken'] = csrf
  const r = await fetch(url, {
    method, headers, credentials: 'same-origin',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (r.status === 401 || r.status === 403) { onUnauthorized?.(); throw new Error('unauthorized') }
  if (!r.ok) {
    let msg = `${r.status} ${url}`
    try { const j = await r.json(); if (j.detail) msg = j.detail } catch { /* no body */ }
    throw new Error(msg)
  }
  return r.status === 204 ? (undefined as T) : r.json()
}

// Загрузка файла (multipart): Content-Type НЕ ставим — браузер сам добавит
// boundary. CSRF-токен подхватываем как в send() (на проде — сессия admin).
async function upload<T>(url: string, file: File, label?: string): Promise<T> {
  const fd = new FormData()
  fd.append('file', file)
  if (label) fd.append('label', label)
  const headers: Record<string, string> = { Accept: 'application/json' }
  const csrf = getCookie('csrftoken')
  if (csrf) headers['X-CSRFToken'] = csrf
  const r = await fetch(url, { method: 'POST', headers, credentials: 'same-origin', body: fd })
  if (r.status === 401 || r.status === 403) { onUnauthorized?.(); throw new Error('unauthorized') }
  if (!r.ok) {
    let msg = `${r.status} ${url}`
    try { const j = await r.json(); if (j.detail) msg = j.detail } catch { /* no body */ }
    throw new Error(msg)
  }
  return r.json()
}

export const api = {
  // ── Аутентификация (волна 12) ──
  // me() зовётся на старте: 401 = не залогинен (null, без хука), заодно ставит
  // CSRF-cookie. Собственный fetch (не get()), чтобы 401 не дёргал onUnauthorized.
  me: async (): Promise<User | null> => {
    const r = await fetch('/api/auth/me/', {
      headers: { Accept: 'application/json' }, credentials: 'same-origin' })
    if (r.status === 401) return null
    if (!r.ok) throw new Error(`${r.status} /api/auth/me/`)
    return r.json()
  },
  login: (username: string, password: string) =>
    send<User>('POST', '/api/auth/login/', { username, password }),
  logout: () => send<void>('POST', '/api/auth/logout/'),
  // Справочник пользователей — пикер авторства шапки ордера (Ф2j).
  users: () => get<UserRow[]>('/api/users/'),

  projects: () => get<ProjectRow[]>('/api/projects/'),
  createProject: (b: { code: string; name: string; budget?: number; started_at?: string }) =>
    send<ProjectRow>('POST', '/api/projects/', b),
  items: () => get<ItemRow[]>('/api/items/'),
  createItem: (b: { code: string; name: string; kind?: string; uom?: string;
    is_manufactured?: boolean; estimated_cost?: number }) =>
    send<ItemRow>('POST', '/api/items/', b),
  project: (id: number) => get<ProjectDetail>(`/api/projects/${id}/`),
  updateProject: (id: number, b: Partial<{ code: string; name: string; budget: number | null; started_at: string | null }>) =>
    send<ProjectDetail>('PATCH', `/api/projects/${id}/`, b),
  deficit: (id: number) => get<Deficit>(`/api/projects/${id}/deficit/`),
  addDemand: (projectId: number, b: { target_item_id: number; qty: number }) =>
    send<Deficit>('POST', `/api/projects/${projectId}/demands/`, b),
  updateDemand: (demandId: number, qty: number) =>
    send<Deficit>('PATCH', `/api/project-demands/${demandId}/`, { qty }),
  deleteDemand: (demandId: number) =>
    send<Deficit>('DELETE', `/api/project-demands/${demandId}/`),
  budget: (id: number) => get<Budget>(`/api/projects/${id}/budget/`),
  item: (id: number) => get<ItemDetail>(`/api/items/${id}/`),
  updateItem: (id: number, b: Partial<{ code: string; name: string; kind: string;
    uom: string; is_manufactured: boolean; estimated_cost: number | null }>) =>
    send<ItemDetail>('PATCH', `/api/items/${id}/`, b),
  addBomLine: (itemId: number, b: { component_id: number; qty: number; position?: string }) =>
    send<ItemDetail>('POST', `/api/items/${itemId}/bom/`, b),
  updateBomLine: (lineId: number, b: Partial<{ qty: number; position: string }>) =>
    send<ItemDetail>('PATCH', `/api/bom-lines/${lineId}/`, b),
  deleteBomLine: (lineId: number) =>
    send<ItemDetail>('DELETE', `/api/bom-lines/${lineId}/`),

  kittings: () => get<KittingRow[]>('/api/kittings/'),
  kitting: (id: number) => get<Cockpit>(`/api/kittings/${id}/`),
  updateKitting: (id: number, b: Partial<{ qty: number; date: string; user_id: number
      project_id: number; target_id: number }>) =>
    send<Cockpit>('PATCH', `/api/kittings/${id}/`, b),
  createKitting: (b: { project_id: number; target_item_id: number; qty: number }) =>
    send<Cockpit>('POST', '/api/kittings/', b),
  pierce: (id: number, b: { component_id: number; lot_id: number; qty: number }) =>
    send<Cockpit>('POST', `/api/kittings/${id}/lines/`, b),
  updateLine: (id: number, qty: number) =>
    send<Cockpit>('PATCH', `/api/kitting-lines/${id}/`, { qty }),
  deleteLine: (id: number) => send<Cockpit>('DELETE', `/api/kitting-lines/${id}/`),
  closeKitting: (id: number) => send<Cockpit>('POST', `/api/kittings/${id}/close/`),
  reopenKitting: (id: number) => send<Cockpit>('POST', `/api/kittings/${id}/reopen/`),
  deleteKitting: (id: number) => send<void>('DELETE', `/api/kittings/${id}/`),

  counterparties: (role?: 'supplier' | 'customer') =>
    get<CounterpartyRow[]>(`/api/counterparties/${role ? `?role=${role}` : ''}`),
  createCounterparty: (b: { name: string; inn?: string; role?: 'supplier' | 'customer' }) =>
    send<CounterpartyRow>('POST', '/api/counterparties/', b),
  receipts: () => get<ReceiptRow[]>('/api/receipts/'),
  receipt: (id: number) => get<ReceiptCockpit>(`/api/receipts/${id}/`),
  updateReceipt: (id: number, b: Partial<{ number: string; date: string; user_id: number; project_id: number }>) =>
    send<ReceiptCockpit>('PATCH', `/api/receipts/${id}/`, b),
  createReceipt: (b: { contractor_id: number; project_id: number; number: string; date: string }) =>
    send<ReceiptCockpit>('POST', '/api/receipts/', b),
  addReceiptLot: (id: number, b: {
    item_id: number; qty: number; unit_cost?: number
    lot_name?: string; part_number?: string
  }) => send<ReceiptCockpit>('POST', `/api/receipts/${id}/lots/`, b),
  updateReceiptLot: (id: number, b: Partial<{
    qty: number; unit_cost: number; lot_name: string; part_number: string
  }>) => send<ReceiptCockpit>('PATCH', `/api/lots/${id}/`, b),
  deleteReceiptLot: (id: number) => send<ReceiptCockpit>('DELETE', `/api/lots/${id}/`),
  approveReceipt: (id: number) => send<ReceiptCockpit>('POST', `/api/receipts/${id}/approve/`),
  unapproveReceipt: (id: number) => send<ReceiptCockpit>('POST', `/api/receipts/${id}/unapprove/`),
  linkReceiptPurchase: (id: number, purchase_id: number | null) =>
    send<ReceiptCockpit>('POST', `/api/receipts/${id}/link/`, { purchase_id }),
  deleteReceipt: (id: number) => send<void>('DELETE', `/api/receipts/${id}/`),

  purchases: () => get<PurchaseRow[]>('/api/purchases/'),
  purchase: (id: number) => get<PurchaseCockpit>(`/api/purchases/${id}/`),
  updatePurchase: (id: number, b: Partial<{ date: string; note: string; user_id: number
      project_id: number; procurement_id: number }>) =>
    send<PurchaseCockpit>('PATCH', `/api/purchases/${id}/`, b),
  createPurchase: (b: { project_id: number; date?: string; note?: string }) =>
    send<PurchaseCockpit>('POST', '/api/purchases/', b),
  addPurchaseLine: (id: number, b: { item_id: number; qty: number }) =>
    send<PurchaseCockpit>('POST', `/api/purchases/${id}/lines/`, b),
  updatePurchaseLine: (id: number, qty: number) =>
    send<PurchaseCockpit>('PATCH', `/api/purchase-lines/${id}/`, { qty }),
  deletePurchaseLine: (id: number) =>
    send<PurchaseCockpit>('DELETE', `/api/purchase-lines/${id}/`),
  sendPurchase: (id: number) => send<PurchaseCockpit>('POST', `/api/purchases/${id}/send/`),
  unsendPurchase: (id: number) => send<PurchaseCockpit>('POST', `/api/purchases/${id}/unsend/`),
  cancelPurchase: (id: number) => send<PurchaseCockpit>('POST', `/api/purchases/${id}/cancel/`),
  restorePurchase: (id: number) => send<PurchaseCockpit>('POST', `/api/purchases/${id}/restore/`),
  projectPurchases: (id: number) => get<ProjectPurchaseRow[]>(`/api/projects/${id}/purchases/`),
  addToOrder: (id: number, b: { item_id: number; qty: number }) =>
    send<{ purchase_id: number }>('POST', `/api/projects/${id}/order/`, b),

  transfers: () => get<TransferRow[]>('/api/transfers/'),
  transfer: (id: number) => get<TransferCockpit>(`/api/transfers/${id}/`),
  updateTransfer: (id: number, b: Partial<{ number: string; date: string; contractor_id: number | null; user_id: number; project_id: number }>) =>
    send<TransferCockpit>('PATCH', `/api/transfers/${id}/`, b),
  createTransfer: (b: { project_id: number; number: string; date?: string; contractor_id?: number }) =>
    send<TransferCockpit>('POST', '/api/transfers/', b),
  addTransferLine: (id: number, b: { lot_id: number; qty: number; display_name?: string }) =>
    send<TransferCockpit>('POST', `/api/transfers/${id}/lines/`, b),
  updateTransferLine: (id: number, b: Partial<{ qty: number; display_name: string }>) =>
    send<TransferCockpit>('PATCH', `/api/transfer-lines/${id}/`, b),
  deleteTransferLine: (id: number) =>
    send<TransferCockpit>('DELETE', `/api/transfer-lines/${id}/`),
  postTransfer: (id: number) => send<TransferCockpit>('POST', `/api/transfers/${id}/post/`),
  unpostTransfer: (id: number) => send<TransferCockpit>('POST', `/api/transfers/${id}/unpost/`),
  deleteTransfer: (id: number) => send<void>('DELETE', `/api/transfers/${id}/`),
  projectAvailableLots: (id: number) =>
    get<AvailableLot[]>(`/api/projects/${id}/available-lots/`),

  writeoffs: () => get<WriteoffRow[]>('/api/writeoffs/'),
  writeoff: (id: number) => get<WriteoffCockpit>(`/api/writeoffs/${id}/`),
  updateWriteoff: (id: number, b: Partial<{ number: string; date: string; reason: string; user_id: number; project_id: number }>) =>
    send<WriteoffCockpit>('PATCH', `/api/writeoffs/${id}/`, b),
  createWriteoff: (b: { project_id: number; number: string; date?: string; reason?: string }) =>
    send<WriteoffCockpit>('POST', '/api/writeoffs/', b),
  addWriteoffLine: (id: number, b: { lot_id: number; qty: number }) =>
    send<WriteoffCockpit>('POST', `/api/writeoffs/${id}/lines/`, b),
  updateWriteoffLine: (id: number, qty: number) =>
    send<WriteoffCockpit>('PATCH', `/api/writeoff-lines/${id}/`, { qty }),
  deleteWriteoffLine: (id: number) =>
    send<WriteoffCockpit>('DELETE', `/api/writeoff-lines/${id}/`),
  postWriteoff: (id: number) => send<WriteoffCockpit>('POST', `/api/writeoffs/${id}/post/`),
  unpostWriteoff: (id: number) => send<WriteoffCockpit>('POST', `/api/writeoffs/${id}/unpost/`),
  deleteWriteoff: (id: number) => send<void>('DELETE', `/api/writeoffs/${id}/`),

  requisitions: () => get<RequisitionRow[]>('/api/requisitions/'),
  requisition: (id: number) => get<RequisitionCockpit>(`/api/requisitions/${id}/`),
  updateRequisition: (id: number, b: Partial<{ number: string; date: string; user_id: number; project_id: number }>) =>
    send<RequisitionCockpit>('PATCH', `/api/requisitions/${id}/`, b),
  createRequisition: (b: { project_id: number; number: string; date?: string }) =>
    send<RequisitionCockpit>('POST', '/api/requisitions/', b),
  addRequisitionLine: (id: number, b: { source_lot_id: number; qty: number }) =>
    send<RequisitionCockpit>('POST', `/api/requisitions/${id}/lines/`, b),
  updateRequisitionLine: (id: number, qty: number) =>
    send<RequisitionCockpit>('PATCH', `/api/requisition-lines/${id}/`, { qty }),
  deleteRequisitionLine: (id: number) =>
    send<RequisitionCockpit>('DELETE', `/api/requisition-lines/${id}/`),
  postRequisition: (id: number) => send<RequisitionCockpit>('POST', `/api/requisitions/${id}/post/`),
  unpostRequisition: (id: number) => send<RequisitionCockpit>('POST', `/api/requisitions/${id}/unpost/`),
  deleteRequisition: (id: number) => send<void>('DELETE', `/api/requisitions/${id}/`),
  allAvailableLots: () => get<AllAvailableLot[]>('/api/available-lots/'),

  inventories: () => get<InventoryRow[]>('/api/inventories/'),
  inventory: (id: number) => get<InventoryCockpit>(`/api/inventories/${id}/`),
  updateInventory: (id: number, b: Partial<{ number: string; date: string; note: string; user_id: number; project_id: number }>) =>
    send<InventoryCockpit>('PATCH', `/api/inventories/${id}/`, b),
  createInventory: (b: { project_id: number; number: string; date?: string; note?: string }) =>
    send<InventoryCockpit>('POST', '/api/inventories/', b),
  addInventoryLot: (id: number, b: {
    item_id?: number; predecessor_id?: number; qty: number
    unit_cost?: number; lot_name?: string; part_number?: string
  }) => send<InventoryCockpit>('POST', `/api/inventories/${id}/lots/`, b),
  updateInventoryLot: (id: number, b: Partial<{
    qty: number; unit_cost: number; lot_name: string; part_number: string
  }>) => send<InventoryCockpit>('PATCH', `/api/inventory-lots/${id}/`, b),
  deleteInventoryLot: (id: number) =>
    send<InventoryCockpit>('DELETE', `/api/inventory-lots/${id}/`),
  postInventory: (id: number) => send<InventoryCockpit>('POST', `/api/inventories/${id}/post/`),
  unpostInventory: (id: number) => send<InventoryCockpit>('POST', `/api/inventories/${id}/unpost/`),
  deleteInventory: (id: number) => send<void>('DELETE', `/api/inventories/${id}/`),
  writtenOffLots: () => get<WrittenOffLot[]>('/api/written-off-lots/'),

  // ── Места хранения / Location (волна 13 Ф3 пикер, Ф4 сущность «Склады») ──
  locations: () => get<LocationRow[]>('/api/locations/'),
  location: (id: number) => get<LocationCockpit>(`/api/locations/${id}/`),
  createLocation: (b: { code: string; name: string; kind?: string }) =>
    send<LocationRow>('POST', '/api/locations/', b),
  updateLocation: (id: number, b: Partial<{ code: string; name: string; kind: string }>) =>
    send<LocationCockpit>('PATCH', `/api/locations/${id}/`, b),

  // ── Перемещение / Relocation (волна 13 Ф3) ──
  relocations: () => get<RelocationRow[]>('/api/relocations/'),
  relocation: (id: number) => get<RelocationCockpit>(`/api/relocations/${id}/`),
  updateRelocation: (id: number, b: Partial<{ number: string; date: string; user_id: number; project_id: number }>) =>
    send<RelocationCockpit>('PATCH', `/api/relocations/${id}/`, b),
  createRelocation: (b: { project_id: number; number: string; date?: string }) =>
    send<RelocationCockpit>('POST', '/api/relocations/', b),
  addRelocationLine: (id: number, b: {
    lot_id: number; qty: number; from_location_id: number; to_location_id: number
  }) => send<RelocationCockpit>('POST', `/api/relocations/${id}/lines/`, b),
  updateRelocationLine: (id: number, lotId: number, b: Partial<{
    qty: number; from_location_id: number; to_location_id: number
  }>) => send<RelocationCockpit>('PATCH', `/api/relocations/${id}/lines/${lotId}/`, b),
  deleteRelocationLine: (id: number, lotId: number) =>
    send<RelocationCockpit>('DELETE', `/api/relocations/${id}/lines/${lotId}/`),
  postRelocation: (id: number) => send<RelocationCockpit>('POST', `/api/relocations/${id}/post/`),
  unpostRelocation: (id: number) => send<RelocationCockpit>('POST', `/api/relocations/${id}/unpost/`),
  deleteRelocation: (id: number) => send<void>('DELETE', `/api/relocations/${id}/`),
  relocationSourceLots: (id: number) =>
    get<RelocationSourceLot[]>(`/api/relocations/${id}/source-lots/`),

  // ── Планирование закупок (волна 7) ──
  commandDeficit: () => get<CommandDeficit>('/api/command-deficit/'),
  addToProcurement: (b: { item_id: number; qty: number }) =>
    send<{ procurement_id: number }>('POST', '/api/command-deficit/add-to-procurement/', b),
  procurements: () => get<ProcurementRow[]>('/api/procurements/'),
  procurement: (id: number) => get<ProcurementCockpit>(`/api/procurements/${id}/`),
  updateProcurement: (id: number, b: Partial<{ date: string; note: string; user_id: number }>) =>
    send<ProcurementCockpit>('PATCH', `/api/procurements/${id}/`, b),
  createProcurement: (b: { note?: string; date?: string }) =>
    send<ProcurementCockpit>('POST', '/api/procurements/', b),
  addProcurementLine: (id: number, b: { item_id: number; qty: number }) =>
    send<ProcurementCockpit>('POST', `/api/procurements/${id}/lines/`, b),
  updateProcurementLine: (id: number, qty: number) =>
    send<ProcurementCockpit>('PATCH', `/api/procurement-lines/${id}/`, { qty }),
  deleteProcurementLine: (id: number) =>
    send<ProcurementCockpit>('DELETE', `/api/procurement-lines/${id}/`),
  sendProcurement: (id: number) => send<ProcurementCockpit>('POST', `/api/procurements/${id}/send/`),
  unsendProcurement: (id: number) => send<ProcurementCockpit>('POST', `/api/procurements/${id}/unsend/`),
  cancelProcurement: (id: number) => send<ProcurementCockpit>('POST', `/api/procurements/${id}/cancel/`),
  restoreProcurement: (id: number) => send<ProcurementCockpit>('POST', `/api/procurements/${id}/restore/`),
  orderXlsxUrl: (id: number) => `/api/procurements/${id}/order.xlsx`,
  // pegging (волна 8)
  pegging: (id: number) => get<Pegging>(`/api/procurements/${id}/pegging/`),
  peg: (id: number, b: { item_id: number; project_id: number; qty: number }) =>
    send<Pegging>('POST', `/api/procurements/${id}/peg/`, b),
  unpeg: (id: number, b: { item_id: number; project_id: number }) =>
    send<Pegging>('POST', `/api/procurements/${id}/unpeg/`, b),
  autopeg: (id: number) => send<Pegging>('POST', `/api/procurements/${id}/autopeg/`),

  // ── Вложения (волна 11) ──
  attachments: (ownerType: string, ownerId: number) =>
    get<AttachmentRow[]>(`/api/attachments/${ownerType}/${ownerId}/`),
  uploadAttachment: (ownerType: string, ownerId: number, file: File, label?: string) =>
    upload<AttachmentRow>(`/api/attachments/${ownerType}/${ownerId}/`, file, label),
  updateAttachment: (id: number, label: string) =>
    send<AttachmentRow>('PATCH', `/api/attachments/${id}/`, { label }),
  deleteAttachment: (id: number) => send<void>('DELETE', `/api/attachments/${id}/`),

  closure: (id: number) => get<ProjectClosure>(`/api/projects/${id}/closure/`),
  writeoffLot: (id: number, b: { lot_id: number; qty: number }) =>
    send<ProjectClosure>('POST', `/api/projects/${id}/writeoff-lot/`, b),
  stockLot: (id: number, b: { lot_id: number; qty: number }) =>
    send<ProjectClosure>('POST', `/api/projects/${id}/stock-lot/`, b),
  closeProject: (id: number) => send<ProjectClosure>('POST', `/api/projects/${id}/close/`),
  reopenProject: (id: number) => send<ProjectClosure>('POST', `/api/projects/${id}/reopen/`),
}
