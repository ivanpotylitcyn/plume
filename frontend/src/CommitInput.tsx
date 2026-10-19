// Автосейв текстового/числового поля: коммит по blur / Enter (без кнопки).
// Единственный контрол ввода форм — и шапки, и строк списка (§6).
//
// Ширины у контрола НЕТ вовсе (Б2а аудита-1, 2026-07-30): её решает CSS — токен
// `--in-num` у числа, колонка (`.c-key`/`.c-desc`/`.c-txt`) у текста, ступень шапки у
// поля формы. Проп `width` (волна 19, Ф12a) снят: он ставил inline-стиль, а тот сильнее
// любого класса — одно и то же «кол-во» разъехалось на 56/60/72 по четырём формам.
//
// Живёт отдельным модулем с волны 19 (Ф12c): раньше лежал в `ReceiptView`, и общие
// поля шапки ордера (`OrderFields` в `FormHeader`) замкнули бы импорты в кольцо.
//
// Гигиена текста (2026-10-15, запрос Ивана): перед сохранением текст спрашивает
// движок (`/api/hygiene/`) — правило одно и живёт там, копии здесь нет. Грязный ввод
// (табуляция, неразрывный пробел, двойные пробелы, у кода — минус вместо дефиса) не
// сохраняется молча: под полем всплывает очищенный вариант с выбором «Принять» /
// «Перепишу сам». Пробелы по краям движок срезает без вопроса. Числа, даты и чисто
// числовой текст (кол-ва в строках таблиц) не спрашиваем — грязи в них не бывает, а
// лишний запрос задержал бы самый частый автосейв продукта.
import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { AnchoredMenu } from './AnchoredMenu'

const PLAIN_NUMBER = /^-?[\d.,]*$/
// Любые пробелы — обычные, неразрывные, узкие (разряды в счетах и PDF).
const SPACES = /\s/g

export function CommitInput({ value, onCommit, disabled, validate, type, code, numeric }: {
  value: string; onCommit: (v: string) => void; disabled?: boolean
  validate?: (v: string) => boolean; type?: string
  code?: boolean               // поле кода: гигиена по кодовому правилу (дефисы)
  // Числовое поле (волна 24, цена строки заказа): пробелы разрядов, скопированные из
  // счёта, вычищаются сразу при вводе — молча, без вопроса гигиены: в числе пробел не
  // смысл, а оформление.
  numeric?: boolean
}) {
  const [v, setV] = useState(value)
  const [offer, setOffer] = useState<string | null>(null)   // очищенный вариант на выбор
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { setV(value) }, [value])

  const save = (next: string) => { if (next !== value) onCommit(next) }

  const commit = () => {
    if (v === value || offer !== null) return
    if (validate && !validate(v)) { setV(value); return }
    if ((type && type !== 'text') || PLAIN_NUMBER.test(v)) { onCommit(v); return }
    // Движок недоступен — сохраняем как есть: запись в БД он всё равно почистит молча.
    api.hygiene(v, !!code)
      .then(h => { if (h.dirty) setOffer(h.cleaned); else { setV(h.cleaned); save(h.cleaned) } })
      .catch(() => onCommit(v))
  }

  const accept = () => {
    if (offer === null) return
    setV(offer); setOffer(null); save(offer)
  }
  // «Перепишу сам»: исходный текст остаётся в поле, фокус возвращается в него.
  const rewrite = () => { setOffer(null); input.current?.focus() }

  useEffect(() => {
    if (offer === null) return
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); rewrite() }
      if (e.key === 'Enter') { e.preventDefault(); accept() }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offer])

  return (
    <>
      <input ref={input} className="qty-in"
        value={v} disabled={disabled} type={type}
        onChange={e => setV(numeric ? e.target.value.replace(SPACES, '') : e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
      {offer !== null && <>
        {/* Подложка на всё окно: клик мимо = «Перепишу сам» (как у меню фильтров). */}
        <AnchoredMenu anchor={input} className="typeahead-menu hygiene-pop" onVeil={rewrite}>
          <div className="hy-note">Лишние символы. Сохранить так?</div>
          <div className={'hy-text' + (code ? ' code' : '')}>{offer || '—'}</div>
          <div className="typeahead-item" onClick={accept}>
            <span className="ci ci-check" /><span>Принять</span>
          </div>
          <div className="typeahead-item" onClick={rewrite}>
            <span className="ci ci-edit" /><span>Перепишу сам</span>
          </div>
        </AnchoredMenu>
      </>}
    </>
  )
}
