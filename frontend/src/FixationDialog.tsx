// Окно перед фиксацией / расфиксацией (волна 23, Ф1) — «осознанная шероховатость».
//
// Фиксация — самое весомое действие формы: заказ начинает считаться в «Заказано»,
// поставка ложится на склад, комплектация рождает прибор. Решение Ивана — сделать шаг
// ощутимым: перед ним окно говорит, к чему это приведёт, ЖИВЫМИ числами. Смысл
// (последствия, отказ) приходит из движка (`engine.fixation_preview`); здесь — только
// загрузка, а коробка общая со всеми окнами продукта (`DialogBox`). Отказ движок
// находит пробной фиксацией с откатом, поэтому окно не разрешит того, чего не разрешит
// кнопка.
import { useEffect, useState } from 'react'
import { api, type FixationPreview } from './api'
import { DialogBox } from './DialogHost'

export function FixationDialog({ path, lock, onConfirm, onClose }: {
  path: string                 // `purchases/12` — сегмент сущности, как у `…/lock/`
  lock: boolean                // фиксация / расфиксация
  onConfirm: () => void
  onClose: () => void
}) {
  const [p, setP] = useState<FixationPreview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.fixation(path, lock).then(setP).catch(e => setErr(e instanceof Error ? e.message : String(e)))
  }, [path, lock])

  const can = !!p && !p.refusal
  return (
    <DialogBox title={p?.title} lines={can ? p.lines : undefined}
      refusal={err ? `ошибка: ${err}` : p?.refusal}
      wait={!p && !err ? 'считаю последствия…' : undefined}
      verb={p?.verb} icon={lock ? 'ci-lock' : 'ci-unlock'}
      onConfirm={can ? () => { onClose(); onConfirm() } : undefined}
      onClose={onClose} closeLabel={can ? 'Отмена' : 'Закрыть'} />
  )
}
