// Сквозной словарь статусов (единый везде): значок + цвет текста, не заливка.
import type { Status } from './api'

// Замок изделия (волна 17; bool с волны 19, Ф1c): зафиксировано — зелёная галочка
// (источник правды/библиотека), расфиксировано — оранжевый кружок (редактируемо).
// Ставится слева от строки Item везде (списки режимов, BOM, потребность проекта).
// Ф1b раскатает этот же глиф на закупки/заказы/ордера/проекты — ось уже общая.
export function ItemStatusGlyph({ locked }: { locked: boolean }) {
  return (
    <span className={`glyph ${locked ? 'g-available' : 'g-draft'}`}
          title={locked ? 'зафиксировано' : 'расфиксировано (редактируется)'}>
      {locked ? '✓' : '○'}
    </span>
  )
}

export const GLYPH: Record<Status, string> = {
  to_order: '▲',     // красный — дефицит, нужна работа
  on_order: '●',     // оранжевый — заказано/делается, ждём
  available: '✓',    // зелёный — покрыто/готово
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

export function num(x: number): string {
  return Number.isInteger(x) ? String(x) : String(x)
}

// Деньги: разряды пробелом + ₽ (округляем до рубля — копейки в бюджете не важны).
export function money(x: number): string {
  return Math.round(x).toLocaleString('ru-RU') + ' ₽'
}
