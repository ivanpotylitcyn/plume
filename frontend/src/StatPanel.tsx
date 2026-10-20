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
import { money } from './status'

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
// Цвета у числа НЕТ (2026-10-20, решение Ивана): блок «Деньги» — информация, а не сигнал.
// Перерасход, запас сверх потребности, переплата бывают почти всегда — красили бы всегда,
// и цвет обесценился бы. Сигналы живут глифами в таблицах табов; здесь — только `dim`
// (пусто/ноль) и `StatWarn` (данных не хватает).
//
// Волна 26 — блок «Деньги»: `main` — ГЛАВНОЕ число формы (самое актуальное на сегодня;
// правило — факт, где он есть). Стоит первым, крупнее, отделено линией от поддержки —
// одна роль на все формы, а не размер по месту. Ставится прямо в `StatPanel`, без группы.
// `note` — короткая расшифровка под значением («факт + оценка», дата и поставщик цены).
export function Stat({ label, value, dim, title, main, note }: {
  label: string; value: string; dim?: boolean; title?: string
  main?: boolean; note?: string
}) {
  return (
    <div className={'stat' + (main ? ' main' : '')} title={title}>
      <div className="stat-label">{label}</div>
      <div className={'stat-val' + (dim ? ' dim' : '')}>{value}</div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  )
}

// Блок «Деньги» формы (волна 26) — главное число в рублях + необязательная поддержка
// (`children`: группы статов, предупреждения). Ордера, место хранения, поставка: у них
// главное число одно, и разметку панели повторять по формам незачем.
export function MoneyBlock({ label, value, title, note, children }: {
  label: string; value: number; title?: string; note?: string; children?: ReactNode
}) {
  return (
    <StatPanel>
      <Stat main label={label} value={money(value)} title={title} note={note} />
      {children}
    </StatPanel>
  )
}

// Предупреждение под статами (во всю ширину панели): «план неполон», «данных не хватает».
// Глиф — codicon `warning` (2026-10-19: текстовый ▲ был «не из того набора»); рисует его
// сам компонент, вызывающий передаёт только текст. Цвет — от `.stat-warn`.
export function StatWarn({ title, children }: { title?: string; children: ReactNode }) {
  return <div className="stat-warn" title={title}><span className="ci sg ci-warning" />{children}</div>
}
