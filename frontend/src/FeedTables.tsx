// Ленты документов — таблицы, которые одинаковы у РАЗНЫХ форм (волна 21).
//
// Закупки, заказы и ордера просматривают в двух разрезах: «у кого покупаем» (форма
// контрагента) и «что я вёл» (форма аккаунта). Вопросы разные, а строка одна и та же —
// движок и считает её одной функцией (`_procurement_rows` / `_purchase_rows` берут
// queryset). Держать две копии таблицы значило бы поддерживать две; отсюда этот модуль.
//
// Пустой таб — своим текстом от места применения (`empty`): «закупок-планов на этого
// контрагента нет» и «вы ещё не вели закупок» — это разные сообщения, и обобщать их до
// «нет данных» значит потерять единственное, что в пустом табе полезно.
import type { AccountDocumentRow, FeedProcurementRow, FeedPurchaseRow,
  FeedReceiptRow } from './api'
import { CounterpartyRef, money, num, StatusGlyph } from './status'
import { viewDate } from './FormField'
import { ORDER_LABEL, type OrderKind } from './orders'
import { EntityLink } from './EntityLink'

// Лента закупок-планов. Глиф = фиксация плана (своей оси покрытия у него нет).
export function ProcurementFeed({ rows, empty, open }: {
  rows: FeedProcurementRow[]; empty: string; open: (id: number) => void
}) {
  if (rows.length === 0) return <div className="tab-empty">{empty}</div>
  return (
    <table className="grid">
      <thead><tr>
        <th className="rn">№</th><th className="gl" /><th className="c-key">Закупка</th>
        <th className="c-desc">Описание</th><th className="c-date">Дата</th>
        <th className="num">Строк</th>
        <th className="num">Кол-во</th>
      </tr></thead>
      <tbody>{rows.map((p, i) => (
        <tr key={p.id} className="row">
          <td className="rn">{i + 1}</td>
          <td className="gl"><StatusGlyph locked={p.locked} /></td>
          <td className="c-key">
            <EntityLink kind="procurement" id={p.id} open={open}>
              {p.code || `Закупка #${p.id}`}</EntityLink></td>
          <td className="c-desc">
            <span className="cell-ellip" title={p.description}>{p.description}</span></td>
          <td className="c-date">
            {p.date ? viewDate(p.date) : ''}</td>
          <td className="num">{p.lines}</td>
          <td className="num">{num(p.qty)}</td>
        </tr>
      ))}</tbody>
    </table>
  )
}

// Разрез ленты — чья это форма (2026-08-28). Вопрос к строке разный, и от него
// зависят ровно две колонки: ВТОРАЯ СТОРОНА (у контрагента — проект, у проекта —
// поставщик) и хвост заказа (у контрагента — сколько штук взяли у него, у проекта —
// во сколько это проекту обходится). Всё остальное — одна таблица на оба места.
export type FeedSide = 'counterparty' | 'project'

// Лента заказов: глиф = замок (фиксация), ЦВЕТ = покрытие лотами — тот же словарь
// ✓/●/▲, что в списке режима «Заказы». Видно, что ещё не довезли.
export function PurchaseFeed({ rows, empty, open, openCounterparty, side = 'counterparty' }: {
  rows: FeedPurchaseRow[]; empty: string; open: (id: number) => void
  openCounterparty?: (id: number) => void
  side?: FeedSide
}) {
  if (rows.length === 0) return <div className="tab-empty">{empty}</div>
  const byProject = side === 'project'
  return (
    <table className="grid">
      <thead><tr>
        <th className="rn">№</th><th className="gl" /><th className="c-key">Заказ</th>
        <th className="c-desc">Описание</th>
        <th className="c-cp">{byProject ? 'Поставщик' : 'Проект'}</th>
        {/* Своего номера у заказа нет — колонка стоит ПУСТОЙ, чтобы дата и всё правее
            неё держались той же вертикали, что в ленте поставок соседнего таба. */}
        <th className="c-no" />
        <th className="c-date">Дата</th>
        <th className="num c-count">Строк</th>
        {/* Деньги заказа — ОЦЕНКА (`Σ qty × estimated_cost`), факт рождается только в
            поставке. Пометки «сумма неполна» здесь НЕТ (правка Ивана 2026-08-28): в
            ленте она шумит, а её место — форма заказа, где с ценами и работают. */}
        <th className="num c-money">{byProject ? 'Цена' : 'Кол-во'}</th>
      </tr></thead>
      <tbody>{rows.map((p, i) => (
        <tr key={p.id} className="row">
          <td className="rn">{i + 1}</td>
          <td className="gl">
            {/* Волна 24: чистый замок, как в списке «Заказы» — обязательство, не поставка. */}
            <StatusGlyph locked={p.locked} /></td>
          <td className="c-key">
            <EntityLink kind="purchase" id={p.id} open={open}>
              {p.code || `Заказ #${p.id}`}</EntityLink></td>
          <td className="c-desc">
            <span className="cell-ellip" title={p.description}>{p.description}</span></td>
          <td className="c-cp">
            {byProject
              ? <CounterpartyRef code={p.contractor_code} name={p.contractor_name}
                  id={p.contractor_id} open={openCounterparty} />
              : <span className="code">{p.project_code}</span>}</td>
          <td className="c-no" />
          <td className="c-date">
            {p.date ? viewDate(p.date) : ''}</td>
          <td className="num c-count">{p.lines}</td>
          <td className="num c-money">{byProject ? money(p.estimate) : num(p.qty)}</td>
        </tr>
      ))}</tbody>
    </table>
  )
}

// Лента поставок — УПД в разрезе «кто привёз» (контрагент) или «что приехало в проект».
// Ссылка — по КОДУ (он есть всегда, фолбэк «Поставка 12»): № УПД у только что
// рождённой пуст, и ссылка на него была бы пустотой (та же правка, что Ф6).
export function ReceiptFeed({ rows, empty, open, openCounterparty, side = 'counterparty' }: {
  rows: FeedReceiptRow[]; empty: string; open: (id: number) => void
  openCounterparty?: (id: number) => void
  side?: FeedSide
}) {
  if (rows.length === 0) return <div className="tab-empty">{empty}</div>
  const byProject = side === 'project'
  return (
    <table className="grid">
      <thead><tr>
        <th className="rn">№</th><th className="gl" /><th className="c-key">Поставка</th>
        <th className="c-desc">Описание</th>
        <th className="c-cp">{byProject ? 'Поставщик' : 'Проект'}</th>
        <th className="c-no">{byProject ? '№' : '№ УПД'}</th>
        <th className="c-date">Дата</th>
        <th className="num c-count">Партий</th>
        {/* Сумма поставки — ФАКТ по партиям (`Σ cost` из УПД, волна 26). */}
        <th className="num c-money">Сумма</th>
      </tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={r.id} className="row">
          <td className="rn">{i + 1}</td>
          <td className="gl"><StatusGlyph locked={r.locked} /></td>
          <td className="c-key">
            <EntityLink kind="receipt" id={r.id} open={open}>
              {r.code || `Поставка #${r.id}`}</EntityLink></td>
          <td className="c-desc">
            <span className="cell-ellip" title={r.description}>{r.description}</span></td>
          <td className="c-cp">
            {byProject
              ? <CounterpartyRef code={r.contractor_code} name={r.contractor_name}
                  id={r.contractor_id} open={openCounterparty} />
              : <span className="code">{r.project_code}</span>}</td>
          <td className="c-no code">{r.number || <span className="hint">не задан</span>}</td>
          <td className="c-date">
            {r.date ? viewDate(r.date) : ''}</td>
          <td className="num c-count">{r.lots}</td>
          <td className="num c-money">{money(r.total)}</td>
        </tr>
      ))}</tbody>
    </table>
  )
}

// Лента ордеров — ОДИН смешанный фид семи видов с колонкой типа, как список режима
// «Ордера». Счётчиков в строке нет: общей меры у семи видов не существует (у поставки
// объём это партии, у передачи — строки), а «сколько всего» живёт в мете формы.
export function DocumentFeed({ rows, empty, open }: {
  rows: AccountDocumentRow[]; empty: string; open: (kind: OrderKind, id: number) => void
}) {
  if (rows.length === 0) return <div className="tab-empty">{empty}</div>
  return (
    <table className="grid">
      <thead><tr>
        <th className="rn">№</th><th className="gl" /><th className="c-key">Ордер</th>
        <th className="c-fit">Тип</th><th className="c-desc">Описание</th>
        <th className="c-fit">Проект</th><th className="c-date">Дата</th>
      </tr></thead>
      <tbody>{rows.map((d, i) => (
        <tr key={d.id} className="row">
          <td className="rn">{i + 1}</td>
          <td className="gl"><StatusGlyph locked={d.locked} /></td>
          {/* Ссылка — по КОДУ (он есть всегда, фолбэк «Поставка 12»); номер у только что
              рождённого пуст, и ссылка на него была бы пустотой. */}
          <td className="c-key">
            <EntityLink kind={d.kind} id={d.id} open={id => open(d.kind, id)}>
              {d.code || `${ORDER_LABEL[d.kind]} #${d.id}`}</EntityLink></td>
          <td className="c-fit">{ORDER_LABEL[d.kind]}</td>
          <td className="c-desc">
            <span className="cell-ellip" title={d.description}>{d.description}</span></td>
          <td className="c-fit code">{d.project_code}</td>
          <td className="c-date">
            {d.date ? viewDate(d.date) : ''}</td>
        </tr>
      ))}</tbody>
    </table>
  )
}
