import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { AlertTriangle, ChevronLeft, ChevronRight, Inbox, Loader2, RefreshCw } from 'lucide-react'
import { motion } from 'framer-motion'

export const cn = (...a) => twMerge(clsx(a))

export function Panel({ className, children, ...p }) {
  return <section className={cn('rounded-xl border border-slate-200 bg-white', className)} {...p}>{children}</section>
}

export function PanelHeader({ title, subtitle, actions, className }) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4', className)}>
      <div>
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function PageHeader({ title, description, actions }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-600">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Button({ variant = 'primary', size = 'md', className, loading, children, ...p }) {
  const styles = {
    primary: 'bg-navy-700 text-white hover:bg-navy-800 disabled:bg-slate-300',
    teal: 'bg-teal-700 text-white hover:bg-teal-800 disabled:bg-slate-300',
    outline: 'border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:opacity-50',
    ghost: 'text-navy-700 hover:bg-slate-100 disabled:opacity-50',
    danger: 'border border-red-300 bg-white text-red-700 hover:bg-red-50 disabled:opacity-50',
  }
  const sizes = { md: 'min-h-10 px-4 text-sm', sm: 'min-h-8 px-3 text-xs' }
  return (
    <button
      className={cn('inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed', sizes[size], styles[variant], className)}
      {...p}
      disabled={loading || p.disabled}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

const TONES = {
  CRITICAL: 'bg-red-50 text-red-700 ring-red-200',
  HIGH: 'bg-orange-50 text-orange-700 ring-orange-200',
  MEDIUM: 'bg-amber-50 text-amber-800 ring-amber-200',
  LOW: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  ALLOW: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  PARTIAL: 'bg-teal-50 text-teal-800 ring-teal-200',
  MASK: 'bg-teal-50 text-teal-800 ring-teal-200',
  DENY: 'bg-red-50 text-red-700 ring-red-200',
  COMPLETED: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  SUCCESS: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  FAILED: 'bg-red-50 text-red-700 ring-red-200',
  RETRYING: 'bg-amber-50 text-amber-800 ring-amber-200',
  RUNNING: 'bg-blue-50 text-blue-700 ring-blue-200',
  neutral: 'bg-slate-100 text-slate-700 ring-slate-200',
  info: 'bg-blue-50 text-blue-700 ring-blue-200',
}

export function Badge({ tone, children, className }) {
  return (
    <span className={cn('inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset', TONES[tone] || TONES.neutral, className)}>
      {children}
    </span>
  )
}

export const strategyTone = (s) => (s === 'DENY' ? 'DENY' : s === 'ALLOW' ? 'ALLOW' : 'MASK')

export const Skeleton = ({ className }) => <div aria-hidden className={cn('animate-pulse rounded-lg bg-slate-100', className)} />

export function Loading({ label = 'Loading…', rows = 3 }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3 p-5">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className={i === 0 ? 'h-5 w-1/3' : 'h-10 w-full'} />)}
    </div>
  )
}

export function ErrorState({ error, onRetry, className }) {
  return (
    <div role="alert" className={cn('m-4 flex flex-col items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800', className)}>
      <div className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" aria-hidden /> {error?.status === 403 ? 'Not permitted' : 'Could not load this data'}</div>
      <p>{error?.message || 'Unexpected error.'}</p>
      {error?.status === 0 && <p className="text-red-700">Nothing was substituted for the missing data. Retry once the backend is reachable.</p>}
      {onRetry && error?.status !== 403 && (
        <Button variant="outline" size="sm" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" aria-hidden /> Retry</Button>
      )}
    </div>
  )
}

export function Empty({ title, hint, action, icon: Icon = Inbox }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <Icon className="h-6 w-6 text-slate-400" aria-hidden />
      <p className="text-sm font-medium text-slate-800">{title}</p>
      {hint && <p className="max-w-md text-xs text-slate-500">{hint}</p>}
      {action}
    </div>
  )
}

export function Notice({ tone = 'info', children, className }) {
  const map = { info: 'border-blue-200 bg-blue-50 text-blue-900', success: 'border-emerald-200 bg-emerald-50 text-emerald-900', warn: 'border-amber-200 bg-amber-50 text-amber-900', error: 'border-red-200 bg-red-50 text-red-800' }
  return <div role={tone === 'error' ? 'alert' : 'status'} className={cn('rounded-lg border px-3 py-2 text-sm', map[tone], className)}>{children}</div>
}

export function Metric({ label, value, sub, tone }) {
  return (
    <div className="px-5 py-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={cn('mt-1 text-2xl font-semibold tabular-nums text-slate-900', tone === 'bad' && 'text-red-700', tone === 'good' && 'text-emerald-700')}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  )
}

export function MetricStrip({ children }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}
      className="grid grid-cols-2 divide-x divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white lg:grid-cols-4 lg:divide-y-0">
      {children}
    </motion.div>
  )
}

export function Table({ caption, children, className }) {
  return (
    <div className="overflow-x-auto">
      <table className={cn('w-full min-w-[36rem] text-left text-sm', className)}>
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  )
}
export const Th = ({ children, className }) => <th scope="col" className={cn('whitespace-nowrap bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500', className)}>{children}</th>
export const Td = ({ children, className }) => <td className={cn('border-t border-slate-100 px-4 py-2.5 align-top', className)}>{children}</td>

export function Select({ label, value, onChange, options, className, id }) {
  return (
    <label className={cn('flex flex-col gap-1 text-xs font-medium text-slate-600', className)}>
      {label}
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className="min-h-9 rounded-lg border border-slate-300 bg-white px-2 text-sm font-normal text-slate-900">
        {options.map((o) => {
          const [v, l] = Array.isArray(o) ? o : [o, o]
          return <option key={v} value={v}>{l}</option>
        })}
      </select>
    </label>
  )
}

export function TextInput({ label, className, hint, error, ...p }) {
  return (
    <label className={cn('flex flex-col gap-1 text-xs font-medium text-slate-600', className)}>
      {label}
      <input {...p} aria-invalid={Boolean(error)} className={cn('min-h-9 rounded-lg border bg-white px-3 text-sm font-normal text-slate-900', error ? 'border-red-400' : 'border-slate-300')} />
      {hint && !error && <span className="text-[11px] font-normal text-slate-500">{hint}</span>}
      {error && <span role="alert" className="text-[11px] font-normal text-red-700">{error}</span>}
    </label>
  )
}

export function Pager({ total, offset, limit, onChange }) {
  if (!total) return null
  const page = Math.floor(offset / limit) + 1
  const pages = Math.max(1, Math.ceil(total / limit))
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-xs text-slate-600">
      <span>{offset + 1}–{Math.min(offset + limit, total)} of {total}</span>
      <span className="flex items-center gap-1">
        <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => onChange(Math.max(0, offset - limit))} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button>
        Page {page} / {pages}
        <Button variant="ghost" size="sm" disabled={page >= pages} onClick={() => onChange(offset + limit)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button>
      </span>
    </nav>
  )
}

export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : '—')
export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString() : '—')
export const qs = (obj) => {
  const p = new URLSearchParams()
  Object.entries(obj).forEach(([k, v]) => v !== '' && v != null && p.set(k, v))
  const s = p.toString()
  return s ? `?${s}` : ''
}
export const inr = (n) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n)
