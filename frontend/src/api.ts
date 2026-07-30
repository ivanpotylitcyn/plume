// API-клиент витрин волны 1. Все эндпоинты — read-only проекции движка.
export type Status = 'available' | 'on_order' | 'to_order'

// Замок изделия (волна 17; строка → bool в волне 19, Ф1c): `locked` = форма
// read-only (свойства+BOM), мутации гейтятся бэком. Ось общая для ВСЕХ сущностей —
// изделия, ордеров, закупки, заказа, проекта: одно поле, один глагол, один глиф.
// Подписи («Зафиксировать»/«Расфиксировать») живут здесь, во вью, а не в БД.

// ── Авторство шапки (волна 13, Ф2j) — единый пикер автора, редактируемо под
//    замком на всех ордерах/закупках. `UserRow` — справочник пикера. ──
export interface UserRow {
  id: number; username: string; full_name: string; is_superuser: boolean
}
export interface Authored { user_id: number; user_name: string }

export interface ProjectRow {
  id: number; code: string; description: string; kind: string; locked: boolean
  health: Status | null   // Ф1b: worst-of здоровья для цвета в списке (null — неприменимо)
}
export interface ProjectDetail extends ProjectRow {
  budget: number | null; started: string | null
}
// Категория изделия (волна 15): FK-справочник. Волна 19 Ф10: единый интерфейс
// идентичности `code` + `description` (`label`→`description`, `icon` удалён).
export interface Category {
  id: number; code: string; description: string
}
export interface ItemRow {
  // `id` — PK (FK-ссылки/мутации); `code` — бизнес-ключ (канон библиотеки).
  id: number; code: string; description: string; category: Category | null
  uom: string; temperature: string; native: boolean; synced: boolean; used: boolean; locked: boolean
}

// Узел дерева аккордеона прибора (Ф5b): плоский pre-order с `depth`. Лист (покупной)
// несёт покрытие; узел-подсборка (`is_leaf=false`) — структурный (без покрытия), статус
// = worst-of поддерева. Купить можно только листья → заказ живёт в своде «Потребность».
export interface DeficitTreeNode {
  component_id: number; component_code: string; component_description: string; uom: string
  component_native: boolean; component_synced: boolean; component_locked: boolean
  need: number; depth: number; is_leaf: boolean; status: Status
  have?: number; on_order?: number; to_order?: number; available_raw?: number; anomaly?: boolean
}
export interface DeficitDemand {
  demand_id: number; target_id: number; target_code: string; target_description: string
  target_native: boolean; target_synced: boolean; target_locked: boolean
  qty: number; device: { done: number; wip: number; not_started: number }
  status: Status; badge: Status; tree: DeficitTreeNode[]
}
// Свод потребности по компонентам на весь проект (секция «Потребность»).
export interface DeficitComponent {
  component_id: number; component_code: string; component_description: string; uom: string
  component_native: boolean; component_synced: boolean; component_locked: boolean
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
  item_id: number; item_code: string; item_description: string; uom: string
  rows: StockMapRow[]
}
// Лента движений изделия (волна 19, Ф12a): ВСЕ ордера, коснувшиеся его партий —
// рождение (`born`, знак +) и движения существующих партий (`move`, знак в `qty`).
// Пришла на смену узкой `ItemShipment` (только передачи).
export interface ItemMovement {
  event: 'born' | 'move'
  kind: string; document_id: number; code: string | null; number: string
  date: string | null; locked: boolean; project_code: string
  lot_id: number; lot_name: string; qty: number
}
export interface ItemDetail {
  id: number; code: string; description: string; category: Category | null
  uom: string; temperature: string; native: boolean; synced: boolean; used: boolean; locked: boolean
  estimated_cost: number | null
  bom: { id: number; component_id: number; component_code: string;
         component_description: string; component_uom: string;
         component_native: boolean; component_synced: boolean; component_locked: boolean;
         qty: number; position: string }[]
  where_used: { parent_id: number; parent_code: string; parent_description: string; qty: number
                parent_native: boolean; parent_synced: boolean; parent_locked: boolean }[]
  // `origin_locked` (Ф15): партия черновика лежит в этом списке, но НЕ на складе —
  // остатка у неё нет вовсе (не «исчерпана»), вью гасит колонку и тон глифа.
  lots: { id: number; project_code: string; origin: string; origin_locked: boolean
          qty_born: number
          live_qty: number; unit_cost: number; part_number: string; lot_name: string }[]
  movements: ItemMovement[]
}

// ── Синхронизация справочника с библиотекой Altium (волна 15) ──
// Диф-строка: `status` задаёт действие/флаг; `incoming` — из библиотеки (нет у
// gone/orphan), `current` — из БД (нет у new), `changes` — что отличается (только changed).
// `mark` (Ф3a, волна 19) — содержимое совпадает с библиотекой, но изделие ещё не
// помечено библиотечным (`synced=false`) → подтвердить = пометить `synced` (замок не
// трогаем). Путь бэкфилла после Ф3a: существующие библиотечные метятся первым синком.
export type LibraryStatus = 'new' | 'changed' | 'mark' | 'gone' | 'orphan' | 'same'
export interface LibrarySnapshot {
  description: string; temperature: string; category: string
  native?: boolean; synced?: boolean; locked?: boolean
}
export interface LibraryChange { old: string; new: string }
export interface LibraryDiffRow {
  status: LibraryStatus; code: string; item_id: number | null
  incoming?: LibrarySnapshot; current?: LibrarySnapshot
  changes?: Partial<Record<'description' | 'temperature' | 'category', LibraryChange>>
}
export interface LibraryDiff { categories: string[]; rows: LibraryDiffRow[] }
export interface LibraryApplySummary { created: number; updated: number; marked: number; deleted: number }
// Роллап стоимости: детальный экран изделия + сводка пересчёта.
export interface RollupResult {
  estimated_cost: number | null; updated: string[]; incomplete: string[]
}
export type ItemDetailWithRollup = ItemDetail & { rollup: RollupResult }

// ── Форма комплектации (волна 2 — записываемое ядро) ──
export interface KittingRow {
  id: number; code: string | null; project_code: string
  target_code: string; target_description: string
  qty: number; locked: boolean; date: string | null
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
export interface KittingFormRow {
  component_id: number; component_code: string; component_description: string; uom: string
  need: number; pierced: number; remaining: number
  real_lines: RealLine[]; ghost: Ghost | null
}
export interface BornLot {
  id: number; qty: number; unit_cost: number; lot_name: string; part_number: string
}
export interface KittingForm extends Authored {
  id: number; locked: boolean; code: string | null; description: string
  project_id: number; project_code: string
  target_id: number | null; target_code: string; target_description: string; uom: string
  qty: number | null; date: string | null; worst_status: Status
  rows: KittingFormRow[]; born_lots: BornLot[]
}

// ── Контрагенты (волна 13, Ф2f+ — единая сущность документооборота) ──
// `has_*` — СТОРОНЫ ПО ФАКТАМ (волна 20, Ф3, вместо снесённых ролей-флагов): что-то у
// него покупали / что-то ему передавали. Считает движок, вью только читает: глиф
// строки справочника и порядок в пикере («свои» для этого вида ордера — наверх).
export interface CounterpartyRow {
  id: number; code: string | null; description: string; inn: string
  has_supply: boolean; has_shipment: boolean
}

// ── Форма контрагента (волна 20 — режим «Контрагенты») ──
// Обе стороны документооборота: `null` = «движений нет» (решает движок).
export interface UomQty { uom: string; qty: number }
// `draft_*` — сколько документов стороны ещё черновики: они считаются документами,
// но в материальный итог не входят (замок гейтит склад, Ф15).
export interface CounterpartySupply {
  procurements: number; purchases: number; open_purchases: number
  receipts: number; draft_receipts: number
  lots: number; qty_by_uom: UomQty[]; total: number
}
export interface CounterpartyShipment {
  transfers: number; draft_transfers: number
  lots: number; qty_by_uom: UomQty[]; total: number
}
export interface CpProcurementRow {
  id: number; code: string | null; description: string
  date: string | null; locked: boolean; lines: number; qty: number
}
export interface CpPurchaseRow extends CpProcurementRow {
  project_code: string; coverage: Status
}
export interface CpReceiptRow {
  id: number; code: string | null; number: string; date: string | null
  locked: boolean; project_code: string; purchase_id: number | null
  lots: number; total: number
}
export interface CpTransferRow {
  id: number; code: string | null; number: string; date: string | null
  locked: boolean; project_code: string; lines: number; qty: number; total: number
}
export interface CounterpartyForm {
  id: number; code: string | null; description: string; inn: string
  supply: CounterpartySupply | null
  shipment: CounterpartyShipment | null
  procurements: CpProcurementRow[]; purchases: CpPurchaseRow[]
  receipts: CpReceiptRow[]; transfers: CpTransferRow[]
}

// ── Приход / УПД (волна 3 — записываемое ядро) ──
export interface ReceiptRow {
  id: number; code: string | null; number: string; date: string; contractor_name: string
  project_code: string; locked: boolean; lines: number
}
export interface ReceiptLot {
  id: number; item_id: number; item_code: string; item_description: string; uom: string
  qty: number; live_qty: number; unit_cost: number; lot_name: string
  part_number: string; consumed: boolean
}
export interface ReceiptForm extends Authored {
  id: number; number: string; date: string
  code: string | null; description: string
  contractor_id: number | null; contractor_name: string
  contractor_mismatch: boolean   // Ф17: «кто привёз» ≠ «у кого купили» (флаг от движка)
  project_id: number; project_code: string; project_name: string
  purchase_id: number | null
  locked: boolean; total_cost: number; lots: ReceiptLot[]
}

// ── Заказ / Purchase (волна 4 — записываемое ядро) ──
export interface PurchaseRow {
  id: number; code: string | null; description: string
  project_code: string; locked: boolean
  date: string | null; lines: number
  coverage: Status   // Ф1b: покрытие лотами для цвета в списке
}
export interface PurchaseFormLine {
  id: number; item_id: number; item_code: string; item_description: string; uom: string
  item_native: boolean; item_synced: boolean; item_locked: boolean
  qty: number; received: number; remaining: number; status: Status
  receipts: LineReceiptRow[]   // Ф6: чем строка закрыта (обычно одна накладная)
}
export interface LineReceiptRow {
  receipt_id: number; number: string; date: string; qty: number
}
export interface PurchaseReceiptRow {
  id: number; code: string | null; number: string; date: string
  locked: boolean; contractor_name: string; lines: number
}
export interface PurchaseForm extends Authored {
  id: number; locked: boolean; project_id: number; project_code: string
  // Ф17: закупка-план опциональна; контрагент — своё поле заказа («у кого купили»).
  project_name: string; procurement_id: number | null
  contractor_id: number | null; contractor_name: string
  contractor_mismatch: boolean   // расхождение с контрагентом закупки — знак, не гейт
  code: string | null; description: string; date: string | null
  editable: boolean; worst_status: Status
  total_ordered: number; total_received: number
  rows: PurchaseFormLine[]; receipts: PurchaseReceiptRow[]
}
export interface ProjectPurchaseRow {
  id: number; locked: boolean; date: string | null
  code: string | null; description: string; lines: number
}

// ── Передача / Transfer (волна 5 — записываемое ядро) ──
export interface TransferRow {
  id: number; code: string | null; number: string; date: string; project_code: string
  locked: boolean; lines: number
}
export interface AvailableLot {
  lot_id: number; item_id: number; item_code: string; item_description: string; uom: string
  live_qty: number; origin: string; part_number: string; lot_name: string
}
export interface TransferFormLine {
  id: number; lot_id: number; lot_label: string; origin: string | null
  item_id: number; item_code: string
  item_description: string; uom: string; qty: number; display_name: string
  lot_live_qty: number; lot_name: string
}
export interface TransferForm extends Authored {
  id: number; number: string; date: string
  code: string | null; description: string
  contractor_id: number | null; contractor_name: string
  project_id: number; project_code: string; project_name: string; locked: boolean
  total_qty: number; lines: TransferFormLine[]
}

// ── Списание / Writeoff (волна 6 — записываемое ядро) ──
export interface WriteoffRow {
  id: number; code: string | null; number: string; date: string; project_code: string
  reason: string; locked: boolean; lines: number
}
export interface WriteoffFormLine {
  id: number; lot_id: number; lot_label: string; origin: string | null
  item_id: number; item_code: string
  item_description: string; uom: string; qty: number; lot_live_qty: number
  lot_name: string
}
export interface WriteoffForm extends Authored {
  id: number; number: string; date: string; reason: string
  code: string | null; description: string
  project_id: number; project_code: string; project_name: string
  locked: boolean; total_qty: number; lines: WriteoffFormLine[]
}

// ── Требование / Requisition (волна 6 — записываемое ядро) ──
export interface RequisitionRow {
  id: number; code: string | null; number: string; date: string; project_code: string
  locked: boolean; lines: number
}
export interface AllAvailableLot {
  lot_id: number; item_id: number; item_code: string; item_description: string; uom: string
  live_qty: number; origin: string; project_id: number; project_code: string
  part_number: string; lot_name: string
}
export interface RequisitionFormLine {
  id: number; source_lot_id: number; lot_label: string; origin: string | null
  source_project_code: string
  item_id: number; item_code: string; item_description: string; uom: string
  qty: number; source_live_qty: number; born_lot_id: number | null
  lot_name: string
}
export interface RequisitionForm extends Authored {
  id: number; number: string; date: string
  code: string | null; description: string
  project_id: number; project_code: string; project_name: string
  locked: boolean; total_qty: number; lines: RequisitionFormLine[]
}

// ── Место хранения / Location (волна 13 Ф3 пикер, Ф4 сущность «Склады») ──
export interface LocationRow { id: number; code: string; description: string; kind: string }
export interface LocationStockLot {
  lot_id: number; lot_label: string; part_number: string; lot_name: string; origin: string | null
  item_id: number; item_code: string; item_description: string; uom: string; qty: number
  project_id: number; project_code: string; project_name: string
}
export interface LocationForm {
  id: number; code: string; description: string; kind: string
  stock: LocationStockLot[]
}

// ── Перемещение / Relocation (волна 13 Ф3 — записываемое ядро) ──
export interface RelocationRow {
  id: number; code: string | null; number: string; date: string; project_code: string
  locked: boolean; lines: number
}
export interface RelocationMove {
  lot_id: number; lot_label: string; origin: string | null
  item_id: number; item_code: string
  item_description: string; uom: string; qty: number
  from_location_id: number | null; from_location: string
  to_location_id: number | null; to_location: string
  from_live_qty: number; to_live_qty: number
}
export interface RelocationForm extends Authored {
  id: number; number: string; date: string
  code: string | null; description: string
  project_id: number; project_code: string; project_name: string
  locked: boolean; total_qty: number; moves: RelocationMove[]
}
export interface LotLocation {
  location_id: number; code: string; description: string; qty: number
}
export interface RelocationSourceLot {
  lot_id: number; item_id: number; item_code: string; item_description: string; uom: string
  live_qty: number; part_number: string; lot_name: string
  by_location: LotLocation[]
}

// ── Инвентаризация / Inventory (волна 9 — записываемое ядро) ──
export interface InventoryRow {
  id: number; code: string | null; description: string
  number: string; date: string; project_code: string
  locked: boolean; lines: number
}
export interface InventoryFormLot {
  id: number; item_id: number; item_code: string; item_description: string; uom: string
  qty: number; live_qty: number; unit_cost: number; lot_name: string
  part_number: string; predecessor_id: number | null; predecessor_label: string
  consumed: boolean
}
export interface InventoryForm extends Authored {
  id: number; number: string; date: string
  code: string | null; description: string
  project_id: number; project_code: string; project_name: string
  locked: boolean; total_cost: number; lots: InventoryFormLot[]
}
export interface WrittenOffLot {
  lot_id: number; item_id: number; item_code: string; item_description: string; uom: string
  written_qty: number; project_code: string; unit_cost: number
  lot_name: string; part_number: string
}

// ── Панель закрытия проекта (волна 6) ──
export interface ResidualLot {
  lot_id: number; lot_label: string; origin: string | null; item_id: number; item_code: string
  item_description: string; uom: string; live_qty: number; anomaly: boolean
}
// Черновой закрывающий документ (волна 19, Ф15): мост панели («списать»/«на баланс»)
// кладёт остаток в расфиксированный ордер, а склад тот двигает только на фиксации —
// панель показывает такие документы, иначе кнопка выглядит несработавшей.
export interface ClosingDraft {
  document_id: number; kind: string; code: string; number: string; qty: number
}
export interface ProjectClosure {
  project_id: number; project_code: string; project_name: string; kind: string
  locked: boolean; closed: string | null; is_external: boolean
  residuals: ResidualLot[]; residual_positive: number; anomaly_count: number
  closing_drafts: ClosingDraft[]
  can_close: boolean; blocker: string
}

// ── Планирование закупок (волна 7): командный свод + Procurement ──
// ── Свод по охвату закупки (волна 19, Ф13; бывший «Командный свод») ──
// Экран-фантом схлопнут в таб «К закупке» обычной закупки: те же строки, но по её
// охвату проектов. `planned` — сколько уже взято в строки плана.
export interface ScopeDeficitProject {
  project_id: number; project_code: string; project_name: string
  need: number; have: number; on_order: number; to_order: number; status: Status
}
export interface ScopeDeficitRow {
  item_id: number; item_code: string; item_description: string; uom: string
  native: boolean
  need: number; have: number; on_order: number; to_order: number; planned: number
  status: Status; by_project: ScopeDeficitProject[]
}
export interface ScopeDeficit { rows: ScopeDeficitRow[] }

export interface ProcurementRow {
  id: number; locked: boolean; date: string | null
  code: string | null; description: string; lines: number
}
export interface ProcurementFormLine {
  id: number; item_id: number; item_code: string; item_description: string
  item_native: boolean; item_synced: boolean; item_locked: boolean
  uom: string; qty: number
}
export interface ProcurementScopeProject {
  id: number; code: string; description: string
}
export interface ProcurementForm extends Authored {
  id: number; locked: boolean; date: string | null
  code: string | null; description: string; editable: boolean
  contractor_id: number | null; contractor_name: string
  projects: ProcurementScopeProject[]        // охват (Ф13): под какие проекты закупка
  total_qty: number; lines: ProcurementFormLine[]
}

// ── Pegging (волна 8): нарезка плана на проектные заказы ──
// Применение изделия в проекте (обратное разузлование, Ф5): «зачем оно тут».
export interface PeggingUsage {
  target_item_id: number; target_code: string; target_description: string
  per_unit: number; demand_qty: number; total: number
}
// Заказ проекта под этим планом — куда пегать (Р2: их может быть несколько).
export interface PeggingPurchase {
  id: number; code: string; locked: boolean; lines: number
}
export interface PeggingProject {
  project_id: number; project_code: string; project_name: string
  suggest: number; pegged: number
  usage: PeggingUsage[]; purchases: PeggingPurchase[]
}
export interface PeggingRow {
  line_id: number; item_id: number; item_code: string; item_description: string
  uom: string; qty: number; pegged: number; remaining: number; status: Status
  by_project: PeggingProject[]
}
export interface PeggingFanRow {
  purchase_id: number; locked: boolean; project_id: number
  project_code: string; project_name: string; lines: number; total: number
}
export interface Pegging {
  id: number; locked: boolean; editable: boolean
  rows: PeggingRow[]; fan: PeggingFanRow[]
}

// ── Вложения (волна 11): PDF/сканы к документам и изделиям ──
export interface AttachmentRow {
  id: number; filename: string; size: number; content_type: string
  description: string; uploaded_at: string; user: string; url: string
  // Состояние файла на диске против записи в БД (волна 19, Ф12a) — цвет глифа строки:
  // ok = совпадает, changed = размер/время не те, missing = файла нет.
  state: 'ok' | 'changed' | 'missing'
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
async function upload<T>(url: string, file: File, description?: string): Promise<T> {
  const fd = new FormData()
  fd.append('file', file)
  if (description) fd.append('description', description)
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

// Мульти-файл загрузка (несколько `files` + произвольные текстовые поля): для
// синхронизации с библиотекой (диф/применение). Content-Type НЕ ставим — браузер
// сам добавит boundary; CSRF-токен как в send()/upload().
async function uploadMulti<T>(url: string, files: File[], fields?: Record<string, string>): Promise<T> {
  const fd = new FormData()
  for (const f of files) fd.append('files', f)
  for (const [k, v] of Object.entries(fields || {})) fd.append(k, v)
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

  // ── Рождение сущности по клику (волна 19, Ф12e) ──
  // Двенадцать `create*` со своими телами схлопнулись в один вызов: форм создания
  // больше нет, «＋ Новый» рождает пустую сущность, а обязательные поля добирает
  // фолбэком бэкенд («Поставка 12») или требует к фиксации. Тело — только там, где
  // клик несёт смысл сверх «создай» (режим «Изделия» → `native`).
  // Ответ проекции нам не нужен целиком: открываем форму по `id`, она грузит себя.
  born: (path: string, body: object = {}) =>
    send<{ id: number }>('POST', `/api/${path}/`, body),

  projects: () => get<ProjectRow[]>('/api/projects/'),
  items: () => get<ItemRow[]>('/api/items/'),
  categories: () => get<Category[]>('/api/categories/'),
  project: (id: number) => get<ProjectDetail>(`/api/projects/${id}/`),
  updateProject: (id: number, b: Partial<{ code: string; description: string; budget: number | null; started: string | null }>) =>
    send<ProjectDetail>('PATCH', `/api/projects/${id}/`, b),
  deleteProject: (id: number) => send<void>('DELETE', `/api/projects/${id}/`),
  deficit: (id: number) => get<Deficit>(`/api/projects/${id}/deficit/`),
  addDemand: (projectId: number, b: { target_item_id: number; qty: number }) =>
    send<Deficit>('POST', `/api/projects/${projectId}/demands/`, b),
  updateDemand: (demandId: number, qty: number) =>
    send<Deficit>('PATCH', `/api/project-demands/${demandId}/`, { qty }),
  deleteDemand: (demandId: number) =>
    send<Deficit>('DELETE', `/api/project-demands/${demandId}/`),
  budget: (id: number) => get<Budget>(`/api/projects/${id}/budget/`),
  item: (id: number) => get<ItemDetail>(`/api/items/${id}/`),
  updateItem: (id: number, b: Partial<{ code: string; description: string;
    category_id: number; uom: string; temperature: string; native: boolean;
    estimated_cost: number | null }>) =>
    send<ItemDetail>('PATCH', `/api/items/${id}/`, b),
  deleteItem: (id: number) => send<void>('DELETE', `/api/items/${id}/`),
  // Фиксация изделия (волна 17). Волна 19 Ф1c: единый глагол `lock`/`unlock`
  // на всех сущностях — approve/unapprove и close/reopen из API ушли.
  lockItem: (id: number) => send<ItemDetail>('POST', `/api/items/${id}/lock/`),
  unlockItem: (id: number) => send<ItemDetail>('POST', `/api/items/${id}/unlock/`),
  addBomLine: (itemId: number, b: { component_id: number; qty: number; position?: string }) =>
    send<ItemDetail>('POST', `/api/items/${itemId}/bom/`, b),
  updateBomLine: (lineId: number, b: Partial<{ qty: number; position: string }>) =>
    send<ItemDetail>('PATCH', `/api/bom-lines/${lineId}/`, b),
  deleteBomLine: (lineId: number) =>
    send<ItemDetail>('DELETE', `/api/bom-lines/${lineId}/`),
  // Пересчёт оценочной стоимости роллапом по BOM (кнопка у производимого изделия).
  recalcCost: (id: number) =>
    send<ItemDetailWithRollup>('POST', `/api/items/${id}/recalc-cost/`),
  // Выгрузка изделия в xlsx (2026-07-30): 'bom' — один лист «Состав», 'all' — все
  // вкладки, кроме «Файлов». Не запрос, а ссылка: скачивание ведёт браузер.
  itemXlsxUrl: (id: number, scope: 'bom' | 'all') =>
    `/api/items/${id}/xlsx/?scope=${scope}`,

  // ── Синхронизация с библиотекой Altium (волна 15) ──
  // diff — загрузить CSV, получить диф без записи; apply — те же файлы + список
  // подтверждённых `code` (сервер пересчитывает диф заново).
  libraryDiff: (files: File[]) =>
    uploadMulti<LibraryDiff>('/api/library/diff/', files),
  libraryApply: (files: File[], confirmed: string[]) =>
    uploadMulti<LibraryApplySummary>('/api/library/apply/', files,
      { confirmed: JSON.stringify(confirmed) }),

  kittings: () => get<KittingRow[]>('/api/kittings/'),
  kitting: (id: number) => get<KittingForm>(`/api/kittings/${id}/`),
  updateKitting: (id: number, b: Partial<{ qty: number; date: string; user_id: number
      project_id: number; target_id: number; code: string | null; description: string }>) =>
    send<KittingForm>('PATCH', `/api/kittings/${id}/`, b),
  pierce: (id: number, b: { component_id: number; lot_id: number; qty: number }) =>
    send<KittingForm>('POST', `/api/kittings/${id}/lines/`, b),
  updateLine: (id: number, qty: number) =>
    send<KittingForm>('PATCH', `/api/kitting-lines/${id}/`, { qty }),
  deleteLine: (id: number) => send<KittingForm>('DELETE', `/api/kitting-lines/${id}/`),
  lockKitting: (id: number) => send<KittingForm>('POST', `/api/kittings/${id}/lock/`),
  unlockKitting: (id: number) => send<KittingForm>('POST', `/api/kittings/${id}/unlock/`),
  deleteKitting: (id: number) => send<void>('DELETE', `/api/kittings/${id}/`),

  // Ф3: список ВЕСЬ, без сужения по роли — прятать записи справочника нельзя.
  counterparties: () => get<CounterpartyRow[]>('/api/counterparties/'),
  createCounterparty: (b: { description: string; code?: string; inn?: string }) =>
    send<CounterpartyRow>('POST', '/api/counterparties/', b),
  // Волна 20 — режим «Контрагенты»: форма стороны документооборота.
  counterparty: (id: number) => get<CounterpartyForm>(`/api/counterparties/${id}/`),
  updateCounterparty: (id: number, b: Partial<{
    code: string | null; description: string; inn: string
  }>) => send<CounterpartyForm>('PATCH', `/api/counterparties/${id}/`, b),
  deleteCounterparty: (id: number) => send<void>('DELETE', `/api/counterparties/${id}/`),
  receipts: () => get<ReceiptRow[]>('/api/receipts/'),
  receipt: (id: number) => get<ReceiptForm>(`/api/receipts/${id}/`),
  updateReceipt: (id: number, b: Partial<{ number: string; date: string; contractor_id: number | null; user_id: number; project_id: number; code: string | null; description: string }>) =>
    send<ReceiptForm>('PATCH', `/api/receipts/${id}/`, b),
  addReceiptLot: (id: number, b: {
    item_id: number; qty: number; unit_cost?: number
    lot_name?: string; part_number?: string
  }) => send<ReceiptForm>('POST', `/api/receipts/${id}/lots/`, b),
  updateReceiptLot: (id: number, b: Partial<{
    qty: number; unit_cost: number; lot_name: string; part_number: string
  }>) => send<ReceiptForm>('PATCH', `/api/lots/${id}/`, b),
  deleteReceiptLot: (id: number) => send<ReceiptForm>('DELETE', `/api/lots/${id}/`),
  lockReceipt: (id: number) => send<ReceiptForm>('POST', `/api/receipts/${id}/lock/`),
  unlockReceipt: (id: number) => send<ReceiptForm>('POST', `/api/receipts/${id}/unlock/`),
  linkReceiptPurchase: (id: number, purchase_id: number | null) =>
    send<ReceiptForm>('POST', `/api/receipts/${id}/link/`, { purchase_id }),
  deleteReceipt: (id: number) => send<void>('DELETE', `/api/receipts/${id}/`),

  purchases: () => get<PurchaseRow[]>('/api/purchases/'),
  purchase: (id: number) => get<PurchaseForm>(`/api/purchases/${id}/`),
  updatePurchase: (id: number, b: Partial<{ date: string; code: string | null; description: string; user_id: number
      project_id: number; procurement_id: number | null; contractor_id: number | null }>) =>
    send<PurchaseForm>('PATCH', `/api/purchases/${id}/`, b),
  deletePurchase: (id: number) => send<void>('DELETE', `/api/purchases/${id}/`),
  addPurchaseLine: (id: number, b: { item_id: number; qty: number }) =>
    send<PurchaseForm>('POST', `/api/purchases/${id}/lines/`, b),
  updatePurchaseLine: (id: number, qty: number) =>
    send<PurchaseForm>('PATCH', `/api/purchase-lines/${id}/`, { qty }),
  deletePurchaseLine: (id: number) =>
    send<PurchaseForm>('DELETE', `/api/purchase-lines/${id}/`),
  lockPurchase: (id: number) => send<PurchaseForm>('POST', `/api/purchases/${id}/lock/`),
  unlockPurchase: (id: number) => send<PurchaseForm>('POST', `/api/purchases/${id}/unlock/`),
  // Ф6: заказ → УПД. Отдаёт форму РОЖДЁННОЙ поставки — в неё и переходим.
  receiptFromPurchase: (id: number) =>
    send<ReceiptForm>('POST', `/api/purchases/${id}/receipt/`),
  projectPurchases: (id: number) => get<ProjectPurchaseRow[]>(`/api/projects/${id}/purchases/`),
  addToPurchase: (id: number, b: { item_id: number; qty: number }) =>
    send<{ purchase_id: number }>('POST', `/api/projects/${id}/add-to-purchase/`, b),

  transfers: () => get<TransferRow[]>('/api/transfers/'),
  transfer: (id: number) => get<TransferForm>(`/api/transfers/${id}/`),
  updateTransfer: (id: number, b: Partial<{ number: string; date: string; contractor_id: number | null; user_id: number; project_id: number; code: string | null; description: string }>) =>
    send<TransferForm>('PATCH', `/api/transfers/${id}/`, b),
  addTransferLine: (id: number, b: { lot_id: number; qty: number; display_name?: string }) =>
    send<TransferForm>('POST', `/api/transfers/${id}/lines/`, b),
  updateTransferLine: (id: number, b: Partial<{ qty: number; display_name: string }>) =>
    send<TransferForm>('PATCH', `/api/transfer-lines/${id}/`, b),
  deleteTransferLine: (id: number) =>
    send<TransferForm>('DELETE', `/api/transfer-lines/${id}/`),
  lockTransfer: (id: number) => send<TransferForm>('POST', `/api/transfers/${id}/lock/`),
  unlockTransfer: (id: number) => send<TransferForm>('POST', `/api/transfers/${id}/unlock/`),
  deleteTransfer: (id: number) => send<void>('DELETE', `/api/transfers/${id}/`),
  projectAvailableLots: (id: number) =>
    get<AvailableLot[]>(`/api/projects/${id}/available-lots/`),

  writeoffs: () => get<WriteoffRow[]>('/api/writeoffs/'),
  writeoff: (id: number) => get<WriteoffForm>(`/api/writeoffs/${id}/`),
  updateWriteoff: (id: number, b: Partial<{ number: string; date: string; reason: string; user_id: number; project_id: number; code: string | null; description: string }>) =>
    send<WriteoffForm>('PATCH', `/api/writeoffs/${id}/`, b),
  addWriteoffLine: (id: number, b: { lot_id: number; qty: number }) =>
    send<WriteoffForm>('POST', `/api/writeoffs/${id}/lines/`, b),
  updateWriteoffLine: (id: number, qty: number) =>
    send<WriteoffForm>('PATCH', `/api/writeoff-lines/${id}/`, { qty }),
  deleteWriteoffLine: (id: number) =>
    send<WriteoffForm>('DELETE', `/api/writeoff-lines/${id}/`),
  lockWriteoff: (id: number) => send<WriteoffForm>('POST', `/api/writeoffs/${id}/lock/`),
  unlockWriteoff: (id: number) => send<WriteoffForm>('POST', `/api/writeoffs/${id}/unlock/`),
  deleteWriteoff: (id: number) => send<void>('DELETE', `/api/writeoffs/${id}/`),

  requisitions: () => get<RequisitionRow[]>('/api/requisitions/'),
  requisition: (id: number) => get<RequisitionForm>(`/api/requisitions/${id}/`),
  updateRequisition: (id: number, b: Partial<{ number: string; date: string; user_id: number; project_id: number; code: string | null; description: string }>) =>
    send<RequisitionForm>('PATCH', `/api/requisitions/${id}/`, b),
  addRequisitionLine: (id: number, b: { source_lot_id: number; qty: number }) =>
    send<RequisitionForm>('POST', `/api/requisitions/${id}/lines/`, b),
  updateRequisitionLine: (id: number, qty: number) =>
    send<RequisitionForm>('PATCH', `/api/requisition-lines/${id}/`, { qty }),
  deleteRequisitionLine: (id: number) =>
    send<RequisitionForm>('DELETE', `/api/requisition-lines/${id}/`),
  lockRequisition: (id: number) => send<RequisitionForm>('POST', `/api/requisitions/${id}/lock/`),
  unlockRequisition: (id: number) => send<RequisitionForm>('POST', `/api/requisitions/${id}/unlock/`),
  deleteRequisition: (id: number) => send<void>('DELETE', `/api/requisitions/${id}/`),
  allAvailableLots: () => get<AllAvailableLot[]>('/api/available-lots/'),

  inventories: () => get<InventoryRow[]>('/api/inventories/'),
  inventory: (id: number) => get<InventoryForm>(`/api/inventories/${id}/`),
  updateInventory: (id: number, b: Partial<{ number: string; date: string; code: string | null; description: string; user_id: number; project_id: number }>) =>
    send<InventoryForm>('PATCH', `/api/inventories/${id}/`, b),
  addInventoryLot: (id: number, b: {
    item_id?: number; predecessor_id?: number; qty: number
    unit_cost?: number; lot_name?: string; part_number?: string
  }) => send<InventoryForm>('POST', `/api/inventories/${id}/lots/`, b),
  updateInventoryLot: (id: number, b: Partial<{
    qty: number; unit_cost: number; lot_name: string; part_number: string
  }>) => send<InventoryForm>('PATCH', `/api/inventory-lots/${id}/`, b),
  deleteInventoryLot: (id: number) =>
    send<InventoryForm>('DELETE', `/api/inventory-lots/${id}/`),
  lockInventory: (id: number) => send<InventoryForm>('POST', `/api/inventories/${id}/lock/`),
  unlockInventory: (id: number) => send<InventoryForm>('POST', `/api/inventories/${id}/unlock/`),
  deleteInventory: (id: number) => send<void>('DELETE', `/api/inventories/${id}/`),
  writtenOffLots: () => get<WrittenOffLot[]>('/api/written-off-lots/'),

  // ── Места хранения / Location (волна 13 Ф3 пикер, Ф4 сущность «Склады») ──
  locations: () => get<LocationRow[]>('/api/locations/'),
  location: (id: number) => get<LocationForm>(`/api/locations/${id}/`),
  updateLocation: (id: number, b: Partial<{ code: string; description: string; kind: string }>) =>
    send<LocationForm>('PATCH', `/api/locations/${id}/`, b),
  deleteLocation: (id: number) => send<void>('DELETE', `/api/locations/${id}/`),

  // ── Перемещение / Relocation (волна 13 Ф3) ──
  relocations: () => get<RelocationRow[]>('/api/relocations/'),
  relocation: (id: number) => get<RelocationForm>(`/api/relocations/${id}/`),
  updateRelocation: (id: number, b: Partial<{ number: string; date: string; user_id: number; project_id: number; code: string | null; description: string }>) =>
    send<RelocationForm>('PATCH', `/api/relocations/${id}/`, b),
  addRelocationLine: (id: number, b: {
    lot_id: number; qty: number; from_location_id: number; to_location_id: number
  }) => send<RelocationForm>('POST', `/api/relocations/${id}/lines/`, b),
  updateRelocationLine: (id: number, lotId: number, b: Partial<{
    qty: number; from_location_id: number; to_location_id: number
  }>) => send<RelocationForm>('PATCH', `/api/relocations/${id}/lines/${lotId}/`, b),
  deleteRelocationLine: (id: number, lotId: number) =>
    send<RelocationForm>('DELETE', `/api/relocations/${id}/lines/${lotId}/`),
  lockRelocation: (id: number) => send<RelocationForm>('POST', `/api/relocations/${id}/lock/`),
  unlockRelocation: (id: number) => send<RelocationForm>('POST', `/api/relocations/${id}/unlock/`),
  deleteRelocation: (id: number) => send<void>('DELETE', `/api/relocations/${id}/`),
  relocationSourceLots: (id: number) =>
    get<RelocationSourceLot[]>(`/api/relocations/${id}/source-lots/`),

  // ── Планирование закупок (волна 7; охват — волна 19, Ф13) ──
  // `/api/command-deficit/` больше нет: свод — витрина конкретной закупки, мост
  // кладёт позицию в неё же (топ-ап до наводки).
  procurementDeficit: (id: number) => get<ScopeDeficit>(`/api/procurements/${id}/deficit/`),
  takeToProcurement: (id: number, b: { item_id: number; qty: number }) =>
    send<ProcurementForm>('POST', `/api/procurements/${id}/take/`, b),
  procurements: () => get<ProcurementRow[]>('/api/procurements/'),
  procurement: (id: number) => get<ProcurementForm>(`/api/procurements/${id}/`),
  deleteProcurement: (id: number) => send<void>('DELETE', `/api/procurements/${id}/`),
  updateProcurement: (id: number, b: Partial<{ date: string; code: string | null; description: string; user_id: number; contractor_id: number | null; project_ids: number[] }>) =>
    send<ProcurementForm>('PATCH', `/api/procurements/${id}/`, b),
  addProcurementLine: (id: number, b: { item_id: number; qty: number }) =>
    send<ProcurementForm>('POST', `/api/procurements/${id}/lines/`, b),
  updateProcurementLine: (id: number, qty: number) =>
    send<ProcurementForm>('PATCH', `/api/procurement-lines/${id}/`, { qty }),
  deleteProcurementLine: (id: number) =>
    send<ProcurementForm>('DELETE', `/api/procurement-lines/${id}/`),
  lockProcurement: (id: number) => send<ProcurementForm>('POST', `/api/procurements/${id}/lock/`),
  unlockProcurement: (id: number) => send<ProcurementForm>('POST', `/api/procurements/${id}/unlock/`),
  xlsxUrl: (id: number) => `/api/procurements/${id}/xlsx/`,
  // pegging (волна 8)
  pegging: (id: number) => get<Pegging>(`/api/procurements/${id}/pegging/`),
  // `purchase_id`: число — в этот заказ, 'new' — в новый, нет ключа — фолбэк (Р2)
  peg: (id: number, b: { item_id: number; project_id: number; qty: number; purchase_id?: number | 'new' }) =>
    send<Pegging>('POST', `/api/procurements/${id}/peg/`, b),
  unpeg: (id: number, b: { item_id: number; project_id: number }) =>
    send<Pegging>('POST', `/api/procurements/${id}/unpeg/`, b),
  autopeg: (id: number) => send<Pegging>('POST', `/api/procurements/${id}/autopeg/`),

  // ── Вложения (волна 11) ──
  attachments: (ownerType: string, ownerId: number) =>
    get<AttachmentRow[]>(`/api/attachments/${ownerType}/${ownerId}/`),
  uploadAttachment: (ownerType: string, ownerId: number, file: File, description?: string) =>
    upload<AttachmentRow>(`/api/attachments/${ownerType}/${ownerId}/`, file, description),
  updateAttachment: (id: number, description: string) =>
    send<AttachmentRow>('PATCH', `/api/attachments/${id}/`, { description }),
  deleteAttachment: (id: number) => send<void>('DELETE', `/api/attachments/${id}/`),

  closure: (id: number) => get<ProjectClosure>(`/api/projects/${id}/closure/`),
  writeoffLot: (id: number, b: { lot_id: number; qty: number }) =>
    send<ProjectClosure>('POST', `/api/projects/${id}/writeoff-lot/`, b),
  stockLot: (id: number, b: { lot_id: number; qty: number }) =>
    send<ProjectClosure>('POST', `/api/projects/${id}/stock-lot/`, b),
  lockProject: (id: number) => send<ProjectClosure>('POST', `/api/projects/${id}/lock/`),
  unlockProject: (id: number) => send<ProjectClosure>('POST', `/api/projects/${id}/unlock/`),
}
