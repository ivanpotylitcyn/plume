// Автосейв текстового/числового поля: коммит по blur / Enter (без кнопки).
// Единственный контрол ввода форм — и шапки, и строк списка (§6).
//
// Ширины у контрола НЕТ вовсе (Б2а аудита-1, 2026-07-30): её решает CSS — токен
// `--in-num` у числа, колонка (`.c-key`/`.c-desc`/`.c-txt`) у текста, ступень шапки у
// поля формы. Проп `width` (волна 19, Ф12a) снят: он ставил inline-стиль, а тот сильнее
// любого класса — одно и то же «кол-во» разъехалось на 56/60/72 по четырём формам.
//
// Живёт отдельным модулем с волны 19 (Ф12c): раньше лежал в `ReceiptView`, и общие
// поля шапки ордера (`OrderFields` в `FormHeader`) замкнули бы импорты в кольцо.
import { useEffect, useState } from 'react'

export function CommitInput({ value, onCommit, disabled, validate, type }: {
  value: string; onCommit: (v: string) => void; disabled?: boolean
  validate?: (v: string) => boolean; type?: string
}) {
  const [v, setV] = useState(value)
  useEffect(() => { setV(value) }, [value])
  const commit = () => {
    if (v === value) return
    if (validate && !validate(v)) { setV(value); return }
    onCommit(v)
  }
  return (
    <input className="qty-in"
      value={v} disabled={disabled} type={type}
      onChange={e => setV(e.target.value)} onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
  )
}
