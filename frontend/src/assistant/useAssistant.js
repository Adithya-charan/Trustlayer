import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { NAV, canSee } from '../lib/router'

// Conversation state for the AI Operator. Lives in Shell, so closing or minimizing the panel never loses it,
// and it is discarded on sign-out (Shell unmounts). Nothing here calls a provider: every request goes to the
// authenticated TrustLayer backend, which owns the model key, the approved-tool list and all permissions.
export function useAssistant({ route, go, role }) {
  const [messages, setMessages] = useState([])
  const [active, setActive] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState({ state: 'loading' }) // loading | online | unconfigured | disconnected
  const [speakOn, setSpeakOn] = useState(false) // read replies aloud; off until the user turns it on
  const [speaking, setSpeaking] = useState(false)
  const seq = useRef(0)
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const audio = useRef(null)
  const speakOnRef = useRef(false)
  speakOnRef.current = speakOn
  const liveRef = useRef(false) // while a live voice session runs, the avatar is the only voice: REST text-to-speech stays silent
  const roomRef = useRef(null) // the caller's live room: the backend sends typed and confirmed replies to the avatar in it

  const add = useCallback((m) => {
    const msg = { id: ++seq.current, ts: new Date().toISOString(), ...m }
    setMessages((cur) => [...cur, msg])
    return msg
  }, [])
  const patch = useCallback((id, p) => setMessages((cur) => cur.map((m) => (m.id === id ? { ...m, ...p } : m))), [])

  const refreshStatus = useCallback(async () => {
    setStatus({ state: 'loading' })
    try {
      const s = await api('/assistant/status')
      setStatus({ state: s.llm.configured ? 'online' : 'unconfigured', voice: s.voice, model: s.llm.model, workflowExecution: s.workflow_execution })
    } catch (e) {
      setStatus({ state: 'disconnected', message: e.message })
    }
  }, [])
  useEffect(() => { refreshStatus() }, [refreshStatus])

  // Approved navigation only: the page must exist in the router and be visible to this role.
  const navigate = useCallback((page) => {
    const item = NAV.find((n) => n.id === page)
    if (!item || !canSee(item, role)) return `The ${page} page is not available for your role.`
    go(page)
    return `Opened ${item.label}.`
  }, [go, role])

  const showError = useCallback((e) => add({ role: 'assistant', error: e.message || 'Something went wrong.', code: e.extra?.code, status: e.status }), [add])
  // The reply text is always shown; if the backend could not hand it to the avatar, say so instead of leaving a silent avatar unexplained.
  const noteSpeech = useCallback((speech) => {
    if (liveRef.current && speech && !speech.requested) add({ role: 'assistant', text: `The avatar could not speak that reply (${speech.reason || 'unknown reason'}). It is shown as text.`, notice: true })
  }, [add])

  const stopSpeaking = useCallback(() => {
    if (audio.current) { audio.current.pause(); audio.current = null }
    setSpeaking(false)
  }, [])
  // Text-to-speech runs on the TrustLayer server; only the assistant's short reply line is spoken, never result data.
  const speak = useCallback(async (text) => {
    if (!text || !speakOnRef.current || liveRef.current) return
    stopSpeaking()
    setSpeaking(true)
    try {
      const r = await api('/assistant/voice/speak', { method: 'POST', body: { text: text.slice(0, 1000) } })
      if (!speakOnRef.current) { setSpeaking(false); return }
      const el = new Audio(`data:${r.mime};base64,${r.audio_base64}`)
      audio.current = el
      el.onended = () => { if (audio.current === el) { audio.current = null; setSpeaking(false) } }
      await el.play()
    } catch (e) {
      setSpeaking(false)
      showError(new Error(`Could not read that aloud. ${e.message || ''}`.trim()))
    }
  }, [showError, stopSpeaking])
  const toggleSpeak = useCallback(() => { if (speakOnRef.current) stopSpeaking(); setSpeakOn(!speakOnRef.current) }, [stopSpeaking])
  useEffect(() => () => { if (audio.current) audio.current.pause() }, [])

  // The backend's page list has no "voice" entry, so the Voice Assistant page sends no page context.
  const send = useCallback(async (text) => {
    const message = text.trim().slice(0, 500)
    if (!message || busy) return
    setActive(true)
    const history = messagesRef.current.filter((m) => m.text && !m.error).slice(-6).map((m) => ({ role: m.role, content: m.text.slice(0, 500) }))
    add({ role: 'user', text: message })
    setBusy(true)
    try {
      const r = await api('/assistant/chat', { method: 'POST', body: { message, page: NAV.some((n) => n.id === route) && route !== 'voice' ? route : null, history, ...(liveRef.current && roomRef.current ? { room: roomRef.current } : {}) } })
      const note = r.result?.kind === 'navigate' ? navigate(r.result.page) : null
      add({ role: 'assistant', text: r.reply, result: r.result?.kind === 'navigate' ? null : r.result, confirmation: r.confirmation ? { ...r.confirmation, state: 'pending' } : null, refused: r.refused, note })
      noteSpeech(r.speech)
      speak(note ? `${r.reply} ${note}` : r.reply)
    } catch (e) {
      showError(e)
      if (e.extra?.code === 'assistant_not_configured') refreshStatus()
    } finally {
      setBusy(false)
    }
  }, [add, busy, navigate, noteSpeech, refreshStatus, route, showError, speak])

  const confirm = useCallback(async (id) => {
    const msg = messagesRef.current.find((m) => m.id === id)
    if (!msg?.confirmation || msg.confirmation.state !== 'pending' || busy) return
    patch(id, { confirmation: { ...msg.confirmation, state: 'running' } })
    setBusy(true)
    try {
      const r = await api('/assistant/confirm', { method: 'POST', body: { token: msg.confirmation.token, ...(liveRef.current && roomRef.current ? { room: roomRef.current } : {}) } })
      patch(id, { confirmation: { ...msg.confirmation, state: 'done' } })
      add({ role: 'assistant', text: r.reply, result: r.result }) // shown only after the backend has answered
      noteSpeech(r.speech)
      speak(r.reply)
    } catch (e) {
      patch(id, { confirmation: { ...msg.confirmation, state: 'failed' } })
      showError(e)
    } finally {
      setBusy(false)
    }
  }, [add, busy, noteSpeech, patch, showError, speak])

  const cancel = useCallback((id) => {
    setMessages((cur) => cur.map((m) => (m.id === id && m.confirmation ? { ...m, confirmation: { ...m.confirmation, state: 'cancelled' } } : m)))
    add({ role: 'assistant', text: 'Cancelled. Nothing was run.' })
  }, [add])

  const end = useCallback(() => { stopSpeaking(); setMessages([]); setActive(false) }, [stopSpeaking])

  // Events from the live voice agent land in the SAME conversation as typed messages. Confirmations still go through confirm() with the user's own session.
  const receive = useCallback((ev) => {
    setActive(true)
    if (ev.type === 'user_transcript') add({ role: 'user', text: ev.text })
    else if (ev.type === 'assistant') {
      const note = ev.result?.kind === 'navigate' ? navigate(ev.result.page) : null
      add({ role: 'assistant', text: ev.reply, result: ev.result?.kind === 'navigate' ? null : ev.result, confirmation: ev.confirmation ? { ...ev.confirmation, state: 'pending' } : null, refused: ev.refused, note })
    } else if (ev.type === 'notice') add({ role: 'assistant', text: ev.message, notice: true })
    else if (ev.type === 'error') add({ role: 'assistant', error: ev.message, code: ev.code })
  }, [add, navigate])
  const setLiveActive = useCallback((on, room = null) => { liveRef.current = on; roomRef.current = on ? room : null; if (on) stopSpeaking() }, [stopSpeaking])

  return { messages, active, busy, status, send, confirm, cancel, end, start: () => setActive(true), refreshStatus, speakOn, speaking, toggleSpeak, stopSpeaking, receive, setLiveActive }
}
