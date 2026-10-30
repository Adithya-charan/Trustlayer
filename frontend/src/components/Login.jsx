import { useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowLeft, Eye, Lock, ScrollText } from 'lucide-react'
import { api, setToken } from '../lib/api'
import { useApi } from '../lib/useApi'
import { AnimatedBackground, Logo } from './brand'
import ShieldIllustration from './ShieldIllustration'
import { Button, ErrorState, Skeleton, cn } from './ui'

const ROLE_LABEL = { security_admin: 'Security admin', compliance_officer: 'Compliance', advisor: 'Financial advisor', analyst: 'Data analyst' }

export default function Login({ onLogin }) {
  const { data: users, error, loading, reload } = useApi('/auth/demo-users')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState(null)

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setFormError(null)
    try {
      const res = await api('/auth/login', { method: 'POST', body: { username, password } })
      setToken(res.token)
      onLogin(res.user)
    } catch (err) {
      setFormError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-screen bg-mist lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-slate-200 bg-gradient-to-br from-blue-50 via-white to-violet-50 p-12 lg:flex lg:flex-col lg:justify-between">
        <AnimatedBackground />
        <a href="#/" className="relative"><Logo id="login-logo" /></a>
        <div className="relative">
          <div className="mx-auto h-56 w-56"><ShieldIllustration /></div>
          <h1 className="mt-6 max-w-md text-4xl font-semibold leading-tight text-body">Every request gets only what it needs.</h1>
          <p className="mt-4 max-w-md text-muted">Sign in with a synthetic demo account to scan data, change policies, request access and read the audit trail. Roles decide what you can see, enforced by the server.</p>
          <ul className="mt-6 space-y-3 text-sm text-slate-700">
            {[[Lock, 'Server-side role-based access', 'bg-blue-50 text-blue-600'], [Eye, 'Masking applied to the response, never the source', 'bg-violet-50 text-violet-600'], [ScrollText, 'Value-free audit trail for every decision', 'bg-teal-50 text-teal-600']].map(([Ic, t, c]) => (
              <li key={t} className="flex items-center gap-3"><span className={cn('flex h-8 w-8 items-center justify-center rounded-lg', c)}><Ic className="h-4 w-4" aria-hidden /></span>{t}</li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-muted">Prototype using synthetic data. Not a compliance certification.</p>
      </section>

      <section className="relative flex items-center justify-center p-5 sm:p-10">
        <div aria-hidden className="absolute -right-24 -top-24 h-72 w-72 rounded-full bg-[radial-gradient(circle,rgba(37,99,235,0.10),transparent_65%)] lg:hidden" />
        <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="relative w-full max-w-md">
          <a href="#/" className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-body"><ArrowLeft className="h-4 w-4" aria-hidden /> Back to product page</a>
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-lift sm:p-8">
            <Logo className="lg:hidden" id="login-logo-m" />
            <h2 className="mt-3 text-2xl font-semibold text-body lg:mt-0">Sign in</h2>
            <p className="mt-1 text-sm text-muted">Choose a demo account and enter the demo password.</p>
            {loading && <Skeleton className="mt-5 h-32 w-full" />}
            {error && <ErrorState error={error} onRetry={reload} className="mx-0" />}
            {users && (
              <form onSubmit={submit} className="mt-5 space-y-4">
                <fieldset>
                  <legend className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Demo account</legend>
                  <div className="grid gap-2">
                    {users.map((u) => (
                      <label key={u.username} className={cn('flex cursor-pointer items-center justify-between rounded-xl border p-3 text-sm transition-colors', username === u.username ? 'border-navy-600 bg-blue-50/60 ring-1 ring-navy-600/30' : 'border-slate-200 hover:bg-slate-50')}>
                        <span><span className="font-medium text-body">{u.display_name}</span><span className="block text-xs text-muted">{ROLE_LABEL[u.role] || u.role} · {u.username}</span></span>
                        <input type="radio" name="user" value={u.username} checked={username === u.username} onChange={() => setUsername(u.username)} className="h-4 w-4 accent-blue-600" />
                      </label>
                    ))}
                  </div>
                </fieldset>
                <div>
                  <label htmlFor="pw" className="mb-1 block text-xs font-semibold uppercase tracking-wider text-muted">Demo password</label>
                  <input id="pw" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm focus:border-navy-600" />
                  <p className="mt-1 text-xs text-muted">The demo password is the DEMO_PASSWORD value in backend/.env.</p>
                </div>
                {formError && <p role="alert" className="rounded-lg bg-rose-50 p-2.5 text-sm text-rose-700">{formError}</p>}
                <Button type="submit" className="w-full" loading={busy} disabled={!username || !password}>Sign in</Button>
              </form>
            )}
          </div>
        </motion.div>
      </section>
    </main>
  )
}
