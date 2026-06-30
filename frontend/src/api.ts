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

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw new Error(`${r.status} ${url}`)
  return r.json()
}

export const api = {
  projects: () => get<ProjectRow[]>('/api/projects/'),
  items: () => get<ItemRow[]>('/api/items/'),
  deficit: (id: number) => get<Deficit>(`/api/projects/${id}/deficit/`),
  item: (id: number) => get<ItemDetail>(`/api/items/${id}/`),
}
