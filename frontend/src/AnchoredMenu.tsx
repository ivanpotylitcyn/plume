// Всплывающее меню, привязанное к полю (волна 19, Ф15-добор — боль Ивана 2026-07-28).
//
// Задача одна: меню пикера не должно резаться контейнерами. Резали его ДВА предка —
// панель табов (`.fs-body { overflow: hidden }`) и прокрутка страницы
// (`.work { overflow-y: auto }`), поэтому «поднять z-index» не помогало в принципе:
// `overflow` отрезает раньше, чем слои начинают спорить. Лечится только выносом меню
// из обоих потоков — портал в `body` + `position: fixed`, координаты от прямоугольника
// поля.
//
// Заодно решается второй случай, который «переносом пикера наверх» не лечился: у
// нижнего края окна меню раскрывается ВВЕРХ, а если тесно с обеих сторон — жмётся по
// доступной высоте и скроллится внутри себя.
//
// Геометрия — знак темы, а не смысл (шов Ф7): `core/useTypeahead` про неё не знает и
// не меняется. Файл экспортирует только компонент — правило `only-export-components`.
import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'
import { createPortal } from 'react-dom'

const GAP = 2        // зазор между полем и меню
const EDGE = 8       // отступ от края окна — меню не липнет к нему вплотную
const MAX = 240      // желаемая высота (та же, что была в CSS)
const MIN = 88       // ниже этого меню бесполезно — лучше раскрыться в другую сторону

interface Box { top: number; left: number; minWidth: number; maxHeight: number }

const same = (a: Box | null, b: Box) =>
  !!a && a.top === b.top && a.left === b.left
  && a.minWidth === b.minWidth && a.maxHeight === b.maxHeight

export function AnchoredMenu({ anchor, className, boxRef, children }: {
  anchor: RefObject<HTMLElement | null>
  className: string
  boxRef?: RefObject<HTMLDivElement | null>   // наружу — для клавиатурной прокрутки
  children: ReactNode
}) {
  const own = useRef<HTMLDivElement>(null)
  const box = boxRef ?? own
  const [pos, setPos] = useState<Box | null>(null)

  const place = useCallback(() => {
    const a = anchor.current
    const el = box.current
    if (!a || !el) return
    const r = a.getBoundingClientRect()
    // `scrollHeight` даёт полную высоту содержимого независимо от текущего клампа,
    // поэтому одного прохода хватает: сначала знаем «сколько хочет», потом решаем куда.
    const want = Math.min(MAX, el.scrollHeight + 2)      // +2 — рамки
    const below = window.innerHeight - r.bottom - GAP - EDGE
    const above = r.top - GAP - EDGE
    // Вниз — по умолчанию; вверх — когда снизу не помещается, а сверху просторнее.
    const up = below < Math.min(want, MIN) || (below < want && above > below)
    const maxHeight = Math.max(0, Math.min(MAX, up ? above : below))
    const height = Math.min(want, maxHeight)
    const width = el.offsetWidth || r.width
    const next: Box = {
      top: up ? Math.max(EDGE, r.top - GAP - height) : r.bottom + GAP,
      left: Math.max(EDGE, Math.min(r.left, window.innerWidth - EDGE - width)),
      minWidth: r.width,
      maxHeight,
    }
    setPos(p => (same(p, next) ? p : next))
  }, [anchor, box])

  // Позиция пересчитывается на каждый рендер (список кандидатов меняется по буквам) и
  // на любую прокрутку/ресайз. `capture: true` — ловим прокрутку ЛЮБОГО предка, не
  // только окна: поле уезжает вместе с панелью, меню обязано ехать за ним.
  useLayoutEffect(place)
  useLayoutEffect(() => {
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [place])

  return createPortal(
    <div ref={box} className={className}
      // До первого замера меню невидимо: иначе кадр в левом верхнем углу экрана.
      style={pos
        ? { top: pos.top, left: pos.left, minWidth: pos.minWidth, maxHeight: pos.maxHeight }
        : { top: 0, left: 0, visibility: 'hidden' }}>
      {children}
    </div>,
    document.body)
}
