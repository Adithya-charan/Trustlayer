import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { AlertTriangle, AudioLines, Bot, ChevronUp, Loader2, MessageSquarePlus, Mic, Minus, RefreshCw, SendHorizontal, Sparkles, Square, Volume2, VolumeX, X } from 'lucide-react'
import { Button, Notice, cn } from '../components/ui'
import { useAssistantContext } from './AssistantContext'
import ResultCard from './ResultCards'
import VoiceStage from './VoiceStage'
import { useDictation } from './useDictation'

const AUDITOR = ['security_admin', 'compliance_officer']
const suggestions = (role) => [
  'Explain this page',
  'Open Data Discovery',
  ...(AUDITOR.includes(role) ? ['Show me the high-severity security events', 'Show recent scans', 'What is the automation status?'] : []),
  ...(role === 'security_admin' ? ['Start a sensitive-data scan'] : []),
]
const time = (iso) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

function Avatar({ className }) {
  return <span aria-hidden className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-navy-600 to-violet-600 text-white', className)}><Bot className="h-[18px] w-[18px]" /></span>
}

const STATUS_VIEW = {
  loading: ['bg-slate-400', 'Connecting…'],
  online: ['bg-emerald-500', 'Online'],
  unconfigured: ['bg-amber-500', 'Not configured'],
  disconnected: ['bg-red-500', 'Disconnected'],
}

export function Typing({ reduced }) {
  return (
    <div role="status" className="flex items-center gap-2 text-xs text-slate-500">
      <span className="sr-only">The assistant is working</span>
      {reduced ? <span aria-hidden>Working…</span> : (
        <span aria-hidden className="flex gap-1 rounded-2xl rounded-bl-md border border-slate-200 bg-white px-3 py-2.5">
          {[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" style={{ animationDelay: `${i * 120}ms` }} />)}
        </span>
      )}
    </div>
  )
}

function Confirmation({ c, onConfirm, onCancel, busy }) {
  if (c.state === 'pending' || c.state === 'running') {
    return (
      <div className="mt-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        <p className="font-semibold">Confirmation required</p>
        <p className="mt-0.5">{c.summary}</p>
        <div className="mt-2 flex gap-2">
          <Button size="sm" onClick={onConfirm} loading={c.state === 'running'} disabled={busy}>Confirm</Button>
          <Button size="sm" variant="outline" onClick={onCancel} disabled={busy}>Cancel</Button>
        </div>
      </div>
    )
  }
  const label = { done: 'Confirmed.', cancelled: 'Cancelled. Nothing was run.', failed: 'Confirmed, but the server did not complete it.' }[c.state]
  return <p className="mt-2 text-xs text-slate-500">{label}</p>
}

export function Message({ m, onConfirm, onCancel, busy }) {
  const mine = m.role === 'user'
  return (
    <li className={cn('flex gap-2', mine && 'flex-row-reverse')}>
      {!mine && <Avatar className="mt-0.5 h-7 w-7" />}
      <div className={cn('min-w-0 max-w-[88%]', mine && 'text-right')}>
        {m.error ? (
          <div role="alert" className="flex items-start gap-2 rounded-2xl rounded-bl-md border border-red-200 bg-red-50 px-3 py-2 text-left text-sm text-red-800">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /><span>{m.error}</span>
          </div>
        ) : (
          <div className={cn('inline-block whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-left text-sm', mine ? 'rounded-br-md bg-navy-600 text-white' : 'rounded-bl-md border border-slate-200 bg-white text-slate-800', m.refused && 'border-amber-300 bg-amber-50')}>{m.text}</div>
        )}
        {m.note && <p className="mt-1 text-xs text-slate-600">{m.note}</p>}
        {m.result && <ResultCard result={m.result} />}
        {m.confirmation && <Confirmation c={m.confirmation} busy={busy} onConfirm={() => onConfirm(m.id)} onCancel={() => onCancel(m.id)} />}
        <p className="mt-1 text-[10px] text-slate-500">{time(m.ts)}</p>
      </div>
    </li>
  )
}

function Header({ a, live, active, onEnd, onMin, onClose }) {
  const { status } = a
  const [dot, label] = STATUS_VIEW[status.state]
  const tts = Boolean(status.voice?.text_to_speech)
  const liveReady = Boolean(status.voice?.realtime_audio)
  return (
    <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
      <Avatar />
      <div className="min-w-0 flex-1">
        <h2 id="assistant-title" className="truncate text-sm font-semibold text-slate-900">TrustLayer AI Operator</h2>
        <p className="flex items-center gap-1.5 text-xs text-slate-600"><span aria-hidden className={cn('h-2 w-2 rounded-full', dot)} />{label}</p>
      </div>
      <button onClick={live.active ? live.end : live.start} disabled={!liveReady || status.state !== 'online'} aria-pressed={live.active} aria-label={live.active ? 'End live voice conversation' : 'Start live voice conversation'}
        title={liveReady ? (live.active ? 'End live voice conversation' : 'Talk to the avatar') : 'Live voice needs LiveKit, the voice agent and a speech service configured on the server'}
        className={cn('rounded-lg p-1.5 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40', live.active ? 'bg-violet-50 text-violet-700' : 'text-slate-500')}>
        <AudioLines className="h-4 w-4" aria-hidden />
      </button>
      <button onClick={a.toggleSpeak} disabled={!tts} aria-pressed={a.speakOn} aria-label="Read replies aloud" title={tts ? 'Read replies aloud' : 'Spoken replies need the speech service configured on the server'}
        className={cn('rounded-lg p-1.5 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40', a.speakOn ? 'bg-navy-50 text-navy-700' : 'text-slate-500')}>
        {a.speakOn ? <Volume2 className="h-4 w-4" aria-hidden /> : <VolumeX className="h-4 w-4" aria-hidden />}
      </button>
      {active && <button onClick={onEnd} className="rounded-lg px-2 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100">End conversation</button>}
      <button onClick={onMin} aria-label="Minimize assistant" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><Minus className="h-4 w-4" aria-hidden /></button>
      <button onClick={onClose} aria-label="Close assistant" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" aria-hidden /></button>
    </header>
  )
}

export function Composer({ a, disabled, inputRef, id = 'assistant-input' }) {
  const [text, setText] = useState('')
  const voice = a.status.voice?.speech_to_text
  // Recognized speech lands in the box for review; the user still presses Send.
  const dictation = useDictation({ onText: (t) => { setText((cur) => (cur ? `${cur} ${t}` : t)); inputRef.current?.focus() } })
  const recording = dictation.state === 'recording'
  const transcribing = dictation.state === 'transcribing'
  const submit = () => { if (text.trim() && !a.busy) { a.send(text); setText('') } }
  return (
    <div className="border-t border-slate-200 bg-white p-3">
      <div aria-live="polite" className="empty:hidden">
        {recording && <p className="mb-2 flex items-center gap-2 rounded-lg bg-red-50 px-3 py-1.5 text-xs font-medium text-red-800"><span aria-hidden className="h-2 w-2 animate-pulse rounded-full bg-red-600 motion-reduce:animate-none" />Listening… speak, then tap stop (up to 25 seconds).
          <button onClick={dictation.cancel} className="ml-auto rounded px-1.5 py-0.5 underline">Cancel</button></p>}
        {transcribing && <p className="mb-2 flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-1.5 text-xs text-slate-700"><Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />Transcribing…</p>}
        {a.speaking && <p className="mb-2 flex items-center gap-2 rounded-lg bg-navy-50 px-3 py-1.5 text-xs text-navy-800"><Volume2 className="h-3.5 w-3.5" aria-hidden />Speaking…
          <button onClick={a.stopSpeaking} className="ml-auto rounded px-1.5 py-0.5 font-medium underline">Stop</button></p>}
        {dictation.error && <p role="alert" className="mb-2 flex items-start gap-2 rounded-lg bg-red-50 px-3 py-1.5 text-xs text-red-800"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /><span className="flex-1">{dictation.error}</span>
          <button onClick={dictation.clearError} aria-label="Dismiss" className="rounded p-0.5"><X className="h-3 w-3" aria-hidden /></button></p>}
      </div>
      <div className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white p-1.5 focus-within:border-navy-500 focus-within:ring-2 focus-within:ring-navy-200">
        <label htmlFor={id} className="sr-only">Message the assistant</label>
        <textarea id={id} ref={inputRef} rows={1} maxLength={500} value={text} disabled={disabled} placeholder="Ask a question or give a command"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          className="max-h-28 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-slate-900 outline-none placeholder:text-slate-500 disabled:cursor-not-allowed" />
        <button type="button" disabled={!voice || disabled || transcribing} onClick={recording ? dictation.stop : dictation.start}
          aria-label={recording ? 'Stop recording' : voice ? 'Start voice input' : 'Voice input is not configured'} aria-pressed={recording}
          title={voice ? (recording ? 'Stop recording' : 'Start voice input') : 'Voice input needs the speech service configured on the server'}
          className={cn('flex h-9 w-9 items-center justify-center rounded-xl enabled:hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40', recording ? 'bg-red-50 text-red-700' : 'text-slate-500')}>
          {recording ? <Square className="h-4 w-4 fill-current" aria-hidden /> : transcribing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Mic className="h-4 w-4" aria-hidden />}
        </button>
        <button type="button" onClick={submit} disabled={disabled || !text.trim() || a.busy} aria-label="Send message"
          className="flex h-9 w-9 items-center justify-center rounded-xl bg-navy-600 text-white transition enabled:hover:bg-navy-700 disabled:bg-slate-300"><SendHorizontal className="h-4 w-4" aria-hidden /></button>
      </div>
      <p className="mt-1.5 px-1 text-[10px] leading-snug text-slate-500">
        {voice ? 'Voice clips are sent to the speech service through the TrustLayer server and are not stored. ' : 'Voice is not connected yet. '}Results are real backend data for your role. Anything that changes state asks you first.
      </p>
    </div>
  )
}

function Body({ a, role, reduced, listRef }) {
  const { status, messages, active } = a
  if (status.state === 'loading') return <div role="status" className="flex flex-1 items-center justify-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />Connecting to the assistant…</div>
  if (status.state === 'disconnected') {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
        <Notice tone="error" className="text-left">{status.message || 'Cannot reach the TrustLayer server.'}</Notice>
        <Button variant="outline" size="sm" onClick={a.refreshStatus}><RefreshCw className="h-3.5 w-3.5" aria-hidden /> Retry</Button>
      </div>
    )
  }
  if (status.state === 'unconfigured') {
    return <div className="flex flex-1 flex-col justify-center px-5"><Notice tone="warn">The AI assistant is not configured on the server yet. An administrator needs to set <code className="font-mono text-xs">GROQ_API_KEY</code> in the backend environment and restart the backend. Nothing is simulated in the meantime.</Notice></div>
  }
  if (!active && messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 overflow-y-auto px-5 py-6 text-center">
        <Avatar className="h-12 w-12" />
        <div>
          <p className="text-sm font-semibold text-slate-900">How can I help?</p>
          <p className="mt-1 text-xs text-slate-600">I can show security events and scans, explain or open pages, and start a scan after you confirm.</p>
        </div>
        <Button size="sm" onClick={a.start}><MessageSquarePlus className="h-4 w-4" aria-hidden /> Start conversation</Button>
        <ul className="flex flex-wrap justify-center gap-2" aria-label="Suggestions">
          {suggestions(role).map((s) => <li key={s}><button onClick={() => a.send(s)} className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 hover:border-navy-300 hover:bg-navy-50">{s}</button></li>)}
        </ul>
      </div>
    )
  }
  return (
    <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-4">
      <ol role="log" aria-live="polite" aria-label="Conversation" className="space-y-4">
        {messages.map((m) => <Message key={m.id} m={m} busy={a.busy} onConfirm={a.confirm} onCancel={a.cancel} />)}
        {a.busy && <li><Typing reduced={reduced} /></li>}
      </ol>
    </div>
  )
}

export default function AssistantDock({ assistant: a, role }) {
  const { live } = useAssistantContext()
  const [mode, setMode] = useState('closed') // closed | open | min
  const reduced = useReducedMotion()
  const launcher = useRef(null)
  const input = useRef(null)
  const list = useRef(null)
  const pending = a.messages.some((m) => m.confirmation?.state === 'pending')

  useEffect(() => { if (mode === 'open') input.current?.focus() }, [mode, a.status.state])
  useEffect(() => { if (list.current) list.current.scrollTop = list.current.scrollHeight }, [a.messages, a.busy, mode])
  const close = () => { setMode('closed'); requestAnimationFrame(() => launcher.current?.focus()) }
  const motionProps = reduced ? {} : { initial: { x: 48, opacity: 0 }, animate: { x: 0, opacity: 1 }, exit: { x: 48, opacity: 0 }, transition: { duration: 0.22, ease: 'easeOut' } }
  const composerOff = a.status.state !== 'online'

  return (
    <>
      <AnimatePresence>
        {mode === 'closed' && (
          <motion.button ref={launcher} key="launcher" onClick={() => setMode('open')} aria-label={pending ? 'Open AI assistant (confirmation waiting)' : 'Open AI assistant'}
            className="fixed bottom-5 right-5 z-30 flex items-center gap-2 rounded-full bg-gradient-to-br from-navy-600 to-violet-600 px-4 py-3 text-sm font-medium text-white shadow-lift transition hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-navy-600"
            {...(reduced ? {} : { initial: { scale: 0.85, opacity: 0 }, animate: { scale: 1, opacity: 1 }, exit: { scale: 0.85, opacity: 0 } })}>
            <Sparkles className="h-5 w-5" aria-hidden /><span className="hidden sm:inline">Ask AI</span>
            {pending && <span aria-hidden className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full bg-amber-400 ring-2 ring-white" />}
          </motion.button>
        )}
        {mode === 'min' && (
          <motion.button key="min" onClick={() => setMode('open')} aria-label="Expand AI assistant"
            className="fixed bottom-5 right-5 z-30 flex items-center gap-3 rounded-2xl border border-slate-200 bg-white py-2 pl-2 pr-4 text-left shadow-lift" {...motionProps}>
            <Avatar /><span className="text-sm font-semibold text-slate-900">TrustLayer AI Operator</span>{pending && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-900">Confirm</span>}<ChevronUp className="h-4 w-4 text-slate-500" aria-hidden />
          </motion.button>
        )}
        {mode === 'open' && (
          <motion.aside key="panel" role="dialog" aria-modal="false" aria-labelledby="assistant-title"
            onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); close() } }}
            className="fixed inset-x-0 bottom-0 top-14 z-40 flex flex-col overflow-hidden border-l border-slate-200 bg-mist shadow-2xl sm:inset-x-auto sm:bottom-4 sm:right-4 sm:top-[4.25rem] sm:w-[26rem] sm:rounded-2xl sm:border md:w-[27.5rem]"
            {...motionProps}>
            <Header a={a} live={live} active={a.active || a.messages.length > 0} onEnd={() => { live.end(); a.end() }} onMin={() => setMode('min')} onClose={close} />
            {(live.active || live.error || live.connection === 'disconnected') && <VoiceStage compact />}
            <Body a={a} role={role} reduced={reduced} listRef={list} />
            <Composer a={a} disabled={composerOff} inputRef={input} />
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  )
}
