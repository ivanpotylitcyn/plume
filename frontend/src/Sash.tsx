// Sash списка режима (волна 25, Ф1) — как в VS Code (`sash.ts`, `sidebarPart.ts`).
//
// Состояние — ЖЕЛАЕМАЯ ширина; действующую считает CSS (`clamp` в `.app`), поэтому
// ресайз окна обходится без JS: область сузилась — список уступил, выросла — вернулся.
// Числа (`--side-min`, `--side-def`, `--work-min`) живут в CSS одним местом; здесь они
// только читаются.
//
// Мышь, тач и перо — одним путём (pointer events + `setPointerCapture`). Во время драга
// пишем CSS-переменную и класс прямо в DOM, а React-стейт — на `pointerup`: иначе `App`
// со всеми его списками перерисовывался бы 60 раз в секунду. Расхождения нет — к
// коммиту DOM уже показывает ровно то, что станет стейтом.
//
// Хранение — `localStorage` (на устройство, не в профиле): у телефона и десктопа ширины
// разные. Ширина `null` = «по умолчанию темы».
import { useRef, type RefObject, type PointerEvent, type KeyboardEvent } from 'react'

export interface Side { w: number | null; hidden: boolean }

const KEY_W = 'plume.side.w'
const KEY_HIDDEN = 'plume.side.hidden'

// Хранилище может быть недоступно (приватное окно, запрет сайта) — тогда живём
// умолчанием и молча не запоминаем.
export function loadSide(): Side {
  try {
    const w = Number(localStorage.getItem(KEY_W))
    return { w: w > 0 ? w : null, hidden: localStorage.getItem(KEY_HIDDEN) === '1' }
  } catch { return { w: null, hidden: false } }
}

export function saveSide({ w, hidden }: Side) {
  try {
    if (w == null) localStorage.removeItem(KEY_W); else localStorage.setItem(KEY_W, String(w))
    if (hidden) localStorage.setItem(KEY_HIDDEN, '1'); else localStorage.removeItem(KEY_HIDDEN)
  } catch { /* не запоминаем — не беда */ }
}

const STEP = 16   // шаг стрелок с клавиатуры

export function Sash({ app, side, onCommit }: {
  app: RefObject<HTMLDivElement | null>; side: Side; onCommit: (s: Side) => void
}) {
  const drag = useRef<{ x: number; w: number; w0: number } | null>(null)
  const live = useRef(side)

  // Пределы — из CSS: пол списка и пол рабочей области (пол шапки формы).
  const limits = () => {
    const el = app.current!
    const px = (name: string) => parseFloat(getComputedStyle(el).getPropertyValue(name))
    const act = (el.querySelector('.activity') as HTMLElement).offsetWidth
    return { min: px('--side-min'), def: px('--side-def'),
             max: el.clientWidth - act - px('--work-min') }
  }
  const fit = (w: number) => {
    const { min, max } = limits()
    return Math.round(Math.max(min, Math.min(w, max)))
  }
  const apply = (s: Side) => {
    const el = app.current!
    if (s.w != null) el.style.setProperty('--side-w', s.w + 'px')
    el.classList.toggle('side-hidden', s.hidden)
    live.current = s
  }

  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    // От ДЕЙСТВУЮЩЕЙ ширины, а не желаемой: если CSS сейчас ужал список, драг
    // начинается от того, что видно, без скачка под пальцем.
    const sb = app.current!.querySelector('.sidebar') as HTMLElement
    const w = side.hidden ? 0 : sb.getBoundingClientRect().width
    drag.current = { x: e.clientX, w, w0: side.w ?? limits().def }
    live.current = side
    document.documentElement.classList.add('sash-drag')
  }
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const raw = d.w + e.clientX - d.x
    // snap: утянули меньше половины минимума — список прячется, ширина до драга
    // сохраняется; потянули обратно — показывается от минимума.
    apply(raw < limits().min / 2 ? { w: d.w0, hidden: true } : { w: fit(raw), hidden: false })
  }
  const up = () => {
    if (!drag.current) return
    drag.current = null
    document.documentElement.classList.remove('sash-drag')
    onCommit(live.current)
  }
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const dir = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : 0
    if (!dir) return
    e.preventDefault()
    const cur = side.hidden ? 0 : (app.current!.querySelector('.sidebar') as HTMLElement).offsetWidth
    const raw = cur + dir * STEP
    onCommit(raw < limits().min / 2 ? { ...side, hidden: true } : { w: fit(raw), hidden: false })
  }

  return (
    <div className="sash" role="separator" aria-orientation="vertical"
      aria-label="Ширина списка (двойной клик — по умолчанию)" tabIndex={0}
      onPointerDown={down} onPointerMove={move} onPointerUp={up}
      onPointerCancel={up} onLostPointerCapture={up}
      onDoubleClick={() => onCommit({ w: null, hidden: false })}
      onKeyDown={key} />
  )
}
