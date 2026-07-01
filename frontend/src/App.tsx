// Каркас витрин (VS Code-подобный): activity-bar + дерево + рабочая область
// (одна, без вкладок) + статус-бар. Навигация по сущностям, проект — ось.
// Волна 2: третий режим «Комплектации» — записываемый кокпит сборки.
import { useCallback, useEffect, useState } from 'react'
import { api, type ProjectRow, type ItemRow, type KittingRow } from './api'
import { DeficitView } from './DeficitView'
import { ItemView } from './ItemView'
import { KittingView } from './KittingView'

type Mode = 'projects' | 'items' | 'kittings'
type Sel =
  | { kind: 'project'; id: number }
  | { kind: 'item'; id: number }
  | { kind: 'kitting'; id: number }
  | { kind: 'new-kitting' }
  | null

const KIT_GLYPH: Record<string, { g: string; cls: string }> = {
  wip: { g: '●', cls: 'g-on_order' },
  closed: { g: '✓', cls: 'g-available' },
  cancelled: { g: '○', cls: 'g-info' },
}

export default function App() {
  const [mode, setMode] = useState<Mode>('projects')
  const [projects, setProjects] = useState<ProjectRow[]>([])
  const [items, setItems] = useState<ItemRow[]>([])
  const [kittings, setKittings] = useState<KittingRow[]>([])
  const [sel, setSel] = useState<Sel>(null)

  const reloadKittings = useCallback(() => api.kittings().then(setKittings), [])

  useEffect(() => {
    api.projects().then(ps => {
      setProjects(ps)
      const ext = ps.find(p => p.kind === 'external') ?? ps[0]
      if (ext) setSel(s => s ?? { kind: 'project', id: ext.id })
    })
    api.items().then(setItems)
    reloadKittings()
  }, [reloadKittings])

  const openItem = (id: number) => { setMode('items'); setSel({ kind: 'item', id }) }
  const openKitting = (id: number) => { setMode('kittings'); setSel({ kind: 'kitting', id }) }

  return (
    <div className="app">
      <div className="activity">
        <button className={mode === 'projects' ? 'active' : ''}
          title="Проекты — дефицит" onClick={() => setMode('projects')}>▣</button>
        <button className={mode === 'items' ? 'active' : ''}
          title="Изделия — остатки" onClick={() => setMode('items')}>≡</button>
        <button className={mode === 'kittings' ? 'active' : ''}
          title="Комплектации — кокпит сборки" onClick={() => setMode('kittings')}>⛭</button>
      </div>

      <div className="sidebar">
        {mode === 'projects' && <>
          <h2>Проекты</h2>
          {projects.map(p => (
            <div key={p.id}
              className={'tree-item' + (sel?.kind === 'project' && sel.id === p.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'project', id: p.id })}>
              <span className="code">{p.code}</span>
              <span className="sub">{p.name}</span>
            </div>
          ))}
        </>}

        {mode === 'items' && <>
          <h2>Изделия</h2>
          {items.map(i => (
            <div key={i.id}
              className={'tree-item' + (sel?.kind === 'item' && sel.id === i.id ? ' sel' : '')}
              onClick={() => setSel({ kind: 'item', id: i.id })}>
              <span className="code">{i.code}</span>
              <span className="sub">{i.name}</span>
            </div>
          ))}
        </>}

        {mode === 'kittings' && <>
          <h2>Комплектации</h2>
          <div className={'tree-item new' + (sel?.kind === 'new-kitting' ? ' sel' : '')}
            onClick={() => setSel({ kind: 'new-kitting' })}>
            <span className="code">＋ Новая</span>
          </div>
          {kittings.map(k => {
            const gl = KIT_GLYPH[k.status] ?? KIT_GLYPH.cancelled
            return (
              <div key={k.id}
                className={'tree-item' + (sel?.kind === 'kitting' && sel.id === k.id ? ' sel' : '')}
                onClick={() => setSel({ kind: 'kitting', id: k.id })}>
                <span className={`glyph ${gl.cls}`}>{gl.g}</span>
                <span className="code">{k.target_code}</span>
                <span className="sub">{k.project_code} ×{k.qty}</span>
              </div>
            )
          })}
        </>}
      </div>

      <div className="work">
        {sel?.kind === 'project' && <DeficitView projectId={sel.id} openItem={openItem} />}
        {sel?.kind === 'item' && <ItemView itemId={sel.id} openItem={openItem} />}
        {sel?.kind === 'kitting' &&
          <KittingView kittingId={sel.id} openItem={openItem} onChanged={reloadKittings} />}
        {sel?.kind === 'new-kitting' &&
          <NewKitting projects={projects} items={items}
            onCreated={id => { reloadKittings(); openKitting(id) }} />}
        {!sel && <div className="empty">Выберите объект слева</div>}
      </div>

      <div className="statusbar">
        <span>plume · волна 2 · кокпит комплектации</span>
        <span className="spacer" />
        <span>проектов {projects.length} · изделий {items.length} · комплектаций {kittings.length}</span>
      </div>
    </div>
  )
}

// Создание новой комплектации: проект + производимый прибор + кол-во образцов.
function NewKitting({ projects, items, onCreated }: {
  projects: ProjectRow[]; items: ItemRow[]; onCreated: (id: number) => void
}) {
  const externalProjects = projects.filter(p => p.kind === 'external')
  const targets = items.filter(i => i.is_manufactured)
  const [projectId, setProjectId] = useState<number | ''>(externalProjects[0]?.id ?? '')
  const [targetId, setTargetId] = useState<number | ''>(targets[0]?.id ?? '')
  const [qty, setQty] = useState('1')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const create = () => {
    const n = Number(qty)
    if (!projectId || !targetId || !(n > 0)) { setErr('Заполните проект, прибор и кол-во'); return }
    setBusy(true); setErr(null)
    api.createKitting({ project_id: projectId, target_item_id: targetId, qty: n })
      .then(c => onCreated(c.id))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div>
      <h1 className="title">Новая комплектация</h1>
      <div className="subtitle">Проект + производимый прибор + количество образцов</div>
      <dl className="props">
        <dt>Проект</dt>
        <dd><select className="lot-sel" value={projectId}
          onChange={e => setProjectId(Number(e.target.value))}>
          {externalProjects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
        </select></dd>
        <dt>Прибор</dt>
        <dd><select className="lot-sel" value={targetId}
          onChange={e => setTargetId(Number(e.target.value))}>
          {targets.map(i => <option key={i.id} value={i.id}>{i.code} — {i.name}</option>)}
        </select></dd>
        <dt>Образцов</dt>
        <dd><input className="qty-in" value={qty} onChange={e => setQty(e.target.value)} /></dd>
      </dl>
      <div className="kit-actions">
        <button className="btn" disabled={busy} onClick={create}>Создать</button>
        {err && <span className="anomaly">{err}</span>}
      </div>
    </div>
  )
}
