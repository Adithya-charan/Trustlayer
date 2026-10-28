import { useState } from 'react'
import { motion } from 'framer-motion'
import { ShieldCheck } from 'lucide-react'
import { api, setToken } from '../lib/api'
import { useApi } from '../lib/useApi'
import { Button, Panel as Card, ErrorState, Skeleton } from './ui'

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
    <main className="flex min-h-screen items-center justify-center bg-navy-900 p-4">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="w-full max-w-md">
        <Card className="space-y-5 p-6 shadow-xl">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-navy-900 p-2 text-teal-400"><ShieldCheck className="h-6 w-6" aria-hidden /></div>
            <div>
              <h1 className="text-xl font-semibold text-navy-900">TrustLayer</h1>
              <p className="text-sm text-slate-600">Share only what each task needs. Synthetic demo data.</p>
            </div>
          </div>
          {loading && <Skeleton className="h-24 w-full" />}
          {error && <ErrorState error={error} onRetry={reload} />}
          {users && (
            <form onSubmit={submit} className="space-y-4">
              <fieldset>
                <legend className="mb-2 text-sm font-medium text-navy-900">Choose a demo account</legend>
                <div className="grid gap-2">
                  {users.map((u) => (
                    <label key={u.username} className={`flex cursor-pointer items-center justify-between rounded-xl border p-3 text-sm ${username === u.username ? 'border-navy-600 bg-navy-50' : 'border-navy-200'}`}>
                      <span><span className="font-medium">{u.display_name}</span><span className="block text-xs text-slate-500">{ROLE_LABEL[u.role] || u.role} · {u.username}</span></span>
                      <input type="radio" name="user" value={u.username} checked={username === u.username} onChange={() => setUsername(u.username)} className="h-4 w-4 accent-navy-700" />
                    </label>
                  ))}
                </div>
              </fieldset>
              <div>
                <label htmlFor="pw" className="mb-1 block text-sm font-medium text-navy-900">Demo password</label>
                <input id="pw" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="min-h-10 w-full rounded-xl border border-navy-200 px-3 text-sm" />
                <p className="mt-1 text-xs text-slate-500">The demo password is the DEMO_PASSWORD value in backend/.env.</p>
              </div>
              {formError && <p role="alert" className="rounded-lg bg-red-50 p-2 text-sm text-red-700">{formError}</p>}
              <Button type="submit" className="w-full" loading={busy} disabled={!username || !password}>Sign in</Button>
            </form>
          )}
        </Card>
      </motion.div>
    </main>
  )
}
