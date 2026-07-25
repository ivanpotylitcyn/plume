// Ядро пикера (волна 19, Ф2). Здесь только логика выбора из справочника: что подходит
// под ввод, что подсвечено, что делают стрелки / Enter / Esc. Ни разметки, ни CSS,
// ни глифов — знак выбирает тема (шов Ф7: движок отдаёт смысл, тема — знак).
//
// Дисциплина `core/`: файл не импортирует ни CSS-классы, ни Codicon, ни компоненты вью.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'

export interface TypeaheadSpec<T> {
  options: T[]
  value: number | ''                 // выбранное (контролирует вызывающий)
  onPick: (id: number) => void       // только настоящий выбор; очистка — своим действием
  keyOf: (o: T) => number
  textOf: (o: T) => string           // что стоит в поле, когда выбор сделан
  searchOf?: (o: T) => string        // по чему ищем (по умолчанию — `textOf`)
  limit?: number
  onEnter?: () => void               // Enter при закрытом меню (обычно «добавить»)
}

export interface Typeahead<T> {
  text: string                       // что показывать в поле ввода
  matches: T[]
  active: number                     // индекс подсвеченного кандидата
  open: boolean                      // меню кандидатов раскрыто
  empty: boolean                     // ввод есть, кандидатов нет
  type: (s: string) => void
  pick: (o: T) => void
  close: () => void
  onKeyDown: (e: KeyboardEvent) => void
}

export function useTypeahead<T>(spec: TypeaheadSpec<T>): Typeahead<T> {
  const { options, value, onPick, keyOf, textOf, limit = 20, onEnter } = spec
  // Функции-экстракторы приходят инлайном (новые на каждый рендер) — держим в ref,
  // чтобы они не гоняли мемоизацию и не текли в зависимости хуков.
  const fns = useRef(spec)
  fns.current = spec

  // `null` = «показываем выбранное» (текст ведёт `value`), строка = «человек печатает».
  // Так поле переживает и внешний сброс `value` (после «добавить»), и правку ввода —
  // без синхронизирующих эффектов и без гонок с `busy`.
  const [q, setQ] = useState<string | null>(null)
  const [active, setActive] = useState(0)

  const selected = value === '' ? undefined : options.find(o => keyOf(o) === value)
  const text = q ?? (selected ? textOf(selected) : '')

  const matches = useMemo(() => {
    const s = (q ?? '').trim().toLowerCase()
    if (!s) return []
    const key = fns.current.searchOf ?? fns.current.textOf
    return options.filter(o => key(o).toLowerCase().includes(s)).slice(0, limit)
  }, [options, q, limit])

  const typed = q !== null && q.trim() !== ''
  const open = typed && matches.length > 0
  const empty = typed && matches.length === 0

  useEffect(() => { setActive(0) }, [q])

  // Ввод не трогает `value`: выбранное живёт, пока не выбрали новое (или не очистили
  // явно). Иначе на формах с немедленным сохранением каждый символ слал бы PATCH.
  const type = (s: string) => setQ(s)
  const pick = (o: T) => { setQ(null); onPick(keyOf(o)) }
  const close = () => setQ(null)

  const onKeyDown = (e: KeyboardEvent) => {
    if (open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault()
      const step = e.key === 'ArrowDown' ? 1 : matches.length - 1
      setActive(a => (a + step) % matches.length)
      return
    }
    if (e.key === 'Escape' && (open || empty)) { e.preventDefault(); close(); return }
    if (e.key === 'Enter') {
      if (open) { e.preventDefault(); pick(matches[active]); return }
      onEnter?.()
    }
  }

  return { text, matches, active, open, empty, type, pick, close, onKeyDown }
}
