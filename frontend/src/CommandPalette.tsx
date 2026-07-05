// Палитра ⌘K (UI_GUIDE §8): глобальный поиск-переход по коду/номеру/названию
// из любого места. Команды-действия лягут сюда позже.
import { useEffect, useMemo, useRef, useState } from 'react'

export interface PaletteEntry {
  key: string
  code: string       // код/номер — моно
  name: string       // литературное название — для поиска и подсказки
  kind: string       // ярлык режима справа (Проект / Изделие / Поставка …)
  open: () => void
}

export function CommandPalette({ entries, onClose }:
  { entries: PaletteEntry[]; onClose: () => void }) {
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const hits = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return entries.slice(0, 40)
    return entries
      .filter(e => e.code.toLowerCase().includes(s) || e.name.toLowerCase().includes(s))
      .slice(0, 40)
  }, [q, entries])

  useEffect(() => { setActive(0) }, [q])

  const choose = (e: PaletteEntry) => { e.open(); onClose() }

  const onKey = (ev: React.KeyboardEvent) => {
    if (ev.key === 'Escape') { onClose(); return }
    if (ev.key === 'ArrowDown') { ev.preventDefault(); setActive(a => Math.min(a + 1, hits.length - 1)) }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (ev.key === 'Enter') { ev.preventDefault(); if (hits[active]) choose(hits[active]) }
  }

  return (
    <div className="palette-scrim" onMouseDown={onClose}>
      <div className="palette" onMouseDown={e => e.stopPropagation()}>
        <input ref={inputRef} value={q} placeholder="Перейти к… (код, номер, название)"
          onChange={e => setQ(e.target.value)} onKeyDown={onKey} />
        <div className="palette-list">
          {hits.length === 0
            ? <div className="palette-empty">Ничего не найдено</div>
            : hits.map((e, i) => (
              <div key={e.key} className={'palette-row' + (i === active ? ' active' : '')}
                onMouseEnter={() => setActive(i)} onMouseDown={() => choose(e)}>
                <span className="p-code">{e.code}</span>
                <span className="p-name">{e.name}</span>
                <span className="p-kind">{e.kind}</span>
              </div>
            ))}
        </div>
      </div>
    </div>
  )
}
