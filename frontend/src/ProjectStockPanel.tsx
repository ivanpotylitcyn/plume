// Витрина волны 6 (докрутка): остатки внутреннего склада (белый/серый).
// Внутренние проекты-склады не имеют потребностей (дефицит пуст) и панели закрытия
// (они постоянны) — но именно сюда «на баланс» кладёт лоты требованием. Показываем
// read-only список живых лотов (live>0), чтобы видеть, куда стекается сток.
import { useEffect, useState } from 'react'
import { api, type AvailableLot } from './api'
import { num } from './status'

const ORIGIN_LABEL: Record<string, string> = {
  receipt: 'приход', kitting: 'сборка', inventory: 'инвентаризация',
  requisition: 'требование',
}

export function ProjectStockPanel({ projectId, projectName, openItem }: {
  projectId: number; projectName: string; openItem: (id: number) => void
}) {
  const [lots, setLots] = useState<AvailableLot[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setLots(null); setErr(null)
    api.projectAvailableLots(projectId).then(setLots).catch(e => setErr(String(e)))
  }, [projectId])

  if (err) return <div className="empty">Ошибка: {err}</div>
  if (!lots) return <div className="empty">Загрузка…</div>

  const total = lots.reduce((s, l) => s + l.live_qty, 0)
  return (
    <div>
      <h1 className="title">
        <span className="glyph g-info">▤</span>{' '}
        <span className="lit">{projectName}</span>
      </h1>
      <div className="subtitle">
        Остатки склада · живых лотов <span className="seg">{lots.length}</span>
        {' · всего единиц '}<span className="seg">{num(total)}</span>
      </div>

      {lots.length === 0
        ? <div className="empty">Склад пуст — живых остатков нет.</div>
        : <table className="grid">
            <thead>
              <tr>
                <th>партия</th><th>изделие</th><th>откуда</th>
                <th style={{ textAlign: 'right' }}>остаток</th>
              </tr>
            </thead>
            <tbody>
              {lots.map(l => (
                <tr key={l.lot_id} className="row s-available">
                  <td>
                    <span className="glyph g-available">✓</span>{' '}
                    <span className="pn">#{l.lot_id}{l.serial_number ? ` ${l.serial_number}` : ''}</span>
                  </td>
                  <td>
                    <a className="link" onClick={() => openItem(l.item_id)}>{l.item_code}</a>{' '}
                    <span style={{ color: 'var(--fg-dim)' }}>{l.item_name}</span>
                  </td>
                  <td style={{ color: 'var(--fg-dim)' }}>{ORIGIN_LABEL[l.origin] ?? l.origin}</td>
                  <td className="num">{num(l.live_qty)} {l.uom}</td>
                </tr>
              ))}
            </tbody>
          </table>}
    </div>
  )
}
