import { motion } from 'framer-motion'
import { ClipboardCheck, EyeOff, FileSearch, SlidersHorizontal } from 'lucide-react'
import { getToken } from '../lib/api'
import { useApi } from '../lib/useApi'
import { CountUp, StatusIndicator } from '../components/brand'
import ShieldIllustration from '../components/ShieldIllustration'
import { cn } from '../components/ui'

// Illustrative cards: synthetic examples of each stage, NOT values read from the database.
const STEPS = [
  { n: 1, icon: FileSearch, title: 'Discover', line: 'pan', detail: 'Government ID · critical', tint: 'bg-violet-50 text-violet-600', ring: 'border-violet-200', pos: 'left-0 top-[3%]' },
  { n: 2, icon: SlidersHorizontal, title: 'Evaluate', line: 'advisor · insurance_assessment', detail: 'Policy checks role and purpose', tint: 'bg-blue-50 text-blue-600', ring: 'border-blue-200', pos: 'right-0 top-[3%]' },
  { n: 3, icon: EyeOff, title: 'Mask or deny', line: 'pan → withheld', detail: 'annual_income → range band', tint: 'bg-teal-50 text-teal-600', ring: 'border-teal-200', pos: 'right-0 bottom-[3%]' },
  { n: 4, icon: ClipboardCheck, title: 'Record', line: 'Decision logged', detail: 'Field names only, no values', tint: 'bg-green-50 text-green-600', ring: 'border-green-200', pos: 'left-0 bottom-[3%]' },
]

function StepCard({ s, i, className }) {
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 + i * 0.1, duration: 0.4 }} whileHover={{ y: -3 }}
      className={cn('rounded-2xl border bg-white p-3.5 text-left shadow-card transition-shadow hover:shadow-lift', s.ring, className)}>
      <div className="flex items-center gap-2.5">
        <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-xl', s.tint)}><s.icon className="h-4 w-4" aria-hidden /></span>
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">Step {s.n}</p>
          <p className="truncate text-sm font-semibold text-body">{s.title}</p>
        </div>
      </div>
      <p className="mt-2 truncate font-mono text-[11px] text-slate-700">{s.line}</p>
      <p className="text-[11px] leading-snug text-muted">{s.detail}</p>
    </motion.div>
  )
}

function LiveActivity() {
  const health = useApi('/health', [])
  const signedIn = Boolean(getToken())
  const m = useApi(signedIn ? '/metrics/overview?days=7' : null, [signedIn])
  const up = health.data?.status === 'ok'
  const d = m.data
  return (
    <div className="mx-auto mt-6 w-full max-w-md rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-card" aria-live="polite">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted">Live system status</p>
        {health.loading ? <StatusIndicator tone="idle" label="Checking…" /> : up ? <StatusIndicator tone="active" pulse label="API online" /> : <StatusIndicator tone="bad" label="API unreachable" />}
      </div>
      <div className="grid grid-cols-3 gap-3 text-center">
        {d ? (
          <>
            <Stat label="Decisions · 7d" value={d.decisions.events_counted} />
            <Stat label="Sensitive fields" value={d.fields.sensitive} />
            <Stat label="High-severity" value={d.risk.available ? d.risk.by_severity.HIGH || 0 : '—'} />
          </>
        ) : (
          <>
            <Stat label="Database" value={health.data ? (health.data.database.connected ? 'Connected' : 'Down') : '—'} text />
            <Stat label="Config" value={health.data ? (health.data.config_ok ? 'Valid' : 'Issues') : '—'} text />
            <Stat label="Data" value="Synthetic" text />
          </>
        )}
      </div>
      <p className="mt-3 text-[11px] leading-snug text-muted">
        {d ? 'Real counts from your session, last 7 days.' : signedIn ? (m.loading ? 'Loading your metrics…' : 'Metrics unavailable right now.') : 'Sign in to see live decision and field counts. Nothing here is simulated.'}
      </p>
    </div>
  )
}

function Stat({ label, value, text }) {
  return (
    <div className="rounded-xl bg-mist px-2 py-2.5">
      <p className={cn('font-semibold text-body', text ? 'text-sm' : 'text-xl tabular-nums')}>{typeof value === 'number' ? <CountUp value={value} /> : value}</p>
      <p className="mt-0.5 text-[10px] uppercase tracking-wider text-muted">{label}</p>
    </div>
  )
}

export default function HeroVisual() {
  return (
    <div className="relative mx-auto w-full max-w-[34rem]">
      {/* Phones: shield on top, cards stacked in a grid (nothing overlaps) */}
      <div className="sm:hidden">
        <div className="mx-auto h-52 w-52"><ShieldIllustration /></div>
        <div className="mt-2 grid grid-cols-2 gap-3">{STEPS.map((s, i) => <StepCard key={s.n} s={s} i={i} />)}</div>
      </div>

      {/* Tablet and up: shield in the centre, four cards in the corners, flow arrows between them */}
      <div className="relative hidden aspect-square sm:block">
        <div className="absolute inset-0 flex items-center justify-center"><div className="aspect-square w-[46%] animate-float-slow"><ShieldIllustration /></div></div>
        <svg aria-hidden viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
          <defs><marker id="hv-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 10 5 0 10z" fill="#2563EB" /></marker></defs>
          {[['M34 17 L66 17'], ['M84 31 L84 69'], ['M66 83 L34 83']].map(([d]) => <path key={d} d={d} fill="none" stroke="#2563EB" strokeOpacity="0.55" strokeWidth="1.6" vectorEffect="non-scaling-stroke" markerEnd="url(#hv-arrow)" className="dash-flow animate-flow" />)}
        </svg>
        {STEPS.map((s, i) => <StepCard key={s.n} s={s} i={i} className={cn('absolute w-[34%]', s.pos)} />)}
      </div>
      <p className="mt-2 text-center text-[11px] text-muted">Illustration with synthetic examples. Not read from the database.</p>
      <LiveActivity />
    </div>
  )
}
