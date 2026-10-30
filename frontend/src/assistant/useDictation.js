import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

const MAX_SECONDS = 25 // the speech service is meant for clips under 30 s
const TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']

// Microphone -> TrustLayer backend -> speech-to-text. The recognized text is handed to the caller to REVIEW before it is sent;
// nothing is submitted automatically. Audio goes only to the TrustLayer server, never directly to a provider.
export function useDictation({ onText }) {
  const [state, setState] = useState('idle') // idle | recording | transcribing
  const [error, setError] = useState(null)
  const recorder = useRef(null)
  const stream = useRef(null)
  const chunks = useRef([])
  const cancelled = useRef(false)
  const timer = useRef(null)

  const release = useCallback(() => {
    clearTimeout(timer.current)
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
  }, [])

  const start = useCallback(async () => {
    if (state !== 'idle') return
    setError(null)
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('This browser cannot record audio. Type your message instead.')
      return
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      setError(e.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow it in the browser to use voice.' : e.name === 'NotFoundError' ? 'No microphone was found.' : 'The microphone could not be started.')
      return
    }
    const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t))
    const rec = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined)
    chunks.current = []
    cancelled.current = false
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data)
    rec.onstop = async () => {
      release()
      if (cancelled.current) { setState('idle'); return }
      const blob = new Blob(chunks.current, { type: rec.mimeType || 'audio/webm' })
      if (blob.size < 800) { setError('I did not hear anything. Try again.'); setState('idle'); return }
      setState('transcribing')
      try {
        const r = await api('/assistant/voice/transcribe', { method: 'POST', raw: blob })
        if (r.text) onText(r.text)
        else setError('I could not make out any words. Try again.')
      } catch (e) {
        setError(e.message)
      } finally {
        setState('idle')
      }
    }
    recorder.current = rec
    rec.start()
    setState('recording')
    timer.current = setTimeout(() => rec.state === 'recording' && rec.stop(), MAX_SECONDS * 1000)
  }, [onText, release, state])

  const stop = useCallback(() => { if (recorder.current?.state === 'recording') recorder.current.stop() }, [])
  const cancel = useCallback(() => { cancelled.current = true; if (recorder.current?.state === 'recording') recorder.current.stop(); else release() }, [release])
  useEffect(() => () => { cancelled.current = true; if (recorder.current?.state === 'recording') recorder.current.stop(); release() }, [release])

  return { state, error, start, stop, cancel, clearError: () => setError(null) }
}
