// Каркас витрин волны 1 (VS Code-подобный): activity-bar + дерево + рабочая
// область (одна, без вкладок) + статус-бар. Навигация по сущностям, проект — ось.
import { useEffect, useState } from 'react'
import { api, type ProjectRow, type ItemRow } from './api'
import { DeficitView } from './DeficitView'
import { ItemView } from './ItemView'

type Mode = 'projects' | 'items'
type Sel =
  | { kind: 'project'; id: number }
  | { kind: 'item'; id: number }
  | null

export default function App() {
  const [mode, setMode] = useState<Mode>('projects')
  const [projects, setProjects] = useState<ProjectRow[]>([])
  const [items, setItems] = useState<ItemRow[]>([])
  const [sel, setSel] = useState<Sel>(null)

  useEffect(() => {
    api.projects().then(ps => {
      setProjects(ps)
      const ext = ps.find(p => p.kind === 'external') ?? ps[0]
      if (ext) setSel(s => s ?? { kind: 'project', id: ext.id })
    })
    api.items().then(setItems)
  }, [])

  const openItem = (id: number) => { setMode('items'); setSel({ kind: 'item', id }) }

  return (
    <div className="app">
      <div className="activity">
        <button className={mode === 'projects' ? 'active' : ''}
          title="Проекты — дефицит" onClick={() => setMode('projects')}>▣</button>
        <button className={mode === 'items' ? 'active' : ''}
          title="Изделия — остатки" onClick={() => setMode('items')}>≡</button>
      </div>

      <div className="sidebar">
        {mode === 'projects' ? (
          <>
            <h2>Проекты</h2>
            {projects.map(p => (
              <div key={p.id}
                className={'tree-item' + (sel?.kind === 'project' && sel.id === p.id ? ' sel' : '')}
                onClick={() => setSel({ kind: 'project', id: p.id })}>
                <span className="code">{p.code}</span>
                <span className="sub">{p.name}</span>
              </div>
            ))}
          </>
        ) : (
          <>
            <h2>Изделия</h2>
            {items.map(i => (
              <div key={i.id}
                className={'tree-item' + (sel?.kind === 'item' && sel.id === i.id ? ' sel' : '')}
                onClick={() => setSel({ kind: 'item', id: i.id })}>
                <span className="code">{i.code}</span>
                <span className="sub">{i.name}</span>
              </div>
            ))}
          </>
        )}
      </div>

      <div className="work">
        {sel?.kind === 'project' && <DeficitView projectId={sel.id} openItem={openItem} />}
        {sel?.kind === 'item' && <ItemView itemId={sel.id} openItem={openItem} />}
        {!sel && <div className="empty">Выберите объект слева</div>}
      </div>

      <div className="statusbar">
        <span>plume · волна 1 · витрины движка (read-only)</span>
        <span className="spacer" />
        <span>проектов {projects.length} · изделий {items.length}</span>
      </div>
    </div>
  )
}
