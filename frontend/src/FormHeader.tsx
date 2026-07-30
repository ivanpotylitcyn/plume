// Единый заголовок формы (UI_GUIDE §4) + замок формы и чип фиксации (§5).
// «Название первое»: литературное имя (Inter 500) сверху, мета-строка (mono, dim)
// снизу; справа — индикатор сохранения + замок формы, ИЛИ чип фиксации.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type Authored, type UserRow, type ProjectRow } from './api'
import { Field, TextField } from './FormField'
import { Dropdown } from './Dropdown'
import { AnchoredMenu } from './AnchoredMenu'

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

// Единая оболочка формы ордера (Ф2i): свод боилерплейта, одинакового у всех шести
// detail-вьюх «Ордера» — загрузка формы по id, обёртка мутации `run` (ответ сервера
// → в стейт + обновить фид), дружелюбное удаление `del` (confirm + guard бэка), замок
// формы и строка ошибки. Специфика вида (тело формы, выражение `fixed`, side-load
// пикеров) остаётся во вьюхе; сюда она входит колбэками `cb`.
export function useOrderForm<C extends { id: number }>(
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

export function AuthorField({ userId, userName, locked, busy, onChange }: {
  userId: number; userName: string; locked: boolean; busy?: boolean
  onChange: (id: number) => void
}) {
  const [users, setUsers] = useState<UserRow[]>([])
  useEffect(() => { loadUsers().then(setUsers) }, [])
  const known = users.some(u => u.id === userId)
  // В просмотре — имя автора текстом (§5, Ф12d): подпись видна и без справочника,
  // поэтому дожидаться загрузки списка не нужно.
  return (
    <Field label="Автор" locked={locked} view={userName}>
      {/* Автор — единственное поле выбора, где показываем НЕ код: у пользователя его
          нет, идентичность человека — имя. */}
      <Dropdown options={[...(!known && userId ? [{ value: userId, label: userName }] : []),
        ...users.map(u => ({ value: u.id, label: u.full_name }))]}
        value={userId || ''} disabled={busy} onPick={v => onChange(Number(v))} />
    </Field>
  )
}

// Единый якорный <select> для шапки формы (Ф2k #A): подписанный выпадающий список,
// который держит текущее значение видимым, даже если его нет в опциях (подпись не
// пропадёт под замком). Опции — {id,label}; `onChange` срабатывает только на реальном
// изменённом выборе. Движок сам откажет в смене якоря у непустого ордера — форма
// ловит отказ строкой ошибки (как у автора).
// Ф12e: `id` может быть пустым — якорь (прибор-цель комплектации) выбирают в форме,
// он обязателен к фиксации, а не к рождению.
// Ф17: `onClear` — якорь можно СНЯТЬ (закупка-план у заказа стала опциональной).
// Пустой выбор живёт первой строкой меню и подписан `placeholder` («— не выбрана —»),
// как в пикере: очистка — такой же выбор, а не отдельная кнопка сбоку.
export function AnchorSelect({ label, id, currentLabel, options, locked, busy, view,
  placeholder, onChange, onClear }: {
  label: string; id: number | null; currentLabel: string
  options: { id: number; label: string }[]
  locked: boolean; busy?: boolean
  view?: ReactNode              // просмотр иначе, чем текстом (ссылка на проект)
  placeholder?: string          // подпись пустого значения (и пустого поля)
  onChange: (id: number) => void
  onClear?: () => void          // задан → якорь снимается пустым пунктом меню
}) {
  const known = options.some(o => o.id === id)
  const empty = onClear ? [{ value: '' as const, label: placeholder ?? '—' }] : []
  return (
    <Field label={label} locked={locked} view={view ?? (id ? currentLabel : '')}>
      <Dropdown options={[...empty,
        ...(!known && id ? [{ value: id, label: currentLabel }] : []),
        ...options.map(o => ({ value: o.id, label: o.label }))]}
        value={id || ''} disabled={busy} placeholder={placeholder}
        onPick={v => (v === '' ? onClear?.() : onChange(Number(v)))} />
    </Field>
  )
}

// Проект-якорь шапки (Ф2k #A): единый пикер проекта на всех ордерах/заказе. Список
// проектов кэшируем один раз на приложение (как справочник авторов) — редко меняется.
let _projectsCache: Promise<ProjectRow[]> | null = null
function loadProjects() { return (_projectsCache ??= api.projects()) }

export function ProjectField({ projectId, projectLabel, locked, busy, onChange, onOpen }: {
  projectId: number; projectLabel: string; locked: boolean; busy?: boolean
  onChange: (id: number) => void
  onOpen?: (id: number) => void   // задан → под замком поле = ссылка на проект
}) {
  const [projects, setProjects] = useState<ProjectRow[]>([])
  useEffect(() => { loadProjects().then(setProjects) }, [])
  // Под замком показываем ОДИН код и делаем его кликабельным (§8: кликабельно то, что
  // названо): расшифровка проекта в форме документа — шум, за ней идут на форму проекта.
  // В списке выбора — тоже только код (решение Ивана 2026-07-29): описание чаще
  // дублирует код, а склейка «КОД — описание» распирала и поле, и меню.
  return (
    <AnchorSelect label="Проект" id={projectId} currentLabel={projectLabel}
      options={projects.map(p => ({ id: p.id, label: p.code }))}
      locked={locked} busy={busy} onChange={onChange}
      view={projectId && onOpen
        ? <a className="link" onClick={() => onOpen(projectId)}>{projectLabel}</a>
        : projectLabel} />
  )
}

// Общие поля шапки ордера (волна 19, Ф12c). Все семь видов держат одну и ту же
// пятёрку — `code` + `description` (§13.4), проект-якорь, номер, дата, автор — и
// раньше каждая вьюха выписывала её руками (пять копий, разъезжавшихся по ширинам и
// подписям).
//
// **Два слота, не один** (волна 19, Ф17; канон §13.4a). Порядок полей формы = порядок
// полей модели: идентичность → замок → якори → внешние атрибуты → автор → специфика
// вида. Специфика расщепляется надвое ровно так, как расщеплена в модели: якори вида
// (`purchase`+`contractor` поставки, `contractor` передачи) идут в слот `anchors`
// СРАЗУ ЗА проектом, а атрибуты вида (`target_item`/`qty` комплектации, `reason`
// списания) остаются хвостовым `children` после автора. Один слот «всё после общих
// полей» этот порядок выразить не мог.
export interface OrderHead extends Authored {
  id: number; code: string | null; description: string
  number?: string; date: string | null
  project_id: number; project_code: string
}
// Общий знаменатель PATCH-тел всех видов ордера (у каждого вида шире, но эти поля
// принимают все — кроме `number` у комплектации, которая его и не рисует).
export type OrderHeadPatch = Partial<{
  number: string; date: string; user_id: number; project_id: number
  code: string | null; description: string
}>

export function OrderFields({ c, locked, busy, patch, numberLabel, openProject, anchors,
  children }: {
  c: OrderHead
  locked: boolean
  busy: boolean
  patch: (b: OrderHeadPatch) => void
  numberLabel?: string          // «№ поставки» / «№ акта» / «№» — у комплектации номера нет
  openProject?: (id: number) => void
  anchors?: ReactNode           // якори вида — сразу за проектом (§13.4a)
  children?: ReactNode          // атрибуты вида — хвостом, после автора
}) {
  return (
    <>
      <TextField label="Код" value={c.code ?? ''} locked={locked} busy={busy}
        onCommit={v => patch({ code: v })} />
      {/* Единственное длинное поле шапки (§13.3). */}
      <TextField label="Описание" wide value={c.description} locked={locked} busy={busy}
        onCommit={v => patch({ description: v })} />
      {/* Проект — ВЕРХНИЙ якорь всего закупочного контура (§13.4a): связи сущности
          важнее её атрибутов, и порядок один на все три уровня. */}
      <ProjectField projectId={c.project_id} projectLabel={c.project_code}
        locked={locked} busy={busy} onOpen={openProject}
        onChange={id => patch({ project_id: id })} />
      {anchors}
      {numberLabel &&
        <TextField label={numberLabel} value={c.number ?? ''} locked={locked} busy={busy}
          onCommit={v => patch({ number: v })} validate={v => v.trim().length > 0} />}
      <TextField label="Дата" type="date" value={c.date ?? ''} locked={locked} busy={busy}
        onCommit={v => patch({ date: v })} />
      <AuthorField userId={c.user_id} userName={c.user_name} locked={locked} busy={busy}
        onChange={id => patch({ user_id: id })} />
      {children}
    </>
  )
}

// Команды формы (§5): единый набор кнопок шапки — режим показа, фиксация, доп.
// действие вида, корзина и «Скачать». Вынесены отдельно (волна 19, Ф12), чтобы
// `FormHeader` (старый лэйаут) и `FormShell` (канон §13) рисовали ОДНИ И ТЕ ЖЕ
// команды, а не две расходящиеся копии: пока формы переезжают на канон, обе
// разметки живут рядом.
export interface FormCommandProps {
  unlocked?: boolean
  onToggleLock?: () => void
  fixed?: boolean
  onFixate?: () => void      // зафиксировать документ (draft→locked); только у расфиксированного
  fixateTitle?: string       // подсказка-последствие («…родить прибор») — слово в кнопке едино
  onUnfix?: () => void       // расфиксировать документ (locked→draft)
  onDelete?: () => void      // удалить документ (только расфиксированный; под замком корзины нет)
  download?: Download        // скачать (xlsx) — нижний слот шапки; см. `Download`

  actions?: FormAction[]     // доп. действия формы в правой колонке («Переоценить»,
                             // «Загрузить») — чтобы кнопки не болтались между шапкой и телом
}

export interface FormAction {
  onClick: () => void; label: string; icon: string; title?: string; disabled?: boolean
}

// «Скачать» (2026-07-30). Целей у выгрузки бывает одна (бланк закупки — `href`) или
// несколько (изделие: «Только состав» / «Все вкладки» — `options`). Во втором случае
// кнопка та же, но открывает меню выбора. ВИДИМОСТЬ решает вызывающая форма: у
// закупки бланк даём только у зафиксированной (документ наружу), у изделия — всегда.
export interface Download {
  title?: string
  href?: string                                     // одна цель — прямая ссылка
  // Выбор цели — меню; `icon` берём у ВКЛАДКИ, которую пункт выгружает (§2: одна
  // сущность носит один знак, где бы ни встретилась).
  options?: { label: string; href: string; title?: string; icon?: string }[]
}

// Верхние команды: вертикальная колонка справа-сверху. `children` — нижний слот
// колонки (корзина/«Скачать»), который в каноне §13.3 прижимается к её низу.
export function FormCommands({ unlocked, onToggleLock, fixed, onFixate, fixateTitle,
  onUnfix, actions, children }: FormCommandProps & { children?: ReactNode }) {
  return (
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
      {/* Доп. действия — ПОД контролами замка/фиксации (низ правой колонки). */}
      {actions?.map(a => (
        <button key={a.label} className="fh-ctl" onClick={a.onClick} disabled={a.disabled}
          title={a.title ?? a.label}>
          <span className="lbl">{a.label}</span>
          <span className={'ci ' + a.icon} />
        </button>
      ))}
      {children}
    </div>
  )
}

// «Скачать» с несколькими целями (2026-07-30): та же кнопка, но открывает меню
// выбора — знак строки берём у пикера (`.typeahead-item`), слой у `AnchoredMenu`
// (портал в body: панель табов и прокрутка страницы режут обычный `absolute`).
// «Отмена» — своя строка, а не только Esc/клик мимо: выбор из трёх пунктов человек
// закрывает тем же движением, каким открыл.
function DownloadMenu({ download }: { download: Download }) {
  const [open, setOpen] = useState(false)
  const btn = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)

  // Клик мимо и Esc закрывают меню. Меню в портале, поэтому «мимо» = ни кнопка, ни
  // сам слой (иначе первый же mousedown по пункту закрыл бы его до перехода по ссылке).
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      const t = e.target as Node
      if (!btn.current?.contains(t) && !menu.current?.contains(t)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', away)
    window.addEventListener('keydown', esc)
    return () => {
      window.removeEventListener('mousedown', away)
      window.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <>
      <button ref={btn} className="fh-ctl fh-download" title={download.title ?? 'Скачать'}
        onClick={() => setOpen(v => !v)}>
        <span className="lbl">Скачать</span><span className="ci ci-file" />
      </button>
      {open &&
        <AnchoredMenu anchor={btn} boxRef={menu} className="typeahead-menu dl-menu">
          {download.options!.map(o => (
            <a key={o.label} className="typeahead-item" href={o.href} download
              title={o.title} onClick={() => setOpen(false)}>
              <span className={'ci ci-' + (o.icon ?? 'file')} /><span>{o.label}</span>
            </a>
          ))}
          <div className="typeahead-item" onClick={() => setOpen(false)}>
            <span className="ci ci-close" /><span>Отмена</span>
          </div>
        </AnchoredMenu>}
    </>
  )
}

// Нижний слот шапки (§5): «Скачать» и корзина — у нижней границы зоны, справа.
// Корзина только в режиме ПРАВКИ: просмотр чист, случайное удаление структурно
// невозможно. Выгрузка от неё не зависит и стоит НАД ней (корзина остаётся самой
// нижней командой формы); показывать ли «Скачать» вообще — решает форма тем, даёт
// она `download` или нет (у закупки бланк только у зафиксированной, у изделия —
// всегда: состав нужен и до фиксации, а покупной компонент не фиксируется вовсе).
export function FormCornerCommand({ fixed, unlocked, onDelete, download }: FormCommandProps) {
  return (
    <>
      {download && (download.options
        ? <DownloadMenu download={download} />
        : <a className="fh-ctl fh-download" href={download.href} download
             title={download.title ?? 'Скачать'}>
            <span className="lbl">Скачать</span><span className="ci ci-file" />
          </a>)}
      {!fixed && unlocked && onDelete &&
        <button className="fh-ctl fh-del" title="Удалить документ" onClick={onDelete}>
          <span className="lbl">Удалить</span><span className="ci ci-trash" />
        </button>}
    </>
  )
}

// Шапка формы (§5, Ф9): контролы — вертикальной колонкой справа, подпись слева от
// иконки, глиф = НАЗНАЧЕНИЕ (куда попадёшь), не состояние. Иконки — Codicons (§2).
// Индикаторы «✓ сохранено»/«● редактируется» сняты (автосейв → «сохранено» всегда,
// ничего не различало). Две оси не путаем: замок ФОРМЫ (Редактировать/Просмотр) —
// личный, режим показа; фиксация ДОКУМЕНТА (Зафиксировать/Расфиксировать) — в данных.
// У зафиксированного степень свободы ровно одна — расфиксировать; корзины под замком нет.
export function FormHeader({ code, meta, error, children, ...cmd }: FormCommandProps & {
  code: ReactNode           // первичная идентичность в H1 (волна 19, Ф11: бывш. `name`)
  meta: ReactNode
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
          <FormCommands {...cmd} />
        </div>
        {children}
        <FormCornerCommand {...cmd} />
      </div>
      {error && <div className="fh-error">ошибка: {error}</div>}
    </>
  )
}
