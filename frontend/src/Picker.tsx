// Единый пикер справочника (волна 19, Ф2). Одно поведение выбора во всех формах:
// вводишь код или описание → список кандидатов сокращается (≤20) → ↑/↓ и Enter
// выбирают, Esc закрывает. Пришёл на смену зоопарку `<select>` со всем справочником.
//
// Логика — в `core/useTypeahead` (шов Ф7), здесь только знак темы: поле `.lot-sel`,
// меню `.typeahead-menu`, строка кандидата по правилу вёрстки `[глиф][code] описание`
// (UI_GUIDE §7a). `renderRow` оставлен подменяемым — под будущий пикер лотов
// (у лота свой словарь строки: изделие + партия + остаток).
//
// Меню и плашка «не найдено» живут в `AnchoredMenu` — портал в `body` с фиксированной
// привязкой к полю (2026-07-28): внутри формы их резали панель табов и прокрутка
// страницы, а у нижнего края окна меню теперь раскрывается вверх.
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { useTypeahead } from './core/useTypeahead'
import { AnchoredMenu } from './AnchoredMenu'
import type { ItemRow, CounterpartyRow, ProjectPurchaseRow } from './api'
import { ItemGlyph, StatusGlyph } from './status'

export function Picker<T>({ options, value, onPick, keyOf, textOf, searchOf, renderRow,
  placeholder, disabled, width, onEnter, onClear, notFound }: {
  options: T[]
  value: number | ''
  onPick: (id: number) => void
  keyOf: (o: T) => number
  textOf: (o: T) => string
  searchOf?: (o: T) => string
  renderRow: (o: T) => ReactNode
  placeholder?: string
  disabled?: boolean
  width?: number
  onEnter?: () => void
  onClear?: () => void          // задан → у выбранного появляется «×» (поле обнуляемо)
  notFound?: string
}) {
  const t = useTypeahead({ options, value, onPick, keyOf, textOf, searchOf, onEnter })
  const menu = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLInputElement>(null)     // якорь меню (портал считает от него)

  // Подсветка = смысл (ядро), прокрутка за ней = знак (тема). Двигаем только свой
  // список: `scrollIntoView` уехал бы вверх по всем прокручиваемым предкам и дёрнул
  // страницу. Ходим по границам — подсвеченный подтягивается ровно к краю окна.
  useEffect(() => {
    const box = menu.current
    const row = box?.children[t.active] as HTMLElement | undefined
    if (!box || !row) return
    if (row.offsetTop < box.scrollTop) box.scrollTop = row.offsetTop
    else if (row.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight)
      box.scrollTop = row.offsetTop + row.offsetHeight - box.clientHeight
  }, [t.active, t.open])

  return (
    <span className="picker">
      <input ref={field} className="lot-sel" style={width ? { width } : undefined} value={t.text}
        disabled={disabled} placeholder={placeholder ?? 'код или описание…'}
        onChange={e => t.type(e.target.value)} onKeyDown={t.onKeyDown} onBlur={t.close} />
      {onClear && value !== '' && !disabled &&
        <button className="x" title="Очистить" onClick={onClear}>×</button>}
      {t.open &&
        <AnchoredMenu anchor={field} boxRef={menu} className="typeahead-menu">
          {t.matches.map((o, i) => (
            // onMouseDown гасим: иначе blur поля закрыл бы меню до клика.
            <div key={keyOf(o)} className={`typeahead-item${i === t.active ? ' active' : ''}`}
              onMouseDown={e => e.preventDefault()} onClick={() => t.pick(o)}>
              {renderRow(o)}
            </div>
          ))}
        </AnchoredMenu>}
      {t.empty &&
        <AnchoredMenu anchor={field} className="picker-empty">
          {notFound ?? 'ничего не найдено'}
        </AnchoredMenu>}
    </span>
  )
}

// ── Пикер изделия: шесть мест выбора изделия говорят одной строкой ──
// Отбор кандидатов (изделия/компоненты, уже занятые, само изделие) — забота места:
// сюда приходит готовый `options`.
const itemText = (i: ItemRow) => `${i.code} — ${i.description}`

export function ItemPicker({ items, value, onPick, disabled, placeholder, width, onEnter,
  onClear, notFound }: {
  items: ItemRow[]
  value: number | ''
  onPick: (id: number) => void
  disabled?: boolean; placeholder?: string; width?: number
  onEnter?: () => void; onClear?: () => void; notFound?: string
}) {
  return <Picker options={items} value={value} onPick={onPick} keyOf={i => i.id}
    textOf={itemText} searchOf={itemText} disabled={disabled} placeholder={placeholder}
    width={width} onEnter={onEnter} onClear={onClear}
    notFound={notFound ?? 'ничего не найдено — изделие должно быть в справочнике.'}
    renderRow={i => <>
      <ItemGlyph native={i.native} synced={i.synced} locked={i.locked} />
      <span className="code">{i.code}</span>
      <span className="dim">{i.description}</span>
    </>} />
}

// ── Пикер контрагента ──
// Глифа в строке нет намеренно: у контрагента пока нет оси состояния (ни замка, ни
// синка), а глиф без смысла — декорация (UI_PRINCIPLES). Заведётся в волне 20.
const cpText = (c: CounterpartyRow) => c.code ? `${c.code} — ${c.description}` : c.description

export function CounterpartyPicker({ counterparties, value, onPick, disabled, placeholder,
  width, onClear }: {
  counterparties: CounterpartyRow[]
  value: number | ''
  onPick: (id: number) => void
  disabled?: boolean; placeholder?: string; width?: number; onClear?: () => void
}) {
  return <Picker options={counterparties} value={value} onPick={onPick} keyOf={c => c.id}
    textOf={cpText} searchOf={c => `${c.code ?? ''} ${c.description} ${c.inn}`}
    disabled={disabled} placeholder={placeholder} width={width} onClear={onClear}
    notFound="ничего не найдено — контрагента можно завести рядом."
    renderRow={c => <>
      {c.code && <span className="code">{c.code}</span>}
      <span>{c.description}</span>
      {c.inn && <span className="dim">ИНН {c.inn}</span>}
    </>} />
}

// ── Пикер заказа (УПД → какой заказ закрывает) ──
// Тип узкий (`ProjectPurchaseRow`): у заказа-кандидата берём только идентичность,
// замок и число строк — этого хватает и списку проекта, и общему списку заказов.
const purchaseText = (p: ProjectPurchaseRow) => p.code ?? `Заказ #${p.id}`

export function PurchasePicker({ purchases, value, onPick, disabled, onClear }: {
  purchases: ProjectPurchaseRow[]
  value: number | ''
  onPick: (id: number) => void
  disabled?: boolean; onClear?: () => void
}) {
  return <Picker options={purchases} value={value} onPick={onPick} keyOf={p => p.id}
    textOf={purchaseText}
    searchOf={p => `${p.code ?? ''} ${p.description} #${p.id}`}
    disabled={disabled} onClear={onClear} placeholder="— не связан —"
    notFound="ничего не найдено — заказ должен существовать."
    renderRow={p => <>
      <StatusGlyph locked={p.locked} />
      <span className="code">{purchaseText(p)}</span>
      <span className="dim">{p.description}</span>
      <span className="dim">{p.lines} стр.</span>
    </>} />
}
