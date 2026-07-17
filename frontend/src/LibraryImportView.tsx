// Синхронизация справочника Item с внешней библиотекой компонентов Altium (волна 15).
// Путь Б: форма в аппе. Мульти-файл CSV → серверный диф (без записи) → таблица со
// статусами и построчными галочками → применение подтверждённого. Полная сверка:
// добавить новые / обновить изменившиеся / удалить пропавшие; сироты и совпадения —
// информационно (действий нет). Диф пересчитывается на сервере при применении —
// клиентские значения не в доверии, галочки шлём только как список ключей.
import { useMemo, useState } from 'react'
import { api, type LibraryDiff, type LibraryDiffRow, type LibraryStatus,
  type LibraryApplySummary } from './api'

// Статус диф-строки → подпись, цвет-класс строки, глагол действия, есть ли галочка.
// Цвета из канона: зелёный=создать, оранжевый=обновить, красный=удалить.
const ST: Record<LibraryStatus, {
  label: string; cls: string; verb: string; actionable: boolean }> = {
  new:     { label: 'новый',       cls: 's-available', verb: 'создать',  actionable: true },
  changed: { label: 'изменился',   cls: 's-on_order',  verb: 'обновить', actionable: true },
  refix:   { label: 'к фиксации',  cls: 's-available', verb: 'зафиксировать (совпадает с библиотекой)', actionable: true },
  gone:    { label: 'пропал',      cls: 's-to_order',  verb: 'удалить',  actionable: true },
  orphan:  { label: 'сирота',      cls: '',            verb: 'нет в библиотеке (используется)', actionable: false },
  same:    { label: 'совпадает',   cls: '',            verb: '', actionable: false },
}
const FIELD_RU: Record<string, string> = {
  description: 'Описание', category: 'Категория', temperature: 'Температура' }

export function LibraryImportView({ onApplied, openItem }:
  { onApplied: () => void; openItem: (id: number) => void }) {
  const [files, setFiles] = useState<File[]>([])
  const [diff, setDiff] = useState<LibraryDiff | null>(null)
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set())
  const [summary, setSummary] = useState<LibraryApplySummary | null>(null)
  const [showSame, setShowSame] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Новый набор файлов → сброс дифа/итога (старая сверка больше не действует).
  const pickFiles = (list: FileList | null) => {
    setFiles(list ? Array.from(list) : [])
    setDiff(null); setSummary(null); setConfirmed(new Set()); setErr(null)
  }

  const runDiff = () => {
    if (files.length === 0) { setErr('Выберите CSV-файлы библиотеки'); return }
    setBusy(true); setErr(null); setSummary(null)
    api.libraryDiff(files)
      .then(d => {
        setDiff(d)
        // Предотметка: добавления, обновления и фиксации — под галочкой сразу
        // (безопасны, `refix` обратим через unpost); удаления (`gone`, необратимо) —
        // вручную. Полная сверка, но с защитой.
        setConfirmed(new Set(d.rows
          .filter(r => r.status === 'new' || r.status === 'changed' || r.status === 'refix')
          .map(r => r.design_item_id)))
      })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  const apply = () => {
    if (!diff || confirmed.size === 0) return
    setBusy(true); setErr(null)
    api.libraryApply(files, [...confirmed])
      .then(s => { setSummary(s); setDiff(null); setConfirmed(new Set()); onApplied() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  const toggle = (key: string) => setConfirmed(prev => {
    const next = new Set(prev)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  })
  // Массовое переключение по статусу (или сразу все действия): отметить/снять весь блок.
  const bulk = (rows: LibraryDiffRow[], on: boolean) => setConfirmed(prev => {
    const next = new Set(prev)
    for (const r of rows) on ? next.add(r.design_item_id) : next.delete(r.design_item_id)
    return next
  })

  // Свод по статусам + отфильтрованный список строк к показу.
  const counts = useMemo(() => {
    const c: Record<LibraryStatus, number> = { new: 0, changed: 0, refix: 0, gone: 0, orphan: 0, same: 0 }
    diff?.rows.forEach(r => { c[r.status]++ })
    return c
  }, [diff])
  const shown = useMemo(() =>
    (diff?.rows ?? []).filter(r => showSame || r.status !== 'same'), [diff, showSame])
  const actionable = useMemo(() =>
    (diff?.rows ?? []).filter(r => ST[r.status].actionable), [diff])
  const allActionableOn = actionable.length > 0 && actionable.every(r => confirmed.has(r.design_item_id))

  return (
    <div>
      <h1 className="title">Синхронизация с библиотекой</h1>
      <div className="subtitle">
        Библиотека компонентов Altium — источник правды по покупным изделиям.
        Загрузите CSV-таблицы (мульти-файл, CP1251) · сверка по «Design Item Id» ·
        пропавшие сверяются только в загруженных категориях.
      </div>

      <div className="kit-actions" style={{ marginBottom: 12 }}>
        <input type="file" multiple accept=".csv,text/csv"
          onChange={e => pickFiles(e.target.files)} />
        <button className="btn" disabled={busy || files.length === 0} onClick={runDiff}>
          Сверить{files.length > 0 ? ` (${files.length})` : ''}
        </button>
        {err && <span className="anomaly">{err}</span>}
      </div>

      {summary && (
        <div className="section-h" style={{ color: 'var(--st-ok)' }}>
          Применено: создано {summary.created} · обновлено {summary.updated} ·
          зафиксировано {summary.fixed} · удалено {summary.deleted}
        </div>
      )}

      {diff && <>
        <div className="section-h">Расхождения
          <span className="hint">
            новых {counts.new} · изменившихся {counts.changed} · к фиксации {counts.refix} ·
            пропавших {counts.gone} · сирот {counts.orphan} · совпадений {counts.same}
          </span>
        </div>
        <div style={{ color: 'var(--fg-dim)', fontSize: 12, marginBottom: 8 }}>
          Загруженные категории: {diff.categories.join(', ') || '—'}
        </div>

        <div className="kit-actions" style={{ marginBottom: 8 }}>
          <button className="btn sm" disabled={busy || actionable.length === 0}
            onClick={() => bulk(actionable, !allActionableOn)}>
            {allActionableOn ? 'снять все действия' : 'отметить все действия'}
          </button>
          {counts.same > 0 &&
            <label style={{ color: 'var(--fg-dim)', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <input type="checkbox" checked={showSame} onChange={e => setShowSame(e.target.checked)} />
              показывать совпадения
            </label>}
        </div>

        {shown.length === 0
          ? <div style={{ color: 'var(--fg-dim)' }}>Расхождений нет — справочник совпадает с библиотекой.</div>
          : <table className="grid" style={{ maxWidth: 920 }}>
              <thead><tr>
                <th style={{ width: 24 }} />
                <th>Статус</th><th>Изделие</th><th>Действие / изменения</th>
              </tr></thead>
              <tbody>{shown.map(r => {
                const m = ST[r.status]
                const checked = confirmed.has(r.design_item_id)
                return (
                  <tr key={r.design_item_id} className={'row ' + m.cls}>
                    <td style={{ textAlign: 'center' }}>
                      {m.actionable
                        ? <input type="checkbox" checked={checked} disabled={busy}
                            onChange={() => toggle(r.design_item_id)} />
                        : <span style={{ color: 'var(--fg-dim)' }}>—</span>}
                    </td>
                    <td className="kind-chip">{m.label}</td>
                    <td>{r.item_id
                      ? <a className="link" onClick={() => openItem(r.item_id!)}>{r.design_item_id}</a>
                      : r.design_item_id}</td>
                    <td style={{ color: 'var(--fg-dim)' }}><RowDetail row={r} verb={m.verb} /></td>
                  </tr>)
              })}</tbody>
            </table>}

        <div className="kit-actions" style={{ marginTop: 12 }}>
          <button className="btn" disabled={busy || confirmed.size === 0} onClick={apply}>
            Применить подтверждённое ({confirmed.size})
          </button>
          {confirmed.size > 0 &&
            <span style={{ color: 'var(--fg-dim)', fontSize: 12 }}>
              будет применено строк: {confirmed.size}
            </span>}
        </div>
      </>}
    </div>
  )
}

// Правая колонка: для нового — что заводим; для изменившегося — поля old→new;
// для пропавшего/сироты — что в БД сейчас + вердикт.
function RowDetail({ row, verb }: { row: LibraryDiffRow; verb: string }) {
  if (row.status === 'new' && row.incoming)
    return <>{verb}: {row.incoming.description}
      <span className="kind-chip"> · {row.incoming.category}
        {row.incoming.temperature ? ` · ${row.incoming.temperature}` : ''}</span></>
  if (row.status === 'changed' && row.changes)
    return <>{Object.entries(row.changes).map(([f, ch]) => (
      <div key={f}>{FIELD_RU[f] || f}: <s>{ch!.old || '—'}</s> → <b style={{ color: 'var(--fg)' }}>{ch!.new || '—'}</b></div>
    ))}</>
  if (row.status === 'refix')
    return <>черновик → <b style={{ color: 'var(--st-ok)' }}>зафиксировать ✓</b>
      <span className="kind-chip"> · совпадает с библиотекой</span></>
  if ((row.status === 'gone' || row.status === 'orphan') && row.current)
    return <>{verb}
      <span className="kind-chip"> · {row.current.description} · {row.current.category}</span></>
  return <>{verb || '—'}</>
}
