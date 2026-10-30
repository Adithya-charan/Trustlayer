import { useEffect, useId, useRef, useState } from 'react'
import { animate, motion, useInView, useReducedMotion } from 'framer-motion'
import { cn } from './ui'

// Shield mark: blue to violet gradient with a white lock. Used as the logo and in illustrations.
export function ShieldMark({ className, id = 'sm' }) {
  const uid = useId().replace(/:/g, '')
  const gid = `${id}-${uid}`
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="5" y1="2" x2="27" y2="30" gradientUnits="userSpaceOnUse">
          <stop stopColor="#2563EB" /><stop offset="1" stopColor="#7C3AED" />
        </linearGradient>
      </defs>
      <path d="M16 2.5 5 6.6v8.2c0 6.3 4.3 11.6 11 14.7 6.7-3.1 11-8.4 11-14.7V6.6L16 2.5Z" fill={`url(#${gid})`} />
      <path d="M16 2.5 5 6.6v8.2c0 6.3 4.3 11.6 11 14.7V2.5Z" fill="#fff" opacity="0.16" />
      <rect x="11.2" y="13.4" width="9.6" height="7.2" rx="1.6" fill="#fff" />
      <path d="M13.2 13.4v-1.9a2.8 2.8 0 0 1 5.6 0v1.9" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="16" cy="17" r="1.1" fill="#2563EB" />
    </svg>
  )
}

export function Logo({ className, id = 'logo' }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5 font-semibold tracking-tight text-body', className)}>
      <ShieldMark className="h-8 w-8 drop-shadow-sm" id={id} />
      <span className="text-lg">TrustLayer</span>
    </span>
  )
}

// SVG dot grid (adapted from the dot-pattern idea; static, aria-hidden, no layout cost).
export function DotPattern({ className, gap = 22, r = 1.1 }) {
  const id = useId().replace(/:/g, '')
  return (
    <svg aria-hidden className={cn('pointer-events-none absolute inset-0 h-full w-full text-navy-300/60', className)}>
      <defs><pattern id={`dp-${id}`} width={gap} height={gap} patternUnits="userSpaceOnUse"><circle cx={r} cy={r} r={r} fill="currentColor" /></pattern></defs>
      <rect width="100%" height="100%" fill={`url(#dp-${id})`} />
    </svg>
  )
}

// Soft blue/violet light behind sections on a LIGHT canvas. Slow transforms only, no blur filters.
export function AnimatedBackground({ className, dots = true }) {
  return (
    <div aria-hidden className={cn('pointer-events-none absolute inset-0 overflow-hidden', className)}>
      {dots && <DotPattern className="[mask-image:radial-gradient(ellipse_70%_60%_at_50%_30%,#000_25%,transparent_75%)]" />}
      <div className="absolute -left-24 -top-28 h-[26rem] w-[26rem] animate-drift rounded-full bg-[radial-gradient(circle,rgba(37,99,235,0.14),transparent_65%)]" />
      <div className="absolute -right-28 top-10 h-[28rem] w-[28rem] animate-drift rounded-full bg-[radial-gradient(circle,rgba(124,58,237,0.13),transparent_65%)] [animation-delay:-6s]" />
      <div className="absolute bottom-[-9rem] left-1/3 h-[22rem] w-[22rem] animate-drift rounded-full bg-[radial-gradient(circle,rgba(13,148,136,0.09),transparent_65%)] [animation-delay:-10s]" />
    </div>
  )
}

// Scroll-triggered reveal; renders plainly when the user prefers reduced motion.
export function Reveal({ children, delay = 0, y = 16, className, as: Tag = 'div' }) {
  const reduce = useReducedMotion()
  const M = motion[Tag] || motion.div
  if (reduce) return <Tag className={className}>{children}</Tag>
  return (
    <M className={className} initial={{ opacity: 0, y }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-50px' }} transition={{ duration: 0.45, delay, ease: [0.22, 1, 0.36, 1] }}>
      {children}
    </M>
  )
}

// Counter for REAL numbers only. The true value is always what React renders; the count-up is decoration that
// starts once the number is visible and always ends on the exact value. No animation under reduced motion.
export function CountUp({ value, className }) {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true })
  const reduce = useReducedMotion()
  const isNum = typeof value === 'number' && Number.isFinite(value)
  const [shown, setShown] = useState(value)
  useEffect(() => {
    if (!isNum || reduce || !inView) { setShown(value); return undefined }
    const controls = animate(0, value, { duration: 0.8, ease: 'easeOut', onUpdate: (v) => setShown(Math.round(v)), onComplete: () => setShown(value) })
    return () => { controls.stop(); setShown(value) }
  }, [value, isNum, reduce, inView])
  return <span ref={ref} className={className}>{isNum ? shown.toLocaleString() : value}</span>
}

const DOT = { ok: 'bg-green-600', warn: 'bg-amber-500', bad: 'bg-rose-600', active: 'bg-teal-500', idle: 'bg-slate-400', info: 'bg-navy-600' }
export function StatusIndicator({ tone = 'idle', label, pulse = false, className }) {
  return (
    <span className={cn('inline-flex items-center gap-2 text-xs font-medium text-slate-700', className)}>
      <span className="relative flex h-2.5 w-2.5">
        {pulse && <span className={cn('absolute inline-flex h-full w-full animate-ring rounded-full opacity-60', DOT[tone])} />}
        <span className={cn('relative inline-flex h-2.5 w-2.5 rounded-full', DOT[tone])} />
      </span>
      {label}
    </span>
  )
}

export function GlassCard({ className, children, ...p }) {
  return <div className={cn('glass-light rounded-2xl shadow-card', className)} {...p}>{children}</div>
}

export function SectionHeading({ eyebrow, title, description, align = 'center' }) {
  return (
    <div className={cn('max-w-2xl', align === 'center' ? 'mx-auto text-center' : 'text-left')}>
      {eyebrow && <p className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-navy-600">{eyebrow}</p>}
      <h2 className="text-3xl font-semibold text-body sm:text-4xl">{title}</h2>
      {description && <p className="mt-4 text-base leading-relaxed text-muted">{description}</p>}
    </div>
  )
}

export function PageTransition({ pageKey, children }) {
  return <motion.div key={pageKey} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, ease: 'easeOut' }}>{children}</motion.div>
}
