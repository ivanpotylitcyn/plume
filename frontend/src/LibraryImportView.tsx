// Синхронизация справочника Item с внешней библиотекой компонентов Altium.
// Путь Б: форма в аппе. Мульти-файл CSV → серверный диф (изделия не трогает) → табы со
// статусами и построчными галочками → применение подтверждённого. Полная сверка:
// добавить новые / обновить изменившиеся / пометить библиотечными / удалить пропавшие;
// сироты и повторы — информационно (действий нет). Диф пересчитывается на сервере при
// применении — клиентские значения не в доверии, галочки шлём только как список кодов.
//
// **Волна 22: экран переехал на канон §13 (FormShell).** До неё это был последний
// кастомный скелет продукта (аудит-1, Б2б-3): свой `h1.title`, свой `.subtitle`, шесть
// статусов одной простынёй и `<input type=file>` посреди разметки. Переезд решил три
// вещи разом:
//
// 1. **Полей у мастера нет — и это правда о нём.** Степеней свободы у экрана ноль:
//    менять нечего, есть что ЗАПУСТИТЬ. Поэтому зону полей шапки занимает инструкция
//    (`.fs-note`), а всё исполнение — команды справа. Тот же приём, что с `username`
//    в форме аккаунта: чего форма не правит, то полем не рисуется.
// 2. **Фиксации и корзины нет.** Сверка — не документ; фиксировать и удалять нечего.
//    Замок формы остаётся — личный, и у него ровно одна работа: под открытым замком
//    правятся описания классов в табе «Категории».
// 3. **Табов до загрузки нет вовсе** (решение Ивана 2026-07-31): пустая полоса табов
//    обещала бы содержимое, которого ещё нет. Файлы загружены → появляются мета и
//    восемь табов, последний из которых показывает сами загруженные файлы.
//
// Действенные статусы разведены по ЧЕТЫРЁМ табам (Новые / Изменения / Пометки /
// Пропавшие), а не свалены в один список со статусом-колонкой: массовая галочка тогда
// бьёт ровно по своему блоку, а необратимое удаление стоит отдельной вкладкой, а не
// вперемешку с безопасным.
import { useEffect, useMemo, useState } from 'react'
import { api, type Category, type LibraryDiff, type LibraryDiffRow, type LibraryStatus,
  type LibraryApplySummary } from './api'
import { FormShell, type FormTab } from './FormShell'
import { useFormLock } from './FormHeader'
import { CommitInput } from './CommitInput'
import { count } from './status'

// Один словарь статуса на всё: подпись таба, глиф, цвет полосы строки, заголовок
// колонки-объяснения, текст пустого таба и склонение для меты. Цвета из канона:
// зелёный = создать/пометить, оранжевый = обновить, красный = удалить; у неактивных
// (повторы, сироты) полосы нет — действия к ним не прилагается.
const ST: Record<LibraryStatus, {
  tab: string; icon: string; col: string; empty: string
  actionable: boolean; word: [string, string, string]
}> = {
  new: {
    tab: 'Новые', icon: 'add', col: 'Что заведём',
    empty: 'Новых изделий в загруженной библиотеке нет.', actionable: true,
    word: ['новое', 'новых', 'новых'],
  },
  changed: {
    tab: 'Изменения', icon: 'diff', col: 'Что изменится',
    empty: 'Изменившихся изделий нет — описания совпадают с библиотекой.',
    actionable: true, word: ['изменение', 'изменения', 'изменений'],
  },
  mark: {
    tab: 'Пометки', icon: 'check', col: 'Почему',
    empty: 'Непомеченных совпадений нет — всё библиотечное уже помечено.',
    actionable: true, word: ['пометка', 'пометки', 'пометок'],
  },
  gone: {
    tab: 'Пропавшие', icon: 'trash', col: 'Что удалим',
    empty: 'Из загруженных классов ничего не пропало.', actionable: true,
    word: ['пропавшее', 'пропавших', 'пропавших'],
  },
  same: {
    tab: 'Повторы', icon: 'pass', col: 'В справочнике',
    empty: 'Совпадений нет.', actionable: false,
    word: ['повтор', 'повтора', 'повторов'],
  },
  orphan: {
    tab: 'Сироты', icon: 'question', col: 'В справочнике',
    empty: 'Сирот нет — всё используемое есть в библиотеке.', actionable: false,
    word: ['сирота', 'сироты', 'сирот'],
  },
}
// Порядок табов = порядок работы: сперва то, что заводим и правим, потом необратимое,
// потом справочное. Мета читает счётчики в этом же порядке (§13.6).
const ORDER: LibraryStatus[] = ['new', 'changed', 'mark', 'gone', 'same', 'orphan']
// Предотметка: добавления, обновления и пометки безопасны — под галочкой сразу;
// удаления (`gone`, необратимо) отмечает рука. Полная сверка с защитой.
const PRESELECT = new Set<LibraryStatus>(['new', 'changed', 'mark'])
const FIELD_RU: Record<string, string> = {
  description: 'Описание', category: 'Категория', temperature: 'Температура' }

// Категория = стем имени файла (зеркало `_category_code_from_filename` движка):
// таб «Файлы» подписывает каждый файл его классом ещё до ответа сервера.
function categoryOf(filename: string): string {
  const base = filename.split(/[\\/]/).pop() ?? ''
  return base.replace(/\.[^.]*$/, '').trim().toLowerCase()
}

function humanSize(n: number): string {
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} КБ`
  return `${(n / (1024 * 1024)).toFixed(1)} МБ`
}

export function LibraryImportView({ onApplied, openItem }:
  { onApplied: () => void; openItem: (id: number) => void }) {
  const [files, setFiles] = useState<File[]>([])
  const [diff, setDiff] = useState<LibraryDiff | null>(null)
  const [cats, setCats] = useState<Category[]>([])
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set())
  const [summary, setSummary] = useState<LibraryApplySummary | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Замок формы — личный и здесь один на всю форму: под открытым правятся описания
  // классов в табе «Категории». `id` = 0 — сущности, на смену которой сбрасывать
  // режим, у экрана нет.
  const { unlocked, toggle } = useFormLock(0)

  // Справочник классов держим полным (не только загруженными): таб «Категории»
  // показывает ВСЕ категории БД, а участие в текущей сверке — глифом.
  useEffect(() => { api.categories().then(setCats).catch(e => setErr(String(e))) }, [])

  // Один путь освежения на «Сверить» и на автосверку после применения: диф теми же
  // файлами + перечитанный справочник классов (сверка заводит недостающие).
  const refresh = (next: File[]) => api.libraryDiff(next).then(d => {
    setDiff(d)
    setConfirmed(new Set(d.rows.filter(r => PRESELECT.has(r.status)).map(r => r.code)))
    return api.categories().then(setCats)
  })

  const run = (p: Promise<unknown>) => {
    setBusy(true); setErr(null)
    p.catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Выбор файлов — КОМАНДА шапки, а не поле в разметке (§13.8, как «Загрузить» у
  // вложений): системный диалог открываем одноразовым скрытым input'ом. Загрузка и
  // сверка — одно движение: выбрал файлы → сразу видишь расхождения.
  const pick = () => {
    const el = document.createElement('input')
    el.type = 'file'
    el.multiple = true
    el.accept = '.csv,text/csv'
    el.onchange = () => {
      const next = Array.from(el.files ?? [])
      if (next.length === 0) return
      setFiles(next); setDiff(null); setSummary(null); setConfirmed(new Set())
      run(refresh(next))
    }
    el.click()
  }

  // Применили → тут же пересверяем ТЕМИ ЖЕ файлами: табы показывают свежее состояние
  // (применённое уезжает в «Повторы»), а не пустой список при выбранных файлах.
  // Лишняя загрузка файлов на сервер — цена честной картинки, экран внутренний.
  const apply = () => {
    if (!diff || confirmed.size === 0) return
    run(api.libraryApply(files, [...confirmed])
      .then(s => { setSummary(s); onApplied(); return refresh(files) }))
  }

  const toggleRow = (code: string) => setConfirmed(prev => {
    const next = new Set(prev)
    if (next.has(code)) next.delete(code); else next.add(code)
    return next
  })
  // Массовая галочка бьёт ровно по своему табу: набор строк однороден, и «отметить
  // все» больше не означает «в том числе удаления с соседнего блока».
  const bulk = (rows: LibraryDiffRow[], on: boolean) => setConfirmed(prev => {
    const next = new Set(prev)
    for (const r of rows) { if (on) next.add(r.code); else next.delete(r.code) }
    return next
  })

  // Строки, разложенные по статусу — по ним же строятся и табы, и счётчики меты.
  const byStatus = useMemo(() => {
    const m = {} as Record<LibraryStatus, LibraryDiffRow[]>
    for (const s of ORDER) m[s] = []
    diff?.rows.forEach(r => m[r.status].push(r))
    return m
  }, [diff])
  // Классы, участвовавшие в этой сверке (нашлись среди загруженных файлов).
  const synced = useMemo(() => new Set(diff?.categories ?? []), [diff])

  const locked = !unlocked
  const loaded = files.length > 0

  const tabs: FormTab[] = loaded ? [
    ...ORDER.map(s => ({
      key: s, label: ST[s].tab, icon: ST[s].icon,
      content: <DiffTable status={s} rows={byStatus[s]} confirmed={confirmed}
        busy={busy} onToggle={toggleRow} onBulk={bulk} openItem={openItem} />,
    })),
    { key: 'categories', label: 'Категории', icon: 'symbol-class',
      content: <CategoryTable cats={cats} synced={synced} locked={locked} busy={busy}
        onCommit={(id, v) => run(api.updateCategory(id, v)
          .then(next => setCats(cs => cs.map(c => (c.id === next.id ? next : c)))))} /> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <FileTable files={files} diff={diff} /> },
  ] : []

  return (
    <FormShell
      id={0} code="Синхронизация с библиотекой" entity="синхронизацию"
      locked={locked} error={err}
      unlocked={unlocked} onToggleLock={toggle}
      actions={[
        { onClick: pick, label: 'Загрузить', icon: 'ci-new-file', disabled: busy,
          title: 'Выбрать CSV-таблицы библиотеки (мульти-файл) — сверка пойдёт сразу' },
        { onClick: () => run(refresh(files)), label: 'Сверить', icon: 'ci-sync',
          disabled: busy || !loaded,
          title: 'Пересверить теми же файлами (справочник мог измениться)' },
        { onClick: apply, label: 'Применить', icon: 'ci-check',
          disabled: busy || confirmed.size === 0,
          title: `Применить подтверждённое (${confirmed.size})` },
      ]}
      // Зона полей = инструкция: степеней свободы у мастера нет (см. шапку файла).
      fields={
        <div className="fs-note">
          <p>Библиотека компонентов Altium — источник правды по покупным изделиям.</p>
          <p>«Загрузить» берёт CSV-таблицы библиотеки (мульти-файл, CP1251). Ключ
            сверки — «Design Item Id», класс изделия — имя файла.</p>
          <p>Расхождения раскладываются по вкладкам: отметьте строки и нажмите
            «Применить». Пропавшие ищутся только в загруженных классах — тот, чей файл
            не грузили, не пострадает.</p>
        </div>}
      extra={summary &&
        <div className="panel fs-applied">
          <span className="ci sg ci-check sg-ok" />
          Применено: создано {summary.created} · обновлено {summary.updated} ·
          помечено {summary.marked} · удалено {summary.deleted}
        </div>}
      meta={loaded && <>
        {ORDER.map(s => count(byStatus[s].length, ...ST[s].word)).join(' · ')}
        {' · '}{count(cats.length, 'категория', 'категории', 'категорий')}
        {' · '}{count(files.length, 'файл', 'файла', 'файлов')}
      </>}
      tabs={tabs}
    />
  )
}

// Тело таба одного статуса: массовая галочка сверху (только у действенных), затем
// грид «код изделия — что произойдёт». Колонки статуса НЕТ — статус назван вкладкой,
// повторять его в каждой строке значило бы печатать одно слово N раз.
function DiffTable({ status, rows, confirmed, busy, onToggle, onBulk, openItem }: {
  status: LibraryStatus
  rows: LibraryDiffRow[]
  confirmed: Set<string>
  busy: boolean
  onToggle: (code: string) => void
  onBulk: (rows: LibraryDiffRow[], on: boolean) => void
  openItem: (id: number) => void
}) {
  const m = ST[status]
  if (rows.length === 0) return <div className="tab-empty">{m.empty}</div>
  const allOn = rows.every(r => confirmed.has(r.code))
  return (
    <>
      {m.actionable &&
        <div className="kit-actions">
          <button className="btn sm" disabled={busy} onClick={() => onBulk(rows, !allOn)}>
            {allOn ? 'снять все' : 'отметить все'}
          </button>
          <span className="lbl">
            отмечено {rows.filter(r => confirmed.has(r.code)).length} из {rows.length}
            {status === 'gone' && ' · удаление необратимо, поэтому по умолчанию не отмечено'}
          </span>
        </div>}
      <table className="grid lib-diff">
        <thead><tr>
          {m.actionable && <th className="pick" />}
          <th className="c-key">Изделие</th>
          <th className="c-desc">{m.col}</th>
        </tr></thead>
        <tbody>{rows.map(r => (
          <tr key={r.code} className="row">
            {m.actionable &&
              <td className="pick">
                <input type="checkbox" checked={confirmed.has(r.code)} disabled={busy}
                  onChange={() => onToggle(r.code)} />
              </td>}
            {/* Код изделия — идентичность (`.code`): у уже заведённого он ссылка
                со своим цветом, у нового — просто код, и приглушать его нельзя. */}
            <td className="c-key">{r.item_id
              ? <a className="link" onClick={() => openItem(r.item_id!)}>{r.code}</a>
              : r.code}</td>
            <td className="c-desc"><RowDetail row={r} /></td>
          </tr>))}</tbody>
      </table>
    </>
  )
}

// Правая колонка: для нового — что заводим; для изменившегося — поля old→new;
// для пометки — вердикт; для пропавшего/сироты/повтора — что в БД сейчас.
function RowDetail({ row }: { row: LibraryDiffRow }) {
  if (row.status === 'new' && row.incoming)
    return <>{row.incoming.description}
      <span className="kind-chip"> · {row.incoming.category}
        {row.incoming.temperature ? ` · ${row.incoming.temperature}` : ''}</span></>
  if (row.status === 'changed' && row.changes)
    return <>{Object.entries(row.changes).map(([f, ch]) => (
      <div key={f}>{FIELD_RU[f] || f}: <s>{ch!.old || '—'}</s> → <b>{ch!.new || '—'}</b></div>
    ))}</>
  if (row.status === 'mark')
    return <>совпадает с библиотекой → <b>пометим библиотечным</b></>
  if (row.current)
    return <>{row.current.description}
      <span className="kind-chip"> · {row.current.category}
        {row.status === 'orphan' ? ' · используется, удалить нельзя' : ''}</span></>
  return <>—</>
}

// Таб «Категории» — справочник классов ЦЕЛИКОМ, а не только загруженных: класс живёт
// дольше одной сверки, и прятать соседей незачем. Глиф — участие в ЭТОЙ сверке
// (зелёный синк = файл класса был среди загруженных). Описание — единственная степень
// свободы, и правится оно под открытым замком формы, как поля любой другой формы (§5).
// До волны 22 задать его можно было только в админке.
function CategoryTable({ cats, synced, locked, busy, onCommit }: {
  cats: Category[]
  synced: Set<string>
  locked: boolean
  busy: boolean
  onCommit: (id: number, description: string) => void
}) {
  if (cats.length === 0)
    return <div className="tab-empty">Классов пока нет — они заводятся сверкой.</div>
  return (
    <>
      <div className="hint-row">
        {locked
          ? 'Описание класса правится под открытым замком — «Редактировать» в шапке.'
          : 'Код класса — ключ синхронизации (имя CSV-файла), он не правится.'}
      </div>
      <table className="grid">
        <thead><tr><th className="gl" /><th className="c-key">Код</th>
          <th className="c-desc">Описание</th></tr></thead>
        <tbody>{cats.map(c => (
          <tr key={c.id} className="row">
            <td className="gl">
              {synced.has(c.code)
                ? <span className="ci sg ci-sync sg-ok"
                    title="класс участвовал в этой сверке — его файл был загружен" />
                : <span className="ci sg ci-sync-ignored sg-none"
                    title="в этой сверке не участвовал — файла класса не загружали" />}
            </td>
            <td className="c-key">{c.code}</td>
            <td className="c-desc">{locked
              ? (c.description || '—')
              : <CommitInput value={c.description} disabled={busy}
                  onCommit={v => onCommit(c.id, v)} />}</td>
          </tr>))}</tbody>
      </table>
    </>
  )
}

// Таб «Файлы» — что именно сейчас загружено (последняя вкладка, как у любой формы).
// Строк считаем по классу файла: у каждой строки дифа с `incoming` класс = стем имени
// файла, из которого она пришла.
function FileTable({ files, diff }: { files: File[]; diff: LibraryDiff | null }) {
  return (
    <table className="grid">
      <thead><tr><th className="gl" /><th className="c-key">Файл</th>
        <th className="c-desc">Класс</th>
        <th className="c-fit num">Строк</th><th className="c-fit num">Размер</th></tr></thead>
      <tbody>{files.map(f => {
        const cat = categoryOf(f.name)
        const rows = diff?.rows.filter(r => r.incoming?.category === cat).length
        return (
          <tr key={f.name} className="row">
            <td className="gl"><span className="ci sg ci-file-text sg-ok" /></td>
            <td className="c-key">{f.name}</td>
            <td className="c-desc">{cat}</td>
            <td className="c-fit num">{rows ?? '—'}</td>
            <td className="c-fit num">{humanSize(f.size)}</td>
          </tr>)
      })}</tbody>
    </table>
  )
}
