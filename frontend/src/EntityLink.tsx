// Ссылка на форму сущности — НАСТОЯЩАЯ `<a href>` (2026-08-10).
//
// Боль, с которой это родилось: по синему коду в таблице хочется щёлкнуть правой
// кнопкой и выбрать «Открыть в новой вкладке» — как по любой ссылке на любой странице.
// Раньше ссылки продукта были `<a onClick>` без `href`: браузеру нечего было открывать,
// контекстное меню пустовало, средний клик молчал, а строка состояния не показывала,
// куда ведёт. Адрес у каждой формы есть с 2026-08-07 (`core/route`), так что не хватало
// ровно атрибута.
//
// Разделение труда: `href` — браузеру (новая вкладка, копирование адреса, средний клик,
// Cmd/Ctrl-клик), обычный левый клик — приложению (переход внутри SPA, без перезагрузки).
// Поэтому перехватываем ТОЛЬКО чистый левый клик, а клик с модификатором отдаём как есть.
import type { MouseEvent, ReactNode } from 'react'
import { hrefOf, type EntityKind } from './core/route'

export function EntityLink({ kind, id, open, title, className, children }: {
  kind: EntityKind
  id: number
  open: (id: number) => void      // переход внутри приложения (тот же колбэк, что был)
  title?: string
  className?: string              // умолчание — роль «ссылка»; своё имя нужно редко
  children: ReactNode
}) {
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    // Модификаторы = осознанное «открой иначе»: новая вкладка (Cmd/Ctrl), новое окно
    // (Shift), скачивание (Alt в части браузеров). Не мешаем.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
    e.preventDefault()
    open(id)
  }
  return (
    <a className={className ?? 'link'} href={hrefOf(kind, id)} title={title}
      onClick={click}>{children}</a>
  )
}

// Ссылка на форму лота, обёрнутая вокруг глифа партии (волна 27): у строк, где своей
// колонки «Партия» нет (строки поставки/инвентаризации), лот открывается по глифу.
// Цвет остаётся у глифа — это знак «как дела», а не синий текст ссылки.
export function LotLink({ id, open, children }: {
  id: number; open: (id: number) => void; children: ReactNode
}) {
  return <EntityLink kind="lot" id={id} open={open} className="lot-link">{children}</EntityLink>
}
