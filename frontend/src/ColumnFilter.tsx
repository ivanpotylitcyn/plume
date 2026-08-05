// Фильтр в ЗАГОЛОВКЕ колонки (2026-08-05) — общий для всех числовых списков.
//
// Родился в своде «Потребность» проекта: список на сотни строк, а вопросы к нему всегда
// узкие — «что не заказано», «что уже лежит», «где перебор». Фильтр живёт там же, где
// число, к которому относится, поэтому отдельной панели над таблицей продукт не заводит.
// Знак — тот же раскрыватель, что везде; выбранное значение горит акцентом, иначе
// спрятанные строки читались бы как пропажа данных.
import { useRef, useState } from 'react'
import { AnchoredMenu } from './AnchoredMenu'
import { Chevron } from './status'

export function ColumnFilter({ opts, value, onPick }: {
  opts: [string, string][]      // [значение, подпись]
  value: string
  onPick: (v: string) => void
}) {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLSpanElement>(null)
  const on = value !== opts[0][0]        // первый вариант — «все», он же нейтральный
  const label = opts.find(([v]) => v === value)?.[1] ?? ''
  return (
    <span className="col-filter" ref={anchor}>
      <button className={'chev' + (on ? ' on' : '')}
        title={on ? `фильтр: ${label}` : 'фильтр по колонке'}
        onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
      {open && <>
        {/* Подложка на всё окно: клик мимо меню закрывает его, как у пикеров. */}
        <div className="col-filter-veil" onClick={() => setOpen(false)} />
        <AnchoredMenu anchor={anchor} className="typeahead-menu col-filter-menu">
          {opts.map(([v, text]) => (
            <div key={v} className={'typeahead-item' + (v === value ? ' active' : '')}
              onClick={() => { onPick(v); setOpen(false) }}>
              <span className={'ci' + (v === value ? ' ci-check' : '')} />
              <span>{text}</span>
            </div>
          ))}
        </AnchoredMenu>
      </>}
    </span>
  )
}
