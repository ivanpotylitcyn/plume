// Единый заголовок формы (UI_GUIDE §4) + замок формы и чип фиксации (§5).
// «Название первое»: литературное имя (Inter 500) сверху, мета-строка (mono, dim)
// снизу; справа — индикатор сохранения + замок формы, ИЛИ чип фиксации.
import { useEffect, useRef, useState, type ReactNode } from 'react'

// Замок формы — интерфейсный, бесплатный, личный: открыт=правим, закрыт=чистый текст.
// Черновики открыты сразу; существующие объекты закрыты по умолчанию.
export function useFormLock(draft: boolean) {
  const [unlocked, setUnlocked] = useState(draft)
  return { unlocked, toggle: () => setUnlocked(v => !v), setUnlocked }
}

// Единая оболочка кокпита ордера (Ф2i): свод боилерплейта, одинакового у всех шести
// detail-вьюх «Ордера» — загрузка кокпита по id, обёртка мутации `run` (ответ сервера
// → в стейт + обновить фид), дружелюбное удаление `del` (confirm + guard бэка), замок
// формы и строка ошибки. Специфика вида (тело кокпита, выражение `fixed`, side-load
// пикеров) остаётся во вьюхе; сюда она входит колбэками `cb`.
export function useOrderCockpit<C extends { id: number }>(
  id: number,
  load: (id: number) => Promise<C>,
  cb: {
    onChanged: () => void          // мутация прошла — перезагрузить список ордеров
    onDeleted: () => void          // документ удалён — сбросить выбор
    onLoad?: (c: C) => void        // side-load после загрузки/мутации (пикеры лотов/заказов)
    remove: (id: number) => Promise<unknown>   // DELETE-эндпойнт вида
    confirmDelete: string          // текст подтверждения удаления
  },
) {
  const [c, setC] = useState<C | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { unlocked, toggle } = useFormLock(true)
  // Колбэки/тексты пересоздаются каждый рендер — держим свежими через ref, чтобы
  // эффект зависел только от id (перезагрузка ровно при смене документа).
  const ref = useRef(cb)
  ref.current = cb

  useEffect(() => {
    setC(null); setErr(null)
    load(id).then(next => { setC(next); ref.current.onLoad?.(next) })
      .catch(e => setErr(String(e)))
  }, [id, load])

  const run = (p: Promise<C>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); ref.current.onLoad?.(next); ref.current.onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  const del = () => {
    if (!c || !confirm(ref.current.confirmDelete)) return
    setBusy(true); setErr(null)
    ref.current.remove(c.id).then(() => ref.current.onDeleted())
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return { c, err, busy, unlocked, toggle, run, del }
}

export function FormHeader({
  name, meta, unlocked, onToggleLock, fixed, fixedLabel, onUnfix, onDelete, error,
}: {
  name: ReactNode
  meta: ReactNode
  unlocked?: boolean
  onToggleLock?: () => void
  fixed?: boolean
  fixedLabel?: string
  onUnfix?: () => void
  onDelete?: () => void   // удаление ордера (только черновик; posted → «сперва расфиксировать»)
  error?: string | null
}) {
  return (
    <div className="form-head">
      <div className="fh-main">
        <div className="fh-name">{name}</div>
        <div className="fh-meta">{meta}</div>
      </div>
      <div className="fh-right">
        {fixed ? (
          // Зафиксирован: чип с заливкой, яркого индикатора нет — документ стабилен.
          <button className="fix-chip" title="Снять фиксацию…"
            onClick={onUnfix} disabled={!onUnfix}>
            🔒 {fixedLabel ?? 'зафиксирован'}
          </button>
        ) : (
          <>
            {/* Индикатор детерминирован по замку: открыт → жёлтый «редактируется»,
                закрыт (чистая форма) → зелёный «сохранено». Ошибка перебивает. */}
            {error
              ? <span className="save-ind error">ошибка: {error}</span>
              : unlocked
                ? <span className="save-ind editing">● редактируется</span>
                : <span className="save-ind saved">✓ сохранено</span>}
            {onToggleLock && (
              <button className={'lock-btn' + (unlocked ? ' open' : '')}
                title={unlocked ? 'Форма открыта — редактируется. Закрыть (чистый текст)'
                                : 'Форма закрыта. Открыть для правки'}
                onClick={onToggleLock}>
                {unlocked ? '🔓' : '🔒'}
              </button>
            )}
            {onDelete && (
              // Удаление — только у черновика (posted перехватывает ветка чипа выше).
              <button className="del-btn" title="Удалить документ" onClick={onDelete}>🗑</button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
