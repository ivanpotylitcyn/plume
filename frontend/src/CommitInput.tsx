// Автосейв текстового/числового поля: коммит по blur / Enter (без кнопки).
// Единственный контрол ввода форм — и шапки, и строк списка (§6).
//
// `width` без значения по умолчанию (волна 19, Ф12a): inline-стиль сильнее любого
// класса, поэтому дефолтные 60px не давали полю растянуться по своей колонке или по
// шапке. Не передан — ширину решает CSS (`.qty-in`, `.c-desc`, шапка формы).
//
// Живёт отдельным модулем с волны 19 (Ф12c): раньше лежал в `ReceiptView`, и общие
// поля шапки ордера (`OrderFields` в `FormHeader`) замкнули бы импорты в кольцо.
import { useEffect, useState } from 'react'

export function CommitInput({ value, onCommit, disabled, width, validate, type }: {
  value: string; onCommit: (v: string) => void; disabled?: boolean
  width?: number; validate?: (v: string) => boolean; type?: string
}) {
  const [v, setV] = useState(value)
  useEffect(() => { setV(value) }, [value])
  const commit = () => {
    if (v === value) return
    if (validate && !validate(v)) { setV(value); return }
    onCommit(v)
  }
  return (
    <input className="qty-in" style={width ? { width } : undefined}
      value={v} disabled={disabled} type={type}
      onChange={e => setV(e.target.value)} onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
  )
}
