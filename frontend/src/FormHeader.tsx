// Единый заголовок формы (UI_GUIDE §4) + замок формы и чип фиксации (§5).
// «Название первое»: литературное имя (Inter 500) сверху, мета-строка (mono, dim)
// снизу; справа — индикатор сохранения + замок формы, ИЛИ чип фиксации.
import { useState, type ReactNode } from 'react'

// Замок формы — интерфейсный, бесплатный, личный: открыт=правим, закрыт=чистый текст.
// Черновики открыты сразу; существующие объекты закрыты по умолчанию.
export function useFormLock(draft: boolean) {
  const [unlocked, setUnlocked] = useState(draft)
  return { unlocked, toggle: () => setUnlocked(v => !v), setUnlocked }
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
