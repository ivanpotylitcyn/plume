// Витрина волны 13 Ф4: экран места хранения / Location (сущность «Склады»).
// ДНК склада (код/название/вид) — мутабельная, правится под интерфейсным замком
// (§5, как Изделие). Специфичная часть — «что лежит на этом складе»: живые лоты
// с проектом-владельцем (проект — свойство лота). Удаления нет — склад с
// движениями бережём.
import { useEffect, useState } from 'react'
import { api, type LocationCockpit } from './api'
import { num } from './status'
import { FormHeader, useFormLock } from './FormHeader'
import { CommitInput } from './ReceiptView'

export function LocationView({ locationId, isNew, openItem, onChanged, onDeleted }: {
  locationId: number
  isNew: boolean
  openItem: (id: number) => void
  onChanged?: () => void
  onDeleted?: () => void
}) {
  const [d, setD] = useState<LocationCockpit | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { unlocked, toggle } = useFormLock(locationId, isNew)   // §5: существующее — в просмотре

  useEffect(() => {
    setD(null); setErr(null)
    api.location(locationId).then(setD).catch(e => setErr(String(e)))
  }, [locationId])

  const run = (p: Promise<LocationCockpit>) => {
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

  const live = d.stock.reduce((s, l) => s + l.qty, 0)
  return (
    <div>
      <FormHeader
        code={d.code}
        meta={<>
          <span className="ci ci-database" style={{ fontSize: 12, marginRight: 5 }} />
          {d.description}{d.kind ? ` · ${d.kind}` : ''} · партий {d.stock.length}
        </>}
        unlocked={unlocked} onToggleLock={toggle} error={err}
        onDelete={del}
      >
      <dl className="props">
        <dt>Код</dt>
        <dd>{unlocked
          ? <CommitInput value={d.code} width={160} disabled={busy}
              onCommit={v => run(api.updateLocation(d.id, { code: v }))}
              validate={v => v.trim() !== ''} />
          : d.code}</dd>
        <dt>Описание</dt>
        <dd>{unlocked
          ? <CommitInput value={d.description} width={260} disabled={busy}
              onCommit={v => run(api.updateLocation(d.id, { description: v }))}
              validate={v => v.trim() !== ''} />
          : d.description}</dd>
        <dt>Вид</dt>
        <dd>{unlocked
          ? <CommitInput value={d.kind} width={200} disabled={busy}
              onCommit={v => run(api.updateLocation(d.id, { kind: v }))} />
          : (d.kind || '—')}</dd>
      </dl>
      </FormHeader>

      <div className="section-h">На складе
        <span className="hint">партий {d.stock.length} · всего {num(live)}</span></div>
      {d.stock.length === 0
        ? <div style={{ color: 'var(--fg-dim)' }}>Пусто — на этом месте нет живых партий.</div>
        : <table className="grid">
            <thead><tr>
              <th>Партия</th><th>Изделие</th><th>Проект</th>
              <th style={{ textAlign: 'right' }}>Остаток</th>
            </tr></thead>
            <tbody>{d.stock.map(l => (
              <tr key={l.lot_id} className="row s-available">
                <td>
                  <span className="glyph g-available">✓</span>{' '}
                  <span className="pn">{l.lot_label}</span>
                </td>
                <td>
                  <a className="link" onClick={() => openItem(l.item_id)}>{l.item_design_item_id}</a>{' '}
                  <span style={{ color: 'var(--fg-dim)' }}>{l.item_description}</span>
                </td>
                <td>{l.project_code}{' '}
                  <span style={{ color: 'var(--fg-dim)' }}>{l.project_name}</span>
                </td>
                <td className="num">{num(l.qty)} {l.uom}</td>
              </tr>))}</tbody>
          </table>}
    </div>
  )
}
