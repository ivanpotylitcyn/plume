// Словарь видов ордера — знание домена, а не компонент (потому отдельным модулем:
// рядом с формой он ломал fast-refresh, «файл экспортирует не только компоненты»).
// Читают: список режима «Ордера», диспетчер detail-формы и ленты, где вид приходит
// данными (движения изделия). Порядок = поток жизненного цикла
// (приёмка → сборка → выбытие → сверка).

// Виды ордера, у которых есть detail-форма (единый режим «Ордера»).
export type OrderKind =
  | 'receipt' | 'kitting' | 'transfer' | 'requisition' | 'writeoff' | 'inventory'
  | 'relocation'

export const ORDER_KINDS: { kind: OrderKind; label: string }[] = [
  { kind: 'receipt',     label: 'Поставка' },
  { kind: 'kitting',     label: 'Комплектация' },
  { kind: 'transfer',    label: 'Передача' },
  { kind: 'requisition', label: 'Требование' },
  { kind: 'writeoff',    label: 'Списание' },
  { kind: 'inventory',   label: 'Инвентаризация' },
  { kind: 'relocation',  label: 'Перемещение' },
]

export const ORDER_LABEL =
  Object.fromEntries(ORDER_KINDS.map(k => [k.kind, k.label])) as Record<OrderKind, string>
