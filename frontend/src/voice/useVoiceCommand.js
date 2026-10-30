import { useCallback, useRef, useState } from 'react'
import { api } from '../lib/api'
import { useDictation } from '../assistant/useDictation'

const YES = /^\s*(yes|yeah|yep|yup|sure|confirm|confirmed|apply( it| that| the change)?|do it|go ahead|approve|ok|okay|proceed)[.! ]*$/i
const NO = /^\s*(no|nope|nah|cancel|stop|don'?t|do not|abort|never mind|negative)[.! ]*$/i

// Voice Command Control. Speech is transcribed on the server, the text is parsed into ONE approved intent by the server, the server checks the
// caller's real role, and only then does this hook carry out the approved action (open a page, start a scan). Nothing here decides access, and
// anything that changes policy waits for an explicit "Yes" that the server re-authorizes.
export function useVoiceCommand({ go, bump }) {
  const [phase, setPhase] = useState('idle') // idle | listening | transcribing | thinking | confirm | done | denied | unknown | error
  const [heard, setHeard] = useState('')
  const [intent, setIntent] = useState(null)
  const [message, setMessage] = useState('')
  const [confirmation, setConfirmation] = useState(null)
  const pending = useRef(null)
  pending.current = confirmation

  const execute = useCallback(async (action) => {
    if (!action) return
    if (action.kind === 'navigate') go(action.route)
    if (action.kind === 'scan') {
      go(action.route)
      try {
        const r = await api('/b1/scan', { method: 'POST', body: { target: sessionStorage.getItem('trustlayer.target') || 'postgres' } })
        setMessage(`Scanned ${r.tables} tables and ${r.columns} columns: ${r.confirmed} confirmed, ${r.uncertain} uncertain.`)
        bump?.()
      } catch (e) { setPhase('error'); setMessage(e.message) }
    }
  }, [go, bump])

  const confirm = useCallback(async () => {
    const c = pending.current
    if (!c) return
    setPhase('thinking')
    try {
      const r = await api('/voice-command/confirm', { method: 'POST', body: { token: c.token } })
      setConfirmation(null); setPhase('done'); setMessage(r.message); setIntent((i) => i && { ...i, name: 'CHANGE_POLICY' })
      bump?.(); execute(r.action)
    } catch (e) { setConfirmation(null); setPhase('error'); setMessage(e.message) }
  }, [bump, execute])

  const cancel = useCallback(() => { setConfirmation(null); setPhase('done'); setMessage('Cancelled. Nothing was changed.') }, [])

  const submit = useCallback(async (text) => {
    const t = (text || '').trim()
    if (!t) return
    setHeard(t)
    if (pending.current && YES.test(t)) { await confirm(); return }
    if (pending.current && NO.test(t)) { cancel(); return }
    setConfirmation(null); setIntent(null); setMessage('')
    setPhase('thinking')
    try {
      const r = await api('/voice-command', { method: 'POST', body: { text: t } })
      setIntent({ name: r.intent, label: r.label })
      setMessage(r.message)
      if (r.status === 'confirm') { setConfirmation(r.confirmation); setPhase('confirm'); return }
      setPhase(r.status === 'ok' ? 'done' : r.status === 'denied' ? 'denied' : 'unknown')
      if (r.status === 'ok') execute(r.action)
    } catch (e) { setPhase('error'); setMessage(e.message) }
  }, [cancel, confirm, execute])

  const dictation = useDictation({ onText: submit })
  const listening = dictation.state === 'recording'
  const status = dictation.state === 'recording' ? 'listening' : dictation.state === 'transcribing' ? 'transcribing' : phase
  const toggleMic = useCallback(() => {
    if (listening) { dictation.stop(); return }
    setHeard(''); setIntent(null); setMessage(''); setPhase('idle')
    dictation.start()
  }, [dictation, listening])
  const reset = useCallback(() => { setPhase('idle'); setHeard(''); setIntent(null); setMessage(''); setConfirmation(null); dictation.clearError() }, [dictation])

  return { status, heard, intent, message, confirmation, micError: dictation.error, listening, toggleMic, submit, confirm, cancel, reset }
}
