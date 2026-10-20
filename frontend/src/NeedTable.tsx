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
import { Anomaly, Balance, Cost, balanceTitle, count, money, num, orderTitle, ItemGlyph } from './status'
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
      <span className="rn" title="номер строки — постоянный, фильтр его не меняет">№</span>
      <span className="tree-cell">{lead}{catHead}</span>
      <span className="name">Описание</span>
      {/* 2026-10-20 (правка Ивана): «Ед.» — сразу за описанием. Дальше идут числа в
          единицах строки, а над ними в строке «Деньги» — тысячи рублей без разрыва. */}
      <span className="puom" title="единица измерения строки">Ед.</span>
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
      <span className="pnum" title={'во сколько обходится строка: по счёту, где позиция уже под'
        + ' обязательством, остальное по оценке; оранжевые — строки, дающие 80% стоимости'}>
        Оценка, ₽</span>
      {acts && <span />}
    </div>
  )
}

// ─── Суммы над колонками (волна 23, Ф2) ───
//
// «Сколько стоит то, что показано»: строка над шапкой, по ОТФИЛЬТРОВАННЫМ строкам —
// фильтр по категории даёт деньги на детали, электронику, крепёж по отдельности. Это и
// было нужно для планирования закупок (решения Ивана 2026-10-15):
//   · Потр. — ЧИСТАЯ ПОТРЕБНОСТЬ (2026-10-20): нужда × оценка, без запаса;
//   · Оценка (хвостовая колонка, 2026-10-20; до того план стоял над «Потр.») — ПЛАН
//     позиций: потрачено + впереди (план закупки с запасом, сборка, нехватка) по оценке
//     (`PlanSumCell`); без фильтров сходится с «планом» шапки проекта до копейки, и
//     Компл. + Склад + Заказ + нехватка = Оценка. Рядом с «Потр.» — «сверх потребности»;
//   · Баланс — по оценке Item (факта у недостающего нет и быть не может);
//   · Компл., Склад — по факту партий (цена УПД / себестоимость);
//   · Заказ — обещанное по счёту, план и сборка по оценке (2026-10-19, см. `OrderSumCell`);
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

// Сумма над «Заказом» с раскладкой под курсором (волна 24, решение Ивана): обещанное
// (зафиксированные заказы, ещё не приехало — по счёту) и то, что ещё предстоит (план
// зафиксированных закупок сверх заказов, у производимого — незакрытая сборка; по оценке).
// Цвет — тот же словарь, что у ящика «Заказ»: зелёное — обязательство, жёлтое — на нас.
//
// ЯЧЕЙКА = СУММА РАСКЛАДКИ, без остатка (багрепорт 2026-10-19: «сумма не сходится»). До
// этого ячейка считала все количества «Заказа» по оценке, а «оплачиваем» — все
// обязательства по счёту, ВКЛЮЧАЯ приехавшее: приехавшее уже стоит в «Складе»/«Компл.»
// по цене партии, и сумма над «Заказом» не сходилась с собственной раскладкой. Теперь
// обе стороны — одни и те же количества колонки; все обязательства целиком — это
// «потрачено» в панели бюджета проекта.
//
// Тон ящика — ТО ЖЕ правило, что у строк (`BalanceCells`), сложенное по показанным строкам
// (багрепорт 2026-10-19: фильтр по крепежу — все ящики зелёные, а у суммы жёлтый): жёлтый,
// если хоть у одной строки есть доля «на нас» (план / сборка), иначе зелёный. Признак —
// по КОЛИЧЕСТВАМ (`ours`), а не по деньгам: позиция плана без оценки тоже «на нас».
function OrderSumCell({ paid, unpaid, unpaidMissing, ours }: {
  paid: number; unpaid: number; unpaidMissing: number; ours: boolean
}) {
  const value = paid + unpaid
  const tone = !value && !ours ? 'none' : ours ? 'wip' : 'ok'
  return (
    <span className="pnum sumtip-host">
      {kRub(value)}
      <span className={`ci sg ci-package sg-${tone}`} />
      <span className="sumtip">
        <span className="all">всего в «Заказе»</span>
        <span className="all">{money(value)}</span>
        <span className="g-available">едет (заказы, по счёту)</span>
        <span className="g-available">{money(paid)}</span>
        <span className="g-on_order">предстоит (план сверх заказов, по оценке)</span>
        <span className="g-on_order">{money(unpaid)}</span>
        {unpaidMissing > 0 &&
          <span className="miss">{count(unpaidMissing, 'позиция', 'позиции', 'позиций')} плана без оценки — «предстоит» неполно</span>}
      </span>
    </span>
  )
}

// Сумма над «Потр.» — ПЛАН (2026-10-19, решение Ивана: «одинаковые числа в разных местах
// обязаны совпадать; явное лучше неявного»). Раньше здесь стояла потребность по оценке, а
// в шапке проекта — «план (прогноз)» с фактами; как только заказы зафиксировали по счетам,
// два «плана» разошлись на разницу счёт/оценка, и пользователь не знал, какому верить.
// Теперь одно правило (движок `plan_cost`), и раскладка показывает сверку явно: без
// фильтров последней строкой стоит тот же «план (прогноз)», что в шапке, — до копейки.
// С фильтром сверки нет (показана часть плана) — так и сказано.
//
// Запас зафиксированной закупки входит в план СРАЗУ (2026-10-19, решение Ивана): «какие
// запасы мы можем себе позволить» — поэтому он назван отдельной строкой («в т.ч.»), а не
// растворён во «впереди». Отсюда же тождество над колонками: Компл. + Склад + Заказ +
// нехватка = план по позициям.
function PlanSumCell({ spent, ahead, reserve, outside, filtered }: {
  spent: number; ahead: number; reserve: number; outside: number; filtered: boolean
}) {
  const value = spent + ahead
  return (
    <span className="pnum sumtip-host">
      {kRub(value)}
      <span className="sumtip">
        <span className="all">план по позициям</span>
        <span className="all">{money(value)}</span>
        <span className="g-available">потрачено (заказы по счёту, УПД без заказа)</span>
        <span className="g-available">{money(spent)}</span>
        <span className="g-on_order">впереди (план закупок, нехватка — по оценке)</span>
        <span className="g-on_order">{money(ahead)}</span>
        {reserve > 0 && <>
          <span className="all">в т.ч. запас сверх потребности по плану закупки</span>
          <span className="all">{money(reserve)}</span>
        </>}
        {filtered
          ? <span className="note">фильтр: показана часть плана проекта</span>
          : <>
              {outside !== 0 && <>
                <span className="all">вне потребности (куплено не по BOM)</span>
                <span className="all">{money(outside)}</span>
              </>}
              <span>= план (прогноз) проекта</span>
              <span>{money(value + outside)}</span>
            </>}
      </span>
    </span>
  )
}

export function NeedSums({ rows, acts, outside, filtered }: {
  rows: DeficitComponent[]; acts?: boolean
  outside: number          // траты вне потребности — замыкают сверку с планом шапки
  filtered: boolean        // показана часть строк: сверки с планом нет
}) {
  let spent = 0, ahead = 0, reserve = 0, kitted = 0, stock = 0, short = 0, need = 0
  let paid = 0, unpaid = 0, unpaidMissing = 0, oursAny = false
  const unestimated: string[] = []
  for (const r of rows) {
    spent += r.spent_cost
    ahead += r.plan_cost - r.spent_cost
    // Запас по плану — та часть плана закупки, что сверх нужды (плюс баланса, но не больше
    // самого плана: плюс от склада запасом закупки не является).
    if (r.price != null && r.planned > 0 && r.balance > 0)
      reserve += Math.min(r.planned, r.balance) * r.price
    if (r.unestimated) unestimated.push(r.component_code)
    need += r.need_cost ?? 0
    kitted += r.kitted_cost
    stock += r.in_stock_cost
    paid += r.ordered_cost
    // Доля «на нас» в «Заказе»: план закупок и незакрытая сборка — только по оценке.
    const ours = r.planned + r.wip
    if (ours > 0) oursAny = true
    if (ours) {
      if (r.price == null) unpaidMissing += 1
      else unpaid += ours * r.price
    }
    if (r.price != null && r.balance < 0) short += r.balance * r.price
  }
  return (
    <div className="prow prow--sums">
      <span className="rn" />
      {/* «Деньги», а не «Оценка» (2026-10-19): в строке и факты партий, и счета, и оценка.
          Единица — в подписи строки (2026-10-20): над «Ед.» пусто, тысячи идут сплошным
          рядом над числами. */}
      <span className="tree-cell">Деньги, тыс. ₽</span>
      {/* Без ▲ (правка Ивана): треугольник занят статусами — здесь просто красный текст.
          Признак — тот же, что в шапке проекта (без фильтров счётчики совпадают); слова
          короче (2026-10-20): «— план неполон» уже сказано блоком «Деньги». */}
      <span className="name">
        {unestimated.length > 0 &&
          <span className="unest" title={'без оценки: ' + unestimated.join(', ')}>
            {count(unestimated.length, 'позиция', 'позиции', 'позиций')} без оценки</span>}
      </span>
      <span className="puom" />
      {/* 2026-10-20: над «Потр.» — чистая потребность (нужда × оценка, без запаса), план
          уехал над «Оценку». Рядом они и есть «сверх потребности» блока «Деньги» — но по
          фильтру: электроника, крепёж, детали по отдельности. */}
      <SumCell value={need} what="чистая потребность: нужда по BOM × оценка, без запаса" />
      <SumCell value={kitted} glyph="notebook" tone="ok" what="впаяно, по цене партий" />
      <SumCell value={stock} glyph="layers" tone="ok" what="на складе, по цене партий" />
      <OrderSumCell paid={paid} unpaid={unpaid} unpaidMissing={unpaidMissing}
        ours={oursAny} />
      <SumCell value={short} glyph="warning" tone="order"
        what="предстоит купить (только минусы баланса), по оценке" />
      <PlanSumCell spent={spent} ahead={ahead} reserve={reserve} outside={outside}
        filtered={filtered} />
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
// зелёные (нужда закрыта). Ящик «Заказ» (волна 24, решение Ивана) — зелёный, когда всё
// в нём под обязательством (зафиксированные заказы: от нас всё сделано, ждём), и
// оранжевый, пока хоть часть держится на нас — только в плане зафиксированной закупки
// или в незакрытой комплектации. НОЛЬ гасим до нейтрального: глиф светит, когда за ним
// что-то есть, иначе колонка нулей шумит.
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
export function BalanceCells({ code, need, kitted, inStock, onOrder, planned = 0, wip = 0,
  balance, status, anomaly }: {
  code: string; need: number; kitted: number; inStock: number; onOrder: number
  planned?: number; wip?: number
  balance: number; status: Status; anomaly?: boolean
}) {
  return (
    <>
      <Member glyph="notebook" tone="ok" value={kitted}
        title="впаяно в изделия проекта (зафиксированные комплектации)" />
      <span className="pnum" title="остаток лотов проекта на складах">
        {num(inStock)}
        {anomaly && <Anomaly title="есть лот с отрицательным остатком" />}
        <span className={`ci sg ci-layers sg-${inStock ? 'ok' : 'none'}`} />
      </span>
      <Member glyph="package" tone={planned > 0 || wip > 0 ? 'wip' : 'ok'} value={onOrder}
        title={orderTitle(onOrder, planned)
          + ' — заказано не приехавшее по зафиксированным заказам + план зафиксированных закупок'} />
      <span className="pnum">
        <Balance value={balance} status={status}
          title={balanceTitle(code, need, kitted, inStock, onOrder, planned)} />
      </span>
    </>
  )
}

// Строка компонента в своде: те же пять чисел, read-only. Команда строки приходит
// СНАРУЖИ (`action`) — витрина сама ничего не умеет, она показывает и помогает выбрать.
// У проекта команды нет вовсе; у закупки это «взять в план» / отметка «уже взято».
export function NeedRow({ ln, no, openItem, action }: {
  ln: DeficitComponent; no?: number; openItem: (id: number) => void; action?: ReactNode
}) {
  return (
    <div className="prow prow--comp">
      <span className="rn">{no}</span>
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
      <span className="puom">{ln.uom}</span>
      <span className="pnum">{num(ln.need)}</span>
      <BalanceCells code={ln.component_code} need={ln.need} kitted={ln.kitted}
        inStock={ln.in_stock} onOrder={ln.on_order} planned={ln.planned} wip={ln.wip}
        balance={ln.balance}
        status={ln.status} anomaly={ln.anomaly} />
      {/* 2026-10-20: план позиции — по счёту, где под обязательством, остальное по оценке.
          Без оценки и без трат — прочерк: неизвестное ≠ бесплатное. */}
      <span className="pnum">
        <Cost cost={ln.unestimated && ln.spent_cost === 0 ? null : ln.plan_cost}
          status={ln.cost_status} /></span>
      {action !== undefined && <span className="act">{action}</span>}
    </div>
  )
}
