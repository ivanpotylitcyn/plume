// Витрина волны 13 Ф4: экран места хранения / Location (сущность «Склады»).
// ДНК склада (код/описание/вид) — мутабельная, правится под интерфейсным замком
// (§5, как Изделие). Специфичная часть — «что лежит на этом складе»: живые лоты
// с проектом-владельцем (проект — свойство лота). Удаления нет — склад с
// движениями бережём.
//
// Волна 19 (Ф12c): форма по канону §13 — один таб «На складе». Вложений у Места нет
// (§13.8: заводим, когда заболит), фиксации тоже — в колонке команд остаются режим
// показа и корзина.
import { useEffect, useState } from 'react'
import { api, type LocationForm } from './api'
import { num, count, sumByUom, LotGlyph } from './status'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { CommitInput } from './CommitInput'

export function LocationView({ locationId, isNew, openItem, onChanged, onDeleted }: {
  locationId: number
  isNew: boolean
  openItem: (id: number) => void
  onChanged?: () => void
  onDeleted?: () => void
}) {
  const [d, setD] = useState<LocationForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { unlocked, toggle } = useFormLock(locationId, isNew)   // §5: существующее — в просмотре

  useEffect(() => {
    setD(null); setErr(null)
    api.location(locationId).then(setD).catch(e => setErr(String(e)))
  }, [locationId])

  const run = (p: Promise<LocationForm>) => {
    setBusy(true); setErr(null)
    p.then(next => { setD(next); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Удаление склада (WAVE14 Ф2) под замком: confirm + friendly-guard (склад с движениями).
  const del = () => {
    if (!d || !confirm('Удалить склад? Действие необратимо.')) return
    setBusy(true); setErr(null)
    api.deleteLocation(d.id).then(() => { onChanged?.(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !d) return <div className="empty">Ошибка: {err}</div>
  if (!d) return <div className="empty">Загрузка…</div>

  const locked = !unlocked          // фиксации у справочника нет (§5) — только замок формы

  const tabs: FormTab[] = [
    { key: 'stock', label: 'Склад', icon: 'layers',
      content: d.stock.length === 0
        ? <div className="tab-empty">Пусто — на этом месте нет живых партий.</div>
        : <table className="grid">
            <thead><tr>
              <th className="gl" /><th className="c-key">Партия</th>
              <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
              <th className="c-fit">Проект</th>
              <th style={{ textAlign: 'right' }}>Остаток</th><th className="uom">Ед.</th>
            </tr></thead>
            <tbody>{d.stock.map(l => (
              <tr key={l.lot_id} className="row">
                <td className="gl"><LotGlyph origin={l.origin} liveQty={l.qty} /></td>
                <td className="c-key"><span className="pn">{l.lot_label}</span></td>
                <td className="c-fit">
                  <a className="link" onClick={() => openItem(l.item_id)}>{l.item_code}</a></td>
                <td className="c-desc" style={{ color: 'var(--fg-dim)' }}>
                  <span className="cell-ellip" title={l.item_description}>{l.item_description}</span></td>
                <td className="c-fit">{l.project_code}</td>
                <td className="num">{num(l.qty)}</td>
                <td className="uom">{l.uom}</td>
              </tr>))}</tbody>
          </table> },
  ]

  return (
    <FormShell
      id={d.id} code={d.code} entity="склад" locked={locked} error={err}
      // Мета (§13.6): счёт по табу + итог в натуре по единицам. Вид склада и описание
      // не повторяем — они в полях.
      meta={<>
        {count(d.stock.length, 'партия', 'партии', 'партий')}
        {sumByUom(d.stock).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      onDelete={del}
      fields={<>
        <dt>Код</dt>
        <dd><CommitInput value={d.code} disabled={locked || busy}
          onCommit={v => run(api.updateLocation(d.id, { code: v }))}
          validate={v => v.trim() !== ''} /></dd>
        <dt>Описание</dt>
        <dd className="wide"><CommitInput value={d.description} disabled={locked || busy}
          onCommit={v => run(api.updateLocation(d.id, { description: v }))}
          validate={v => v.trim() !== ''} /></dd>
        <dt>Вид</dt>
        <dd><CommitInput value={d.kind} disabled={locked || busy}
          onCommit={v => run(api.updateLocation(d.id, { kind: v }))} /></dd>
      </>}
      tabs={tabs}
    />
  )
}
