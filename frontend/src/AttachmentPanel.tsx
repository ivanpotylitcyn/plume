// Волна 11: панель вложений — переиспуемая во всех кокпитах-владельцах
// (приход/передача/комплектация/инвентаризация/списание/требование) и на экране
// изделия. PDF/сканы подписанных документов, datasheet/КД изделия. Самодостаточна:
// грузит свой список по (ownerType, ownerId) и перечитывает его после мутаций —
// вложения не двигают склад, освежать соседние панели не нужно.
import { useEffect, useRef, useState } from 'react'
import { api, type AttachmentRow } from './api'
import { CommitInput } from './ReceiptView'

function humanSize(n: number): string {
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} КБ`
  return `${(n / (1024 * 1024)).toFixed(1)} МБ`
}

export function AttachmentPanel({ ownerType, ownerId }: {
  ownerType: string; ownerId: number
}) {
  const [rows, setRows] = useState<AttachmentRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const reload = () =>
    api.attachments(ownerType, ownerId).then(setRows).catch(e => setErr(String(e)))
  useEffect(() => { setRows(null); setErr(null); reload() }, [ownerType, ownerId])

  const run = (p: Promise<unknown>) => {
    setBusy(true); setErr(null)
    p.then(() => reload())
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy(true); setErr(null)
    api.uploadAttachment(ownerType, ownerId, file)
      .then(() => reload())
      .catch(er => setErr(er instanceof Error ? er.message : String(er)))
      .finally(() => { setBusy(false); if (fileRef.current) fileRef.current.value = '' })
  }

  return (
    <>
      <div className="section-h">Вложения
        <span className="hint">PDF/сканы · подписанные документы</span></div>
      <div className="kit-actions">
        <input ref={fileRef} type="file" disabled={busy} onChange={onPick} />
        {busy && <span className="hint">загружаю…</span>}
        {err && <span className="anomaly">{err}</span>}
      </div>
      {rows && rows.length > 0 &&
        <table className="grid">
          <thead><tr><th>файл</th><th>подпись</th>
            <th style={{ textAlign: 'right' }}>размер</th><th>загрузил</th><th /></tr></thead>
          <tbody>{rows.map(a => (
            <tr key={a.id} className="row">
              <td><a className="link" href={a.url} target="_blank" rel="noreferrer">{a.filename}</a></td>
              <td><CommitInput value={a.label} width={220} disabled={busy}
                onCommit={v => run(api.updateAttachment(a.id, v))} /></td>
              <td className="num" style={{ color: 'var(--fg-dim)' }}>{humanSize(a.size)}</td>
              <td style={{ color: 'var(--fg-dim)' }}>{a.user || '—'}</td>
              <td style={{ textAlign: 'right' }}>
                <button className="x" title="удалить вложение" disabled={busy}
                  onClick={() => run(api.deleteAttachment(a.id))}>×</button></td>
            </tr>))}</tbody>
        </table>}
      {rows && rows.length === 0 &&
        <div style={{ color: 'var(--fg-dim)' }}>Нет вложений</div>}
    </>
  )
}
