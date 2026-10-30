import { useCallback, useEffect, useRef, useState } from 'react'
import { ConnectionState, Room, RoomEvent, Track } from 'livekit-client'
import { api } from '../lib/api'

const TOPIC = 'trustlayer.event'
const AGENT_STATES = { initializing: 'idle', idle: 'idle', listening: 'listening', thinking: 'processing', speaking: 'speaking' }

// One LiveKit room per conversation. The backend mints the token (the browser never sees a LiveKit secret); the browser may only publish its
// microphone. The avatar's video/audio arrive as the agent's remote tracks; everything the agent decides arrives as data events that are
// fed into the same conversation as typed messages.
export function useLiveVoice({ receive, setLiveActive }) {
  const [connection, setConnection] = useState('idle') // idle | connecting | connected | reconnecting | disconnected | error
  const [agentState, setAgentState] = useState('idle') // idle | listening | processing | speaking
  const [error, setError] = useState(null)
  const [micOn, setMicOn] = useState(false)
  const [micError, setMicError] = useState(null) // non-fatal: the session continues without a microphone
  const [avatar, setAvatar] = useState(false)
  const [videoTrack, setVideoTrack] = useState(null)
  const room = useRef(null)
  const audioEls = useRef([])
  const receiveRef = useRef(receive)
  receiveRef.current = receive

  const cleanup = useCallback(() => {
    audioEls.current.forEach((el) => el.remove())
    audioEls.current = []
    setVideoTrack(null)
    setAvatar(false)
    setMicOn(false)
    setMicError(null)
    setAgentState('idle')
    setLiveActive(false)
  }, [setLiveActive])

  const end = useCallback(async () => {
    const r = room.current
    room.current = null
    if (r) await r.disconnect()
    cleanup()
    setConnection('idle')
    setError(null)
  }, [cleanup])

  const start = useCallback(async () => {
    if (room.current) return
    setError(null)
    setConnection('connecting')
    let session
    try {
      session = await api('/assistant/live/session', { method: 'POST' })
    } catch (e) {
      setConnection('error')
      setError(e.message)
      return
    }
    const r = new Room({ adaptiveStream: true, dynacast: true })
    room.current = r
    r.on(RoomEvent.Connected, () => setConnection('connected'))
    r.on(RoomEvent.Reconnecting, () => setConnection('reconnecting'))
    r.on(RoomEvent.Reconnected, () => setConnection('connected'))
    r.on(RoomEvent.Disconnected, () => {
      if (room.current === r) { room.current = null; cleanup(); setConnection('disconnected') } // dropped by the network, the agent or the time limit
    })
    r.on(RoomEvent.MediaDevicesError, () => setMicError('The microphone could not be used. Check that it is connected and allowed.'))
    r.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Video) { setVideoTrack(track); setAvatar(true) }
      else if (track.kind === Track.Kind.Audio) { const el = track.attach(); el.style.display = 'none'; document.body.appendChild(el); audioEls.current.push(el) }
    })
    r.on(RoomEvent.TrackUnsubscribed, (track) => { track.detach().forEach((el) => el.remove()); if (track.kind === Track.Kind.Video) setVideoTrack(null) })
    r.on(RoomEvent.DataReceived, (payload, _p, _k, topic) => {
      if (topic !== TOPIC) return
      let ev
      try { ev = JSON.parse(new TextDecoder().decode(payload)) } catch { return }
      if (ev.type === 'agent_state') setAgentState(AGENT_STATES[ev.state] || 'idle')
      else if (ev.type === 'ready') setAvatar(Boolean(ev.avatar))
      else receiveRef.current(ev)
    })
    try {
      setLiveActive(true, session.room)
      await r.connect(session.url, session.token)
      await r.startAudio() // some browsers hold audio until a user gesture; this call comes from the Start click
    } catch {
      room.current = null
      await r.disconnect().catch(() => {})
      cleanup()
      setConnection('error')
      setError('Could not connect to the live voice service. Please try again.')
      return
    }
    try {
      await r.localParticipant.setMicrophoneEnabled(true) // browser permission prompt happens here, by explicit user action
      setMicOn(true)
    } catch (e) {
      // No microphone is not fatal: the avatar still speaks every typed reply, so the conversation continues by typing.
      setMicOn(false)
      setMicError(e?.name === 'NotAllowedError' || /permission|denied/i.test(e?.message || '') ? 'Microphone permission was denied, so you can type to the avatar instead. Allow the microphone in the browser and press Unmute to talk.' : 'No microphone could be used, so you can type to the avatar instead.')
    }
  }, [cleanup, setLiveActive])

  const toggleMic = useCallback(async () => {
    const r = room.current
    if (!r || r.state !== ConnectionState.Connected) return
    const next = !micOn
    try {
      await r.localParticipant.setMicrophoneEnabled(next)
      setMicOn(next)
      if (next) setMicError(null)
    } catch {
      setMicError('The microphone could not be turned on. Check that it is connected and allowed in the browser.')
    }
  }, [micOn])

  useEffect(() => () => { room.current?.disconnect(); audioEls.current.forEach((el) => el.remove()) }, [])

  const active = connection === 'connecting' || connection === 'connected' || connection === 'reconnecting'
  return { connection, agentState, error, micError, micOn, avatar, videoTrack, active, start, end, toggleMic }
}
