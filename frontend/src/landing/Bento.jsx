import { motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'
import { cn } from '../components/ui'

// Bento layout adapted from the Magic UI BentoGrid structure (MIT): a 3-column grid of cards that each hold an
// icon, name, description and a visual slot. Re-written for a LIGHT theme in plain JS; the call to action stays
// visible (not hover-only) so keyboard and touch users can reach it.
export function BentoGrid({ className, children }) {
  return <div className={cn('grid grid-cols-1 gap-4 md:grid-cols-3', className)}>{children}</div>
}

const ACCENT = {
  violet: { icon: 'bg-violet-100 text-violet-600', hover: 'hover:border-violet-300', glow: 'from-violet-100' },
  blue: { icon: 'bg-blue-100 text-blue-600', hover: 'hover:border-blue-300', glow: 'from-blue-100' },
  teal: { icon: 'bg-teal-100 text-teal-600', hover: 'hover:border-teal-300', glow: 'from-teal-100' },
  green: { icon: 'bg-green-100 text-green-600', hover: 'hover:border-green-300', glow: 'from-green-100' },
  amber: { icon: 'bg-amber-100 text-amber-600', hover: 'hover:border-amber-300', glow: 'from-amber-100' },
  rose: { icon: 'bg-rose-100 text-rose-600', hover: 'hover:border-rose-300', glow: 'from-rose-100' },
}

export function BentoCard({ name, icon: Icon, accent = 'blue', description, href, cta, className, children }) {
  const a = ACCENT[accent]
  return (
    <motion.article whileHover={{ y: -3 }} transition={{ duration: 0.18 }}
      className={cn('group relative flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white p-6 shadow-card transition-shadow hover:shadow-lift', a.hover, className)}>
      <div aria-hidden className={cn('pointer-events-none absolute -right-14 -top-14 h-40 w-40 rounded-full bg-gradient-to-br to-transparent opacity-80', a.glow)} />
      <span className={cn('relative flex h-11 w-11 items-center justify-center rounded-xl', a.icon)}><Icon className="h-5 w-5" aria-hidden /></span>
      <h3 className="relative mt-4 text-lg font-semibold text-body">{name}</h3>
      <p className="relative mt-1.5 text-sm leading-relaxed text-muted">{description}</p>
      <div className="relative mt-4 flex-1">{children}</div>
      <a href={href} className="relative mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-navy-700 hover:underline">{cta} <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden /></a>
    </motion.article>
  )
}
