// API-клиент витрин волны 1. Все эндпоинты — read-only проекции движка.
export type Status = 'available' | 'on_order' | 'to_order'

export interface ProjectRow {
  id: number; code: string; name: string; kind: string; status: string
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
export interface Deficit {
  project_id: number; project_code: string; project_name: string
  demands: DeficitDemand[]
}

export interface StockMapRow {
  project_id: number; project_code: string; project_name: string
  project_kind: string; available: number
}
export interface StockMap {
  item_id: number; item_code: string; item_name: string; uom: string
  rows: StockMapRow[]
}
export interface ItemDetail {
  id: number; code: string; name: string; kind: string; uom: string
  is_manufactured: boolean; estimated_cost: number | null
  bom: { component_id: number; component_code: string; component_name: string; qty: number }[]
  where_used: { parent_id: number; parent_code: string; parent_name: string; qty: number }[]
  lots: { id: number; project_code: string; origin: string; qty_born: number;
          live_qty: number; unit_cost: number; serial_number: string }[]
  stock_map: StockMap
}

// ── Кокпит комплектации (волна 2 — записываемое ядро) ──
export interface KittingRow {
  id: number; project_code: string; target_code: string; target_name: string
  qty: number; status: string; date: string | null
}
export interface CandidateLot {
  lot_id: number; live_qty: number; unit_cost: number; serial_number: string
  origin: string; received_name: string
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
  id: number; qty: number; unit_cost: number; serial_number: string
}
export interface Cockpit {
  id: number; status: string; project_id: number; project_code: string
  target_id: number; target_code: string; target_name: string; uom: string
  qty: number; date: string | null; cockpit_status: Status
  rows: CockpitRow[]; born_lots: BornLot[]
}

// ── Приход / УПД (волна 3 — записываемое ядро) ──
export interface SupplierRow { id: number; name: string; inn: string }
export interface ReceiptRow {
  id: number; number: string; date: string; supplier_name: string
  project_code: string; approved: boolean; lines: number
}
export interface ReceiptLot {
  id: number; item_id: number; item_code: string; item_name: string; uom: string
  qty: number; live_qty: number; unit_cost: number; received_name: string
  serial_number: string; consumed: boolean
}
export interface ReceiptCockpit {
  id: number; number: string; date: string; supplier_id: number; supplier_name: string
  project_id: number; project_code: string; project_name: string
  approved: boolean; total_cost: number; lots: ReceiptLot[]
}

function getCookie(name: string): string | null {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)')
  return m ? decodeURIComponent(m[2]) : null
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: 'application/json' } })
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
  if (!r.ok) {
    let msg = `${r.status} ${url}`
    try { const j = await r.json(); if (j.detail) msg = j.detail } catch { /* no body */ }
    throw new Error(msg)
  }
  return r.status === 204 ? (undefined as T) : r.json()
}

export const api = {
  projects: () => get<ProjectRow[]>('/api/projects/'),
  items: () => get<ItemRow[]>('/api/items/'),
  deficit: (id: number) => get<Deficit>(`/api/projects/${id}/deficit/`),
  item: (id: number) => get<ItemDetail>(`/api/items/${id}/`),

  kittings: () => get<KittingRow[]>('/api/kittings/'),
  kitting: (id: number) => get<Cockpit>(`/api/kittings/${id}/`),
  createKitting: (b: { project_id: number; target_item_id: number; qty: number }) =>
    send<Cockpit>('POST', '/api/kittings/', b),
  pierce: (id: number, b: { component_id: number; lot_id: number; qty: number }) =>
    send<Cockpit>('POST', `/api/kittings/${id}/lines/`, b),
  updateLine: (id: number, qty: number) =>
    send<Cockpit>('PATCH', `/api/kitting-lines/${id}/`, { qty }),
  deleteLine: (id: number) => send<Cockpit>('DELETE', `/api/kitting-lines/${id}/`),
  closeKitting: (id: number) => send<Cockpit>('POST', `/api/kittings/${id}/close/`),
  reopenKitting: (id: number) => send<Cockpit>('POST', `/api/kittings/${id}/reopen/`),

  suppliers: () => get<SupplierRow[]>('/api/suppliers/'),
  createSupplier: (b: { name: string; inn?: string }) =>
    send<SupplierRow>('POST', '/api/suppliers/', b),
  receipts: () => get<ReceiptRow[]>('/api/receipts/'),
  receipt: (id: number) => get<ReceiptCockpit>(`/api/receipts/${id}/`),
  createReceipt: (b: { supplier_id: number; project_id: number; number: string; date: string }) =>
    send<ReceiptCockpit>('POST', '/api/receipts/', b),
  addReceiptLot: (id: number, b: {
    item_id: number; qty: number; unit_cost?: number
    received_name?: string; serial_number?: string
  }) => send<ReceiptCockpit>('POST', `/api/receipts/${id}/lots/`, b),
  updateReceiptLot: (id: number, b: Partial<{
    qty: number; unit_cost: number; received_name: string; serial_number: string
  }>) => send<ReceiptCockpit>('PATCH', `/api/lots/${id}/`, b),
  deleteReceiptLot: (id: number) => send<ReceiptCockpit>('DELETE', `/api/lots/${id}/`),
  approveReceipt: (id: number) => send<ReceiptCockpit>('POST', `/api/receipts/${id}/approve/`),
  unapproveReceipt: (id: number) => send<ReceiptCockpit>('POST', `/api/receipts/${id}/unapprove/`),
}
