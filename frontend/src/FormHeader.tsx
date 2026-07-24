// Единый заголовок формы (UI_GUIDE §4) + замок формы и чип фиксации (§5).
// «Название первое»: литературное имя (Inter 500) сверху, мета-строка (mono, dim)
// снизу; справа — индикатор сохранения + замок формы, ИЛИ чип фиксации.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type UserRow, type ProjectRow } from './api'

// Замок формы — интерфейсный, бесплатный, личный: открыт=правим, закрыт=чистый текст.
// Канон §5 (Ф9): всё существующее открывается В ПРОСМОТРЕ; исключение ровно одно —
// только что созданный документ, он открыт в правке сразу. Признак «только что создан»
// приносит `isNew` (App выводит его из `justCreated`). Сброс режима на смене `id`
// лечит протечку Ф8: `useState` держал режим предыдущего документа, и он перетекал.
export function useFormLock(id: number, isNew = false) {
  const [unlocked, setUnlocked] = useState(isNew)
  const freshRef = useRef(isNew); freshRef.current = isNew
  // Ровно на смену документа: вернуть режим к дефолту этого документа (новый→правка,
  // существующий→просмотр). Зависимость строго [id] — иначе гашение `justCreated` в App
  // (isNew: true→false без смены id) слэмнуло бы открытую новую форму обратно в просмотр.
  useEffect(() => { setUnlocked(freshRef.current) }, [id])
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
  isNew = false,                   // §5: только что созданный открыть в правке
) {
  const [c, setC] = useState<C | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { unlocked, toggle } = useFormLock(id, isNew)
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
  // dt/dd-пара для сетки `.props` шапки (Ф3): подпись отдельно от контрола.
  return (
    <>
      <dt>Автор</dt>
      <dd>
        <select className="lot-sel" value={userId || ''} disabled={disabled}
          onChange={e => { const v = Number(e.target.value); if (v) onChange(v) }}>
          {!known && userId ? <option value={userId}>{userName}</option> : null}
          {users.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
        </select>
      </dd>
    </>
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
  // dt/dd-пара для сетки `.props` шапки (Ф3): подпись-якорь отдельно от контрола.
  return (
    <>
      <dt>{label}</dt>
      <dd>
        <select className="lot-sel" value={id || ''} disabled={disabled}
          onChange={e => { const v = Number(e.target.value); if (v && v !== id) onChange(v) }}>
          {!known && id ? <option value={id}>{currentLabel}</option> : null}
          {options.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </dd>
    </>
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
    <AnchorSelect label="Проект" id={projectId} currentLabel={projectLabel}
      options={projects.map(p => ({ id: p.id, label: `${p.code} — ${p.description}` }))}
      disabled={disabled} onChange={onChange} />
  )
}

// Шапка формы (§5, Ф9): контролы — вертикальной колонкой справа, подпись слева от
// иконки, глиф = НАЗНАЧЕНИЕ (куда попадёшь), не состояние. Иконки — Codicons (§2).
// Индикаторы «✓ сохранено»/«● редактируется» сняты (автосейв → «сохранено» всегда,
// ничего не различало). Две оси не путаем: замок ФОРМЫ (Редактировать/Просмотр) —
// личный, режим показа; фиксация ДОКУМЕНТА (Зафиксировать/Расфиксировать) — в данных.
// У зафиксированного степень свободы ровно одна — расфиксировать; корзины под замком нет.
export function FormHeader({
  code, meta, unlocked, onToggleLock, fixed, onFixate, fixateTitle, onUnfix, onDelete,
  download, error, children,
}: {
  code: ReactNode           // первичная идентичность в H1 (волна 19, Ф11: бывш. `name`)
  meta: ReactNode
  unlocked?: boolean
  onToggleLock?: () => void
  fixed?: boolean
  onFixate?: () => void      // зафиксировать документ (draft→locked); только у расфиксированного
  fixateTitle?: string       // подсказка-последствие («…родить прибор») — слово в кнопке едино
  onUnfix?: () => void       // расфиксировать документ (locked→draft)
  onDelete?: () => void      // удалить документ (только расфиксированный; под замком корзины нет)
  download?: { href: string; title?: string }  // скачать (xlsx) — в слоте корзины, но
                             // только у ЗАФИКСИРОВАННОГО (слоты не сталкиваются с корзиной)
  error?: string | null
  children?: ReactNode       // блок свойств (.props) — входит в зону шапки, чтобы корзина
                             // села у её НИЖНЕЙ границы (§5: слоты разнесены по вертикали)
}) {
  return (
    <>
      {/* Зона шапки = заголовок+мета+свойства. relative — чтобы корзина легла в её
          нижний правый угол, а не в плотную колонку под верхними контролами (§5). */}
      <div className="fhz">
        <div className="form-head">
          <div className="fh-main">
            <div className="fh-name">{code}</div>
            <div className="fh-meta">{meta}</div>
          </div>
          <div className="fh-right">
            {fixed ? (
              // Зафиксирован: единственная степень свободы — расфиксировать. Корзины нет
              // (движок всё равно не даст удалить запертое — «сперва расфиксируйте»).
              onUnfix && (
                <button className="fh-ctl" title="Снять фиксацию документа" onClick={onUnfix}>
                  <span className="lbl">Расфиксировать</span><span className="ci ci-unlock" />
                </button>
              )
            ) : (
              <>
                {/* Режим показа: подпись/иконка говорят, КУДА ведёт клик (§5). */}
                {onToggleLock && (
                  <button className="fh-ctl" onClick={onToggleLock}
                    title={unlocked ? 'Просмотр — закрыть форму (чистый текст)'
                                    : 'Редактировать — открыть форму для правки'}>
                    <span className="lbl">{unlocked ? 'Просмотр' : 'Редактировать'}</span>
                    <span className={'ci ' + (unlocked ? 'ci-eye' : 'ci-edit')} />
                  </button>
                )}
                {onFixate && (
                  <button className="fh-ctl" onClick={onFixate}
                    title={fixateTitle ?? 'Зафиксировать документ'}>
                    <span className="lbl">Зафиксировать</span><span className="ci ci-lock" />
                  </button>
                )}
              </>
            )}
          </div>
        </div>
        {children}
        {/* Корзина — у нижней границы зоны (низ-право), только в режиме ПРАВКИ
            (§5, Ф9): просмотр чист и от случайного удаления защищён структурно. */}
        {!fixed && unlocked && onDelete && (
          <button className="fh-ctl fh-del" title="Удалить документ" onClick={onDelete}>
            <span className="lbl">Удалить</span><span className="ci ci-trash" />
          </button>
        )}
        {/* Скачать (xlsx) — тот же слот, но у ЗАФИКСИРОВАННОГО: корзины там нет, слоты
            не сталкиваются. Зелёная подсветка намекает на выгрузку. */}
        {fixed && download && (
          <a className="fh-ctl fh-download" href={download.href} download
             title={download.title ?? 'Скачать'}>
            <span className="lbl">Скачать</span><span className="ci ci-file" />
          </a>
        )}
      </div>
      {error && <div className="fh-error">ошибка: {error}</div>}
    </>
  )
}
