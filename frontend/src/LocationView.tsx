// Витрина волны 13 Ф4: экран места хранения / Location. Волна 27: режим «Склады» стал
// «Локациями» (склад — это теперь список партий), снято текстовое «Вид»; один из мест —
// Центральный склад (синглтон: переименовать можно, удалить нельзя, корзины у него нет).
// Таб «Ордера» — требования и перемещения с участием места.
// ДНК места (код/описание) — мутабельная, правится под интерфейсным замком
// (§5, как Изделие). Специфичная часть — «что лежит на этом складе»: живые лоты
// с проектом-владельцем (проект — свойство лота). Удаление есть (корзина), но
// склад с движениями бережёт guard бэкенда — отказ, а не каскад.
//
// Волна 19 (Ф12c): форма по канону §13 — один таб «На складе». Вложений у Места нет
// (§13.8: заводим, когда заболит), фиксации тоже — в колонке команд остаются режим
// показа и корзина.
import { useEffect, useState } from 'react'
import { api, type LocationForm } from './api'
import { ORDER_LABEL, type OrderKind } from './orders'
import { num, count, sumByUom, LotGlyph } from './status'
import { useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { MoneyBlock } from './StatPanel'
import { Field, TextField } from './FormField'
import { EntityLink } from './EntityLink'
import { ask } from './dialog'

export function LocationView({ locationId, isNew, openItem, openLot, openOrder, onChanged,
  onDeleted }: {
  locationId: number
  isNew: boolean
  openItem: (id: number) => void
  openLot: (id: number) => void
  openOrder: (kind: OrderKind, id: number) => void
  onChanged?: () => void
  onDeleted?: () => void
}) {
  const [d, setD] = useState<LocationForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { unlocked, toggle } = useFormLock(locationId, isNew)   // §5: существующее — в просмотре

  useEffect(() => {
    setD(null); setErr(null)
    api.location(locationId).then(setD).catch(e => setErr(String(e)))
  }, [locationId])

  const run = (p: Promise<LocationForm>) => {
    setBusy(true); setErr(null)
    p.then(next => { setD(next); onChanged?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Удаление склада (WAVE14 Ф2) под замком: confirm + friendly-guard (склад с движениями).
  const del = async () => {
    if (!d || !(await ask({ title: `Удалить локацию «${d.code}»?`, verb: 'Удалить', icon: 'ci-trash', danger: true }))) return
    setBusy(true); setErr(null)
    api.deleteLocation(d.id).then(() => { onChanged?.(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !d) return <div className="empty">Ошибка: {err}</div>
  if (!d) return <div className="empty">Загрузка…</div>

  const locked = !unlocked          // фиксации у справочника нет (§5) — только замок формы

  const tabs: FormTab[] = [
    { key: 'stock', label: 'Склад', icon: 'layers',
      content: d.stock.length === 0
        ? <div className="tab-empty">{d.central
            ? 'Пусто — всё пришедшее выдано Требованиями. Так и должно быть.'
            : 'Пусто — на этом месте нет живых партий.'}</div>
        : <table className="grid">
            <thead><tr>
              <th className="rn">№</th><th className="gl" /><th className="c-key">Партия</th>
              <th className="c-fit">Изделие</th><th className="c-desc">Описание</th>
              <th className="c-fit">Проект</th>
              <th className="num">Остаток</th><th className="uom">Ед.</th>
            </tr></thead>
            <tbody>{d.stock.map((l, i) => (
              <tr key={l.lot_id} className="row">
                <td className="rn">{i + 1}</td>
                <td className="gl"><LotGlyph native={l.item_native} liveQty={l.qty}
                  central={d.central} /></td>
                <td className="c-key">
                  <EntityLink kind="lot" id={l.lot_id} open={openLot}>{l.lot_label}</EntityLink></td>
                <td className="c-fit">
                  <EntityLink kind="item" id={l.item_id} open={openItem}>
                    {l.item_code}</EntityLink></td>
                <td className="c-desc">
                  <span className="cell-ellip" title={l.item_description}>{l.item_description}</span></td>
                <td className="c-fit code">{l.project_code}</td>
                <td className="num">{num(l.qty)}</td>
                <td className="uom">{l.uom}</td>
              </tr>))}</tbody>
          </table> },
    { key: 'orders', label: 'Ордера', icon: 'notebook',
      content: d.orders.length === 0
        ? <div className="tab-empty">Требований и перемещений с этим местом ещё не было.</div>
        : <table className="grid">
            <thead><tr>
              <th className="rn">№</th><th className="c-fit c-date">Дата</th>
              <th className="c-key">Ордер</th><th className="c-fit c-cp">Вид</th>
              <th className="c-fit">Проект</th>
              <th className="num" title="приехало на это место">Приход</th>
              <th className="num" title="уехало с этого места">Расход</th>
            </tr></thead>
            <tbody>{d.orders.map((o, i) => (
              <tr key={o.id} className="row">
                <td className="rn">{i + 1}</td>
                <td className="c-fit c-date">{o.date ?? ''}</td>
                <td className="c-key">
                  <EntityLink kind={o.kind as OrderKind} id={o.id}
                    open={id => openOrder(o.kind as OrderKind, id)}>{o.label}</EntityLink>
                  {!o.locked && <span className="hint"> · черновик</span>}</td>
                <td className="c-fit c-cp">{ORDER_LABEL[o.kind as OrderKind] ?? o.kind}</td>
                <td className="c-fit code">{o.project_code}</td>
                <td className="num">{o.qty_in ? num(o.qty_in) : ''}</td>
                <td className="num">{o.qty_out ? num(o.qty_out) : ''}</td>
              </tr>))}</tbody>
          </table> },
  ]

  return (
    <FormShell
      id={d.id} code={d.code} entity="локацию" locked={locked} error={err}
      // Мета (§13.6): счёт по табам + итог в натуре по единицам. Описание не повторяем
      // — оно в полях.
      meta={<>
        {count(d.stock.length, 'партия', 'партии', 'партий')}
        {sumByUom(d.stock).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(d.orders.length, 'ордер', 'ордера', 'ордеров')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      // Центральный не удаляется (движок откажет) — корзину ему не рисуем вовсе.
      onDelete={d.central ? undefined : del}
      fields={<>
        <TextField label="Код" code value={d.code} locked={locked} busy={busy}
          onCommit={v => run(api.updateLocation(d.id, { code: v }))}
          validate={v => v.trim() !== ''} />
        <TextField label="Описание" wide value={d.description} locked={locked} busy={busy}
          onCommit={v => run(api.updateLocation(d.id, { description: v }))}
          validate={v => v.trim() !== ''} />
        {d.central && <Field label="Роль" locked
          view="Центральный склад — сюда приходят поставки, отсюда выдают Требованием" wide />}
      </>}
      // Блок «Деньги» (волна 26): ★ лежит на сумму — живые остатки партий на этом месте.
      extra={<MoneyBlock label="лежит на сумму" value={d.total_cost}
        title="Стоимость живых остатков партий на этом месте хранения" />}
      tabs={tabs}
    />
  )
}
