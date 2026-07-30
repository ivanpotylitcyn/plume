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
import type { AccountDocumentRow, FeedProcurementRow, FeedPurchaseRow } from './api'
import { num, StatusGlyph, statusTone } from './status'
import { viewDate } from './FormField'
import { ORDER_LABEL, type OrderKind } from './orders'

// Лента закупок-планов. Глиф = фиксация плана (своей оси покрытия у него нет).
export function ProcurementFeed({ rows, empty, open }: {
  rows: FeedProcurementRow[]; empty: string; open: (id: number) => void
}) {
  if (rows.length === 0) return <div className="tab-empty">{empty}</div>
  return (
    <table className="grid">
      <thead><tr>
        <th className="gl" /><th className="c-key">Закупка</th>
        <th className="c-desc">Описание</th><th className="c-fit">Дата</th>
        <th className="num">Строк</th>
        <th className="num">Кол-во</th>
      </tr></thead>
      <tbody>{rows.map(p => (
        <tr key={p.id} className="row">
          <td className="gl"><StatusGlyph locked={p.locked} /></td>
          <td className="c-key">
            <a className="link" onClick={() => open(p.id)}>
              {p.code || `Закупка #${p.id}`}</a></td>
          <td className="c-desc">
            <span className="cell-ellip" title={p.description}>{p.description}</span></td>
          <td className="c-fit">
            {p.date ? viewDate(p.date) : ''}</td>
          <td className="num">{p.lines}</td>
          <td className="num">{num(p.qty)}</td>
        </tr>
      ))}</tbody>
    </table>
  )
}

// Лента заказов: глиф = замок (фиксация), ЦВЕТ = покрытие лотами — тот же словарь
// ✓/●/▲, что в списке режима «Заказы». Видно, что ещё не довезли.
export function PurchaseFeed({ rows, empty, open }: {
  rows: FeedPurchaseRow[]; empty: string; open: (id: number) => void
}) {
  if (rows.length === 0) return <div className="tab-empty">{empty}</div>
  return (
    <table className="grid">
      <thead><tr>
        <th className="gl" /><th className="c-key">Заказ</th>
        <th className="c-desc">Описание</th><th className="c-fit">Проект</th>
        <th className="c-fit">Дата</th>
        <th className="num">Строк</th>
        <th className="num">Кол-во</th>
      </tr></thead>
      <tbody>{rows.map(p => (
        <tr key={p.id} className="row">
          <td className="gl">
            <StatusGlyph locked={p.locked} tone={statusTone(p.coverage)} /></td>
          <td className="c-key">
            <a className="link" onClick={() => open(p.id)}>
              {p.code || `Заказ #${p.id}`}</a></td>
          <td className="c-desc">
            <span className="cell-ellip" title={p.description}>{p.description}</span></td>
          <td className="c-fit code">{p.project_code}</td>
          <td className="c-fit">
            {p.date ? viewDate(p.date) : ''}</td>
          <td className="num">{p.lines}</td>
          <td className="num">{num(p.qty)}</td>
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
        <th className="gl" /><th className="c-key">Ордер</th>
        <th className="c-fit">Тип</th><th className="c-desc">Описание</th>
        <th className="c-fit">Проект</th><th className="c-fit">Дата</th>
      </tr></thead>
      <tbody>{rows.map(d => (
        <tr key={d.id} className="row">
          <td className="gl"><StatusGlyph locked={d.locked} /></td>
          {/* Ссылка — по КОДУ (он есть всегда, фолбэк «Поставка 12»); номер у только что
              рождённого пуст, и ссылка на него была бы пустотой. */}
          <td className="c-key">
            <a className="link" onClick={() => open(d.kind, d.id)}>
              {d.code || `${ORDER_LABEL[d.kind]} #${d.id}`}</a></td>
          <td className="c-fit">{ORDER_LABEL[d.kind]}</td>
          <td className="c-desc">
            <span className="cell-ellip" title={d.description}>{d.description}</span></td>
          <td className="c-fit code">{d.project_code}</td>
          <td className="c-fit">
            {d.date ? viewDate(d.date) : ''}</td>
        </tr>
      ))}</tbody>
    </table>
  )
}
