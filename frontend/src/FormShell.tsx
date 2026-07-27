// Канон формы (UI_GUIDE §13; волна 19, Ф12): ОДИН лэйаут на все формы.
//
//        код-титул            ← `code`, по центру панелей; пустой = пустой
//   ┌──────────────────────┐
//   │ поля       │ команды │  ← панель ШАПКА (две зоны в одной горизонтали)
//   └──────────────────────┘
//        мета (по центру)     ← только то, чего в полях нет
//   [⊞ Таб] [🗎 Таб]           ← табы, рисуем всегда (даже один)
//   ┌──────────────────────┐
//   │ список активного табa│  ← панель СПИСОК
//   └──────────────────────┘
//
// Живёт в ТЕМЕ (не в `core/`): это знак, а не смысл — вторая тема волны 19 Ф7
// получит свой лэйаут и унаследует всё остальное. Пока слой темы лежит плоско в
// `src/`; в Ф7 он переедет в `themes/ide/` целиком, одним движением.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { FormCommands, FormCornerCommand, type FormCommandProps } from './FormHeader'

// Таб = один список формы. Счётчиков в табах НЕТ (решение 2026-07-26): числа рядом с
// подписью шумели — счёт переехал в мету, которая без него была скудной (§13.6).
export interface FormTab {
  key: string
  label: string
  icon: string              // codicon-класс без префикса `ci-`
  content: ReactNode
}

export function FormShell({ id, code, entity, fields, meta, extra, tabs, error, locked, ...cmd }:
  FormCommandProps & {
    id: number              // смена = другая сущность: сброс таба (канон Ф9)
    code: string            // титул; пустой — так и остаётся пустым (§13.5)
    entity: string          // винительный падеж для предупреждения: «удалите изделие»
    fields: ReactNode       // содержимое `.props` (пары dt/dd) — зона полей шапки
    meta?: ReactNode
    extra?: ReactNode       // органичное дополнение стека (§13.1): панель бюджета проекта
    tabs: FormTab[]
    error?: string | null
    locked: boolean         // форма read-only (фиксация ИЛИ закрытый замок формы)
  }) {
  const [tab, setTab] = useState(0)
  useEffect(() => { setTab(0) }, [id])
  // Набор табов у формы подвижен (у покупного изделия нет состава) — держим индекс
  // в границах, чтобы после сужения набора панель не осталась пустой.
  const active = tabs[Math.min(tab, tabs.length - 1)]

  // Мягкое предупреждение при уходе с формы с пустым/пробельным кодом (§13.5):
  // схему не ужесточаем (`code` остаётся nullable), обязательность держится
  // подталкиванием. Ругаемся ровно на уходе — пока форма открыта, пустой титул
  // и так давит. Удалённую сущность не поминаем: `gone` ставится кликом по корзине
  // (после него форма либо исчезнет, либо пользователь останется — и тогда одно
  // предупреждение будет пропущено; менее навязчиво, чем ложная ругань).
  const codeRef = useRef(code); codeRef.current = code
  const entityRef = useRef(entity); entityRef.current = entity
  const gone = useRef(false)
  useEffect(() => {
    gone.current = false
    return () => {
      if (!gone.current && !codeRef.current.trim())
        alert(`Код оставлять пустым нельзя. Задайте поле Код или удалите ${entityRef.current}.`)
    }
  }, [id])

  const onDelete = cmd.onDelete && (() => { gone.current = true; cmd.onDelete!() })

  return (
    <div className={locked ? 'form-locked' : ''}>
      <div className="fs-title">{code}</div>

      {/* Высоту шапки задают ПОЛЯ. Колонка команд — один флекс-столбец во всю высоту:
          верхние команды идут построчно с полями, нижняя (корзина/«Скачать») прижата
          к низу и встаёт вровень с последним полем (§13.3). */}
      <div className="panel fs-head">
        <dl className="props">{fields}</dl>
        <FormCommands {...cmd}>
          <FormCornerCommand {...cmd} onDelete={onDelete} />
        </FormCommands>
      </div>
      {error && <div className="fh-error">ошибка: {error}</div>}

      {meta && <div className="fs-meta">{meta}</div>}

      {/* Дополнение стека той же карточной раскладкой (§13.1) — сейчас это панель
          бюджета на форме проекта: не список (табом быть не может) и не поле шапки. */}
      {extra}

      {/* Табы и тело — одна карточка: полоса табов вверху панели (§13.7). */}
      <div className="panel fs-body">
        <div className="fs-tabs">
          {tabs.map((t, i) => (
            <button key={t.key} className={'fh-ctl fs-tab' + (t === active ? ' on' : '')}
              onClick={() => setTab(i)}>
              <span className={'ci ci-' + t.icon} />
              <span className="lbl">{t.label}</span>
            </button>
          ))}
        </div>
        <div className="fs-list">{active?.content}</div>
      </div>
    </div>
  )
}
