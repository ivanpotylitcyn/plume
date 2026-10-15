// Витрина волны 7: форма закупки-плана (Procurement) — записываемое ядро.
// План под ОХВАТ проектов (Ф13; до неё — «без проекта, командная высота»). Строки
// (item + qty, автосейв, пока расфиксирована). Замок делает строки read-only.
// Кнопка выгрузки xlsx-бланка поставщику (имя файла = код закупки). Волна 8 — панель pegging: нарезка плана на
// проектные заказы (веер Purchase под этим планом-родителем).
//
// Волна 19 (Ф12c): форма по канону §13. Табы пересобраны 2026-08-11 —
// Строки · Потребность · Заказы · Файлы (разбор в комментарии к `tabs`).
//
// Ф13: у закупки есть ОХВАТ — проекты её заказов (вычисляемый, поле «Проекты» в шапке).
// Он задаёт область расчёта: и витрина «Потребность», и деньги намерения считаются по
// нему. Общий `OrderFields` тут неприменим — у закупки проектов много, а не один.
import { useEffect, useState } from 'react'
import { api, type ProcurementForm, type CounterpartyRow } from './api'
import { AuthorField, useFormLock } from './FormHeader'
import { IntentBudget } from './IntentBudget'
import { FormShell, type FormTab } from './FormShell'
import { Field, TextField } from './FormField'
import { AttachmentList, useAttachments } from './AttachmentPanel'
import { AllocationRows, PurchaseFan, useAllocation } from './AllocationPanel'
import { DemandRows, useDemand } from './DemandPanel'
import { CounterpartyPicker } from './Picker'
import { CounterpartyRef, count, num, sumByUom } from './status'
import { ask } from './dialog'

// `items` (справочник изделий) форме больше не нужен: своего пикера у неё нет —
// позицию выбирают в «Потребности», из того, что проекты охвата действительно просят.
export function ProcurementView({ procurementId, isNew, openItem,
  openProject, openPurchase, openCounterparty, onChanged, onDeleted }: {
  procurementId: number; isNew: boolean
  openItem: (id: number) => void; openProject: (id: number) => void
  openPurchase: (id: number) => void; openCounterparty: (id: number) => void
  onChanged: () => void
  onDeleted?: () => void
}) {
  const [c, setC] = useState<ProcurementForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rev, setRev] = useState(0)     // растёт на мутациях — освежает панель pegging
  const [suppliers, setSuppliers] = useState<CounterpartyRow[]>([])
  const { unlocked, toggle } = useFormLock(procurementId, isNew)

  // Контрагенты (Ф4): закупка = поток общения с поставщиком. Список ВЕСЬ (Ф3) —
  // пикер поднимает наверх тех, у кого уже покупали, но никого не прячет.
  useEffect(() => { api.counterparties().then(setSuppliers) }, [])
  const att = useAttachments('procurement', procurementId)   // владелец заведён Ф12b (§13.8)
  const alloc = useAllocation(procurementId, rev)            // табы «Строки» и «Заказы»
  const need = useDemand('procurement', procurementId, rev)  // таб «Потребность»

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

  // Коды охвата — ссылки на проекты. Разделитель — ЗАПЯТАЯ вне ссылки (правка Ивана
  // 2026-07-29): так видно, что перечислено несколько проектов, а не один длинный код.
  const scopeLinks = c.projects.map((pr, i) => (
    <span key={pr.id}>
      {i > 0 && ', '}
      <a className="link scope-chip" title={pr.description}
        onClick={() => openProject(pr.id)}>{pr.code}</a>
    </span>
  ))

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
        openItem={openItem} openProject={openProject} openPurchase={openPurchase}
        onQty={(lineId, qty) => run(api.updateProcurementLine(lineId, qty))}
        onDelete={lineId => run(api.deleteProcurementLine(lineId))} /> },
    { key: 'need', label: 'Потребность', icon: 'chip',
      content: <DemandRows st={need} editable={!locked} openItem={openItem}
        /* Пусто у закупки значит «нет охвата»: он вычисляется из заказов, и пока их
           нет — считать нечего. */
        empty="Нет потребностей по охвату — заведите заказ под эту закупку."
        /* «Взять» = обычная строка плана с НУЛЁМ: витрина выбирает позицию, количество
           набирают в «Строках». Путь назад — корзина той же строки. */
        take={itemId => run(api.addProcurementLine(c.id, { item_id: itemId, qty: 0 }))} /> },
    { key: 'fan', label: 'Заказы', icon: 'package',
      content: <PurchaseFan st={alloc} openPurchase={openPurchase} /> },
    { key: 'files', label: 'Файлы', icon: 'files',
      content: <AttachmentList att={att} locked={locked} /> },
  ]

  return (
    <FormShell
      id={c.id} code={c.code ?? ''} entity="закупку" locked={locked} error={err}
      // Мета (§13.6): счёт по табам + итог плана в натуре. Контрагент и дата — в полях.
      meta={<>
        {count(c.lines.length, 'позиция', 'позиции', 'позиций')}
        {sumByUom(c.lines).map(([uom, qty]) => <span key={uom}> · {num(qty)} {uom}</span>)}
        {' · '}{count(c.projects.length, 'проект', 'проекта', 'проектов')} в охвате
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
        /* «Разрезать по проектам» (autopeg) снята 2026-08-05 вместе с автосозданием
           заказов: раскладка — дело рук и глаз, а кнопка «нажал и жди чуда» здесь
           слишком ответственная. Понадобится — вернём осознанно. */
        { onClick: att.pick, label: 'Загрузить', icon: 'ci-new-file',
          title: 'Загрузить файл (КП, счёт) — появится в табе «Файлы»', disabled: att.busy },
      ]}
      fields={<>
        <TextField label="Код" code value={c.code ?? ''} locked={locked} busy={busy}
          onCommit={v => run(api.updateProcurement(c.id, { code: v }))} />
        <TextField label="Описание" wide value={c.description} locked={locked} busy={busy}
          onCommit={v => run(api.updateProcurement(c.id, { description: v }))} />
        {/* Порядок — канон §13.4a (Ф17): идентичность → якори (охват, контрагент) →
            внешние атрибуты → автор. Верхний якорь закупки — ОХВАТ: место, которое у
            заказа и поставки занимает `project`.
            2026-08-05: охват стал ПРОИЗВОДНЫМ — это проекты заказов закупки, галочек
            больше нет (два источника правды на одно отношение молча расходились).
            Поэтому поле всегда в режиме просмотра, даже под карандашом. Пояснение
            «(из заказов)» появляется ТОЛЬКО в правке — там оно и нужно: рядом все поля
            стали контролами, и без него это читалось бы как сломанное. В просмотре
            пояснять нечего, и лишняя подпись под меткой только шумит. */}
        <Field label="Проекты" wide locked
          view={<>
            {c.projects.length ? scopeLinks
              : <span className="hint" title={'охват задаётся заказами: заведите заказ '
                  + 'и укажите в нём эту закупку'}>—</span>}
            {!locked && <span className="hint"> (из заказов)</span>}
          </>} />
        {/* Контрагент закупки — НАМЕРЕНИЕ плана («у кого собираемся купить»). Ф17:
            источником поставщика для «Заказ → УПД» он больше не является — заказ несёт
            своего, унаследованного отсюда копией при нарезке. */}
        <Field label="Контрагент" locked={locked}
          view={<CounterpartyRef code={c.contractor_code} name={c.contractor_name}
            id={c.contractor_id} open={openCounterparty} />}>
          <CounterpartyPicker counterparties={suppliers} side="supply"
            value={c.contractor_id ?? ''}
            disabled={busy} placeholder="— не указан —"
            onPick={id => run(api.updateProcurement(c.id, { contractor_id: id }))}
            onClear={() => run(api.updateProcurement(c.id, { contractor_id: null }))}
            onCreate={name => api.createCounterparty({ description: name })
              .then(cp => { api.counterparties().then(setSuppliers)
                run(api.updateProcurement(c.id, { contractor_id: cp.id })) })} />
        </Field>
        <TextField label="Дата" type="date" value={c.date ?? ''} locked={locked}
          busy={busy} onCommit={v => run(api.updateProcurement(c.id, { date: v }))} />
        <AuthorField userId={c.user_id} userName={c.user_name} locked={locked} busy={busy}
          onChange={id => run(api.updateProcurement(c.id, { user_id: id }))} />
      </>}
      // Деньги закупки — панелью над метой (2026-08-07), одна на обе формы контура.
      // Поле «Оценка» отсюда снято: это ровно стат «Закупка». Потребность считается по
      // ОХВАТУ — пока заказов нет, спросить не у кого, и весь план читается переплатой.
      extra={<IntentBudget demand={c.demand} total={c.estimate} totalLabel="Закупка"
        overpay={c.overpay} unestimated={c.unestimated} />}
      tabs={tabs}
    />
  )
}

// `LineRow` и `GhostRow` плоского таба «Строки» сняты 2026-08-11 вместе с ним самим:
// строку плана показывает `AllocationPanel` (тот же план, но с раскладкой по заказам и
// балансом проекта), а рождает её витрина «Потребность» — нулём. Двух вёрсток одной
// строки в форме больше нет.
