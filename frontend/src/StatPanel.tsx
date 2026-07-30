// Панель интеграла — «органичное дополнение стека» формы (§13.1): не список (табом
// быть не может) и не поле шапки, а несколько крупных чисел, которые движок ВЫЧИСЛЯЕТ.
// Живёт между метой и табами (слот `extra` у `FormShell`).
//
// Волна 20: панель поднята из `ProjectView` (там она была бюджетом проекта) — форма
// контрагента стала вторым её пользователем, и «бюджетные» имена классов (`.budget`,
// `.bstat`, `.bval`) переехали в нейтральные (`.stats`, `.stat`, `.stat-val`).
// Дублировать вёрстку не стали: стат — единица чтения, и она обязана выглядеть одинаково
// в бюджете проекта и в интеграле контрагента ([[form-consistency-standard]]).
import type { ReactNode } from 'react'

// Карточка-панель. `caption` — имя панели: нужен, когда на форме их несколько (две
// стороны документооборота контрагента); у одинокой панели бюджета его нет.
export function StatPanel({ caption, icon, children }: {
  caption?: string; icon?: string; children: ReactNode
}) {
  return (
    <div className="panel stats">
      {caption && <div className="stats-caption">
        {icon && <span className={`ci sg ci-${icon}`} />}{caption}
      </div>}
      {children}
    </div>
  )
}

// Группа статов. `aside` прижимает её вправо и отделяет линией (второй смысловой блок
// в одной панели — «себестоимость/экономия» рядом с деньгами бюджета).
export function StatGroup({ aside, children }: { aside?: boolean; children: ReactNode }) {
  return <div className={'sgroup' + (aside ? ' aside' : '')}>{children}</div>
}

// Один стат: подпись сверху, значение крупным моно (числа сканируют, а не читают).
// `tone` — знак от смысла, который посчитал движок ([[engine-view-seam]]).
export function Stat({ label, value, tone, dim, title }: {
  label: string; value: string; tone?: 'ok' | 'bad'; dim?: boolean; title?: string
}) {
  return (
    <div className="stat" title={title}>
      <div className="stat-label">{label}</div>
      <div className={'stat-val' + (tone ? ` t-${tone}` : '') + (dim ? ' dim' : '')}>{value}</div>
    </div>
  )
}

// Предупреждение под статами (во всю ширину панели): «план неполон», «данных не хватает».
export function StatWarn({ title, children }: { title?: string; children: ReactNode }) {
  return <div className="stat-warn" title={title}>{children}</div>
}
