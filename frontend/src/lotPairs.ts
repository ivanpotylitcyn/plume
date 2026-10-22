// Пикеры строк расхода — пары «лот @ локация» (волна 27, решение Ивана «выбор лота =
// выбор места»). Строка пикера — партия В КОНКРЕТНОМ МЕСТЕ: выбрав её, человек выбрал и
// откуда списать. Ключ и подпись пары — одни на все пикеры (комплектация, передача,
// списание, перевод), поэтому живут модулем, а не копиями в формах.
import { num } from './status'

interface Pair {
  lot_id: number; location_id: number; location_code: string; location_central: boolean
  live_qty: number; lot_code: string; lot_description: string
}

export const pairKey = (p: Pair) => `${p.lot_id}@${p.location_id}`

// «#12 RC0603 · LAB · 30» — партия, её PN (или наименование), место и остаток там.
// Центральный помечен: брать прямо оттуда можно, но это значит «без Требования».
export function pairLabel(p: Pair, head?: string): string {
  const name = p.lot_code || p.lot_description
  return `${head ?? `#${p.lot_id}`}${name ? ` ${name}` : ''} · `
    + `${p.location_code}${p.location_central ? ' (центр.)' : ''} · ${num(p.live_qty)}`
}
