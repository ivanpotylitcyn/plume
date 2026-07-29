// Единый выпадающий список темы (волна 19, Ф12d-добор; решение Ивана 2026-07-29).
//
// Нативный `<select>` рисует меню средствами ОС — синее системное выделение посреди
// тёмной темы, своя метрика строки, свой шрифт. Пока таких списков было два, это не
// мешало; сейчас их восемнадцать, и половина интерфейса выглядела чужой. Здесь
// оформление живёт в ОДНОМ месте: правится один раз — меняется везде.
//
// Отношение к пикеру (§6a): `Picker` — type-ahead, там человек ЗНАЕТ, что ищет, и
// сокращает список набором. `Dropdown` — выбор из наличного, набирать нечего. Общего
// у них ровно два: всплывающий слой (`AnchoredMenu` — портал в `body`, иначе слой
// режут прокрутка и панель табов) и знак строки меню (`.typeahead-item`).
//
// Поле — `<input readOnly>`, а не кнопка: так все существующие правила темы (ширина
// поля шапки, `.form-locked` в строках списка, ширина колонки таблицы) продолжают
// действовать без единого нового селектора, а поле выбора выглядит ровно как поле
// ввода рядом с ним.
import { useEffect, useRef, useState } from 'react'
import { AnchoredMenu } from './AnchoredMenu'

export interface DropdownOption {
  value: number | string
  label: string
}

export function Dropdown({ options, value, onPick, disabled, placeholder, className, title }: {
  options: DropdownOption[]
  value: number | string          // '' — ничего не выбрано
  onPick: (v: number | string) => void
  disabled?: boolean
  placeholder?: string
  className?: string              // ширина/тон в месте применения (`peg-into`, `list-proj`)
  title?: string
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const field = useRef<HTMLInputElement>(null)
  const menu = useRef<HTMLDivElement>(null)

  const idx = options.findIndex(o => o.value === value)
  const text = idx >= 0 ? options[idx].label : ''

  // Открываем — подсвечиваем текущий выбор (клавиатура идёт от него, а не с начала).
  const show = () => { setActive(idx >= 0 ? idx : 0); setOpen(true) }
  const close = () => setOpen(false)
  const pick = (o: DropdownOption) => { close(); if (o.value !== value) onPick(o.value) }

  // Закрытие — по клику МИМО, а не по `blur` (урок пикера 2026-07-29: каждый выбор
  // шлёт PATCH, поле на это время становится `disabled`, и браузер `blur` не шлёт —
  // раскрытие остаётся включённым и снять его нечем).
  useEffect(() => {
    if (!open) return
    const outside = (e: PointerEvent) => {
      const t = e.target as Node
      if (field.current?.contains(t) || menu.current?.contains(t)) return
      close()
    }
    document.addEventListener('pointerdown', outside, true)
    return () => document.removeEventListener('pointerdown', outside, true)
  })

  // Поле «ожило» после сохранения, а меню ещё раскрыто — вернуть ему фокус, иначе
  // стрелки и Esc работают только до первого выбора.
  useEffect(() => {
    if (!disabled && open && document.activeElement !== field.current) field.current?.focus()
  }, [disabled, open])

  // Подсвеченный пункт подтягиваем к краю СВОЕГО списка: `scrollIntoView` уехал бы
  // вверх по всем прокручиваемым предкам и дёрнул страницу.
  useEffect(() => {
    const box = menu.current
    const row = box?.children[active] as HTMLElement | undefined
    if (!box || !row) return
    if (row.offsetTop < box.scrollTop) box.scrollTop = row.offsetTop
    else if (row.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight)
      box.scrollTop = row.offsetTop + row.offsetHeight - box.clientHeight
  }, [active, open])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); show() }
      return
    }
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, options.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (options[active]) pick(options[active]) }
    else if (e.key === 'Escape') { e.preventDefault(); close() }
  }

  return (
    <span className="picker dd">
      <input ref={field} className={'lot-sel' + (className ? ' ' + className : '')}
        readOnly value={text} disabled={disabled} placeholder={placeholder} title={title}
        onKeyDown={onKeyDown} onClick={() => (open ? close() : show())} />
      {/* Аффорданс закрытого списка: набирать в этом поле нечего, и без знака оно
          читалось бы как обычный ввод. У type-ahead шеврона нет намеренно — там
          набирать как раз нужно. */}
      <span className="ci ci-chevron-down dd-chev" />
      {open &&
        <AnchoredMenu anchor={field} boxRef={menu} className="typeahead-menu">
          {options.map((o, i) => (
            // onMouseDown гасим: иначе blur поля закрыл бы меню до клика.
            <div key={o.value} className={`typeahead-item${i === active ? ' active' : ''}`}
              onMouseDown={e => e.preventDefault()} onClick={() => pick(o)}>
              {/* Отметка выбранного — тем же знаком, что в множественном пикере (Ф13). */}
              <span className={'ci' + (o.value === value ? ' ci-check' : '')} />
              <span>{o.label}</span>
            </div>
          ))}
        </AnchoredMenu>}
    </span>
  )
}
