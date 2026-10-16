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
// 2026-08-19 витрина встала и в форму ЗАКАЗА; волна 24 её оттуда сняла — планируют в
// закупке, а не в заказе («отучить планировать в Заказе», решение Ивана). Закупка
// однопроектная, область счёта — её проект.
import { useEffect, useState, type ReactNode } from 'react'
import { api, type Demand } from './api'
import { NeedHead, NeedRow, NeedSums, needPass, useNeedFilters } from './NeedTable'
import { useCategoryFilter } from './ColumnFilter'

// Состояние витрины: перечитывается на `rev` (мутации формы — взяли позицию, убрали
// строку, сменился проект), как и распределение.
export function useDemand(procurementId: number, rev: number) {
  const [d, setD] = useState<Demand | null>(null)
  const [err, setErr] = useState<string | null>(null)

  // Сменилась закупка — прежние данные и ошибка ей не принадлежат (см. `useAllocation`).
  useEffect(() => { setD(null); setErr(null) }, [procurementId])
  useEffect(() => {
    api.procurementDemand(procurementId)
      .then(next => { setD(next); setErr(null) })
      .catch(e => setErr(String(e)))
  }, [procurementId, rev])

  // `key` — ключ сброса фильтров колонок: сменился документ — и вопросы к нему другие.
  return { d, err, key: `procurement:${procurementId}` }
}

export type DemandState = ReturnType<typeof useDemand>

export function DemandRows({ st, editable, empty, openItem, take }: {
  st: DemandState
  editable: boolean                              // документ правится — можно брать позиции
  empty: ReactNode                               // пусто = пусто: почему именно, знает форма
  openItem: (id: number) => void
  take: (itemId: number) => void                 // взять позицию в документ (количество 0)
}) {
  const { d, err, key } = st
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
      <NeedSums rows={shown} acts />
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
                ? <span className="fh-ctl icon is-state" title="уже в строках закупки">
                    <span className="ci ci-check" /></span>
                : editable
                  ? <button className="fh-ctl icon" title="Взять позицию в закупку"
                      onClick={() => take(r.component_id)}>
                      <span className="ci ci-add" /></button>
                  : null} />
          ))}
    </div>
  )
}
