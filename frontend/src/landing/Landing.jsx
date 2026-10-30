import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowRight, Binary, Check, ClipboardCheck, Database, EyeOff, FileSearch, GitBranch, Layers, Lock, Menu, ScrollText, ShieldAlert, SlidersHorizontal, UserCheck, X } from 'lucide-react'
import { getToken } from '../lib/api'
import { AnimatedBackground, Logo, Reveal, SectionHeading } from '../components/brand'
import ShieldIllustration from '../components/ShieldIllustration'
import { cn } from '../components/ui'
import ArchitectureDiagram from './ArchitectureDiagram'
import { BentoCard, BentoGrid } from './Bento'
import HeroVisual from './HeroVisual'

const NAV = [['features', 'Features'], ['how', 'How It Works'], ['security', 'Security'], ['architecture', 'Architecture']]
const scrollTo = (id) => document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
const gradientBtn = 'inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-navy-600 to-violet-600 px-6 text-sm font-semibold text-white shadow-lift transition duration-150 hover:brightness-110 active:scale-[0.98]'
const outlineBtn = 'inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-6 text-sm font-semibold text-body shadow-sm transition duration-150 hover:bg-slate-50 active:scale-[0.98]'

function Nav() {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)
  const signedIn = Boolean(getToken())
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 12)
    on()
    window.addEventListener('scroll', on, { passive: true })
    return () => window.removeEventListener('scroll', on)
  }, [])
  const go = (id) => { setOpen(false); scrollTo(id) }
  return (
    <header className={cn('fixed inset-x-0 top-0 z-40 border-b transition-all duration-300', scrolled ? 'border-slate-200 bg-white/85 py-2 shadow-sm backdrop-blur-md' : 'border-transparent bg-white/60 py-3.5 backdrop-blur-sm')}>
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-5">
        <a href="#/" aria-label="TrustLayer home"><Logo id="nav-logo" /></a>
        <nav aria-label="Primary" className="ml-6 hidden items-center gap-1 lg:flex">
          {NAV.map(([id, label]) => <button key={id} onClick={() => go(id)} className="whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-body">{label}</button>)}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {!signedIn && <a href="#/signin" className="hidden whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 sm:block">Sign In</a>}
          <a href="#/overview" className="whitespace-nowrap rounded-lg bg-gradient-to-r from-navy-600 to-violet-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition duration-150 hover:brightness-110 active:scale-[0.98]">{signedIn ? 'Open Dashboard' : 'Get Started'}</a>
          <button className="rounded-lg p-2 text-slate-700 hover:bg-slate-100 lg:hidden" aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}</button>
        </div>
      </div>
      {open && (
        <div className="border-t border-slate-200 bg-white px-5 py-3 lg:hidden">
          {NAV.map(([id, label]) => <button key={id} onClick={() => go(id)} className="block w-full rounded-lg px-3 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-100">{label}</button>)}
          {!signedIn && <a href="#/signin" className="block rounded-lg px-3 py-3 text-sm font-medium text-slate-700 hover:bg-slate-100">Sign In</a>}
        </div>
      )}
    </header>
  )
}

const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.09, delayChildren: 0.05 } } }
const rise = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } } }

function Hero() {
  return (
    <section id="top" className="relative overflow-hidden bg-gradient-to-b from-white via-blue-50/50 to-mist pb-20 pt-28 sm:pt-32 lg:pb-28">
      <AnimatedBackground />
      <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-5 lg:grid-cols-2">
        <motion.div variants={stagger} initial="hidden" animate="show" className="text-center lg:text-left">
          <motion.p variants={rise} className="mx-auto inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-semibold text-navy-700 shadow-sm lg:mx-0">
            <Lock className="h-3.5 w-3.5" aria-hidden /> Privacy-first data access
          </motion.p>
          <motion.h1 variants={rise} className="mt-6 text-4xl font-semibold leading-[1.1] text-body sm:text-5xl xl:text-6xl">
            Protect Sensitive Data. <span className="text-gradient">Enable Smarter Decisions.</span>
          </motion.h1>
          <motion.p variants={rise} className="mx-auto mt-6 max-w-xl text-base leading-relaxed text-muted sm:text-lg lg:mx-0">
            TrustLayer discovers sensitive fields in financial and insurance data, then enforces role-based policies so each request receives only what its declared purpose needs: allowed, masked or denied, with every decision explained and recorded.
          </motion.p>
          <motion.div variants={rise} className="mt-8 flex flex-wrap items-center justify-center gap-3 lg:justify-start">
            <a href="#/overview" className={gradientBtn}>Get Started <ArrowRight className="h-4 w-4" aria-hidden /></a>
            <button onClick={() => scrollTo('features')} className={outlineBtn}>Explore Features</button>
          </motion.div>
          <motion.ul variants={rise} className="mt-8 flex flex-wrap justify-center gap-x-6 gap-y-3 text-sm text-slate-700 lg:justify-start">
            {[[FileSearch, 'Discover PII', 'bg-violet-100 text-violet-600'], [SlidersHorizontal, 'Enforce Policies', 'bg-blue-100 text-blue-600'], [ClipboardCheck, 'Audit Every Decision', 'bg-green-100 text-green-600']].map(([Ic, t, c]) => (
              <li key={t} className="flex items-center gap-2"><span className={cn('flex h-7 w-7 items-center justify-center rounded-lg', c)}><Ic className="h-4 w-4" aria-hidden /></span>{t}</li>
            ))}
          </motion.ul>
        </motion.div>
        <HeroVisual />
      </div>
    </section>
  )
}

const chip = (t, c) => <span key={t} className={cn('rounded-full px-2.5 py-1 text-[11px] font-medium', c)}>{t}</span>

function Features() {
  return (
    <section id="features" className="relative bg-mist py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-5">
        <Reveal><SectionHeading eyebrow="Features" title="Everything between raw schema and explained decision" description="Seven capabilities on one backend. Each links to the working feature in the dashboard." /></Reveal>
        <Reveal delay={0.05} className="mt-14">
          <BentoGrid>
            <BentoCard className="md:col-span-2" accent="violet" icon={FileSearch} name="Sensitive Data Discovery" href="#/discovery" cta="Open Discovery"
              description="Scans allow-listed sources and flags likely sensitive fields from column names, value formats and Presidio entity detection. Reviewers can correct any classification.">
              <div className="flex flex-wrap gap-1.5" aria-label="Field categories">
                {[['Government ID', 'bg-rose-50 text-rose-700'], ['Account ID', 'bg-rose-50 text-rose-700'], ['Direct identifier', 'bg-orange-50 text-orange-700'], ['Contact', 'bg-orange-50 text-orange-700'], ['Financial', 'bg-blue-50 text-blue-700'], ['Demographic', 'bg-amber-50 text-amber-800'], ['Non-sensitive', 'bg-green-50 text-green-700']].map(([t, c]) => chip(t, c))}
              </div>
            </BentoCard>
            <BentoCard accent="blue" icon={UserCheck} name="Role-Based Access Control" href="#/policies" cta="Open Policies"
              description="Backend-enforced roles and declared purposes decide what each request may see.">
              <div className="flex flex-wrap gap-1.5">{['Security admin', 'Compliance officer', 'Advisor', 'Analyst'].map((t) => chip(t, 'bg-blue-50 text-blue-700'))}</div>
            </BentoCard>
            <BentoCard accent="teal" icon={EyeOff} name="Dynamic Data Masking" href="#/access" cta="Open Access Gateway"
              description="Protection is applied to the response; stored data is never overwritten.">
              <ul className="space-y-1.5 text-[11px]">
                {[['dependents', '2', 'Allowed', 'bg-green-50 text-green-700'], ['pan', 'XXXXXX234F', 'Masked', 'bg-blue-50 text-blue-700'], ['account_number', 'withheld', 'Denied', 'bg-rose-50 text-rose-700']].map(([f, v, s, c]) => (
                  <li key={f} className="flex items-center justify-between gap-2 rounded-lg bg-mist px-2.5 py-1.5"><code className="text-slate-600">{f}</code><span className="font-mono text-slate-500">{v}</span><span className={cn('rounded-full px-2 py-0.5 font-semibold', c)}>{s}</span></li>
                ))}
                <li className="text-muted">Synthetic example values.</li>
              </ul>
            </BentoCard>
            <BentoCard className="md:col-span-2" accent="blue" icon={Database} name="SQL Access Gateway" href="#/access" cta="Open Access Gateway"
              description="A restricted SELECT front door. SQL is parsed, never executed: the gateway rebuilds a parameterized query and rejects shapes it cannot judge.">
              <div className="grid gap-2 text-xs sm:grid-cols-2">
                <pre className="overflow-x-auto rounded-xl border border-green-200 bg-green-50/60 p-3 font-mono text-[11px] leading-relaxed text-slate-700"><span className="font-sans text-[10px] font-bold uppercase tracking-wider text-green-700">Accepted</span>{'\n'}SELECT id, annual_income{'\n'}FROM customers LIMIT 5</pre>
                <pre className="overflow-x-auto rounded-xl border border-rose-200 bg-rose-50/60 p-3 font-mono text-[11px] leading-relaxed text-slate-700"><span className="font-sans text-[10px] font-bold uppercase tracking-wider text-rose-700">Rejected</span>{'\n'}JOIN · subquery · UNION{'\n'}functions · comments</pre>
              </div>
            </BentoCard>
            <BentoCard accent="rose" icon={ShieldAlert} name="Security Risk Monitoring" href="#/risk" cta="Open Risk Monitoring"
              description="Deterministic rules flag repeated restricted access, unusual volume and reconstruction patterns. One weak signal is never blocked.">
              <div className="flex flex-wrap gap-1.5">{[['Restricted access', 'bg-rose-50 text-rose-700'], ['Volume', 'bg-amber-50 text-amber-800'], ['Reconstruction', 'bg-violet-50 text-violet-700']].map(([t, c]) => chip(t, c))}</div>
            </BentoCard>
            <BentoCard accent="green" icon={ClipboardCheck} name="Audit Trail" href="#/audit" cta="Open Audit Logs"
              description="Every decision records who, why, which policy and what protection was applied, with field names and never values.">
              <p className="rounded-lg bg-mist px-3 py-2 font-mono text-[11px] text-slate-600">query · analyst · <span className="font-semibold text-blue-700">Masked</span> · 3 fields</p>
            </BentoCard>
            <BentoCard accent="amber" icon={GitBranch} name="Automated Security Workflows" href="#/automation" cta="Open Automation"
              description="Optional n8n workflows schedule scans, record alerts and store summary reports. Alerts are recorded in TrustLayer; none is sent externally.">
              <div className="flex flex-wrap gap-1.5">{['Scheduled scan', 'Security alerts', 'Summary report'].map((t) => chip(t, 'bg-amber-50 text-amber-800'))}</div>
            </BentoCard>
          </BentoGrid>
        </Reveal>
      </div>
    </section>
  )
}

const STEPS = [
  { icon: FileSearch, title: 'Discover', text: 'Scan sources and classify sensitive fields.', c: 'bg-violet-100 text-violet-600' },
  { icon: SlidersHorizontal, title: 'Evaluate policies', text: 'Look up the rule for each field category.', c: 'bg-blue-100 text-blue-600' },
  { icon: UserCheck, title: 'Check role and purpose', text: 'Match the authenticated role and declared purpose.', c: 'bg-sky-100 text-sky-600' },
  { icon: EyeOff, title: 'Mask or deny', text: 'Mask, hash, redact, allow or deny each field.', c: 'bg-teal-100 text-teal-600' },
  { icon: ScrollText, title: 'Record', text: 'Write the decision to the audit trail, without values.', c: 'bg-green-100 text-green-600' },
]

function HowItWorks() {
  return (
    <section id="how" className="relative overflow-hidden bg-white py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-5">
        <Reveal><SectionHeading eyebrow="How it works" title="Five steps from raw schema to explained decision" description="Not every request is allowed: policies can mask or deny. Automation records alerts rather than guaranteeing external delivery." /></Reveal>
        <ol className="relative mt-14 grid gap-4 lg:grid-cols-5">
          <svg aria-hidden className="pointer-events-none absolute left-[10%] right-[10%] top-12 hidden h-2 w-[80%] lg:block" preserveAspectRatio="none" viewBox="0 0 100 2"><line x1="0" y1="1" x2="100" y2="1" stroke="#2563EB" strokeOpacity="0.45" strokeWidth="2" vectorEffect="non-scaling-stroke" className="dash-flow animate-flow" /></svg>
          {STEPS.map((s, i) => (
            <Reveal key={s.title} delay={i * 0.07} as="li" className="relative">
              <div tabIndex={0} className="group relative flex h-full flex-col items-center rounded-2xl border border-slate-200 bg-white p-5 text-center shadow-card outline-none transition duration-200 hover:-translate-y-1 hover:border-navy-300 hover:shadow-lift focus-visible:-translate-y-1 focus-visible:border-navy-400 focus-visible:shadow-lift">
                <span className={cn('relative z-10 flex h-14 w-14 items-center justify-center rounded-2xl ring-4 ring-white transition-transform group-hover:scale-105', s.c)}><s.icon className="h-6 w-6" aria-hidden /></span>
                <span className="mt-3 text-[11px] font-bold uppercase tracking-widest text-navy-600">Step {i + 1}</span>
                <h3 className="mt-1 text-base font-semibold text-body">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-snug text-muted">{s.text}</p>
              </div>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  )
}

const PILLARS = [
  { icon: Lock, title: 'Server-side access control', text: 'Every decision is enforced by the backend with role-based permissions. Hiding a button in the UI is never treated as authorization.', c: 'bg-blue-100 text-blue-600' },
  { icon: Layers, title: 'Data minimization', text: 'Each task receives only the fields it needs. The insurance demo sends seven inputs to its calculator and loads nothing else.', c: 'bg-violet-100 text-violet-600' },
  { icon: Binary, title: 'Auditable decisions', text: 'Each decision records who, why, which policy and what protection was applied, with field names and never field values.', c: 'bg-teal-100 text-teal-600' },
]

function Security() {
  return (
    <section id="security" className="relative overflow-hidden bg-gradient-to-b from-blue-50/70 to-blue-50/30 py-20 sm:py-28">
      <AnimatedBackground dots={false} />
      <div className="relative mx-auto grid max-w-7xl items-center gap-14 px-5 lg:grid-cols-2">
        <div>
          <Reveal><SectionHeading align="left" eyebrow="Security" title="Privacy by design, enforced where it counts" description="Protection happens in the backend, before data reaches a screen, a workflow or a calculator." /></Reveal>
          <ul className="mt-8 space-y-3">
            {PILLARS.map((p, i) => (
              <Reveal as="li" key={p.title} delay={i * 0.07}>
                <div className="flex gap-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-card transition-shadow hover:shadow-lift">
                  <span className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-xl', p.c)}><p.icon className="h-5 w-5" aria-hidden /></span>
                  <div><h3 className="font-semibold text-body">{p.title}</h3><p className="mt-1 text-sm leading-relaxed text-muted">{p.text}</p></div>
                </div>
              </Reveal>
            ))}
          </ul>
          <p className="mt-6 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
            <Check className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
            This is a prototype that uses synthetic demonstration data. It makes no compliance certification and no production-security claim; masking reduces exposure but does not guarantee anonymity.
          </p>
        </div>
        <div className="mx-auto w-full max-w-md" aria-hidden><div className="aspect-square"><ShieldIllustration /></div></div>
      </div>
    </section>
  )
}

function Architecture() {
  return (
    <section id="architecture" className="relative bg-white py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-5">
        <Reveal><SectionHeading eyebrow="Architecture" title="One backend, one database, optional automation" description="The implemented system: a React dashboard on a FastAPI modular monolith backed by Neon PostgreSQL. n8n is an optional orchestration layer that calls only the automation endpoints." /></Reveal>
        <Reveal delay={0.08}><div className="mt-12 rounded-3xl border border-slate-200 bg-gradient-to-br from-white to-blue-50/50 p-4 shadow-card sm:p-8"><ArchitectureDiagram /></div></Reveal>
      </div>
    </section>
  )
}

function FinalCta() {
  const signedIn = Boolean(getToken())
  return (
    <section className="bg-mist px-5 py-16 sm:py-20">
      <Reveal className="relative mx-auto max-w-5xl overflow-hidden rounded-3xl border border-blue-200 bg-gradient-to-br from-blue-100 via-white to-violet-100 px-6 py-14 text-center shadow-soft sm:px-12">
        <AnimatedBackground dots={false} />
        <div className="relative">
          <h2 className="mx-auto max-w-2xl text-3xl font-semibold text-body sm:text-4xl">Privacy-first data access, built for intelligent financial workflows.</h2>
          <p className="mx-auto mt-4 max-w-xl text-base text-muted">Try the full flow with synthetic data: scan, set policies, request access and read the audit trail.</p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <a href="#/overview" className={gradientBtn}>Open Dashboard <ArrowRight className="h-4 w-4" aria-hidden /></a>
            {!signedIn && <a href="#/signin" className={outlineBtn}>Sign In</a>}
          </div>
        </div>
      </Reveal>
    </section>
  )
}

function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-white py-12 text-muted">
      <div className="mx-auto grid max-w-7xl gap-10 px-5 md:grid-cols-4">
        <div className="md:col-span-2">
          <Logo id="foot-logo" />
          <p className="mt-3 max-w-sm text-sm leading-relaxed">Decision-level data minimization for financial and insurance workflows: discover sensitive fields, enforce policies, protect responses and audit every decision.</p>
        </div>
        <nav aria-label="Product"><h3 className="text-xs font-semibold uppercase tracking-widest text-body">Product</h3><ul className="mt-3 space-y-2 text-sm">{[['features', 'Features'], ['how', 'How It Works']].map(([id, l]) => <li key={id}><button className="hover:text-body" onClick={() => scrollTo(id)}>{l}</button></li>)}<li><a className="hover:text-body" href="#/overview">Dashboard</a></li></ul></nav>
        <nav aria-label="Security and architecture"><h3 className="text-xs font-semibold uppercase tracking-widest text-body">Trust</h3><ul className="mt-3 space-y-2 text-sm">{[['security', 'Security'], ['architecture', 'Architecture']].map(([id, l]) => <li key={id}><button className="hover:text-body" onClick={() => scrollTo(id)}>{l}</button></li>)}</ul></nav>
      </div>
      <p className="mx-auto mt-10 max-w-7xl border-t border-slate-200 px-5 pt-6 text-xs">TrustLayer is a prototype that uses synthetic data only. It is not a certified compliance product, and no real customer data should be used.</p>
    </footer>
  )
}

export default function Landing() {
  useEffect(() => { document.title = 'TrustLayer · Privacy-first data access' }, [])
  return (
    <div className="bg-mist">
      <a href="#top" onClick={(e) => { e.preventDefault(); scrollTo('top') }} className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">Skip to content</a>
      <Nav />
      <main>
        <Hero />
        <Features />
        <HowItWorks />
        <Security />
        <Architecture />
        <FinalCta />
      </main>
      <Footer />
    </div>
  )
}
