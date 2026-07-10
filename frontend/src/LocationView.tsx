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

export function LocationView({ locationId, openItem, onChanged }: {
  locationId: number
  openItem: (id: number) => void
  onChanged?: () => void
}) {
  const [d, setD] = useState<LocationCockpit | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { unlocked, toggle } = useFormLock(false)   // замок §5: свойства правим открыв

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

  if (err && !d) return <div className="empty">Ошибка: {err}</div>
  if (!d) return <div className="empty">Загрузка…</div>

  const live = d.stock.reduce((s, l) => s + l.qty, 0)
  return (
    <div>
      <FormHeader
        name={d.name}
        meta={<>
          <span className="ci ci-database" style={{ fontSize: 12, marginRight: 5 }} />
          {d.code}{d.kind ? ` · ${d.kind}` : ''} · партий {d.stock.length}
        </>}
        unlocked={unlocked} onToggleLock={toggle} error={err}
      />
      <dl className="props">
        <dt>Код</dt>
        <dd>{unlocked
          ? <CommitInput value={d.code} width={160} disabled={busy}
              onCommit={v => run(api.updateLocation(d.id, { code: v }))}
              validate={v => v.trim() !== ''} />
          : d.code}</dd>
        <dt>Название</dt>
        <dd>{unlocked
          ? <CommitInput value={d.name} width={260} disabled={busy}
              onCommit={v => run(api.updateLocation(d.id, { name: v }))}
              validate={v => v.trim() !== ''} />
          : d.name}</dd>
        <dt>Вид</dt>
        <dd>{unlocked
          ? <CommitInput value={d.kind} width={200} disabled={busy}
              onCommit={v => run(api.updateLocation(d.id, { kind: v }))} />
          : (d.kind || '—')}</dd>
      </dl>

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
                  <a className="link" onClick={() => openItem(l.item_id)}>{l.item_code}</a>{' '}
                  <span style={{ color: 'var(--fg-dim)' }}>{l.item_name}</span>
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
