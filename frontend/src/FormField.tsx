// Поле шапки формы — ОДИН компонент на весь продукт (волна 19, Ф12d).
//
// До Ф12d «просмотр» жил двумя разными механизмами: `ItemView` рисовала под замком
// настоящий текст, а остальные одиннадцать форм всегда держали контрол в DOM и гасили
// ему рамку классом `.form-locked`. Отсюда шла кривизна шапок: строка с текстом имела
// высоту 16px, с инпутом — 20, с датой/селектом — 22, и шапка прыгала при каждом
// переключении режима (Изделие 165→191, Проект 85→104). Решение Ивана 2026-07-29 —
// **текст везде**, буквально по §5: «закрыт → вся форма чистый текст без единого поля
// ввода». Развилку решает ЭТОТ модуль, вьюхи о ней больше не знают.
//
// Второе, что здесь централизовано, — ШРИФТ значения. Он идёт от смысла поля (§3:
// mono для кодов/номеров/дат/чисел, Inter для описаний), а НЕ от режима: иначе одно
// и то же описание читалось бы в правке моноширинным, а в просмотре — литературным.
// Класс садится на `dd`, оттуда CSS красит и текст, и контрол — оба одинаково.
import type { ReactNode } from 'react'
import { CommitInput } from './CommitInput'

// Дата в просмотре — `дд.мм.гггг`, без часовых поясов: `new Date('2026-07-29')`
// разбирается как UTC-полночь и в минусовых зонах уезжает на день назад.
export function viewDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return m ? `${m[3]}.${m[2]}.${m[1]}` : (iso || '')
}

export interface FieldProps {
  label: string
  locked: boolean           // замок формы закрыт → показываем текст
  view?: ReactNode          // значение в просмотре; пустое → прочерк
  mono?: boolean            // значение — код/номер/дата/число (§3)
  wide?: boolean            // длинная ступень ширины (§13.3)
}

// Пустое значение — прочерк, а не пустая строка: пустое место в шапке читается как
// «поля нет», прочерк — как «поле есть, значение не задано» (правило заглушки, Ф6).
function dash(view: ReactNode): ReactNode {
  return view === null || view === undefined || view === '' ? '—' : view
}

export function Field({ label, locked, view, mono, wide, children }:
  FieldProps & { children?: ReactNode }) {
  const cls = [wide ? 'wide' : '', mono ? 'mono' : ''].filter(Boolean).join(' ')
  return (
    <>
      <dt>{label}</dt>
      <dd className={cls || undefined}>{locked ? dash(view) : children}</dd>
    </>
  )
}

// Текстовое поле с автосейвом — самый частый случай шапки (код, описание, номер,
// дата, число). `view` по умолчанию = само значение, у даты — человеческий формат.
export function TextField({ value, onCommit, busy, validate, type, view, ...f }:
  FieldProps & {
    value: string
    onCommit: (v: string) => void
    busy?: boolean
    validate?: (v: string) => boolean
    type?: string
  }) {
  return (
    <Field {...f} view={view ?? (type === 'date' ? viewDate(value) : value)}>
      {/* `disabled` — только про `busy`: под замком контрола в DOM нет вовсе, а
          мигать «контрол → текст → контрол» на время PATCH нельзя (та же боль, что
          у пикера в Ф13: элемент, отключённый под фокусом, роняет ввод). */}
      <CommitInput value={value} type={type} disabled={busy}
        onCommit={onCommit} validate={validate} />
    </Field>
  )
}
