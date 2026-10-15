// Витрина ПОТРЕБНОСТИ — одна на продукт (вынесена из `ProjectView` 2026-08-11).
//
// Один и тот же свод покупных листьев показывают две формы, и это сознательно ОДИН
// экран, а не два похожих:
//   · проект — по своим приборам («хватает ли мне»);
//   · закупка — по всем проектам своего охвата («что брать в план»).
// Колонки, фильтры, тон и порядок обязаны совпадать: человек читает их одним навыком.
// Разница между формами — ровно в командной колонке: у проекта её нет (витрина
// read-only), у закупки в ней «взять в план» / отметка «уже взято».
//
// Пять чисел вместо трёх сегментов разбора (2026-08-05). Разбор клампован потребностью,
// поэтому перебор в нём невидим: заказали 10 при нужде 6 — сегмент всё равно 6. Здесь
// все члены сырые, а «Баланс» — их невязка со знаком: минус не хватает, плюс запас.
// Порядок колонок = убывающая готовность (впаяно → лежит → едет → нет), то есть прежняя
// ось ✓●▲, разложенная на четыре члена. Заголовки сокращены до 4–6 знаков: полное
// «Скомплектовано» распирало колонку под слово, которое ни одно число не заполняет.
import { useState, type ReactNode } from 'react'
import type { DeficitComponent, Status } from './api'
import { Balance, balanceTitle, money, num, ItemGlyph } from './status'
import { ColumnFilter } from './ColumnFilter'
import { EntityLink } from './EntityLink'

// ─── Фильтры колонок свода (2026-08-05) ───
//
// Свод — это весь закупочный состав, сотни строк; вопросы к нему всегда узкие: «что не
// заказано», «что уже лежит», «где перебор». Поэтому фильтр живёт в ЗАГОЛОВКЕ колонки —
// там же, где число, к которому он относится, — и не заводит отдельной панели над
// таблицей. Знак — тот же раскрыватель, что везде в продукте.
//
// Словарь значений: у членов «есть/пусто» (наличие), у баланса — три его состояния,
// названные тем же языком, каким мы говорим о них в подсказках и журнале: не хватает /
// впритык / запас.
type MemberFilter = 'any' | 'zero' | 'some'
type BalanceFilter = 'any' | 'short' | 'even' | 'surplus'

const MEMBER_OPTS: [string, string][] = [
  ['any', 'все'], ['some', 'есть'], ['zero', 'пусто'],
]
const BALANCE_OPTS: [string, string][] = [
  ['any', 'все'], ['short', 'не хватает'], ['even', 'впритык'], ['surplus', 'запас'],
]

export interface NeedFilters {
  kitted: MemberFilter; in_stock: MemberFilter; on_order: MemberFilter
  balance: BalanceFilter
}
const NO_FILTERS: NeedFilters = {
  kitted: 'any', in_stock: 'any', on_order: 'any', balance: 'any',
}
export interface FilterBar extends NeedFilters {
  set: (key: keyof NeedFilters, value: string) => void
}

// Состояние фильтров — вью, на сервер не ходит: строки уже все здесь, а вопрос к ним
// меняется чаще, чем данные. `reset` — смена документа (форма показывает другой свод).
export function useNeedFilters(resetKey?: unknown): FilterBar {
  const [f, setF] = useState<NeedFilters>(NO_FILTERS)
  const [key, setKey] = useState(resetKey)
  if (key !== resetKey) { setKey(resetKey); setF(NO_FILTERS) }
  return { ...f, set: (k, v) => setF(prev => ({ ...prev, [k]: v })) }
}

function memberPass(v: number, f: MemberFilter) {
  return f === 'any' || (f === 'zero' ? v === 0 : v !== 0)
}

export function needPass(c: DeficitComponent, f: NeedFilters) {
  return memberPass(c.kitted, f.kitted)
    && memberPass(c.in_stock, f.in_stock)
    && memberPass(c.on_order, f.on_order)
    && (f.balance === 'any'
      || (f.balance === 'short' ? c.balance < 0
        : f.balance === 'even' ? c.balance === 0 : c.balance > 0))
}

// Шапка колонок. Совпадает по сетке со строкой прибора: код↔Компонент, потребность↔Потр.
//
// `filters` — только у свода: в аккордеоне прибора фильтровать нечего (там состав одного
// изделия, и дыры в дереве читались бы как ошибка состава). `tree` — ведущая колонка
// отступает на раскрыватель. `acts` — у строк есть командная колонка.
//
// «Ед.» стоит ПЕРЕД командами: единица квалифицирует всю строку — все пять чисел в ней
// одной размерности, — а не примыкает к одному числу (решение Ивана 2026-08-05).
export function NeedHead({ f, lead = 'Компонент', catHead, tree, acts }: {
  f?: FilterBar
  lead?: string                 // подпись ведущей колонки: она называет СУЩНОСТЬ (§7a)
  catHead?: ReactNode           // фильтр по классу изделия — в ячейке своей подписи
  tree?: boolean; acts?: boolean
}) {
  return (
    <div className={'prow prow--head' + (tree ? ' head--tree' : '')}>
      <span className="tree-cell">{lead}{catHead}</span>
      <span>Описание</span>
      <span className="pnum" title="потребность: разузлование BOM на все приборы">
        Потр.</span>
      <span className="pnum" title="скомплектовано: впаяно в изделия проекта">
        Компл.{f && <ColumnFilter opts={MEMBER_OPTS} value={f.kitted}
          onPick={v => f.set('kitted', v)} />}</span>
      <span className="pnum" title="на складе: остаток лотов проекта">
        Склад{f && <ColumnFilter opts={MEMBER_OPTS} value={f.in_stock}
          onPick={v => f.set('in_stock', v)} />}</span>
      <span className="pnum" title="в заказе: ещё не приехало по зафиксированным заказам">
        Заказ{f && <ColumnFilter opts={MEMBER_OPTS} value={f.on_order}
          onPick={v => f.set('on_order', v)} />}</span>
      <span className="pnum" title="баланс: (компл. + склад + заказ) − потребность">
        Баланс{f && <ColumnFilter opts={BALANCE_OPTS} value={f.balance}
          onPick={v => f.set('balance', v)} />}</span>
      <span className="puom" title="единица измерения строки">Ед.</span>
      {acts && <span />}
    </div>
  )
}

// ─── Суммы над колонками (волна 23, Ф2) ───
//
// «Сколько стоит то, что показано»: строка над шапкой, по ОТФИЛЬТРОВАННЫМ строкам —
// фильтр по категории даёт деньги на детали, электронику, крепёж по отдельности. Это и
// было нужно для планирования закупок (решения Ивана 2026-10-15):
//   · Потр., Заказ, Баланс — по оценке Item (факта тут нет и быть не может);
//   · Компл., Склад — по факту партий (цена УПД / себестоимость);
//   · над Балансом — ТОЛЬКО минусы, «предстоит купить»: излишек одной позиции не
//     покупает другую, а плюсы и нули уже учтены в Компл./Складе/Заказе.
// В тысячах, единица — в колонке «Ед.» («тыс ₽», правка Ивана: единица квалифицирует
// всю строку, как «шт» у строк): с суффиксом «тыс» в ячейке число с глифом не влезало в
// 74px (замер); точное число в рублях — под курсором.
// Глифы после сумм — те же, что у строк: так суммы встают ровно над числами.
function kRub(x: number): string {
  if (x === 0) return '0'
  const k = x / 1000
  return (Math.abs(k) < 10
    ? k.toLocaleString('ru-RU', { maximumFractionDigits: 1 })
    : Math.round(k).toLocaleString('ru-RU'))
}

function SumCell({ value, glyph, tone, what }: {
  value: number; glyph?: string; tone?: string; what: string
}) {
  return (
    <span className="pnum" title={`${what}: ${money(value)}`}>
      {kRub(value)}
      {glyph && <span className={`ci sg ci-${glyph} sg-${value ? tone : 'none'}`} />}
    </span>
  )
}

export function NeedSums({ rows, acts }: { rows: DeficitComponent[]; acts?: boolean }) {
  let need = 0, kitted = 0, stock = 0, order = 0, short = 0
  const unestimated: string[] = []
  for (const r of rows) {
    kitted += r.kitted_cost
    stock += r.in_stock_cost
    if (r.price == null) { if (r.need || r.on_order) unestimated.push(r.component_code); continue }
    need += r.need * r.price
    order += r.on_order * r.price
    if (r.balance < 0) short += r.balance * r.price
  }
  return (
    <div className="prow prow--sums">
      <span className="tree-cell">Оценка</span>
      {/* Без ▲ (правка Ивана): треугольник занят статусами — здесь просто красный текст. */}
      <span className="name">
        {unestimated.length > 0 &&
          <span className="unest" title={'без оценки: ' + unestimated.join(', ')}>
            {unestimated.length} поз. без оценки — суммы неполны</span>}
      </span>
      <SumCell value={need} what="потребность по оценке" />
      <SumCell value={kitted} glyph="notebook" tone="ok" what="впаяно, по цене партий" />
      <SumCell value={stock} glyph="layers" tone="ok" what="на складе, по цене партий" />
      <SumCell value={order} glyph="package" tone="wip" what="в заказе, по оценке" />
      <SumCell value={short} glyph="warning" tone="order"
        what="предстоит купить (только минусы баланса), по оценке" />
      <span className="puom">тыс ₽</span>
      {acts && <span />}
    </div>
  )
}

// Число члена баланса с глифом ПОСЛЕ него (правка Ивана 2026-08-05). Глиф впереди
// плясал по горизонтали: числа разной ширины при выключке вправо сдвигали его на
// каждой строке, и колонка глифов шла зигзагом. За числом он встаёт на правую кромку —
// вертикальный строй ровный, а числа по-прежнему выключены вправо.
//
// Форма глифа — вид члена (что это), цвет — его роль в покрытии: впаяно и склад
// зелёные (нужда закрыта), заказ оранжевый (закрыта обещанием). НОЛЬ гасим до
// нейтрального: глиф светит, когда за ним что-то есть, иначе колонка нулей шумит.
export function Member({ glyph, tone, value, title }: {
  glyph: string; tone: string; value: number; title: string
}) {
  return (
    <span className="pnum" title={title}>
      {num(value)}<span className={`ci sg ci-${glyph} sg-${value ? tone : 'none'}`} />
    </span>
  )
}

// Числовой хвост строки-листа: четыре члена + баланс. Один и тот же в дереве прибора и
// в сводной «Потребности» — колонки обязаны совпадать, поэтому и разметка одна.
export function BalanceCells({ code, need, kitted, inStock, onOrder, balance, status,
  anomaly }: {
  code: string; need: number; kitted: number; inStock: number; onOrder: number
  balance: number; status: Status; anomaly?: boolean
}) {
  return (
    <>
      <Member glyph="notebook" tone="ok" value={kitted}
        title="впаяно в изделия проекта (зафиксированные комплектации)" />
      <span className="pnum" title="остаток лотов проекта на складах">
        {num(inStock)}
        {anomaly && <span className="anomaly" title="есть лот с отрицательным остатком">▲</span>}
        <span className={`ci sg ci-layers sg-${inStock ? 'ok' : 'none'}`} />
      </span>
      <Member glyph="package" tone="wip" value={onOrder}
        title="ещё не приехало по зафиксированным заказам проекта" />
      <span className="pnum">
        <Balance value={balance} status={status}
          title={balanceTitle(code, need, kitted, inStock, onOrder)} />
      </span>
    </>
  )
}

// Строка компонента в своде: те же пять чисел, read-only. Команда строки приходит
// СНАРУЖИ (`action`) — витрина сама ничего не умеет, она показывает и помогает выбрать.
// У проекта команды нет вовсе; у закупки это «взять в план» / отметка «уже взято».
export function NeedRow({ ln, openItem, action }: {
  ln: DeficitComponent; openItem: (id: number) => void; action?: ReactNode
}) {
  return (
    <div className="prow prow--comp">
      {/* `lead--item` — ведущая ячейка «глиф + код» в ТОЙ ЖЕ геометрии, что у строк
          компонентов в таблицах (§7a, 2026-08-11): один и тот же зазор глиф→код, где бы
          строка компонента ни стояла. Без модификатора здесь работал зазор дерева (5px),
          и «Потребность» начиналась теснее, чем состав изделия и строки заказа. */}
      <span className="tree-cell lead--item">
        <ItemGlyph native={ln.component_native} synced={ln.component_synced}
          locked={ln.component_locked} />
        <EntityLink kind="item" id={ln.component_id} open={openItem}>
          {ln.component_code}</EntityLink>
      </span>
      <span className="name">{ln.component_description}</span>
      <span className="pnum">{num(ln.need)}</span>
      <BalanceCells code={ln.component_code} need={ln.need} kitted={ln.kitted}
        inStock={ln.in_stock} onOrder={ln.on_order} balance={ln.balance}
        status={ln.status} anomaly={ln.anomaly} />
      <span className="puom">{ln.uom}</span>
      {action !== undefined && <span className="act">{action}</span>}
    </div>
  )
}
