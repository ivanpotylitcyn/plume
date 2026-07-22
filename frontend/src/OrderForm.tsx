// Единая форма «Ордера» (Ф2i): один вход `<OrderForm kind=… id=…>` вместо шести
// условных веток в App. Общая оболочка кокпита свёрнута в `useOrderCockpit`
// (FormHeader) — здесь остаётся только диспетчер тела по `kind`. Тела шести видов
// несводимы (разные кокпиты/пикеры/API), но шапка/замок/удаление у них единые.
import type { ItemRow } from './api'
import { KittingView } from './KittingView'
import { ReceiptView } from './ReceiptView'
import { TransferView } from './TransferView'
import { WriteoffView } from './WriteoffView'
import { RequisitionView } from './RequisitionView'
import { InventoryView } from './InventoryView'
import { RelocationView } from './RelocationView'

// Виды ордера, у которых есть detail-форма (единый режим «Ордера»).
export type OrderKind =
  | 'receipt' | 'kitting' | 'transfer' | 'requisition' | 'writeoff' | 'inventory'
  | 'relocation'

export function OrderForm({ kind, id, items, isNew, openItem, openPurchase, onChanged, onDeleted }: {
  kind: OrderKind
  id: number
  items: ItemRow[]
  isNew: boolean            // §5: только что созданный ордер открыть в правке
  openItem: (id: number) => void
  openPurchase: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  switch (kind) {
    case 'receipt':
      return <ReceiptView receiptId={id} items={items} isNew={isNew} openItem={openItem}
        openPurchase={openPurchase} onChanged={onChanged} onDeleted={onDeleted} />
    case 'kitting':
      return <KittingView kittingId={id} isNew={isNew} openItem={openItem}
        onChanged={onChanged} onDeleted={onDeleted} />
    case 'transfer':
      return <TransferView transferId={id} isNew={isNew} openItem={openItem}
        onChanged={onChanged} onDeleted={onDeleted} />
    case 'requisition':
      return <RequisitionView requisitionId={id} isNew={isNew} openItem={openItem}
        onChanged={onChanged} onDeleted={onDeleted} />
    case 'writeoff':
      return <WriteoffView writeoffId={id} isNew={isNew} openItem={openItem}
        onChanged={onChanged} onDeleted={onDeleted} />
    case 'inventory':
      return <InventoryView inventoryId={id} items={items} isNew={isNew} openItem={openItem}
        onChanged={onChanged} onDeleted={onDeleted} />
    case 'relocation':
      return <RelocationView relocationId={id} isNew={isNew} openItem={openItem}
        onChanged={onChanged} onDeleted={onDeleted} />
  }
}
