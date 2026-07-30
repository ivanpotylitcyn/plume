// Таб «К закупке» (волна 19, Ф13) — что купить по ОХВАТУ этой закупки.
//
// Раньше это был отдельный экран «Командный свод»: пункт сайдбара без сущности, без
// кода, без замка, вечно один и со своим третьим скелетом формы. Считал он по всем
// активным проектам организации, а мост «＋ в закупку» искал-или-создавал последний
// черновик плана. Теперь это обычный таб обычной закупки: область расчёта задаёт её
// охват, а мост кладёт позицию в неё же. Отметить все проекты = прежний общий свод.
//
// Строка: Σ проектных дефицитов по Item (без перенеттинга — профицит одного проекта
// не гасит нужду другого). Раскрытие показывает, откуда нужда. Красное наверху.
import { useEffect, useState } from 'react'
import { api, type ScopeDeficit, type ScopeDeficitRow } from './api'
import { Chevron, Glyph, Segment, num } from './status'

// Состояние витрины: перечитывается на `rev` (мутации формы — взяли позицию в план,
// поменяли охват), как и пеггинг.
export function useScopeDeficit(procurementId: number, rev: number) {
  const [d, setD] = useState<ScopeDeficit | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.procurementDeficit(procurementId).then(setD).catch(e => setErr(String(e)))
  }, [procurementId, rev])

  return { d, err }
}

export type ScopeDeficitState = ReturnType<typeof useScopeDeficit>

export function ScopeDeficitRows({ st, openItem, editable, onTake }: {
  st: ScopeDeficitState
  openItem: (id: number) => void
  editable: boolean
  onTake: (itemId: number, qty: number) => void
}) {
  const { d, err } = st
  if (err) return <div className="anomaly">{err}</div>
  if (!d) return <div className="tab-empty">Загрузка…</div>
  // Пусто = пусто (Ф13): без охвата закупка ничего не считает — и говорит об этом.
  if (d.rows.length === 0)
    return <div className="tab-empty">
      Нет потребностей по охвату — отметьте проекты в поле «Проекты».
    </div>
  return (
    <table className="grid">
      <thead>
        <tr>
          <th className="gl" /><th className="c-key">Изделие</th>
          <th className="c-desc">Описание</th>
          <th className="num">Надо</th><th className="uom">Ед.</th>
          <th>Разбор</th>
          <th className="num">Закупить</th>
          <th className="num">В плане</th>
          <th className="act" />
        </tr>
      </thead>
      <tbody>
        {d.rows.map(r => (
          <Row key={r.item_id} r={r} openItem={openItem} editable={editable}
            onTake={onTake} />
        ))}
      </tbody>
    </table>
  )
}

function Row({ r, openItem, editable, onTake }: {
  r: ScopeDeficitRow
  openItem: (id: number) => void
  editable: boolean
  onTake: (itemId: number, qty: number) => void
}) {
  const [open, setOpen] = useState(false)
  // Взято ли уже столько, сколько просит наводка: мост — топ-ап, повтор ничего не
  // изменит, поэтому кнопка гаснет вместо того, чтобы врать про действие.
  const taken = r.planned >= r.to_order
  return (
    <>
      <tr className={`row s-${r.status}`}>
        <td className="gl"><Glyph status={r.status} /></td>
        <td className="c-key">
          <a className="link" onClick={() => openItem(r.item_id)}>{r.item_code}</a></td>
        <td className="c-desc">
          <span className="cell-ellip" title={r.item_description}>{r.item_description}</span></td>
        <td className="num">{num(r.need)}</td>
        <td className="uom">{r.uom}</td>
        <td>
          <Segment status="available" value={r.have} />
          <Segment status="on_order" value={r.on_order} />
          <Segment status="to_order" value={r.to_order} />
        </td>
        <td className="num">{r.to_order > 0 ? num(r.to_order) : '—'}</td>
        <td className="num" style={{ color: r.planned > 0 ? undefined : 'var(--fg-dim)' }}>
          {r.planned > 0 ? num(r.planned) : '—'}</td>
        <td className="act">
          <button className="fh-ctl icon" title="Откуда нужда (по проектам охвата)"
            onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
          {editable && r.to_order > 0 && !taken &&
            <button className="btn sm" style={{ marginLeft: 6 }}
              title={`Взять в план ${num(r.to_order)} ${r.uom}`}
              onClick={() => onTake(r.item_id, r.to_order)}>＋ в план</button>}
        </td>
      </tr>
      {open && r.by_project.map(bp => (
        <tr key={bp.project_id} className={`row ghost s-${bp.status}`}>
          <td className="gl"><Glyph status={bp.status} /></td>
          <td className="c-key"><span className="code">{bp.project_code}</span></td>
          <td className="c-desc"><span className="sub">{bp.project_name}</span></td>
          <td className="num sub">{num(bp.need)}</td>
          <td className="uom" />
          <td>
            <Segment status="available" value={bp.have} />
            <Segment status="on_order" value={bp.on_order} />
            <Segment status="to_order" value={bp.to_order} />
          </td>
          <td className="num sub">{bp.to_order > 0 ? num(bp.to_order) : '—'}</td>
          <td className="num" />
          <td className="act" />
        </tr>
      ))}
    </>
  )
}
