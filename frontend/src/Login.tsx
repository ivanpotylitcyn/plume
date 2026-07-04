// Экран входа (волна 12). Внутренний инструмент: сам-регистрации нет, юзеров
// заводят в admin. Моно-forward карточка в фирменном стиле; на успех отдаёт
// пользователя наверх (App перерисуется в приложение).
import { useState } from 'react'
import { api, type User } from './api'

export function Login({ onSuccess }: { onSuccess: (u: User) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) { setErr('Введите логин и пароль'); return }
    setBusy(true); setErr(null)
    api.login(username.trim(), password)
      .then(onSuccess)
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">plume</div>
        <div className="login-sub">PLM-система · вход</div>
        <label className="login-field">
          <span>Логин</span>
          <input autoFocus value={username} disabled={busy}
            onChange={e => setUsername(e.target.value)} />
        </label>
        <label className="login-field">
          <span>Пароль</span>
          <input type="password" value={password} disabled={busy}
            onChange={e => setPassword(e.target.value)} />
        </label>
        <button className="btn login-btn" type="submit" disabled={busy}>
          {busy ? 'Вход…' : 'Войти'}
        </button>
        {err && <div className="login-err">{err}</div>}
      </form>
    </div>
  )
}
