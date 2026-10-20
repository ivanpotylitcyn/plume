// Сквозной словарь статусов (единый везде): значок + цвет текста, не заливка.
import type { CostStatus, Status } from './api'
import { EntityLink } from './EntityLink'

// Единый глиф оси фиксации (Ф1b, волна 19): строгая проекция `bool locked` на codicon
// `lock` (зафиксировано) / `unlock` (расфиксировано). Никаких эмодзи и ✓/○ — только
// замок. Цвет — отдельная ось (`tone`): 'fix' красит по фиксации (зелёный заперт /
// оранжевый открыт), 'ok'/'wip'/'order' — явный тон (покрытие/worst-of по сущности),
// 'none' — нейтральный. Раскатан на все списки: изделия, компоненты, ордера, закупки,
// заказы, проекты. Две оси не путать: глиф = замок, цвет = «как идут дела».
type Tone = 'fix' | 'ok' | 'wip' | 'order' | 'none'
export function StatusGlyph({ locked, tone = 'fix', title }: {
  locked: boolean; tone?: Tone; title?: string
}) {
  const sg = tone === 'fix' ? (locked ? 'sg-ok' : 'sg-wip') : `sg-${tone}`
  return <span className={`ci sg ci-${locked ? 'lock' : 'unlock'} ${sg}`}
    title={title ?? (locked ? 'зафиксировано' : 'расфиксировано')} />
}

// Глиф ЗАКАЗА (2026-10-20, решение Ивана): `verified` — зафиксирован, обязательство
// возникло (оплачен или подписан договор); `unverified` оранжевый — черновик. Та же ось
// `locked`, что у всех, — модель не трогали; меняется только знак: у заказа фиксация значит
// «обязательство подтверждено», и печать читается точнее замка. Ставится везде, где на
// экране стоит заказ (список режима, ленты, веер и ячейки закупки, пикер).
//
// Цвет печати — не одна фиксация (2026-10-20, правка Ивана): зелёной она становится,
// только когда к заказу приложен хоть один файл — подтверждение из оффлайна (счёт,
// договор с ценами). Зафиксирован, а файлов нет — та же печать, но оранжевая: форма
// говорит «обязательство», цвет — «подтверждения ещё нет» (§7a, форма ⟂ цвет).
//
// Третья ступень (2026-10-20, решение Ивана): заказ, закрытый поставками целиком
// (`coverage === 'available'` — каждую строку погасили ЗАФИКСИРОВАННЫЕ УПД), — печать
// `verified-filled`, всегда зелёная: обязательство исполнено, ждать больше нечего.
// Файлы здесь цвет не решают — исполнение и есть подтверждение.
export function PurchaseGlyph({ locked, files, coverage, title }: {
  locked: boolean; files: number; coverage: Status; title?: string
}) {
  const filled = coverage === 'available'
  const tone = filled || (locked && files > 0) ? 'ok' : 'wip'
  const icon = filled ? 'verified-filled' : locked ? 'verified' : 'unverified'
  return <span className={`ci sg ci-${icon} sg-${tone}`}
    title={title ?? (filled ? 'закрыт поставками целиком'
      : !locked ? 'черновик — обязательства нет'
      : files > 0 ? 'зафиксирован — обязательство'
      : 'зафиксирован, но без файлов — приложите подтверждение (счёт, договор)')} />
}

// Глиф ЗАКУПКИ (2026-10-20, решение Ивана): форма — замок фиксации, как у всех; цвет
// отличает составленный план от завершённой работы. Открытый замок — всегда оранжевый
// (план ещё правится). Закрытый — зелёный, только когда закупка закрыта обязательствами
// целиком (`closed`: каждую строку плана взяли зафиксированные заказы — то же правило,
// что «факт: всё заказано» в её блоке «Деньги»); пока нет — оранжевый.
export function ProcurementGlyph({ locked, closed }: { locked: boolean; closed: boolean }) {
  return <StatusGlyph locked={locked} tone={locked && closed ? 'ok' : 'wip'}
    title={!locked ? 'черновик — план правится'
      : closed ? 'зафиксирована и закрыта заказами целиком'
      : 'зафиксирована, но заказами закрыта не вся'} />
}

// Глиф расхождения контрагентов (волна 19, Ф17). Контрагент есть у всех трёх уровней
// закупочного контура и наследуется копией при рождении; расхождение — законная
// ситуация («одна закупка может пойти от разных поставщиков»), поэтому это
// предупреждение, а НЕ гейт: форма кричит и подсказывает путь исправления, но не
// останавливает. Флаг считает движок ([[engine-view-seam]]) — здесь только знак.
export function MismatchGlyph({ title }: { title: string }) {
  return <span className="ci sg sg-wip trail ci-warning" title={title} />
}

// Аномалия строки — красный `warning` после числа (2026-10-19, вместо текстового ▲):
// отрицательный остаток, перетянутый источник. Тот же глиф, что у расхождения
// контрагентов и баланса (§7a: форма одна, смысл — тоном), но тон всегда красный.
export function Anomaly({ title }: { title: string }) {
  return <span className="ci sg sg-order trail ci-warning" title={title} />
}

// Раскрыватель аккордеона — ЕДИНЫЙ везде (волна 19, полировка 2026-07-26): codicon
// `chevron-right` (свёрнуто) / `chevron-down` (раскрыто) вместо текстовых ▸/▾. По §7a
// раскрыватель — первый символ строки, поэтому форма у него одна на весь продукт.
// Размер — компаундом `.ci.chv` (как у `.sg`): базовые 18px разорвали бы высоту строк.
export function Chevron({ open }: { open: boolean }) {
  return <span className={`ci chv ci-chevron-${open ? 'down' : 'right'}`} />
}

// Глиф оси СИНКА (Ф3a, волна 19) — для КОМПОНЕНТОВ (`native=false`). Ровно один глиф
// по режиму: у компонентов показываем синк (у изделий — замок, `StatusGlyph`).
// `synced=true` (из библиотеки) → codicon `sync` зелёный; `false` (ручной) →
// `sync-ignored` оранжевый («внимание: не из библиотеки», важно при сборке закупки).
export function SyncGlyph({ synced, title }: { synced: boolean; title?: string }) {
  return <span
    className={`ci sg ci-${synced ? 'sync' : 'sync-ignored'} ${synced ? 'sg-ok' : 'sg-wip'}`}
    title={title ?? (synced ? 'из библиотеки' : 'заведено вручную')} />
}

// Глиф строки Item (Ф3a): РОВНО ОДИН. Раскатан во ВСЕ списки, где встречается
// изделие/компонент: справочник, BOM, дерево дефицита, потребность, закупка. Так глиф
// «перетекает» с сущностью одинаково везде.
//
// Волна 23, Ф5 (решение Ивана): глиф выбирает не `native`, а ЧЕМ защищена сущность.
// Библиотечный компонент (`synced`) защищён библиотекой — зелёные стрелки, фиксации у
// него нет. Всё остальное — изделие И ручной компонент — защищено фиксацией: замок
// (оранжевый открыт / зелёный заперт). Синк, подтвердив ручной компонент, снимает замок
// и метит `synced` — глиф сам меняется на стрелки.
export function ItemGlyph({ native, synced, locked, tone, title }: {
  native: boolean; synced: boolean; locked: boolean
  tone?: 'fix' | 'ok' | 'wip' | 'order' | 'none'; title?: string
}) {
  return synced && !native
    ? <SyncGlyph synced title={title} />
    : <StatusGlyph locked={locked} tone={tone} title={title} />
}

// Глиф вложения (волна 19, Ф12a). ФОРМА = вид файла (по расширению: pdf, картинка,
// код, архив, прочее-бинарь), ЦВЕТ = живо ли оно на диске: зелёный — файл на месте и
// совпадает с записью, оранжевый — на месте, но размер/время разошлись (перезалили
// мимо приложения), красный — записи есть, файла нет. Две оси не путаем — тот же
// принцип, что у ItemGlyph (глиф ⟂ цвет, §7a).
const FILE_GLYPH: [RegExp, string][] = [
  [/\.pdf$/i, 'file-pdf'],
  [/\.(png|jpe?g|gif|bmp|webp|svg|tiff?)$/i, 'file-media'],
  [/\.(zip|rar|7z|tar|gz)$/i, 'file-zip'],
  [/\.(json|xml|ya?ml|csv|py|ts|tsx|js|sql|sh|md|txt)$/i, 'file-code'],
  [/\.(exe|dll|bin|hex|elf|step|stp|stl|dwg|sch|pcb)$/i, 'file-binary'],
]
const FILE_TONE: Record<'ok' | 'changed' | 'missing', string> = {
  ok: 'sg-ok', changed: 'sg-wip', missing: 'sg-order',
}
const FILE_TITLE: Record<'ok' | 'changed' | 'missing', string> = {
  ok: 'файл на месте',
  changed: 'файл на месте, но размер или время изменились — перезаписан мимо Plume',
  missing: 'файла нет на сервере (запись осталась)',
}

export function FileGlyph({ filename, state }: {
  filename: string; state: 'ok' | 'changed' | 'missing'
}) {
  const icon = FILE_GLYPH.find(([re]) => re.test(filename))?.[1] ?? 'file'
  return <span className={`ci sg ci-${icon} ${FILE_TONE[state]}`} title={FILE_TITLE[state]} />
}

// Глиф партии (волна 19, Ф12c). Своей оси состояния у лота нет — решение Ивана
// 2026-07-26: ФОРМА = откуда партия родилась (origin-ордер, `Lot.origin_kind`), ЦВЕТ =
// живость остатка (зелёный — есть, приглушённый — исчерпана, красный — минус, то есть
// недостача «подбей лоты»). Тот же приём, что у `FileGlyph`: форма отвечает «что это»,
// цвет — «как дела» (§7a, ось ⟂ ось). Лот без origin (данные до волны 13) — `layers`.
const LOT_GLYPH: Record<string, string> = {
  receipt: 'inbox',            // приехало от поставщика по УПД
  kitting: 'tools',            // изготовлено нами (комплектация родила прибор)
  inventory: 'checklist',      // найдено сверкой
  requisition: 'git-branch',   // отпочковано требованием от другой партии
}
const LOT_ORIGIN: Record<string, string> = {
  receipt: 'из поставки', kitting: 'изготовлено',
  inventory: 'найдено инвентаризацией', requisition: 'отпочковано требованием',
}
// `draft` — партия ещё не на складе: её родил РАСФИКСИРОВАННЫЙ ордер (волна 19, Ф15 —
// замок гейтит склад). Живости у неё нет вовсе, поэтому цвет не «исчерпана» (это была
// бы ложь про израсходованную партию), а нейтральный «ждёт фиксации».
export function LotGlyph({ origin, liveQty, draft }: {
  origin: string | null; liveQty: number; draft?: boolean
}) {
  const icon = LOT_GLYPH[origin ?? ''] ?? 'layers'
  const tone = draft ? 'sg-none' : liveQty > 0 ? 'sg-ok' : liveQty < 0 ? 'sg-order' : 'sg-none'
  const life = draft ? 'ещё не на складе — зафиксируйте документ'
    : liveQty > 0 ? 'есть остаток' : liveQty < 0 ? 'недостача — подбей лоты' : 'исчерпана'
  return <span className={`ci sg ci-${icon} ${tone}`}
    title={`${LOT_ORIGIN[origin ?? ''] ?? 'партия'} · ${life}`} />
}

// Status → тон StatusGlyph (Ф1b): ось покрытия/worst-of в цвет замка (списки Заказов
// и Проектов). Красный (to_order) / оранжевый (on_order) / зелёный (available).
export function statusTone(s: Status): 'ok' | 'wip' | 'order' {
  return s === 'available' ? 'ok' : s === 'on_order' ? 'wip' : 'order'
}

// Глиф покрытия (2026-10-19, вместо текстовой тройки ▲/●/✓ «не из того набора»): ОДИН
// codicon `warning`, смысл — тоном (§7a: форма ⟂ цвет). Тот же знак, что у баланса.
export function CoverageGlyph({ status, title }: { status: Status; title?: string }) {
  return <span className={`ci sg ci-warning sg-${statusTone(status)}`} title={title} />
}

// Сегмент разбора строки «3 ⚠ · 2 ⚠» (на заказе / к заказу) — только непустой.
export function Segment({ status, value }: { status: Status; value: number }) {
  if (!value) return null
  return <span className="seg"><CoverageGlyph status={status} />{num(value)}</span>
}

// `LayerSeg` (разбор на codicon `layers`: форма одна, состояние — цветом) снят
// 2026-08-11 вместе с `LABEL`. Пилот в форме проекта не пережил переход на пять
// СЫРЫХ числовых колонок (2026-08-05): разбор-сегменты там заменил ряд чисел, каждое
// со своим глифом-членом (`Member` в `ProjectView`), и тройка сегментов больше не
// собиралась ни на одном экране.

// Парето на вью (2026-10-20) — то же правило, что `engine.mark_pareto`: по убыванию
// стоимости, пока накопленное ДО строки меньше 80% суммы набора. Живёт здесь только там,
// где набор зависит от состояния вью (фронт аккордеона «Приборов»); всё остальное красит
// движок. Строки без цены и нулевые в ранжировании не участвуют.
export const PARETO_SHARE = 0.8
export function paretoKeys(rows: { key: string; cost: number | null }[]): Set<string> {
  const ranked = rows.filter(r => r.cost != null && r.cost > 0)
    .sort((a, b) => (b.cost as number) - (a.cost as number))
  const bar = PARETO_SHARE * ranked.reduce((s, r) => s + (r.cost as number), 0)
  const out = new Set<string>()
  let acc = 0
  for (const r of ranked) {
    if (acc < bar) out.add(r.key)
    acc += r.cost as number
  }
  return out
}

// Видимые строки аккордеона-дерева (Ф5b → общая 2026-10-20: «Приборы» проекта и
// «Состав» изделия). Плоский pre-order + `depth` от бэка: узел скрыт, если он глубже
// ближайшего свёрнутого предка. `isExp` — узел раскрыт; фронт динамического Парето —
// видимые строки, которые сами не раскрыты (`!(hasChildren && isExp)`).
export interface VisibleNode<T> { n: T; i: number; hasChildren: boolean; isExp: boolean }
export function visibleTree<T extends { depth: number; is_leaf: boolean }>(
  tree: T[], expanded: Set<number>): VisibleNode<T>[] {
  const visible: VisibleNode<T>[] = []
  let hideDepth = Infinity
  tree.forEach((n, i) => {
    if (n.depth > hideDepth) return       // под свёрнутым узлом — прячем
    hideDepth = Infinity                  // вернулись на уровень предка — снимаем сокрытие
    const hasChildren = !n.is_leaf
    const isExp = expanded.has(i)
    if (hasChildren && !isExp) hideDepth = n.depth   // свёрнут → прячем его поддерево
    visible.push({ n, i, hasChildren, isExp })
  })
  return visible
}

// Стоимость строки — всегда в колонке таблицы, поэтому без рубля (`moneyCol`). (2026-08-07) — одинаково в «Строках» закупки (на обоих её уровнях) и
// в составе изделия (2026-10-20). Знак берём у движка (`cost_status`), сами ничего не
// решаем: красный — взято больше чем в полтора раза от нужды, оранжевый — по Парето:
// строка из тех, что вместе дают 80% стоимости набора. Цены нет — прочерк, а не ноль (неизвестное ≠ бесплатное).
// Подсказка красного называет ПОРОГ числом, а не правилом: «можно было до 20» отвечает
// на вопрос закупщика сразу, тогда как «полторы нормы, округлённые вверх» он должен был
// бы ещё посчитать. Порог считает движок (`overpay_at`) — вью его только произносит.
export function Cost({ cost, status, overpayAt, uom }: {
  cost: number | null; status: CostStatus
  overpayAt?: number; uom?: string
}) {
  if (cost === null) return <span className="dim" title="у изделия нет оценки">—</span>
  const tone = status === 'overpaid' ? 'g-to_order' : status === 'costly' ? 'g-on_order' : ''
  const title = status === 'overpaid'
    ? (overpayAt !== undefined
        ? `перебор: без красного можно было до ${num(overpayAt)}${uom ? ' ' + uom : ''}`
        : 'взято сверх потребности с запасом')
    : status === 'costly' ? 'дорогая: вместе с более дорогими даёт 80% стоимости'
    : undefined
  return <span className={tone} title={title}>{moneyCol(cost)}</span>
}

// Номера строк документа (2026-10-16): постоянный адрес строки — позиция в ПОЛНОМ
// списке, а не в отфильтрованном. Фильтр скрывает строки, номера не переезжают
// (решение Ивана: «проверь строку 12» значит одно и то же при любом фильтре).
export function rowNumbers<T>(rows: readonly T[] | undefined): Map<T, number> {
  const m = new Map<T, number>()
  rows?.forEach((r, i) => m.set(r, i + 1))
  return m
}

// Порядок списков-документов (2026-10-20, решение Ивана): молодые сверху, старые
// естественно уходят вниз и не тянут внимание. Без даты — наверх: дата пуста только у
// черновика, а черновик и есть самое живое. Равные даты — по id, новее выше. Одно правило
// на «Закупки», «Заказы» и «Ордера».
export function newestFirst(a: { date: string | null; id: number },
                            b: { date: string | null; id: number }): number {
  if ((a.date === null) !== (b.date === null)) return a.date === null ? -1 : 1
  return (b.date ?? '').localeCompare(a.date ?? '') || b.id - a.id
}

export function num(x: number): string {
  return Number.isInteger(x) ? String(x) : String(x)
}

// Деньги: разряды пробелом + копейки + ₽ («1 200 300,00 ₽»). Единый формат везде —
// бюджет проекта, суммы документов, оценка изделия (принято 2026-07-26).
export function money(x: number): string {
  return x.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₽'
}

// Цена штуки (волна 26): производная величина, бывает в долях копейки (10 000 резисторов
// за 3 519,78 ₽ → 0,352 ₽) — до четырёх знаков, не меньше двух.
export function unitMoney(x: number): string {
  return x.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) + ' ₽'
}

// Деньги в КОЛОНКЕ таблицы (2026-10-20, правка Ивана): копейки есть, знака рубля нет —
// он повторялся в каждой строке и съедал место; рубль один раз в заголовке («Оценка, ₽»).
// Отдельные числа (статы, подсказки) остаются с рублём — `money`.
export function moneyCol(x: number): string {
  return x.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// Деньги в поле ввода: ровно два знака после запятой, без разрядов («35197,80») — так
// поле читается тем же числом, что и просмотр, а ввод остаётся простым числом. Общее
// для цены строки заказа и стоимости строки поставки/акта (волна 26: сумма первична).
export function moneyField(x: number): string {
  return Number(x).toFixed(2).replace('.', ',')
}

// Разбор ввода денег: запятая или точка; пробелы разрядов и знак рубля из скопированного
// счёта допустимы; до копейки. Пусто — `null`; не число — `NaN`, его отобьёт `validate`.
export function parseMoney(v: string): number | null {
  const s = v.replace(/\s|₽|руб\.?/gi, '').replace(',', '.')
  if (s === '') return null
  return Math.round(Number(s) * 100) / 100
}

// Доли в блоке «Деньги» (волна 26): освоение — «43%» (целые, их сравнивают глазом);
// отклонение — со знаком «+22%» / «−8%» (минус типографский, как у переплаты); `null` —
// знаменателя нет, процент от нуля не бывает.
export function pct(x: number | null): string {
  return x === null ? '—' : `${Math.round(x * 100)}%`
}
export function signedPct(x: number | null): string {
  if (x === null) return '—'
  const v = Math.round(x * 100)
  return v === 0 ? '0%' : (v > 0 ? '+' : '−') + `${Math.abs(v)}%`
}

// Расхождение в рублях со знаком: «+12,40 ₽» / «−3,00 ₽» / «0,00 ₽».
export function gapMoney(x: number): string {
  return x === 0 ? money(0) : (x > 0 ? '+' : '−') + money(Math.abs(x))
}

// Цена штуки под курсором у стоимости строки: производная, до копейки для глаза.
export function perUnitTitle(cost: number, qty: number): string | undefined {
  return qty ? `за штуку ${money(Math.round(cost / qty * 100) / 100)}` : undefined
}

// Итог списка в натуре: количества сворачиваются ПО ЕДИНИЦАМ (§13.6) — штуки с метрами
// не складываем. Порядок групп — как единицы встретились в списке, чтобы итог читался в
// том же порядке, что строки; нулевые группы не показываем. Общий для всех форм
// (волна 19, Ф12c: жил в `ReceiptView`, понадобился каждому списку с количеством).
export function sumByUom(rows: { uom: string; qty: number }[]): [string, number][] {
  const sums = new Map<string, number>()
  for (const r of rows) sums.set(r.uom, (sums.get(r.uom) ?? 0) + r.qty)
  return [...sums].filter(([, qty]) => qty !== 0)
}

// Русское склонение при числе: `count(2, 'вхождение', 'вхождения', 'вхождений')`
// → «2 вхождения». Число ВПЕРЕДИ подписи — так строка меты читается фразой (§13.6).
export function count(n: number, one: string, few: string, many: string): string {
  const mod100 = n % 100
  const mod10 = n % 10
  const word = mod100 >= 11 && mod100 <= 14 ? many
    : mod10 === 1 ? one
    : mod10 >= 2 && mod10 <= 4 ? few
    : many
  return `${n} ${word}`
}

// Контрагент в форме и в списке — ЕДИНЫЙ вид (2026-08-05). Показываем `code`
// («КОМПЭЛ»), не описание из ЕГРЮЛ: код — первичная идентичность, он короче и
// узнаваемее, а полное имя всегда под курсором. Клик ведёт в карточку контрагента.
//
// Код у контрагента nullable (авто-фолбэка нет), поэтому пустой код — не ошибка, а
// повод мягко попросить: показываем описание и приглушённую пометку «код не задан»
// (тот же приём, что у номеров документов в карточке контрагента).
// 2026-08-10: ссылка стала настоящей (`EntityLink`), поэтому компонент принимает `id`
// контрагента, а не готовый колбэк без аргумента: адрес формы собирается из вида и id.
export function CounterpartyRef({ code, name, id, open }: {
  code: string; name: string
  id?: number | null                       // нет id — показываем текстом, ссылки нет
  open?: (id: number) => void
}) {
  if (!name) return null
  const body = code
    ? <span className="code">{code}</span>
    : <>{name}<span className="hint"> код не задан</span></>
  return id && open
    ? <EntityLink kind="counterparty" id={id} open={open} title={name}>{body}</EntityLink>
    : <span title={name}>{body}</span>
}

// ─── Баланс потребности — ОДИН на весь продукт (2026-08-05) ───
// Показывается в ТРЁХ местах и обязан читаться одинаково: свод «Потребность» проекта
// (общая оценка), ячейка «Привязки» закупки (раскладка) и строка заказа (2026-08-07 —
// «без него тяжело»: заказ не отвечал, сколько вообще надо).
//
// Невязка со знаком: `−4` не хватает четырёх, `+4` запас, `0` сошлось впритык. Глиф
// один (warning), различает ТОН: красный / оранжевый / зелёный (§7a — форма ⟂ цвет).
// Ноль здесь НЕ гасим, в отличие от членов баланса: это не «ничего нет», а
// содержательное состояние «сошлось, запаса нет».
//
// Значение и ЯЧЕЙКА разведены (2026-08-07): баланс живёт и в `.prow` (span.pnum), и в
// `table.grid` (td.num) — у них разные ячейки-роли, но одно содержимое. Обёртку задаёт
// вызывающий, компонент отвечает только за само число со знаком и тоном.
export function Balance({ value, status, title }: {
  value: number; status: Status; title: string
}) {
  return (
    <span title={title}>
      {value > 0 ? `+${num(value)}` : num(value)}
      <CoverageGlyph status={status} />
    </span>
  )
}

// Расшифровка баланса под курсором: из чего он собрался. Четыре слагаемых неочевидны —
// особенно впаянное, которого на складе уже нет (решение Ивана: подпись должна не
// подписывать, а объяснять).
export function balanceTitle(code: string, need: number, kitted: number,
                             inStock: number, onOrder: number, planned = 0): string {
  return `${code} · надо ${num(need)}, скомплектовано ${num(kitted)}, `
    + `склад ${num(inStock)}, ${orderTitle(onOrder, planned)}`
}

// «Заказ» с волны 24 = заказано + в плане. Расклад — в подсказке, когда план есть:
// число одно, а держится оно на разном (обязательство или только намерение).
export function orderTitle(onOrder: number, planned = 0): string {
  return planned > 0
    ? `в заказе ${num(onOrder)}: ${num(onOrder - planned)} в заказах · ${num(planned)} в плане`
    : `в заказах ${num(onOrder)}`
}
