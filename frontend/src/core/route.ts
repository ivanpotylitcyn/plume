// Адрес страницы ↔ выбранная форма (2026-08-07). Раньше приложение жило на одном
// адресе: открыть заказ можно было только руками, и «посмотри вот этот заказ» в чате
// не работало. Теперь каждая форма имеет свой путь, и ссылку можно отдать коллеге.
//
// Живёт в `core/` — это СМЫСЛ навигации (какая сущность открыта), а не её вид
// ([[engine-view-seam]]): тема рисует списки и формы как хочет, но «мы сейчас на заказе
// 12» — факт продукта, общий для любой темы.
//
// Формат — `вид/id` (решение Ивана 2026-08-07): `/purchase/12`, `/project/1`. По id, а
// не по коду: код правят (и он бывает с кириллицей и слэшем — «Нева-1/03»), а ссылка,
// умирающая от переименования, хуже нечитаемой. Сегмент вида — это сам `kind` из `Sel`,
// без второго словаря: он уже канонический язык продукта.
//
// Сервер к этому готов давно: catch-all в `config/urls.py` отдаёт `index.html` на любой
// путь, поэтому прямой заход и F5 работают без отдельной настройки.

// Режим сайдбара — какой СПИСОК открыт. Волна 13 Ф1b свернула 6 складских документов в
// один режим «Ордера», волна 17 разделила справочник по оси `native`, волна 20 добавила
// контрагентов. Переехал сюда из `App` вместе с `Sel`: типы навигации — не вьюха.
export type Mode = 'projects' | 'products' | 'items' | 'orders' | 'locations'
  | 'procurements' | 'purchases' | 'counterparties'

export const MODES: Mode[] = ['projects', 'products', 'items', 'orders', 'locations',
  'procurements', 'purchases', 'counterparties']

// Выбранная форма. Волна 19, Ф12e: вариантов `new-*` нет — «＋ Новый» рождает сущность
// и уводит в её обычную форму. `library-sync` и `account` — формы БЕЗ режима: они не
// список, а экран («я сам», «синхронизация»), и сайдбар при них держит прежний список.
export type Sel =
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
  | { kind: 'account' }
  | null

// В каком режиме живёт форма этого вида — тот же ответ, что дают `open*` в `App`
// (заказ в «Заказах», любой складской документ в «Ордерах»). Нужен при заходе ПО
// ССЫЛКЕ: адрес называет форму, а список под ней приложение выбирает само.
const KIND_MODE: Record<string, Mode> = {
  project: 'projects', item: 'items',
  kitting: 'orders', receipt: 'orders', transfer: 'orders', writeoff: 'orders',
  requisition: 'orders', inventory: 'orders', relocation: 'orders',
  purchase: 'purchases', procurement: 'procurements',
  location: 'locations', counterparty: 'counterparties',
}

// Формы без id — свой сегмент и никакого режима.
const SOLO = new Set(['library-sync', 'account'])

export interface Route { mode: Mode; sel: Sel }

// Форма → адрес. Пустой выбор = адрес СПИСКА: сайдбар — тоже состояние, которым делятся
// («смотри в Заказах»), и возвращаться по такой ссылке нужно туда же.
export function pathOf({ mode, sel }: Route): string {
  if (!sel) return `/${mode}`
  if (SOLO.has(sel.kind)) return `/${sel.kind}`
  return `/${sel.kind}/${'id' in sel ? sel.id : ''}`
}

// Адрес → форма. Неизвестный путь возвращает `null` — вызывающий остаётся на дефолте,
// а не падает: чужая ссылка с опечаткой не должна ронять приложение.
export function parsePath(path: string, fallbackMode: Mode): Route | null {
  const [head, tail] = path.replace(/^\/+|\/+$/g, '').split('/')
  if (!head) return { mode: fallbackMode, sel: null }
  if (SOLO.has(head)) return { mode: fallbackMode, sel: { kind: head } as Sel }
  if (!tail) {
    return (MODES as string[]).includes(head)
      ? { mode: head as Mode, sel: null }
      : null
  }
  const id = Number(tail)
  const mode = KIND_MODE[head]
  if (!mode || !Number.isInteger(id) || id <= 0) return null
  return { mode, sel: { kind: head, id } as Sel }
}
