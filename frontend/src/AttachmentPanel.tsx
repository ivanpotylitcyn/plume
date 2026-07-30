// Волна 11: панель вложений — переиспуемая во всех формах-владельцах
// (приход/передача/комплектация/инвентаризация/списание/требование) и на экране
// изделия. PDF/сканы подписанных документов, datasheet/КД изделия. Самодостаточна:
// грузит свой список по (ownerType, ownerId) и перечитывает его после мутаций —
// вложения не двигают склад, освежать соседние панели не нужно.
//
// Волна 19, Ф12a-добор: загрузка файла — КОМАНДА ШАПКИ («Загрузить», §13.8), а не
// поле выбора над списком. Поэтому состояние вынесено в хук `useAttachments`: форма
// берёт из него `pick` для кнопки шапки, а таб «Файлы» рисует один только список —
// такой же грид, как везде.
import { useCallback, useEffect, useState } from 'react'
import { api, type AttachmentRow } from './api'
import { FileGlyph } from './status'
import { CommitInput } from './CommitInput'

function humanSize(n: number): string {
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} КБ`
  return `${(n / (1024 * 1024)).toFixed(1)} МБ`
}

export interface Attachments {
  rows: AttachmentRow[] | null
  err: string | null
  busy: boolean
  pick: () => void                       // открыть выбор файла (команда шапки)
  run: (p: Promise<unknown>) => void
}

export function useAttachments(ownerType: string, ownerId: number): Attachments {
  const [rows, setRows] = useState<AttachmentRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(
    () => api.attachments(ownerType, ownerId).then(setRows).catch(e => setErr(String(e))),
    [ownerType, ownerId])
  useEffect(() => { setRows(null); setErr(null); reload() }, [reload])

  const run = (p: Promise<unknown>) => {
    setBusy(true); setErr(null)
    p.then(() => reload())
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Поле выбора файла в разметке не держим: команда живёт в шапке, а системный диалог
  // открываем одноразовым скрытым input'ом. Так у таба «Файлы» — чистый список.
  const pick = () => {
    const el = document.createElement('input')
    el.type = 'file'
    el.onchange = () => {
      const file = el.files?.[0]
      if (file) run(api.uploadAttachment(ownerType, ownerId, file))
    }
    el.click()
  }

  return { rows, err, busy, pick, run }
}

// Дата загрузки — коротко и в порядке возрастания разрядов, как везде в списках.
function shortDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('ru-RU')
}

// Список вложений — тело таба «Файлы» (§13.8). Колонки как у любого списка формы:
// глиф (вид файла × живость на диске) · имя · описание · размер · загружено · кем ·
// команды строки. Дубль «имя + Скачать» оставлен намеренно и оправдался: клик по
// имени ОТКРЫВАЕТ файл во вкладке, кнопка `download` — СКАЧИВАЕТ (принято 2026-07-26).
export function AttachmentList({ att, locked }: { att: Attachments; locked: boolean }) {
  const { rows, err, busy, run } = att
  return (
    <>
      {err && <div className="anomaly">{err}</div>}
      {busy && <div className="hint">загружаю…</div>}
      {rows && rows.length > 0 &&
        <table className="grid">
          <thead><tr><th className="gl" /><th className="c-key">Файл</th>
            <th className="c-desc">Описание</th>
            <th className="c-fit num">Размер</th>
            <th className="c-fit">Загружено</th><th className="c-fit">Загрузил</th>
            <th className="act" /></tr></thead>
          <tbody>{rows.map(a => (
            <tr key={a.id} className="row">
              <td className="gl"><FileGlyph filename={a.filename} state={a.state} /></td>
              <td className="c-key">
                <a className="link" href={a.url} target="_blank" rel="noreferrer">{a.filename}</a></td>
              <td className="c-desc"><CommitInput value={a.description} disabled={locked || busy}
                onCommit={v => run(api.updateAttachment(a.id, v))} /></td>
              <td className="num c-fit">{humanSize(a.size)}</td>
              <td className="c-fit">{shortDate(a.uploaded_at)}</td>
              <td className="c-fit">{a.user || '—'}</td>
              {/* Команды строки — одними глифами (подписи есть в `title`): в списке
                  их много, и текст на каждой строке шумел бы (§7a). Удаление — только
                  в режиме ПРАВКИ, как корзина шапки (§5): просмотр чист и от случайного
                  удаления защищён структурно. Скачать можно всегда. */}
              <td className="act">
                <a className="fh-ctl icon" href={a.url} download title="Скачать файл">
                  <span className="ci ci-download" /></a>
                {!locked &&
                  <button className="fh-ctl icon fh-del" title="Удалить вложение" disabled={busy}
                    onClick={() => run(api.deleteAttachment(a.id))}>
                    <span className="ci ci-trash" /></button>}</td>
            </tr>))}</tbody>
        </table>}
      {rows && rows.length === 0 &&
        <div className="tab-empty">Нет вложений — «Загрузить» в шапке формы</div>}
    </>
  )
}
