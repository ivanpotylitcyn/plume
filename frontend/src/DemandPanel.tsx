// Таб «Потребность» ДОКУМЕНТА закупочного контура (2026-08-11) — ТЕЛЕСКОП.
//
// Пришёл на смену табу «К закупке» (волна 19, Ф13; а тот — экрану-фантому «Командный
// свод», у которого не было ни кода, ни замка). Прежняя витрина отвечала «сколько
// докупить» клампленным числом и предлагала мост «＋ в план» — взять сразу столько,
// сколько насчитано. Решение Ивана: витрина показывает состояние складов и заказов и
// помогает ВЫБРАТЬ ПОЗИЦИЮ, больше ничего. Сколько брать — вопрос другого масштаба, и
// на него отвечают «Строки»: там один компонент под микроскопом, с его балансом и
// раскладкой по заказам.
//
// Отсюда устройство: строки — та же `NeedTable`, что в «Потребности» проекта (одна
// витрина на продукт, разница только в области счёта), а своя здесь ровно одна колонка —
// команда «взять» и отметка «уже взято».
//
// 2026-08-19: витрина встала и в форму ЗАКАЗА, поэтому панель говорит о ДОКУМЕНТЕ, а не
// о закупке. Область счёта задаёт бэкенд (`kind`): у закупки — её охват, у заказа — его
// проект. Разница между формами — только в словах («в закупку» / «в заказ») и в тексте
// пустого состояния, который даёт сама форма: у закупки пусто значит «нет охвата», у
// заказа — «у проекта нет приборов».
import { useEffect, useState, type ReactNode } from 'react'
import { api, type Demand } from './api'
import { NeedHead, NeedRow, needPass, useNeedFilters } from './NeedTable'
import { useCategoryFilter } from './ColumnFilter'

// Вид документа-хозяина витрины. Он же выбирает ручку движка и падеж в подсказках —
// больше витрина о форме ничего не знает.
export type DemandKind = 'procurement' | 'purchase'
const ENTITY: Record<DemandKind, string> = {
  procurement: 'закупку', purchase: 'заказ',
}
const IN_LINES: Record<DemandKind, string> = {
  procurement: 'уже в строках закупки', purchase: 'уже в строках заказа',
}

// Состояние витрины: перечитывается на `rev` (мутации формы — взяли позицию, убрали
// строку, поменялся охват), как и привязка.
export function useDemand(kind: DemandKind, id: number, rev: number) {
  const [d, setD] = useState<Demand | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const load = kind === 'procurement' ? api.procurementDemand : api.purchaseDemand
    load(id).then(setD).catch(e => setErr(String(e)))
  }, [kind, id, rev])

  // `key` — ключ сброса фильтров колонок: сменился документ, значит и вопросы к нему
  // другие. Вид в ключе обязателен — id у закупки и заказа свои, и «#3» у них разные.
  return { d, err, kind, key: `${kind}:${id}` }
}

export type DemandState = ReturnType<typeof useDemand>

export function DemandRows({ st, editable, empty, openItem, take }: {
  st: DemandState
  editable: boolean                              // документ правится — можно брать позиции
  empty: ReactNode                               // пусто = пусто: почему именно, знает форма
  openItem: (id: number) => void
  take: (itemId: number) => void                 // взять позицию в документ (количество 0)
}) {
  const { d, err, kind, key } = st
  const f = useNeedFilters(key)
  // Фильтр по классу изделия — тот же движок, что во всех колонках «Компонент».
  const byCat = useCategoryFilter(d?.rows, r => r.component_category, key)
  if (err) return <div className="anomaly">{err}</div>
  if (!d) return <div className="tab-empty">Загрузка…</div>
  // Пусто = пусто (Ф13): считать нечего, и витрина говорит это прямо, а не показывает
  // пустую таблицу. Причина у форм разная — текст приходит от формы.
  if (d.rows.length === 0) return <div className="tab-empty">{empty}</div>
  const shown = byCat.shown.filter(r => needPass(r, f))
  return (
    <div className="pgrid pgrid--acts">
      <NeedHead f={f} catHead={byCat.head} acts />
      {shown.length === 0
        ? <div className="prow prow--comp prow--empty">
            <span>Ни одна строка не подходит под фильтры колонок.</span>
          </div>
        : shown.map(r => (
            <NeedRow key={r.component_id} ln={r} openItem={openItem}
              action={r.in_lines
                /* Взято — состояние, а не команда: глиф без кнопки и без тона. Цвета у
                   него нет намеренно (правка Ивана): зелёный означал бы «хорошо», а
                   здесь всего лишь «позиция уже в строках». Путь назад — корзина той
                   строки в «Строках», где её и завели. */
                ? <span className="fh-ctl icon is-state" title={IN_LINES[kind]}>
                    <span className="ci ci-check" /></span>
                : editable
                  ? <button className="fh-ctl icon" title={`Взять позицию в ${ENTITY[kind]}`}
                      onClick={() => take(r.component_id)}>
                      <span className="ci ci-add" /></button>
                  : null} />
          ))}
    </div>
  )
}
