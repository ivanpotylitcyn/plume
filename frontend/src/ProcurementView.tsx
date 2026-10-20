// Витрина волны 7: форма закупки (Procurement) — записываемое ядро.
// Волна 24 (2026-10-16): закупка — ИСТОЧНИК ПРАВДЫ закупочного контура. Однопроектная
// (поле «Проект» вместо вычисляемого охвата), одно поле ввода — «сколько хотим», а заказы
// рождаются отсюда кнопкой «Новый заказ» (окно с позициями плана, количество — остаток).
// Распределение строки по заказам — только чтение; правят его в форме заказа.
//
// Волна 19 (Ф12c): форма по канону §13. Табы — Строки · Потребность · Заказы · Файлы
// (разбор в комментарии к `tabs`).
import { useEffect, useState } from 'react'
import { api, type ProcurementForm, type AllocationRow } from './api'
import { AuthorField, ProjectField, useFormLock } from './FormHeader'
import { ProcurementMoney } from './ProcurementMoney'
import { FormShell, type FormTab } from './FormShell'
import { TextField } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { AllocationRows, PurchaseFan, useAllocation } from './AllocationPanel'
import { DemandRows, useDemand } from './DemandPanel'
import { DialogBox } from './DialogHost'
import { count, num, sumByUom } from './status'
import { ask } from './dialog'

// `items` (справочник изделий) форме не нужен: своего пикера у неё нет — позицию
// выбирают в «Потребности», из того, что проект действительно просит.
export function ProcurementView({ procurementId, isNew, openItem,
  openProject, openPurchase, openCounterparty, onPurchaseBorn, onChanged, onDeleted }: {
  procurementId: number; isNew: boolean
  openItem: (id: number) => void; openProject: (id: number) => void
  openPurchase: (id: number) => void; openCounterparty: (id: number) => void
  onPurchaseBorn: (id: number) => void   // «Новый заказ» родил заказ — открыть его в правке
  onChanged: () => void
  onDeleted?: () => void
}) {
  const [c, setC] = useState<ProcurementForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rev, setRev] = useState(0)     // растёт на мутациях — освежает панель pegging
  const { unlocked, toggle } = useFormLock(procurementId, isNew)
  const [picking, setPicking] = useState(false)   // открыто окно «Новый заказ»

  const att = useAttachments('procurement', procurementId)   // владелец заведён Ф12b (§13.8)
  const alloc = useAllocation(procurementId, rev)   // «Строки», «Заказы», окно «Новый заказ»
  const need = useDemand(procurementId, rev)        // таб «Потребность»

  useEffect(() => {
    setC(null); setErr(null)
    api.procurement(procurementId).then(setC).catch(e => setErr(String(e)))
  }, [procurementId])

  const run = (p: Promise<ProcurementForm>) => {
    setBusy(true); setErr(null)
    p.then(next => { setC(next); setRev(n => n + 1); onChanged() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Удаление закупки-плана (WAVE14 Ф2): корзина в шапке только у расфиксированной
  // (§5: у запертой одна степень свободы — расфиксировать); friendly-guard бэка
  // держит привязанные заказы.
  const del = async () => {
    if (!c || !(await ask({ title: `Удалить закупку «${c.code ?? `#${c.id}`}»?`,
      lines: ['строки плана будут сняты'], verb: 'Удалить', icon: 'ci-trash', danger: true }))) return
    setBusy(true); setErr(null)
    api.deleteProcurement(c.id).then(() => { onChanged(); onDeleted?.() })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !c) return <div className="empty">Ошибка: {err}</div>
  if (!c) return <div className="empty">Загрузка…</div>

  const editable = c.editable
  const fixed = !editable                  // зафиксирована — read-only
  const locked = !editable || !unlocked

  // «Новый заказ» (волна 24): окно выбора позиций → черновой заказ остатком → его форма.
  // Закупку он не меняет, поэтому доступен и у зафиксированной, и в просмотре — фиксация
  // плана инструмент работы с планом, а не блок для заказа (решение Ивана).
  const bornPurchase = (itemIds: number[]) => {
    setPicking(false); setBusy(true); setErr(null)
    api.newPurchase(c.id, itemIds)
      .then(pu => { setRev(n => n + 1); onPurchaseBorn(pu.id) })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Порядок табов (пересборка 2026-08-11, решение Ивана): СТРОКИ · ПОТРЕБНОСТЬ ·
  // ЗАКАЗЫ · ФАЙЛЫ — содержимое документа первым, как у Заказа.
  //
  // Что снято и почему. Плоский таб «Строки» показывал тот же план беднее, чем
  // «Привязка», и не оправдал себя — поэтому «Привязка» ЗАНЯЛА его имя (функции те же,
  // название честнее: это содержимое документа) и забрала корзину строки. Таб «К
  // закупке» тоже снят: наводка «докупить N» предлагала решение вместо того, чтобы
  // помочь его принять. Его место заняла «Потребность» — та же витрина, что у проекта,
  // но по всем проектам охвата.
  //
  // Два масштаба, и это главное в пересборке. «Потребность» — ТЕЛЕСКОП: весь контур
  // разом, состояние складов и заказов, помогает выбрать ПОЗИЦИЮ. «Строки» — МИКРОСКОП:
  // один компонент, его баланс и раскладка по заказам, помогает выбрать КОЛИЧЕСТВО.
  // Отсюда и разделение команд: взять позицию можно только в телескопе, набрать
  // количество — только в микроскопе, и ни один экран не делает работу другого.
  const tabs: FormTab[] = [
    // Правимость вкладок — по полному замку (`!locked`), а не по одной фиксации:
    // в просмотре форма не предлагает ни править количество, ни брать позиции.
    { key: 'lines', label: 'Строки', icon: 'checklist',
      content: <AllocationRows st={alloc} procurementId={c.id} editable={!locked}
        openItem={openItem} openPurchase={openPurchase} openCounterparty={openCounterparty}
        onQty={(lineId, qty) => run(api.updateProcurementLine(lineId, qty))}
        onDelete={lineId => run(api.deleteProcurementLine(lineId))} /> },
    { key: 'need', label: 'Потребность', icon: 'chip',
      content: <DemandRows st={need} editable={!locked} openItem={openItem}
        /* Пусто значит «проекту нечего покупать»: свод считается по его приборам. */
        empty="Нет потребностей по проекту — задайте приборы и их составы."
        /* «Взять» = обычная строка плана с НУЛЁМ: витрина выбирает позицию, количество
           набирают в «Строках». Путь назад — корзина той же строки. */
        take={itemId => run(api.addProcurementLine(c.id, { item_id: itemId, qty: 0 }))} /> },
    { key: 'fan', label: 'Заказы', icon: 'package',
      content: <PurchaseFan st={alloc} openPurchase={openPurchase}
        openCounterparty={openCounterparty} /> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (<>
    {picking && alloc.p &&
      <NewPurchaseDialog rows={alloc.p.rows} code={c.code ?? `#${c.id}`}
        onConfirm={bornPurchase} onClose={() => setPicking(false)} />}
    <FormShell
      id={c.id} code={c.code ?? ''} entity="закупку" locked={locked} error={err}
      // Мета (§13.6): счёт по табам + итог плана в натуре. Проект и дата — в полях.
      meta={<>
        {count(c.lines.length, 'позиция', 'позиции', 'позиций')}
        {sumByUom(c.lines).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(alloc.p?.fan.length ?? 0, 'заказ', 'заказа', 'заказов')}
        {' · '}{count(att.rows?.length ?? 0, 'файл', 'файла', 'файлов')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      onDelete={del}
      fixed={fixed}
      onFixate={() => run(api.lockProcurement(c.id))}
      fixateTitle="Зафиксировать закупку — строки станут read-only"
      onUnfix={() => run(api.unlockProcurement(c.id))}
      fixation={`procurements/${c.id}`}
      /* Бланк наружу отдаём только у ЗАФИКСИРОВАННОЙ закупки: до фиксации план ещё
         не решение (правило переехало сюда 2026-07-30, когда «Скачать» перестала
         быть исключительно «командой запертого» — у изделия она есть всегда). */
      download={fixed
        ? { href: api.xlsxUrl(c.id),
            title: 'Скачать xlsx-бланк для поставщика (имя файла = код закупки)' }
        : undefined}
      actions={[
        { onClick: () => setPicking(true), label: 'Новый заказ', icon: 'ci-package',
          title: 'Родить заказ из позиций плана — количество по остатку',
          disabled: busy || !alloc.p || c.lines.length === 0 },
        { onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
          title: 'Загрузить файл (КП, счёт) — появится в табе «Файлы»', disabled: att.busy },
      ]}
      fields={<>
        <TextField label="Код" code value={c.code ?? ''} locked={locked} busy={busy}
          onCommit={v => run(api.updateProcurement(c.id, { code: v }))} />
        <TextField label="Описание" wide value={c.description} locked={locked} busy={busy}
          onCommit={v => run(api.updateProcurement(c.id, { description: v }))} />
        {/* Порядок — канон §13.4a (Ф17): идентичность → якори (проект, контрагент) →
            внешние атрибуты → автор. Волна 24: верхний якорь — ПРОЕКТ, как у заказа и
            поставки (вычисляемый охват снят). Меняется, пока заказов нет: у них проект
            выводится отсюда. */}
        <ProjectField projectId={c.project_id} projectLabel={c.project_code}
          locked={locked || !c.project_editable} busy={busy} onOpen={openProject}
          onChange={id => run(api.updateProcurement(c.id, { project_id: id }))} />
        {/* Контрагента у закупки нет (волна 24, решение Ивана): закупка — внутреннее
            планирование, контрагент появляется только у заказа — обязательства. */}
        <TextField label="Дата" type="date" value={c.date ?? ''} locked={locked}
          busy={busy} onCommit={v => run(api.updateProcurement(c.id, { date: v }))} />
        <AuthorField userId={c.user_id} userName={c.user_name} locked={locked} busy={busy}
          onChange={id => run(api.updateProcurement(c.id, { user_id: id }))} />
      </>}
      // Деньги закупки — панелью над метой (2026-08-07), одна на обе формы контура.
      // Поле «Оценка» отсюда снято: это ровно стат «Закупка». Потребность — по проекту.
      extra={<ProcurementMoney c={c} />}
      tabs={tabs}
    />
  </>)
}

// Окно «Новый заказ» (волна 24, решение Ивана): какие позиции плана попадут в новый
// заказ. По умолчанию отмечены строки с остатком > 0 — частый случай «выбрать всё,
// приложить счёт, конец». Строки без остатка видны, но сняты: взять их — осознанное
// действие (уйдут нулём). Разъезд по счетам — второй «Новый заказ» по остатку, особого
// режима нет. Пустой выбор законен: заказ наберут руками в его форме.
function NewPurchaseDialog({ rows, code, onConfirm, onClose }: {
  rows: AllocationRow[]; code: string
  onConfirm: (itemIds: number[]) => void; onClose: () => void
}) {
  const [picked, setPicked] = useState(
    () => new Set(rows.filter(r => r.remaining > 0).map(r => r.item_id)))
  const allOn = picked.size === rows.length
  const toggle = (id: number) => setPicked(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })
  return (
    <DialogBox wide title={`Новый заказ из закупки «${code}»`}
      lines={[{ text: 'отмеченные позиции уйдут в черновой заказ количеством остатка — '
        + 'дальше заказ правится в своей форме' }]}
      verb="Создать заказ" icon="ci-package" closeLabel="Отмена"
      onConfirm={() => onConfirm(rows.filter(r => picked.has(r.item_id)).map(r => r.item_id))}
      onClose={onClose}>
      <div className="kit-actions">
        <button className="btn sm"
          onClick={() => setPicked(allOn ? new Set() : new Set(rows.map(r => r.item_id)))}>
          {allOn ? 'снять все' : 'выбрать все'}
        </button>
        <span className="lbl">отмечено {picked.size} из {rows.length}</span>
      </div>
      <div className="dialog-body">
        <table className="grid">
          <thead><tr>
            <th className="pick" /><th className="rn">№</th><th className="c-key">Компонент</th>
            <th className="c-desc">Описание</th>
            <th className="num" title="хотим − уже в заказах; столько уйдёт в новый заказ">
              Остаток</th>
            <th className="uom">Ед.</th>
          </tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={r.item_id} className="row">
              <td className="pick">
                <input type="checkbox" checked={picked.has(r.item_id)}
                  onChange={() => toggle(r.item_id)} /></td>
              <td className="rn">{i + 1}</td>
              <td className="c-key"><span className="code">{r.item_code}</span></td>
              <td className="c-desc">
                <span className="cell-ellip" title={r.item_description}>
                  {r.item_description}</span></td>
              <td className="num">
                <span className={r.remaining > 0 ? undefined : 'dim'}>
                  {num(Math.max(0, r.remaining))}</span></td>
              <td className="uom">{r.uom}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </DialogBox>
  )
}

// `LineRow` и `GhostRow` плоского таба «Строки» сняты 2026-08-11 вместе с ним самим:
// строку плана показывает `AllocationPanel` (тот же план, но с раскладкой по заказам и
// балансом проекта), а рождает её витрина «Потребность» — нулём. Двух вёрсток одной
// строки в форме больше нет.
