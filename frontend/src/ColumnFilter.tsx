// Фильтр в ЗАГОЛОВКЕ колонки (2026-08-05) — общий для всех списков-таблиц.
//
// Здесь же живёт `useCategoryFilter` (2026-08-10) — движок фильтра по категории
// изделия, единый на все формы (см. его комментарий ниже).
//
// Родился в своде «Потребность» проекта: список на сотни строк, а вопросы к нему всегда
// узкие — «что не заказано», «что уже лежит», «где перебор». Фильтр живёт там же, где
// число, к которому относится, поэтому отдельной панели над таблицей продукт не заводит.
// Знак — тот же раскрыватель, что везде; выбранное значение горит акцентом, иначе
// спрятанные строки читались бы как пропажа данных.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { AnchoredMenu } from './AnchoredMenu'
import { Chevron } from './status'

export function ColumnFilter({ opts, value, onPick }: {
  opts: [string, string][]      // [значение, подпись]
  value: string
  onPick: (v: string) => void
}) {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLSpanElement>(null)
  const on = value !== opts[0][0]        // первый вариант — «все», он же нейтральный
  const label = opts.find(([v]) => v === value)?.[1] ?? ''
  return (
    <span className="col-filter" ref={anchor}>
      <button className={'chev' + (on ? ' on' : '')}
        title={on ? `фильтр: ${label}` : 'фильтр по колонке'}
        onClick={() => setOpen(o => !o)}><Chevron open={open} /></button>
      {open && <>
        {/* Подложка на всё окно: клик мимо меню закрывает его, как у пикеров. */}
        <div className="col-filter-veil" onClick={() => setOpen(false)} />
        <AnchoredMenu anchor={anchor} className="typeahead-menu col-filter-menu">
          {opts.map(([v, text]) => (
            <div key={v} className={'typeahead-item' + (v === value ? ' active' : '')}
              onClick={() => { onPick(v); setOpen(false) }}>
              <span className={'ci' + (v === value ? ' ci-check' : '')} />
              <span>{text}</span>
            </div>
          ))}
        </AnchoredMenu>
      </>}
    </span>
  )
}

// ── Фильтр по КАТЕГОРИИ изделия (2026-08-10) ───────────────────────────────────
//
// Одна ручка на шесть таблиц: состав изделия, строки комплектации, поставки, заказа,
// закупки-плана и её «Строки». Списки там на сотни строк, а вопрос к ним один и тот
// же — «покажи только конденсаторы». Поэтому и движок один: правило отбора, словарь
// вариантов и порог показа живут ЗДЕСЬ, а форма только говорит, где у её строки класс.
// Захотим мульти-выбор («галочки») — меняем этот файл, и он появляется разом везде;
// вьюхам про устройство значения знать нечего.
//
// Значение фильтра — код категории; «все» и «без категории» занимают два служебных
// ключа. Пустая строка = нейтральное «все» (первый вариант — контракт `ColumnFilter`),
// поэтому «без категории» получает свой ключ, а не притворяется пустотой.
// Сентинел — NUL, кодом категории он быть не может. Записан ЭКРАНИРОВАННО (2026-08-11):
// литеральный байт NUL в исходнике делал файл «бинарным», и grep без `-a` молча
// пропускал его целиком — файл выпадал и из поиска по коду, и из проверок на мёртвый
// код. Значение прежнее, изменилась только запись.
const NO_CATEGORY = '\0'

// Форма зовёт хук ДО своей проверки «данные приехали» (правило хуков), поэтому строки
// принимаем и пустыми: `undefined` → общая пустая ссылка, чтобы memo не пересобирался
// на каждый рендер загрузки.
const NO_ROWS: never[] = []

export function useCategoryFilter<T>(
  rows: T[] | undefined,
  categoryOf: (row: T) => string | null | undefined,
  resetKey?: unknown,          // сменился документ — фильтр начинает с чистого листа
): { shown: T[]; head: ReactNode } {
  const [value, setValue] = useState('')
  useEffect(() => { setValue('') }, [resetKey])

  // Варианты — из САМИХ строк, а не из справочника категорий: класса, которого в этой
  // таблице нет, в меню быть не должно — он обещал бы строки, которых не покажет.
  const list = rows ?? NO_ROWS
  const opts = useMemo<[string, string][]>(() => {
    const present = [...new Set(list.map(categoryOf).filter((x): x is string => !!x))].sort()
    return [['', 'все категории'], ...present.map(c => [c, c] as [string, string]),
      ...(list.some(r => !categoryOf(r))
        ? [[NO_CATEGORY, 'без категории'] as [string, string]] : [])]
    // `categoryOf` — стрелка на месте вызова, в зависимости её не берём (иначе memo
    // пересчитывался бы каждый рендер, что и есть отсутствие memo).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list])

  // Выбранный класс мог уйти из таблицы (строку удалили, приехали другие данные) —
  // тогда значение читается сброшенным, иначе фильтр застрял бы на пропавшем и прятал
  // всё содержимое.
  const sel = opts.some(([v]) => v === value) ? value : ''
  const shown = sel
    ? list.filter(r => (sel === NO_CATEGORY ? !categoryOf(r) : categoryOf(r) === sel))
    : list
  // Порог показа — как у фильтров списков режимов: один класс на всю таблицу не выбор,
  // и ручка там только шумит. Два варианта в `opts` = «все» + один класс.
  const head = opts.length > 2
    ? <ColumnFilter opts={opts} value={sel} onPick={setValue} />
    : null
  return { shown, head }
}
