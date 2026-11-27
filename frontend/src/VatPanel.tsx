import { useRef, useState } from 'react'
import type { CostStatus, VatFacts, VatPatch, VatSummary, VatTerms } from './api'
import { AnchoredMenu } from './AnchoredMenu'
import { CommitInput } from './CommitInput'
import { Dropdown } from './Dropdown'
import { Cost, money, moneyCol, moneyField } from './status'
import { Stat, StatGroup, StatWarn } from './StatPanel'

// Передаём исходные десятичные строки серверу; Number нужен только для отображения.
export const decimalInput = (v: string) => v.trim() === '' ? null
  : v.replace(/\s/g, '').replace(',', '.')
const validMoney = (v: string) => v.trim() === '' || /^\d+(?:[.,]\d{0,2})?$/.test(v.replace(/\s/g, ''))
const amount = (v: string | null) => v === null ? '—' : money(Number(v))
const columnAmount = (v: string | null) => v === null ? '—' : moneyCol(Number(v))
const modeLabel = (v: VatTerms) => v.vat_mode === 'excluded' ? 'без НДС' : 'с НДС'
const categoryLabel = (v: VatTerms) => v.vat_category === 'unknown' ? 'НДС не указан'
  : v.vat_category === 'exempt' ? 'Без НДС' : `НДС ${Number(v.vat_rate)}%`

function Terms({ value, busy, patch }: {
  value: VatTerms; busy: boolean; patch: (p: VatPatch) => void
}) {
  return <>
    <Dropdown value={value.vat_category} disabled={busy} title="Налоговая категория"
      options={[{ value: 'unknown', label: 'НДС не указан' },
        { value: 'exempt', label: 'Без НДС' }, { value: 'taxable', label: 'По ставке' }]}
      onPick={v => patch({ vat_category: v as VatTerms['vat_category'],
        vat_rate: v === 'taxable' ? value.vat_rate ?? '22' : null,
        ...(v === 'unknown' ? { vat_mode: 'included' as const } : {}) })} />
    {value.vat_category === 'taxable' && <label className="vat-rate">
      <CommitInput value={String(Number(value.vat_rate))} disabled={busy} numeric
        onCommit={v => patch({ vat_rate: decimalInput(v) })}
        validate={v => /^\d+(?:[.,]\d{0,4})?$/.test(v) && Number(v.replace(',', '.')) <= 100} />%
    </label>}
    {value.vat_category === 'taxable' && <Dropdown value={value.vat_mode} disabled={busy}
      title="Какие суммы вводятся из документа"
      options={[{ value: 'included', label: 'Суммы с НДС' },
        { value: 'excluded', label: 'Суммы без НДС' }]}
      onPick={v => patch({ vat_mode: v as VatTerms['vat_mode'] })} />}
  </>
}

export function VatAmount({ value, locked, busy, patch, status }: {
  value: VatFacts; locked: boolean; busy: boolean; patch: (p: VatPatch) => void; status?: CostStatus
}) {
  return <span className="vat-line-amount">
    {locked ? (status && value.document_amount !== null
      ? <Cost cost={Number(value.document_amount)} status={status} /> : columnAmount(value.document_amount))
      : <CommitInput value={value.document_amount === null ? '' : moneyField(Number(value.document_amount))}
          disabled={busy} numeric validate={validMoney}
          onCommit={v => patch({ document_amount: decimalInput(v) })} />}
  </span>
}

// Редкие изменения условий — в привязанном меню; оно не меняет высоту строки.
function RowTerms({ row, busy, patch }: {
  row: VatFacts; busy: boolean; patch: (p: VatPatch) => void
}) {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLButtonElement>(null)
  const close = () => { setOpen(false); anchor.current?.focus() }
  return <>
    <button ref={anchor} className="fh-ctl vat-terms-button" disabled={busy}
      aria-label="Условия НДС строки" aria-expanded={open}
      title={categoryLabel(row) + ' · ' + modeLabel(row)}
      onClick={() => setOpen(!open)} onKeyDown={e => { if (e.key === 'Escape') close() }}>
      {row.vat_category === 'taxable' ? `${Number(row.vat_rate)}%`
        : row.vat_category === 'exempt' ? 'Без НДС' : 'Не указан'}
      <span className="ci ci-chevron-down" />
    </button>
    {open && <AnchoredMenu anchor={anchor} className="typeahead-menu vat-terms-menu" onVeil={close}>
      <div onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); close() } }}>
        <Terms value={row} busy={busy} patch={patch} />
        {row.vat_amount_manual && <button className="fh-ctl" disabled={busy}
          onClick={() => patch({ vat_amount: null })}>Рассчитать по ставке</button>}
        <div className="sub">{row.vat_amount_manual ? 'НДС из документа' : 'Расчёт / преднабивка'}</div>
        {row.vat_difference !== null && Number(row.vat_difference) !== 0 &&
          <div className="sub">От расчёта: {amount(row.vat_difference)}</div>}
      </div>
    </AnchoredMenu>}
  </>
}

export function VatStats({ value }: { value: VatSummary }) {
  return <>
    <StatGroup>
      <Stat label="без НДС" value={amount(value.net_amount)} />
      <Stat label="НДС" value={amount(value.vat_amount)} />
    </StatGroup>
    {value.unknown_rows > 0 && <StatWarn>
      НДС не указан у {value.unknown_rows} строк — налоговые итоги неполны
    </StatWarn>}
    {((value.total_gap !== null && Number(value.total_gap) !== 0)
      || (value.vat_gap !== null && Number(value.vat_gap) !== 0)) && <StatWarn>
      Расхождение с документом: итог {amount(value.total_gap)}, НДС {amount(value.vat_gap)}
    </StatWarn>}
  </>
}

export function VatPanel({ value, rows, locked, busy, patch, patchRow }: {
  value: VatSummary
  rows: (VatFacts & { id: number; item_code: string })[]
  locked: boolean; busy: boolean
  patch: (p: VatPatch) => void; patchRow: (id: number, p: VatPatch) => void
}) {
  return <div className="vat-panel">
    <div className="vat-defaults">
      <span>Новые строки:</span>
      {locked ? <span>{categoryLabel(value)} · {modeLabel(value)}</span>
        : <><Terms value={value} busy={busy} patch={patch} />
          <button className="fh-ctl" disabled={busy || rows.length === 0}
            title="Применить к каждому исходному числу строки. Режим «без НДС» начислит налог сверху."
            onClick={() => patch({ apply_to_lines: true })}>Применить ко всем строкам</button></>}
    </div>
    <div className="vat-defaults">
      {(['document_total', 'document_vat_total'] as const).map(key => <label key={key}>
        {key === 'document_total' ? 'Всего с НДС по документу' : 'НДС по документу'}
        {locked ? <span>{amount(value[key])}</span>
          : <CommitInput value={value[key] === null ? '' : moneyField(Number(value[key]))}
              disabled={busy} numeric validate={validMoney}
              onCommit={v => patch({ [key]: decimalInput(v) })} />}
      </label>)}
    </div>
    <table className="grid vat-grid">
      <thead><tr><th className="rn">№</th><th className="c-key">Компонент</th>
        <th className="num" title="Сумма строки в выбранном режиме ввода">Сумма, ₽</th><th className="num">НДС, ₽</th>
        <th className="num">Без НДС, ₽</th><th className="num">С НДС, ₽</th></tr></thead>
      <tbody>{rows.map((row, i) => <tr key={row.id} className="row">
        <td className="rn">{i + 1}</td><td className="c-key">{row.item_code}</td>
        <td className="num"><VatAmount value={row} locked={locked} busy={busy}
          patch={p => patchRow(row.id, p)} /></td>
        <td className="vat-tax" title={(row.vat_amount_manual ? 'НДС из документа' : 'Расчёт / преднабивка')
          + (row.vat_difference !== null && Number(row.vat_difference) !== 0
            ? ` · От расчёта: ${amount(row.vat_difference)}` : '')}>
          <span className="vat-line-tax">
          {locked ? <><span className="sub">{row.vat_category === 'taxable'
              ? `${Number(row.vat_rate)}%` : categoryLabel(row)}</span>
              <span className="vat-tax-value">{columnAmount(row.vat_amount)}</span></>
            : <><RowTerms row={row} busy={busy} patch={p => patchRow(row.id, p)} />
              {row.vat_category === 'taxable' &&
                <CommitInput value={row.vat_amount === null ? '' : moneyField(Number(row.vat_amount))}
                  disabled={busy} numeric validate={validMoney}
                  onCommit={v => patchRow(row.id, { vat_amount: decimalInput(v) })} />}</>}
          </span>
        </td>
        <td className="num">{columnAmount(row.net_amount)}</td>
        <td className="num">{columnAmount(row.gross_amount)}</td>
      </tr>)}</tbody>
    </table>
  </div>
}
