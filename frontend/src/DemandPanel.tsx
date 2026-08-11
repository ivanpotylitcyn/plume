// Таб «Потребность» формы закупки (2026-08-11) — ТЕЛЕСКОП закупочного контура.
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
// команда «взять в план» и отметка «уже взято».
import { useEffect, useState } from 'react'
import { api, type ProcurementDemand } from './api'
import { NeedHead, NeedRow, needPass, useNeedFilters } from './NeedTable'
import { useCategoryFilter } from './ColumnFilter'

// Состояние витрины: перечитывается на `rev` (мутации формы — взяли позицию, убрали
// строку, поменялся охват), как и привязка.
export function useProcurementDemand(procurementId: number, rev: number) {
  const [d, setD] = useState<ProcurementDemand | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.procurementDemand(procurementId).then(setD).catch(e => setErr(String(e)))
  }, [procurementId, rev])

  return { d, err }
}

export type ProcurementDemandState = ReturnType<typeof useProcurementDemand>

export function DemandRows({ st, procurementId, editable, openItem, take }: {
  st: ProcurementDemandState
  procurementId: number
  editable: boolean                              // закупка правится — можно брать позиции
  openItem: (id: number) => void
  take: (itemId: number) => void                 // взять позицию в план (количество 0)
}) {
  const { d, err } = st
  const f = useNeedFilters(procurementId)
  // Фильтр по классу изделия — тот же движок, что во всех колонках «Компонент».
  const byCat = useCategoryFilter(d?.rows, r => r.component_category, procurementId)
  if (err) return <div className="anomaly">{err}</div>
  if (!d) return <div className="tab-empty">Загрузка…</div>
  // Пусто = пусто (Ф13): охват вычисляется из заказов закупки, и пока их нет — считать
  // нечего. Витрина говорит это прямо, а не показывает пустую таблицу.
  if (d.rows.length === 0)
    return <div className="tab-empty">
      Нет потребностей по охвату — заведите заказ под эту закупку.
    </div>
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
              action={r.in_plan
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
