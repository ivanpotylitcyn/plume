// Единая форма «Ордера» (Ф2i): один вход `<OrderForm kind=… id=…>` вместо шести
// условных веток в App. Общая оболочка формы свёрнута в `useOrderForm`
// (FormHeader) — здесь остаётся только диспетчер тела по `kind`. Тела шести видов
// несводимы (разные формы/пикеры/API), но шапка/замок/удаление у них единые.
import type { ItemRow } from './api'
import { KittingView } from './KittingView'
import { ReceiptView } from './ReceiptView'
import { TransferView } from './TransferView'
import { WriteoffView } from './WriteoffView'
import { RequisitionView } from './RequisitionView'
import { InventoryView } from './InventoryView'
import { RelocationView } from './RelocationView'

// Тип и подписи видов — в `./orders` (знание домена, не компонент).
import type { OrderKind } from './orders'
export type { OrderKind }

export function OrderForm({ kind, id, items, isNew, openItem, openPurchase, openProject,
  openCounterparty, onChanged, onDeleted }: {
  kind: OrderKind
  id: number
  items: ItemRow[]
  isNew: boolean            // §5: только что созданный ордер открыть в правке
  openItem: (id: number) => void
  openPurchase: (id: number) => void
  openProject: (id: number) => void   // якорь-проект шапки кликабелен под замком (§8)
  openCounterparty: (id: number) => void   // контрагент в шапке — ссылка в его карточку
  onChanged: () => void
  onDeleted: () => void
}) {
  switch (kind) {
    case 'receipt':
      return <ReceiptView receiptId={id} items={items} isNew={isNew} openItem={openItem}
        openPurchase={openPurchase} openProject={openProject}
        openCounterparty={openCounterparty}
        onChanged={onChanged} onDeleted={onDeleted} />
    case 'kitting':
      return <KittingView kittingId={id} isNew={isNew} openItem={openItem}
        openProject={openProject} onChanged={onChanged} onDeleted={onDeleted} />
    case 'transfer':
      return <TransferView transferId={id} isNew={isNew} openItem={openItem}
        openProject={openProject} openCounterparty={openCounterparty}
        onChanged={onChanged} onDeleted={onDeleted} />
    case 'requisition':
      return <RequisitionView requisitionId={id} isNew={isNew} openItem={openItem}
        openProject={openProject} onChanged={onChanged} onDeleted={onDeleted} />
    case 'writeoff':
      return <WriteoffView writeoffId={id} isNew={isNew} openItem={openItem}
        openProject={openProject} onChanged={onChanged} onDeleted={onDeleted} />
    case 'inventory':
      return <InventoryView inventoryId={id} items={items} isNew={isNew} openItem={openItem}
        openProject={openProject} onChanged={onChanged} onDeleted={onDeleted} />
    case 'relocation':
      return <RelocationView relocationId={id} isNew={isNew} openItem={openItem}
        openProject={openProject} onChanged={onChanged} onDeleted={onDeleted} />
  }
}
