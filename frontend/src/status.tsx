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
// (заказано, ждём) → `layers-active` зелёный (на складе). Пока только DeficitView.
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

// Деньги: разряды пробелом + ₽ (округляем до рубля — копейки в бюджете не важны).
export function money(x: number): string {
  return Math.round(x).toLocaleString('ru-RU') + ' ₽'
}
