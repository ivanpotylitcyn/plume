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
// 2. **Фиксации, корзины и замка нет.** Сверка — не документ; фиксировать и удалять
//    нечего. Замок формы жил ради правки описаний в табе «Категории» — таб снят
//    2026-10-15 вместе с классами по имени файла, и замку стало нечего запирать.
// 3. **Табов до загрузки нет вовсе** (решение Ивана 2026-07-31): пустая полоса табов
//    обещала бы содержимое, которого ещё нет. Файлы загружены → появляются мета и
//    семь табов, последний из которых показывает сами загруженные файлы.
//
// **2026-10-15: библиотека грузится ЦЕЛИКОМ.** Класс по имени файла упразднён — всё
// библиотечное получает категорию «Электронный компонент», а «пропавшие» ищутся среди
// всех библиотечных изделий, а не в классах загруженных файлов.
//
// Действенные статусы разведены по ЧЕТЫРЁМ табам (Новые / Изменения / Пометки /
// Пропавшие), а не свалены в один список со статусом-колонкой: массовая галочка тогда
// бьёт ровно по своему блоку, а необратимое удаление стоит отдельной вкладкой, а не
// вперемешку с безопасным.
import { useMemo, useState } from 'react'
import { api, type LibraryDiff, type LibraryDiffRow, type LibraryStatus,
  type LibraryApplySummary } from './api'
import { FormShell, type FormTab } from './FormShell'
import { count } from './status'
import { EntityLink } from './EntityLink'

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
    empty: 'Из библиотеки ничего не пропало.', actionable: true,
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

function humanSize(n: number): string {
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} КБ`
  return `${(n / (1024 * 1024)).toFixed(1)} МБ`
}

export function LibraryImportView({ onApplied, openItem }:
  { onApplied: () => void; openItem: (id: number) => void }) {
  const [files, setFiles] = useState<File[]>([])
  const [diff, setDiff] = useState<LibraryDiff | null>(null)
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set())
  const [summary, setSummary] = useState<LibraryApplySummary | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Один путь освежения на «Сверить» и на автосверку после применения: диф теми же
  // файлами.
  const refresh = (next: File[]) => api.libraryDiff(next).then(d => {
    setDiff(d)
    setConfirmed(new Set(d.rows.filter(r => PRESELECT.has(r.status)).map(r => r.code)))
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
  const loaded = files.length > 0

  const tabs: FormTab[] = loaded ? [
    ...ORDER.map(s => ({
      key: s, label: ST[s].tab, icon: ST[s].icon,
      content: <DiffTable status={s} rows={byStatus[s]} confirmed={confirmed}
        busy={busy} onToggle={toggleRow} onBulk={bulk} openItem={openItem} />,
    })),
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <FileTable files={files} /> },
  ] : []

  return (
    <FormShell
      id={0} code="Синхронизация с библиотекой" entity="синхронизацию"
      locked={false} error={err}
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
          <p>«Загрузить» берёт CSV-таблицы библиотеки (мульти-файл, CP1251) — <b>всю
            библиотеку целиком</b>. Ключ сверки — «Design Item Id», категория всего
            загруженного — «Электронный компонент».</p>
          <p>Расхождения раскладываются по вкладкам: отметьте строки и нажмите
            «Применить». Библиотечное, чего нет ни в одном файле, попадает в
            «Пропавшие» — поэтому грузить нужно все таблицы разом.</p>
        </div>}
      extra={summary &&
        <div className="panel fs-applied">
          <span className="ci sg ci-check sg-ok" />
          Применено: создано {summary.created} · обновлено {summary.updated} ·
          помечено {summary.marked} · удалено {summary.deleted}
        </div>}
      meta={loaded && <>
        {ORDER.map(s => count(byStatus[s].length, ...ST[s].word)).join(' · ')}
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
          <th className="rn">№</th>
          <th className="c-key">Изделие</th>
          <th className="c-desc">{m.col}</th>
        </tr></thead>
        <tbody>{rows.map((r, i) => (
          <tr key={r.code} className="row">
            {m.actionable &&
              <td className="pick">
                <input type="checkbox" checked={confirmed.has(r.code)} disabled={busy}
                  onChange={() => onToggle(r.code)} />
              </td>}
            <td className="rn">{i + 1}</td>
            {/* Код изделия — идентичность (`.code`): у уже заведённого он ссылка
                со своим цветом, у нового — просто код, и приглушать его нельзя. */}
            <td className="c-key">{r.item_id
              ? <EntityLink kind="item" id={r.item_id} open={openItem}>{r.code}</EntityLink>
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

// Таб «Файлы» — что именно сейчас загружено (последняя вкладка, как у любой формы).
// Колонки «Класс» и «Строк» сняты 2026-10-15: класс по имени файла упразднён, а
// строка дифа не помнит, из какого файла пришла.
function FileTable({ files }: { files: File[] }) {
  return (
    <table className="grid">
      <thead><tr><th className="rn">№</th><th className="gl" /><th className="c-key">Файл</th>
        <th className="c-fit num">Размер</th></tr></thead>
      <tbody>{files.map((f, i) => (
        <tr key={f.name} className="row">
          <td className="rn">{i + 1}</td>
          <td className="gl"><span className="ci sg ci-file-text sg-ok" /></td>
          <td className="c-key">{f.name}</td>
          <td className="c-fit num">{humanSize(f.size)}</td>
        </tr>))}</tbody>
    </table>
  )
}
