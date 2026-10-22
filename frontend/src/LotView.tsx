// Волна 27: форма лота (партии) — главной учётной единицы склада. Решения Ивана
// 2026-10-21 (JOURNAL «Складской контур: интервью»):
//
// * Форма **целиком только для чтения**. Идентичность лота — два факта, введённые один раз
//   в origin-ордере: PN с коробки (`code`) и наименование из УПД (`description`). Править их
//   место — форма поставки (у прибора — комплектации), а не здесь: команд у формы нет.
// * **Шапка** — только однозначное: идентичность и якоря (изделие, проект, origin,
//   предшественник). Где лежит — не однозначно (бывает два места), поэтому разбивка по
//   локациям стоит в «Деньгах» у строки «Остаток».
// * **Деньги** — раскладка жизни: рождено = впаяно + передано + списано + переведено +
//   остаток, каждый член в рублях и штуках. Сумма сходится до копейки (движок).
// * **Табы**: История (`notebook` — ордера) · Применение (`rocket` — изделия) · Состав
//   (`chip`, только у лота-прибора — паспорт). Глифы — у режимов (§2).
import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { api, type DocRef, type LotCompositionRow, type LotForm, type LotRef } from './api'
import { FormShell, type FormTab } from './FormShell'
import { Field, viewDate } from './FormField'
import { MoneyBlock, Stat, StatGroup } from './StatPanel'
import { EntityLink } from './EntityLink'
import { LotGlyph, count, money, moneyCol, num } from './status'
import { ORDER_LABEL, type OrderKind } from './orders'

export function LotView({ lotId, openItem, openProject, openOrder, openLot }: {
  lotId: number
  openItem: (id: number) => void
  openProject: (id: number) => void
  openOrder: (kind: OrderKind, id: number) => void
  openLot: (id: number) => void
}) {
  const [d, setD] = useState<LotForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    setD(null); setErr(null)
    api.lot(lotId).then(setD).catch(e => setErr(String(e)))
  }, [lotId])

  if (err && !d) return <div className="empty">Ошибка: {err}</div>
  if (!d) return <div className="empty">Загрузка…</div>

  const m = d.money
  const uom = d.uom
  const doc = (r: DocRef) => (
    <EntityLink kind={r.kind as OrderKind} id={r.id}
      open={id => openOrder(r.kind as OrderKind, id)}>{r.label}</EntityLink>)
  const lot = (r: LotRef) => (
    <EntityLink kind="lot" id={r.id} open={openLot} title={r.description}>{r.label}</EntityLink>)
  const part = (label: string, p: { qty: number; cost: number }, title: string) => (
    <Stat label={label} value={money(p.cost)} dim={!p.qty} title={title}
      note={`${num(p.qty)} ${uom}`} />)
  const places = m.remaining.places.map(p => `${p.location_code} ${num(p.qty)}`).join(' · ')

  const tabs: FormTab[] = [
    { key: 'history', label: 'История', icon: 'notebook',
      content: d.history.length === 0
        ? <div className="tab-empty">
            {d.draft ? 'Партия ещё не на складе — её ордер не зафиксирован.' : 'Движений нет.'}</div>
        : <table className="grid">
            <thead><tr>
              <th className="rn">№</th><th className="c-date">Дата</th>
              <th className="c-name">Ордер</th><th className="c-cp">Вид</th>
              <th className="c-fit">Место</th>
              <th className="num">Кол-во</th><th className="uom">Ед.</th>
              <th className="num c-money">Сумма, ₽</th>
              <th className="c-desc">Связано</th>
            </tr></thead>
            <tbody>{d.history.map((r, i) => (
              <tr key={r.id} className="row">
                <td className="rn">{i + 1}</td>
                <td className="c-date">{r.document.date ? viewDate(r.document.date) : ''}</td>
                <td className="c-name">{doc(r.document)}</td>
                {/* Что ордер родил партию, читается из вида (поставка / комплектация /
                    инвентаризация / перевод) — подписью не дублируем, только подсказкой. */}
                <td className="c-cp" title={r.event === 'born' ? 'этим ордером партия родилась' : undefined}>
                  {ORDER_LABEL[r.document.kind as OrderKind] ?? r.document.kind}</td>
                <td className="c-fit code">{r.location_code}</td>
                <td className="num">{r.qty > 0 ? '+' : ''}{num(r.qty)}</td>
                <td className="uom">{uom}</td>
                <td className="num c-money">{moneyCol(r.cost)}</td>
                <td className="c-desc">{r.related.map((x, j) => (
                  <span key={x.id}>{j > 0 && ', '}{lot(x)}</span>))}</td>
              </tr>))}</tbody>
          </table> },
    { key: 'usage', label: 'Применение', icon: 'rocket',
      content: d.usage.length === 0
        ? <div className="tab-empty">В изделия партия ещё не уходила.</div>
        : <table className="grid">
            <thead><tr>
              <th className="rn">№</th><th className="c-date">Дата</th>
              <th className="c-name">Комплектация</th><th className="c-fit">Изделие</th>
              <th className="num">Впаяно</th><th className="uom">Ед.</th>
              <th className="num c-money">Сумма, ₽</th>
              <th className="c-desc">Партия изделия</th>
            </tr></thead>
            <tbody>{d.usage.map((r, i) => (
              <tr key={r.id} className="row">
                <td className="rn">{i + 1}</td>
                <td className="c-date">{r.document.date ? viewDate(r.document.date) : ''}</td>
                <td className="c-name">{doc(r.document)}</td>
                <td className="c-fit">{r.target_id
                  ? <EntityLink kind="item" id={r.target_id} open={openItem}>{r.target_code}</EntityLink>
                  : ''}</td>
                <td className="num">{num(r.qty)}</td>
                <td className="uom">{uom}</td>
                <td className="num c-money">{moneyCol(r.cost)}</td>
                <td className="c-desc">{r.devices.map((x, j) => (
                  <span key={x.id}>{j > 0 && ', '}{lot(x)}</span>))}</td>
              </tr>))}</tbody>
          </table> },
  ]
  if (d.composable) tabs.push({
    key: 'composition', label: 'Состав', icon: 'chip',
    content: d.composition.length === 0
      ? <div className="tab-empty">Комплектация не списала ни одной партии.</div>
      : <table className="grid">
          <thead><tr>
            <th className="rn">№</th><th className="gl" /><th className="c-key">Партия</th>
            <th className="c-fit">Изделие</th>
            <th className="num">Кол-во</th><th className="uom">Ед.</th>
            <th className="num c-money">Сумма, ₽</th>
          </tr></thead>
          <tbody><CompositionRows rows={d.composition} depth={0} lot={lot}
            openItem={openItem} /></tbody>
        </table>,
  })

  return (
    <FormShell
      // Титул — Part Number (2026-10-22, решение Ивана); пустой — заглушка «без PN».
      id={d.id} code={d.code} noCode="без PN" entity="партию" locked error={err}
      meta={<>
        {count(d.history.length, 'движение', 'движения', 'движений')}
        {' · '}{count(d.usage.length, 'комплектация', 'комплектации', 'комплектаций')}
      </>}
      fields={<>
        <Field label="Код (PN)" locked view={d.code} />
        <Field label="Наименование" locked wide view={d.description} />
        <Field label="Изделие" locked view={<>
          <LotGlyph native={d.item_native} liveQty={m.remaining.qty} draft={d.draft}
            central={m.remaining.places.some(p => p.location_central && p.qty > 0)} />{' '}
          <EntityLink kind="item" id={d.item_id} open={openItem}
            title={d.item_description}>{d.item_code}</EntityLink></>} />
        <Field label="Проект" locked view={
          <EntityLink kind="project" id={d.project_id} open={openProject}>{d.project_code}</EntityLink>} />
        <Field label="Откуда" locked view={<>
          {ORDER_LABEL[d.origin.kind as OrderKind] ?? d.origin.kind} {doc(d.origin)}
          {d.draft && <span className="hint"> · не зафиксирован</span>}</>} />
        {d.predecessor && <Field label="Предшественник" locked view={lot(d.predecessor)} />}
      </>}
      // Блок «Деньги»: главное — остаток (что лежит сегодня), поддержка — откуда он:
      // рождено и куда ушло. Члены сходятся с рождённым до копейки (движок).
      extra={<MoneyBlock label="остаток" value={m.remaining.cost}
        title="Стоимость живого остатка партии"
        note={`${num(m.remaining.qty)} ${uom}${places ? ` · ${places}` : ''}`}>
        <StatGroup>
          <Stat label="рождено" value={money(m.born.cost)}
            note={`${num(m.born.qty)} ${uom}` + (m.born.unit_cost != null
              ? ` · ${money(m.born.unit_cost)} за ${uom}` : '')}
            title="Стоимость и количество партии при рождении" />
          {part('впаяно', m.kitted, 'Ушло в изделия — зафиксированные комплектации')}
          {part('передано', m.transferred, 'Отгружено заказчикам')}
          {part('списано', m.written_off, 'Списано актами')}
          {part('переведено', m.reassigned, 'Переведено в другие проекты лотами-потомками')}
        </StatGroup>
      </MoneyBlock>}
      tabs={tabs}
    />
  )
}

// Паспорт прибора: лоты компонентов, списанные его комплектацией, ступенью вглубь по
// подсборкам (прибор из прибора) — тем же приёмом `.c-key.ind`, что дерево пеггинга.
function CompositionRows({ rows, depth, lot, openItem }: {
  rows: LotCompositionRow[]; depth: number
  lot: (r: LotRef) => ReactNode; openItem: (id: number) => void
}) {
  return <>{rows.map((r, i) => (
    <Fragment key={r.id}>
      <tr className="row">
        <td className="rn">{depth === 0 ? i + 1 : ''}</td>
        {/* Форма глифа — что это (изделие/компонент); цвета «как дела» в паспорте нет:
            здесь важно, ЧТО впаяно, а не сколько этой партии осталось. */}
        <td className="gl"><span className={`ci sg sg-none ci-${r.lot.item_native ? 'rocket' : 'chip'}`}
          title={r.lot.item_native ? 'партия изделия (подсборка)' : 'партия компонента'} /></td>
        <td className={'c-key' + (depth ? ' ind' : '')}>{lot(r.lot)}</td>
        <td className="c-fit">
          <EntityLink kind="item" id={r.lot.item_id} open={openItem}>{r.lot.item_code}</EntityLink></td>
        <td className="num">{num(r.qty)}</td>
        <td className="uom">{r.uom}</td>
        <td className="num c-money">{moneyCol(r.cost)}</td>
      </tr>
      <CompositionRows rows={r.children} depth={depth + 1} lot={lot} openItem={openItem} />
    </Fragment>))}</>
}
