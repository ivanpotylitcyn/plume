// Панель бюджета документа-намерения (2026-08-07): заказ и закупка отвечают на вопрос
// «сколько из этих денег нужно по-настоящему». Три числа движка (`engine.intent_money`):
//
//   Потребность  ← нужда проекта × цена (зелёный: столько надо, без запаса)
//   Переплата    ← разница со знаком (оранжевый + / красный −, см. ниже)
//   Заказ        ← сумма самого документа (обычный: просто факт его строк)
//
// Панель, а не поля шапки (§13.1): это крупные числа, которые ВЫЧИСЛЯЕТ движок, и место
// им в слоте `extra` — над метой, ровно как панели бюджета проекта. Прежнее поле
// «Оценка» в шапке снято обеими формами: это то же число, что «Заказ»/«Закупка» здесь.
//
// Одна панель на две формы ([[form-consistency-standard]]): арифметика у заказа и
// закупки одна, отличается только знаменатель (свой проект / охват) — а он считается на
// бэкенде, и вью про эту разницу не знает. Меняется лишь подпись суммы (`totalLabel`).
import { StatGroup, StatPanel, StatWarn, Stat } from './StatPanel'
import { money } from './status'

// Разница со знаком: `+` переплата (взяли с запасом), `−` недозаказ (взяли меньше
// нужды), ноль — «Переплата 0» без знака и без цвета (решение Ивана 2026-08-07).
// Знак, цвет и подпись говорят одно и то же — они все выведены из знака ОДНОГО числа,
// поэтому разойтись не могут, а читается такой стат без раздумий.
// Минус — типографский U+2212: рядом с `+` дефис выглядит короче и ниже.
function overpayStat(overpay: number) {
  if (overpay === 0) return { label: 'Переплата', value: money(0) }
  const over = overpay > 0
  return {
    label: over ? 'Переплата' : 'Недозаказ',
    value: (over ? '+' : '−') + money(Math.abs(overpay)),
    tone: over ? ('wip' as const) : ('bad' as const),
  }
}

export function IntentBudget({ demand, total, totalLabel, overpay, unestimated }: {
  demand: number            // потребность в деньгах (нужда проекта/охвата × цена)
  total: number             // сумма документа (Σ qty × цена)
  totalLabel: string        // «Заказ» / «Закупка» — имя самого документа
  overpay: number           // total − demand, со знаком
  unestimated: string[]     // коды позиций без `estimated_cost`
}) {
  const op = overpayStat(overpay)
  return (
    <StatPanel>
      <StatGroup>
        <Stat label="Потребность" value={money(demand)} tone="ok"
          title="Сколько эти позиции стоят по потребности проекта — без запаса" />
        <Stat label={op.label} value={op.value} tone={op.tone}
          title="Разница между суммой документа и реальной потребностью" />
        <Stat label={totalLabel} value={money(total)}
          title="Сумма строк документа по оценочной стоимости изделий" />
      </StatGroup>
      {unestimated.length > 0 &&
        <StatWarn title={'без оценки: ' + unestimated.join(', ')}>
          ▲ {unestimated.length} поз. без оценки — обе суммы неполны
        </StatWarn>}
    </StatPanel>
  )
}
