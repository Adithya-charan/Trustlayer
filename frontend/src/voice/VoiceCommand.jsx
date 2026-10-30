import { useEffect, useRef, useState } from 'react'
import { Check, Loader2, Mic, Send, Square, X } from 'lucide-react'
import { Badge, Button, cn } from '../components/ui'
import { useVoiceCommand } from './useVoiceCommand'

const EXAMPLES = ['Show high risk PII', 'Open audit center', 'Run the masking demo', 'Show denied requests', 'Open cards table', 'Show analyst policies']

const STATUS_TEXT = { idle: 'Press the microphone and speak, or type a command.', listening: 'Listening…', transcribing: 'Transcribing…', thinking: 'Working on it…', confirm: 'Waiting for your confirmation', done: 'Done', denied: 'Not allowed', unknown: 'Not understood', error: 'Something went wrong' }

// The visible "Voice Command" control in the app header. It is a command palette, not a chatbot: one utterance in, one validated action out.
export default function VoiceCommand({ go, bump }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const v = useVoiceCommand({ go, bump })
  const panel = useRef(null)
  const input = useRef(null)

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  useEffect(() => { if (open) input.current?.focus() }, [open])

  const send = (t) => { if (t.trim()) { v.submit(t); setText('') } }
  const busy = ['transcribing', 'thinking'].includes(v.status)

  return (
    <div className="relative">
      <Button size="sm" variant={v.listening ? 'primary' : 'outline'} onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls="voice-command-panel" aria-label="Voice Command">
        <Mic className={cn('h-4 w-4', v.listening && 'animate-pulse')} aria-hidden /> <span className="hidden sm:inline">Voice Command</span>
      </Button>
      {open && (
        <div id="voice-command-panel" ref={panel} role="dialog" aria-label="Voice Command" className="absolute right-0 top-11 z-40 w-[min(24rem,92vw)] rounded-2xl border border-slate-200 bg-white p-4 shadow-2xl">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">Voice Command</h2>
              <p className="text-xs text-slate-500">One command in, one checked action out. Your role and policies still apply.</p>
            </div>
            <button type="button" onClick={() => setOpen(false)} className="rounded-lg p-1 text-slate-500 hover:bg-slate-100" aria-label="Close Voice Command"><X className="h-4 w-4" /></button>
          </div>

          <div className="mt-3 flex items-center gap-3">
            <button type="button" onClick={v.toggleMic} disabled={busy} aria-pressed={v.listening} aria-label={v.listening ? 'Stop listening' : 'Start listening'}
              className={cn('flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-white shadow transition active:scale-95 disabled:opacity-50', v.listening ? 'bg-rose-600' : 'bg-navy-600 hover:brightness-110')}>
              {busy ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> : v.listening ? <Square className="h-4 w-4" aria-hidden /> : <Mic className="h-5 w-5" aria-hidden />}
            </button>
            <p role="status" aria-live="polite" className="text-sm font-medium text-slate-800">{STATUS_TEXT[v.status]}</p>
          </div>

          {(v.heard || v.intent || v.message || v.micError) && (
            <dl className="mt-3 space-y-1.5 rounded-xl bg-slate-50 p-3 text-xs">
              {v.heard && <div className="flex gap-2"><dt className="w-14 shrink-0 text-slate-500">Heard</dt><dd className="text-slate-900">“{v.heard}”</dd></div>}
              {v.intent && <div className="flex items-center gap-2"><dt className="w-14 shrink-0 text-slate-500">Intent</dt><dd><Badge tone={v.intent.name === 'UNKNOWN' ? 'WARNING' : 'info'}>{v.intent.name}</Badge></dd></div>}
              {v.message && <div className="flex gap-2"><dt className="w-14 shrink-0 text-slate-500">Result</dt><dd className={cn(v.status === 'denied' || v.status === 'error' ? 'text-red-800' : v.status === 'unknown' ? 'text-amber-800' : 'text-slate-900')}>{v.message}</dd></div>}
              {v.micError && <div className="flex gap-2"><dt className="w-14 shrink-0 text-slate-500">Mic</dt><dd className="text-amber-800">{v.micError} You can type the command below.</dd></div>}
            </dl>
          )}

          {v.confirmation && (
            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3">
              <p className="text-sm text-amber-950">{v.confirmation.summary}</p>
              <p className="mt-1 text-[11px] text-amber-800">Say or click “Yes” to apply, “No” to cancel. Nothing changes until you confirm.</p>
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={v.confirm}><Check className="h-4 w-4" aria-hidden /> Yes, apply</Button>
                <Button size="sm" variant="outline" onClick={v.cancel}>No, cancel</Button>
              </div>
            </div>
          )}

          <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(text) }}>
            <input ref={input} value={text} onChange={(e) => setText(e.target.value)} maxLength={300} placeholder='Type a command, e.g. "Show high risk PII"' aria-label="Type a voice command"
              className="min-h-9 flex-1 rounded-lg border border-slate-300 px-3 text-sm" />
            <Button size="sm" type="submit" disabled={!text.trim() || busy} aria-label="Send command"><Send className="h-4 w-4" aria-hidden /></Button>
          </form>
          <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Example commands">
            {EXAMPLES.map((e) => <button key={e} type="button" onClick={() => send(e)} disabled={busy} className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-50">{e}</button>)}
          </div>
        </div>
      )}
    </div>
  )
}
