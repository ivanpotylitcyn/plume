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
import type { ItemRow, CounterpartyRow, ProjectPurchaseRow, ProjectRow } from './api'
import { ItemGlyph, StatusGlyph } from './status'

export function Picker<T>({ options, value, onPick, keyOf, textOf, searchOf, renderRow,
  placeholder, disabled, width, onEnter, onClear, notFound, onCreate, multi, summary,
  eager }: {
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
  // Ф12e: «нет в справочнике» перестало быть тупиком. Форм создания больше нет, и
  // заводить справочную мелочь (контрагента) надо оттуда, где о ней вспомнили —
  // из самого поля. Задан → плашка «не найдено» становится кнопкой.
  onCreate?: (text: string) => void
  // Ф13: множественный выбор — `onPick` переключает отметку, меню живёт до Esc/blur.
  // Галочку рисует `renderRow` (это знак темы), ядро о ней не знает.
  multi?: boolean
  summary?: string              // что стоит в поле при множественном выборе
  eager?: boolean               // раскрывать весь справочник по клику (выбор из списка)
}) {
  const t = useTypeahead({ options, value, onPick, keyOf, textOf, searchOf, onEnter,
    multi, summary, eager })
  const menu = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLInputElement>(null)     // якорь меню (портал считает от него)

  // Закрытие НЕ вешаем на один `blur` (боль Ивана 2026-07-29: меню залипало намертво).
  // Каждый выбор шлёт PATCH, на время которого поле становится `disabled` — а браузер
  // при отключении сфокусированного элемента `blur` НЕ шлёт: фокус тихо уходит в body,
  // раскрытие остаётся включённым, и закрыть его больше нечем (Esc некому доставить,
  // клик по полю лишь повторяет `focus`). Поэтому истина о «клике мимо» берётся у
  // документа — она не зависит ни от фокуса, ни от того, что меню живёт в портале.
  const open = t.open || t.empty
  useEffect(() => {
    if (!open) return
    const outside = (e: PointerEvent) => {
      const target = e.target as Node
      if (field.current?.contains(target) || menu.current?.contains(target)) return
      t.close()
    }
    document.addEventListener('pointerdown', outside, true)
    return () => document.removeEventListener('pointerdown', outside, true)
  })

  // Поле «ожило» после сохранения, а меню ещё раскрыто — вернуть ему фокус, иначе
  // стрелки и Esc работают только до первого выбора.
  useEffect(() => {
    if (!disabled && open && document.activeElement !== field.current) field.current?.focus()
  }, [disabled, open])

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
        onChange={e => t.type(e.target.value)} onKeyDown={t.onKeyDown} onBlur={t.close}
        // Множественный выбор раскрывается и по фокусу, и по КЛИКУ: после Esc поле
        // остаётся сфокусированным, и одного `onFocus` не хватило бы — клик в поле
        // выглядел бы сломанным (поймано браузерным прогоном Ф13).
        onFocus={t.focus} onClick={t.focus} />
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
      {/* Плашки «не найдено» тоже держат `boxRef`: без него сторож клика-мимо считал
          бы их чужой территорией и гасил меню раньше, чем клик дойдёт до «Завести». */}
      {t.empty && (onCreate
        ? <AnchoredMenu anchor={field} boxRef={menu} className="typeahead-menu">
            <div className="typeahead-item active"
              onMouseDown={e => e.preventDefault()}
              onClick={() => { const s = t.text.trim(); t.close(); onCreate(s) }}>
              <span className="ci ci-add" />
              <span>Завести «{t.text.trim()}»</span>
            </div>
          </AnchoredMenu>
        : <AnchoredMenu anchor={field} boxRef={menu} className="picker-empty">
            {notFound ?? 'ничего не найдено'}
          </AnchoredMenu>)}
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
//
// **Выбор из СПИСКА, а не по памяти** (решение Ивана 2026-07-29): клик по полю
// раскрывает весь справочник поставщиков/заказчиков. Type-ahead хорош там, где
// справочник большой и человек знает, что ищет (изделия — тысячи, код на руках);
// контрагентов десятки, и держать их коды в голове никто не обязан — требовать
// первую букву значило заставлять угадывать. Ввод продолжает фильтровать, а
// «Завести «X»» из Ф12e работает как прежде.
const cpText = (c: CounterpartyRow) => c.code ? `${c.code} — ${c.description}` : c.description

export function CounterpartyPicker({ counterparties, value, onPick, disabled, placeholder,
  width, onClear, onCreate }: {
  counterparties: CounterpartyRow[]
  value: number | ''
  onPick: (id: number) => void
  disabled?: boolean; placeholder?: string; width?: number; onClear?: () => void
  onCreate?: (name: string) => void
}) {
  return <Picker options={counterparties} value={value} onPick={onPick} keyOf={c => c.id}
    textOf={cpText} searchOf={c => `${c.code ?? ''} ${c.description} ${c.inn}`}
    disabled={disabled} placeholder={placeholder} width={width} onClear={onClear}
    onCreate={onCreate} eager
    notFound="ничего не найдено — контрагента можно завести рядом."
    renderRow={c => <>
      {c.code && <span className="code">{c.code}</span>}
      <span>{c.description}</span>
      {c.inn && <span className="dim">ИНН {c.inn}</span>}
    </>} />
}

// ── Пикер охвата закупки (волна 19, Ф13): множественный выбор проектов ──
// Ориентир — выбор папки в мессенджере: список с галочками, Enter/клик переключает и
// список НЕ закрывается. Форма растёт ровно на одно поле: отмеченное свёрнуто в поле
// («ДОП ДЗЗ, ЛК-1 +2»), полный состав виден в меню и в табе «К закупке».
export function ProjectScopePicker({ projects, selected, onToggle, disabled }: {
  projects: ProjectRow[]
  selected: number[]
  onToggle: (id: number) => void
  disabled?: boolean
}) {
  const chosen = new Set(selected)
  const names = projects.filter(p => chosen.has(p.id)).map(p => p.code)
  // Сводка: два кода целиком, остальные счётчиком — иначе поле уезжает по ширине.
  const summary = names.length === 0 ? ''
    : names.slice(0, 2).join(', ') + (names.length > 2 ? ` +${names.length - 2}` : '')
  return <Picker options={projects} value={''} onPick={onToggle} keyOf={p => p.id}
    multi summary={summary}
    textOf={p => p.code} searchOf={p => `${p.code} ${p.description}`}
    disabled={disabled} placeholder="— не выбраны —" width={260}
    notFound="ничего не найдено — проект должен быть в справочнике."
    renderRow={p => <>
      <span className={'ci' + (chosen.has(p.id) ? ' ci-check' : '')} />
      <span className="code">{p.code}</span>
      <span className="dim">{p.description}</span>
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
