// Единый заголовок формы (UI_GUIDE §4) + замок формы и чип фиксации (§5).
// «Название первое»: литературное имя (Inter 500) сверху, мета-строка (mono, dim)
// снизу; справа — индикатор сохранения + замок формы, ИЛИ чип фиксации.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type UserRow, type ProjectRow } from './api'

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

// Пикер авторства шапки (Ф2j): единое поле «автор» для всех ордеров/закупок.
// Справочник пользователей грузим один раз на всё приложение (модульный кэш —
// список редко меняется, дёргать его в каждой из 8 вьюх незачем). Если текущий
// автор не активен (нет в списке) — держим его первой опцией по `userName`, чтобы
// подпись не пропала под замком.
let _usersCache: Promise<UserRow[]> | null = null
function loadUsers() { return (_usersCache ??= api.users()) }

export function AuthorField({ userId, userName, disabled, onChange }: {
  userId: number; userName: string; disabled: boolean; onChange: (id: number) => void
}) {
  const [users, setUsers] = useState<UserRow[]>([])
  useEffect(() => { loadUsers().then(setUsers) }, [])
  const known = users.some(u => u.id === userId)
  return (
    <label>автор{' '}
      <select className="lot-sel" value={userId || ''} disabled={disabled}
        onChange={e => { const v = Number(e.target.value); if (v) onChange(v) }}>
        {!known && userId ? <option value={userId}>{userName}</option> : null}
        {users.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
      </select>
    </label>
  )
}

// Единый якорный <select> для шапки формы (Ф2k #A): подписанный выпадающий список,
// который держит текущее значение видимым, даже если его нет в опциях (подпись не
// пропадёт под замком). Опции — {id,label}; `onChange` срабатывает только на реальном
// изменённом выборе. Движок сам откажет в смене якоря у непустого ордера — форма
// ловит отказ строкой ошибки (как у автора).
export function AnchorSelect({ label, id, currentLabel, options, disabled, onChange }: {
  label: string; id: number; currentLabel: string
  options: { id: number; label: string }[]
  disabled: boolean; onChange: (id: number) => void
}) {
  const known = options.some(o => o.id === id)
  return (
    <label>{label}{' '}
      <select className="lot-sel" value={id || ''} disabled={disabled}
        onChange={e => { const v = Number(e.target.value); if (v && v !== id) onChange(v) }}>
        {!known && id ? <option value={id}>{currentLabel}</option> : null}
        {options.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
  )
}

// Проект-якорь шапки (Ф2k #A): единый пикер проекта на всех ордерах/заказе. Список
// проектов кэшируем один раз на приложение (как справочник авторов) — редко меняется.
let _projectsCache: Promise<ProjectRow[]> | null = null
function loadProjects() { return (_projectsCache ??= api.projects()) }

export function ProjectField({ projectId, projectLabel, disabled, onChange }: {
  projectId: number; projectLabel: string; disabled: boolean; onChange: (id: number) => void
}) {
  const [projects, setProjects] = useState<ProjectRow[]>([])
  useEffect(() => { loadProjects().then(setProjects) }, [])
  return (
    <AnchorSelect label="проект" id={projectId} currentLabel={projectLabel}
      options={projects.map(p => ({ id: p.id, label: `${p.code} — ${p.name}` }))}
      disabled={disabled} onChange={onChange} />
  )
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
