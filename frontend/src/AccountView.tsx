// Форма АККАУНТА (волна 21) — канон §13. Пользователь становится сущностью со своей
// каноничной формой, а не строкой в пикере авторства:
//
//   титул = username                          ← идентичность, полем НЕ рисуется
//   ДНК (Имя / Фамилия / Почта) + Тема        ← шапка `.props`
//   [Закупки] [Заказы] [Ордера]               ← табы: «что я вёл»
//
// Три решения, из-за которых форма выглядит не как остальные:
//
// 1. **Титул есть, поля нет** (Р3). `username` — это `code` человека: короткий
//    уникальный жаргон, которым он и опознаётся. Но задаётся он админкой, значит
//    степенью свободы ЭТОЙ формы не является — и полем не рисуется вовсе. Это не
//    исключение из §13.4, а уже принятый приём: «признак, задаваемый вне формы, полем
//    не рисуем» (так с 2026-07-26 снят `Item.native`). Его ОТСУТСТВИЕ и есть сообщение:
//    это не то, что ты правишь. Серое поле сказало бы то же самое, но шумом.
// 2. **Фиксации нет** (Р2). `locked` в продукте значит «стал фактом, движок дальше не
//    даст менять». Человек не документ — замораживать нечего. Остаётся личный замок
//    формы (`useFormLock`). Прецедент — контрагент (волна 20).
// 3. **Корзины нет.** Себя не удаляем: `onDelete` не передаётся, и кнопки просто не
//    существует. Пользователей заводит и гасит админка (`is_active`).
//
// Табы, в отличие от формы контрагента, НЕ сужаются. Там сторона — факт о внешней
// организации, и пустой стороны у неё не бывает. Здесь три таба — рабочее место
// человека, а не факт о нём: пустой таб с текстом «вы ещё не вели закупок» честнее
// исчезнувшего.
import { useEffect, useState } from 'react'
import { api, type AccountForm } from './api'
import { count } from './status'
import { resetUsersCache, useFormLock } from './FormHeader'
import { FormShell, type FormTab } from './FormShell'
import { Field, TextField } from './FormField'
import { Dropdown } from './Dropdown'
import { DocumentFeed, ProcurementFeed, PurchaseFeed } from './FeedTables'
import { applyTheme, type ThemeSlug } from './core/theme'
import { THEMES, THEME_LABEL } from './themes/registry'
import type { OrderKind } from './orders'

export function AccountView({ openProcurement, openPurchase, openOrder, onChanged,
  onLogout }: {
  openProcurement: (id: number) => void
  openPurchase: (id: number) => void
  openOrder: (kind: OrderKind, id: number) => void
  onChanged: (fullName: string) => void   // подпись в панели режимов знает новое имя
  onLogout: () => void
}) {
  const [a, setA] = useState<AccountForm | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Форма существующей сущности открывается В ПРОСМОТРЕ (§5). `id` замка — 0: аккаунт
  // один, сменить его в этой форме нельзя, и сбрасывать режим на смену нечего.
  const { unlocked, toggle } = useFormLock(0)
  // Смена пароля — раскрывающаяся тройка полей. Живёт локально: это не свойство
  // пользователя, а состояние формы (см. ниже, почему тут нет автосейва).
  const [pw, setPw] = useState<{ current: string; next: string; repeat: string } | null>(null)

  useEffect(() => {
    api.account().then(setA).catch(e => setErr(String(e)))
  }, [])

  // Закрыли замок — свернуть и панель пароля: под замком форма чистый текст без
  // единого поля ввода (§5), и три поля пароля в ней были бы прямым исключением.
  useEffect(() => { if (!unlocked) setPw(null) }, [unlocked])

  const run = (p: Promise<AccountForm>) => {
    setBusy(true); setErr(null)
    p.then(next => {
      setA(next)
      // Долг, закрытый здесь же: модульный кэш справочника пользователей не сбрасывался
      // никогда, и после смены имени дропдаун авторов в правке показывал старое.
      resetUsersCache()
      onChanged(next.full_name)
    })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  // Тема применяется СРАЗУ по выбору (Р4), как любой автосейв: промежуточное «выбрано,
  // но не применено» продукт убивал везде, и заводить его здесь — значит заводить
  // кнопку «Применить», которой в продукте нет ни на одной форме.
  const pickTheme = (slug: ThemeSlug) => {
    applyTheme(slug)
    run(api.updateAccount({ theme: slug }))
  }

  // Пароль — ЕДИНСТВЕННОЕ место продукта, где поле не коммитится по blur, и это
  // честно: пароль нельзя сохранить по уходу фокуса, его подтверждают. Успех МОЛЧИТ
  // (поля схлопываются, кнопка возвращается) — тостов в продукте нет, и городить
  // инфраструктуру уведомлений ради одного случая значит делать запас на будущее.
  const savePassword = () => {
    if (!pw) return
    setBusy(true); setErr(null)
    api.changePassword({ current: pw.current, new: pw.next, repeat: pw.repeat })
      .then(() => setPw(null))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (err && !a) return <div className="empty">Ошибка: {err}</div>
  if (!a) return <div className="empty">Загрузка…</div>

  const locked = !unlocked

  const tabs: FormTab[] = [
    { key: 'procurements', label: 'Закупки', icon: 'law',
      content: <ProcurementFeed rows={a.procurements} open={openProcurement}
        empty="Вы ещё не вели закупок." /> },
    { key: 'purchases', label: 'Заказы', icon: 'package',
      content: <PurchaseFeed rows={a.purchases} open={openPurchase}
        empty="Вы ещё не оформляли заказов." /> },
    // Один таб на семь видов, вид — колонка (как в списке режима «Ордера»). Семь
    // табов рассказывали бы про устройство модели, а не про работу человека.
    { key: 'documents', label: 'Ордера', icon: 'notebook',
      content: <DocumentFeed rows={a.documents} open={openOrder}
        empty="Вы ещё не оформляли ордеров." /> },
  ]

  return (
    <FormShell
      id={0} code={a.username} entity="аккаунт" locked={locked} error={err}
      meta={<>
        {count(a.procurements.length, 'закупка', 'закупки', 'закупок')}
        {' · '}{count(a.purchases.length, 'заказ', 'заказа', 'заказов')}
        {' · '}{count(a.documents.length, 'ордер', 'ордера', 'ордеров')}
      </>}
      unlocked={unlocked} onToggleLock={toggle}
      actions={[
        // Кнопка сама себе подпись состояния: закрытая говорит, что сделает клик,
        // раскрытая — что подтвердит (§5, «глиф = назначение»).
        ...(unlocked ? [{
          onClick: () => (pw ? savePassword()
            : setPw({ current: '', next: '', repeat: '' })),
          label: pw ? 'Сохранить пароль' : 'Сменить пароль',
          icon: pw ? 'ci-check' : 'ci-key',
          title: pw ? 'Подтвердить смену пароля'
            : 'Сменить пароль — три поля в шапке (текущий / новый / повтор)',
          disabled: busy,
        }] : []),
        // «Выход» переехал сюда из панели режимов: его место — среди команд «себя»,
        // а не рядом с режимами работы.
        { onClick: onLogout, label: 'Выход', icon: 'ci-sign-out',
          title: 'Выйти из системы' },
      ]}
      // Порядок §13.4a: литературное имя → внешний атрибут (почта) → настройка (тема).
      // `username` полем не рисуется — он титул (см. шапку файла).
      fields={<>
        <TextField label="Имя" value={a.first_name} locked={locked} busy={busy}
          onCommit={v => run(api.updateAccount({ first_name: v }))} />
        <TextField label="Фамилия" value={a.last_name} locked={locked} busy={busy}
          onCommit={v => run(api.updateAccount({ last_name: v }))} />
        <TextField label="Почта" value={a.email} locked={locked} busy={busy}
          onCommit={v => run(api.updateAccount({ email: v }))} />
        {/* Тема — настройка ВЬЮ, но свойство ЧЕЛОВЕКА: движок хранит слаг, ярлыки
            приходят из реестра темы (`themes/registry.ts`), и о цветах форма не знает. */}
        <Field label="Тема интерфейса" locked={locked} view={THEME_LABEL[a.theme]}>
          <Dropdown value={a.theme} disabled={busy}
            options={THEMES.map(t => ({ value: t.slug, label: t.label }))}
            onPick={v => pickTheme(v as ThemeSlug)} />
        </Field>
        {/* Три поля пароля живут в шапке, а не в отдельной панели: это ДНК человека,
            там же, где имя. Раскрыты только под открытым замком. */}
        {pw && <>
          <Field label="Текущий пароль" locked={false}>
            <input className="qty-in" type="password" autoComplete="current-password"
              value={pw.current} disabled={busy}
              onChange={e => setPw({ ...pw, current: e.target.value })} />
          </Field>
          <Field label="Новый пароль" locked={false}>
            <input className="qty-in" type="password" autoComplete="new-password"
              value={pw.next} disabled={busy}
              onChange={e => setPw({ ...pw, next: e.target.value })} />
          </Field>
          <Field label="Повтор пароля" locked={false}>
            <input className="qty-in" type="password" autoComplete="new-password"
              value={pw.repeat} disabled={busy}
              onChange={e => setPw({ ...pw, repeat: e.target.value })}
              onKeyDown={e => { if (e.key === 'Enter') savePassword() }} />
          </Field>
        </>}
      </>}
      tabs={tabs}
    />
  )
}
