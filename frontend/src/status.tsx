// Сквозной словарь статусов (единый везде): значок + цвет текста, не заливка.
import type { Status } from './api'

// Единый глиф оси фиксации (Ф1b, волна 19): строгая проекция `bool locked` на codicon
// `lock` (зафиксировано) / `unlock` (расфиксировано). Никаких эмодзи и ✓/○ — только
// замок. Цвет — отдельная ось (`tone`): 'fix' красит по фиксации (зелёный заперт /
// оранжевый открыт), 'ok'/'wip'/'order' — явный тон (покрытие/worst-of по сущности),
// 'none' — нейтральный. Раскатан на все списки: изделия, компоненты, ордера, закупки,
// заказы, проекты. Две оси не путать: глиф = замок, цвет = «как идут дела».
type Tone = 'fix' | 'ok' | 'wip' | 'order' | 'none'
export function StatusGlyph({ locked, tone = 'fix', title }: {
  locked: boolean; tone?: Tone; title?: string
}) {
  const sg = tone === 'fix' ? (locked ? 'sg-ok' : 'sg-wip') : `sg-${tone}`
  return <span className={`ci sg ci-${locked ? 'lock' : 'unlock'} ${sg}`}
    title={title ?? (locked ? 'зафиксировано' : 'расфиксировано')} />
}

// Глиф расхождения контрагентов (волна 19, Ф17). Контрагент есть у всех трёх уровней
// закупочного контура и наследуется копией при рождении; расхождение — законная
// ситуация («одна закупка может пойти от разных поставщиков»), поэтому это
// предупреждение, а НЕ гейт: форма кричит и подсказывает путь исправления, но не
// останавливает. Флаг считает движок ([[engine-view-seam]]) — здесь только знак.
export function MismatchGlyph({ title }: { title: string }) {
  return <span className="ci sg sg-wip mism ci-warning" title={title} />
}

// Раскрыватель аккордеона — ЕДИНЫЙ везде (волна 19, полировка 2026-07-26): codicon
// `chevron-right` (свёрнуто) / `chevron-down` (раскрыто) вместо текстовых ▸/▾. По §7a
// раскрыватель — первый символ строки, поэтому форма у него одна на весь продукт.
// Размер — компаундом `.ci.chv` (как у `.sg`): базовые 18px разорвали бы высоту строк.
export function Chevron({ open }: { open: boolean }) {
  return <span className={`ci chv ci-chevron-${open ? 'down' : 'right'}`} />
}

// Глиф оси СИНКА (Ф3a, волна 19) — для КОМПОНЕНТОВ (`native=false`). Ровно один глиф
// по режиму: у компонентов показываем синк (у изделий — замок, `StatusGlyph`).
// `synced=true` (из библиотеки) → codicon `sync` зелёный; `false` (ручной) →
// `sync-ignored` оранжевый («внимание: не из библиотеки», важно при сборке закупки).
export function SyncGlyph({ synced, title }: { synced: boolean; title?: string }) {
  return <span
    className={`ci sg ci-${synced ? 'sync' : 'sync-ignored'} ${synced ? 'sg-ok' : 'sg-wip'}`}
    title={title ?? (synced ? 'из библиотеки' : 'заведено вручную')} />
}

// Глиф строки Item по режиму (Ф3a): РОВНО ОДИН. `native` → замок (`StatusGlyph`, ось
// фиксации); `not native` → sync (`SyncGlyph`). Раскатан во ВСЕ списки, где встречается
// изделие/компонент: справочник, BOM, дерево дефицита, потребность, закупка. Так глиф
// «перетекает» с сущностью одинаково везде.
export function ItemGlyph({ native, synced, locked, tone, title }: {
  native: boolean; synced: boolean; locked: boolean
  tone?: 'fix' | 'ok' | 'wip' | 'order' | 'none'; title?: string
}) {
  return native
    ? <StatusGlyph locked={locked} tone={tone} title={title} />
    : <SyncGlyph synced={synced} title={title} />
}

// Глиф вложения (волна 19, Ф12a). ФОРМА = вид файла (по расширению: pdf, картинка,
// код, архив, прочее-бинарь), ЦВЕТ = живо ли оно на диске: зелёный — файл на месте и
// совпадает с записью, оранжевый — на месте, но размер/время разошлись (перезалили
// мимо приложения), красный — записи есть, файла нет. Две оси не путаем — тот же
// принцип, что у ItemGlyph (глиф ⟂ цвет, §7a).
const FILE_GLYPH: [RegExp, string][] = [
  [/\.pdf$/i, 'file-pdf'],
  [/\.(png|jpe?g|gif|bmp|webp|svg|tiff?)$/i, 'file-media'],
  [/\.(zip|rar|7z|tar|gz)$/i, 'file-zip'],
  [/\.(json|xml|ya?ml|csv|py|ts|tsx|js|sql|sh|md|txt)$/i, 'file-code'],
  [/\.(exe|dll|bin|hex|elf|step|stp|stl|dwg|sch|pcb)$/i, 'file-binary'],
]
const FILE_TONE: Record<'ok' | 'changed' | 'missing', string> = {
  ok: 'sg-ok', changed: 'sg-wip', missing: 'sg-order',
}
const FILE_TITLE: Record<'ok' | 'changed' | 'missing', string> = {
  ok: 'файл на месте',
  changed: 'файл на месте, но размер или время изменились — перезаписан мимо Plume',
  missing: 'файла нет на сервере (запись осталась)',
}

export function FileGlyph({ filename, state }: {
  filename: string; state: 'ok' | 'changed' | 'missing'
}) {
  const icon = FILE_GLYPH.find(([re]) => re.test(filename))?.[1] ?? 'file'
  return <span className={`ci sg ci-${icon} ${FILE_TONE[state]}`} title={FILE_TITLE[state]} />
}

// Глиф партии (волна 19, Ф12c). Своей оси состояния у лота нет — решение Ивана
// 2026-07-26: ФОРМА = откуда партия родилась (origin-ордер, `Lot.origin_kind`), ЦВЕТ =
// живость остатка (зелёный — есть, приглушённый — исчерпана, красный — минус, то есть
// недостача «подбей лоты»). Тот же приём, что у `FileGlyph`: форма отвечает «что это»,
// цвет — «как дела» (§7a, ось ⟂ ось). Лот без origin (данные до волны 13) — `layers`.
const LOT_GLYPH: Record<string, string> = {
  receipt: 'inbox',            // приехало от поставщика по УПД
  kitting: 'tools',            // изготовлено нами (комплектация родила прибор)
  inventory: 'checklist',      // найдено сверкой
  requisition: 'git-branch',   // отпочковано требованием от другой партии
}
const LOT_ORIGIN: Record<string, string> = {
  receipt: 'из поставки', kitting: 'изготовлено',
  inventory: 'найдено инвентаризацией', requisition: 'отпочковано требованием',
}
// `draft` — партия ещё не на складе: её родил РАСФИКСИРОВАННЫЙ ордер (волна 19, Ф15 —
// замок гейтит склад). Живости у неё нет вовсе, поэтому цвет не «исчерпана» (это была
// бы ложь про израсходованную партию), а нейтральный «ждёт фиксации».
export function LotGlyph({ origin, liveQty, draft }: {
  origin: string | null; liveQty: number; draft?: boolean
}) {
  const icon = LOT_GLYPH[origin ?? ''] ?? 'layers'
  const tone = draft ? 'sg-none' : liveQty > 0 ? 'sg-ok' : liveQty < 0 ? 'sg-order' : 'sg-none'
  const life = draft ? 'ещё не на складе — зафиксируйте документ'
    : liveQty > 0 ? 'есть остаток' : liveQty < 0 ? 'недостача — подбей лоты' : 'исчерпана'
  return <span className={`ci sg ci-${icon} ${tone}`}
    title={`${LOT_ORIGIN[origin ?? ''] ?? 'партия'} · ${life}`} />
}

export const GLYPH: Record<Status, string> = {
  to_order: '▲',     // красный — дефицит, нужна работа
  on_order: '●',     // оранжевый — заказано/делается, ждём
  available: '✓',    // зелёный — покрыто/готово
}

// Status → тон StatusGlyph (Ф1b): ось покрытия/worst-of в цвет замка (списки Заказов
// и Проектов). Красный (to_order) / оранжевый (on_order) / зелёный (available).
export function statusTone(s: Status): 'ok' | 'wip' | 'order' {
  return s === 'available' ? 'ok' : s === 'on_order' ? 'wip' : 'order'
}

export const LABEL: Record<Status, string> = {
  to_order: 'заказать',
  on_order: 'заказано/делается',
  available: 'есть',
}

export function Glyph({ status }: { status: Status }) {
  return <span className={`glyph g-${status}`}>{GLYPH[status]}</span>
}

// «4 ✓ · 3 ● · 3 ▲» — тройной разбор строки (только непустые сегменты).
export function Segment({ status, value }: { status: Status; value: number }) {
  if (!value) return null
  return (
    <span className="seg">
      <span className={`glyph g-${status}`}>{GLYPH[status]}</span>
      {num(value)}
    </span>
  )
}

// Ось разбора на codicon `layers` (Ф1b, пилот в проекте): глиф = «слои склада»
// (перекликается с режимом «Склады»), а состояние несёт ЦВЕТ, не форма — треугольники
// и кружки больше не шумят. `layers` красный (не заказано) → `layers-dot` оранжевый
// (заказано, ждём) → `layers-active` зелёный (на складе). Пока только форма проекта.
const LAYER_GLYPH: Record<Status, string> = {
  to_order: 'layers', on_order: 'layers-dot', available: 'layers-active',
}
const STATUS_TONE: Record<Status, string> = {
  to_order: 'sg-order', on_order: 'sg-wip', available: 'sg-ok',
}
export function LayerSeg({ status, value }: { status: Status; value: number }) {
  if (!value) return null
  return (
    <span className="seg">
      <span className={`ci sg ci-${LAYER_GLYPH[status]} ${STATUS_TONE[status]}`} />
      {num(value)}
    </span>
  )
}

export function num(x: number): string {
  return Number.isInteger(x) ? String(x) : String(x)
}

// Деньги: разряды пробелом + копейки + ₽ («1 200 300,00 ₽»). Единый формат везде —
// бюджет проекта, суммы документов, оценка изделия (принято 2026-07-26).
export function money(x: number): string {
  return x.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₽'
}

// Итог списка в натуре: количества сворачиваются ПО ЕДИНИЦАМ (§13.6) — штуки с метрами
// не складываем. Порядок групп — как единицы встретились в списке, чтобы итог читался в
// том же порядке, что строки; нулевые группы не показываем. Общий для всех форм
// (волна 19, Ф12c: жил в `ReceiptView`, понадобился каждому списку с количеством).
export function sumByUom(rows: { uom: string; qty: number }[]): [string, number][] {
  const sums = new Map<string, number>()
  for (const r of rows) sums.set(r.uom, (sums.get(r.uom) ?? 0) + r.qty)
  return [...sums].filter(([, qty]) => qty !== 0)
}

// Русское склонение при числе: `count(2, 'вхождение', 'вхождения', 'вхождений')`
// → «2 вхождения». Число ВПЕРЕДИ подписи — так строка меты читается фразой (§13.6).
export function count(n: number, one: string, few: string, many: string): string {
  const mod100 = n % 100
  const mod10 = n % 10
  const word = mod100 >= 11 && mod100 <= 14 ? many
    : mod10 === 1 ? one
    : mod10 >= 2 && mod10 <= 4 ? few
    : many
  return `${n} ${word}`
}
