// Словарь видов ордера — знание домена, а не компонент (потому отдельным модулем:
// рядом с формой он ломал fast-refresh, «файл экспортирует не только компоненты»).
// Читают: список режима «Ордера», диспетчер detail-формы и ленты, где вид приходит
// данными (движения изделия). Порядок = поток жизненного цикла
// (приёмка → выдача в работу → сборка → выбытие → сверка). Волна 27: «Требование» —
// официальная выдача с Центрального склада, «Перевод» — бывшее отпочкование.

// Виды ордера, у которых есть detail-форма (единый режим «Ордера»).
export type OrderKind =
  | 'receipt' | 'kitting' | 'transfer' | 'reassignment' | 'writeoff' | 'inventory'
  | 'relocation' | 'requisition'

export const ORDER_KINDS: { kind: OrderKind; label: string }[] = [
  { kind: 'receipt',     label: 'Поставка' },
  { kind: 'requisition', label: 'Требование' },
  { kind: 'kitting',     label: 'Комплектация' },
  { kind: 'transfer',    label: 'Передача' },
  { kind: 'reassignment', label: 'Перевод' },
  { kind: 'writeoff',    label: 'Списание' },
  { kind: 'inventory',   label: 'Инвентаризация' },
  { kind: 'relocation',  label: 'Перемещение' },
]

export const ORDER_LABEL =
  Object.fromEntries(ORDER_KINDS.map(k => [k.kind, k.label])) as Record<OrderKind, string>
