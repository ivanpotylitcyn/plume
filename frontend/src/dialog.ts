// Фирменные окна вместо браузерных `confirm()` / `alert()` (волна 23, Ф1, решение
// Ивана 2026-10-15: «и вообще все окна»).
//
// Вызов — как у браузерного: `if (!(await ask({...}))) return`. Окно рисует один хост
// (`DialogHost` в `App`), поэтому оно живо и тогда, когда вызвавшая форма уже
// размонтирована (предупреждение «код пустой» при уходе с формы). Окна идут очередью.
//
// Разметка окна — `DialogBox` (там же, где хост): ею же рисуется окно фиксации, так что
// у продукта одна коробка на все вопросы.

export interface DialogLine { text: string; warn?: boolean }

export interface Ask {
  title: string
  lines?: (string | DialogLine)[]
  verb?: string           // подпись действия; по умолчанию «Да»
  icon?: string           // Codicon действия, напр. `ci-trash`
  danger?: boolean        // необратимое: красная команда + строка «действие необратимо»
}

export interface Pending extends Ask {
  kind: 'ask' | 'tell'
  resolve: (ok: boolean) => void
}

let push: ((p: Pending) => void) | null = null

export function bindDialogHost(fn: ((p: Pending) => void) | null) { push = fn }

/** Вопрос с двумя командами — замена `confirm()`. */
export function ask(a: Ask): Promise<boolean> {
  if (!push) return Promise.resolve(window.confirm(a.title))   // хоста нет — не теряем вопрос
  return new Promise(resolve => push!({ ...a, kind: 'ask', resolve }))
}

/** Сообщение с одной командой «Понятно» — замена `alert()`. */
export function tell(a: Omit<Ask, 'verb' | 'icon' | 'danger'>): Promise<void> {
  if (!push) { window.alert(a.title); return Promise.resolve() }
  return new Promise(resolve => push!({ ...a, kind: 'tell', resolve: () => resolve() }))
}

export function dialogLines(a: Ask): DialogLine[] {
  const lines = (a.lines ?? []).map(l => (typeof l === 'string' ? { text: l } : l))
  return a.danger ? [...lines, { text: 'действие необратимо', warn: true }] : lines
}
