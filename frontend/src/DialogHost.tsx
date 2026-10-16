// Хост фирменных окон и их общая коробка (волна 23, Ф1). Вызовы — в `dialog.ts`.
//
// `DialogBox` — одна разметка на все окна продукта: заголовок, список строк
// (предупреждения — тоном «ждём»), необязательный отказ (тоном «нужна работа») и
// команды на языке шапки (`.fh-ctl`: подпись + Codicon). Слой — `.scrim`, общий с
// палитрой ⌘K. Esc — отмена, Enter — действие (если оно есть). Клик мимо — отмена.
import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { bindDialogHost, dialogLines, type DialogLine, type Pending } from './dialog'

export function DialogBox({ title, lines, refusal, wait, verb, icon, danger, onConfirm, onClose,
  closeLabel, wide, children }: {
  title?: string
  lines?: DialogLine[]
  refusal?: string | null
  wait?: ReactNode           // пока движок считает — вместо списка
  verb?: string
  icon?: string
  danger?: boolean
  onConfirm?: () => void     // нет — окно-сообщение (одна команда)
  onClose: () => void
  closeLabel: string
  wide?: boolean             // окно с таблицей выбора (волна 24, «Новый заказ»)
  children?: ReactNode       // содержимое окна — между последствиями и командами
}) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      if (e.key === 'Enter') { e.preventDefault(); (onConfirm ?? onClose)() }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  })
  return createPortal(
    <div className="scrim" onMouseDown={onClose}>
      <div className={'dialog' + (wide ? ' dialog--wide' : '')}
        onMouseDown={e => e.stopPropagation()}>
        {title && <h3>{title}</h3>}
        {wait && <div className="wait">{wait}</div>}
        {refusal && <div className="refusal">Нельзя: {refusal}</div>}
        {!!lines?.length &&
          <ul>{lines.map((l, i) =>
            <li key={i} className={l.warn ? 'warn' : undefined}>{l.text}</li>)}</ul>}
        {children}
        <div className="dialog-cmds">
          <button className="fh-ctl" onClick={onClose}>
            <span className="lbl">{closeLabel}</span>
            <span className="ci ci-close" />
          </button>
          {onConfirm &&
            <button className={'fh-ctl' + (danger ? ' fh-del' : '')} onClick={onConfirm} autoFocus>
              <span className="lbl">{verb}</span>
              {icon && <span className={'ci ' + icon} />}
            </button>}
        </div>
      </div>
    </div>,
    document.body)
}

export function DialogHost() {
  const [queue, setQueue] = useState<Pending[]>([])
  useEffect(() => {
    bindDialogHost(p => setQueue(q => [...q, p]))
    return () => bindDialogHost(null)
  }, [])
  const cur = queue[0]
  if (!cur) return null
  const done = (ok: boolean) => { setQueue(q => q.slice(1)); cur.resolve(ok) }
  return cur.kind === 'tell'
    ? <DialogBox title={cur.title} lines={dialogLines(cur)}
        closeLabel="Понятно" onClose={() => done(true)} />
    : <DialogBox title={cur.title} lines={dialogLines(cur)}
        verb={cur.verb ?? 'Да'} icon={cur.icon} danger={cur.danger}
        closeLabel="Отмена" onConfirm={() => done(true)} onClose={() => done(false)} />
}
