"""HTTP surface for the assistant. Every route requires a signed-in user; provider keys never leave the server."""
import base64
import datetime as dt

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant import live, n8n, service, voice
from app.assistant.tools import Page
from app.core.config import get_settings
from app.core.security import Actor, current_actor, limiter, require
from app.database.models import User
from app.database.session import get_session

router = APIRouter(prefix="/api/assistant")


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)  # long audit answers are echoed back by clients; the router truncates each turn to 500 characters


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=500)
    page: Page | None = None
    history: list[Turn] = Field(default_factory=list, max_length=12)
    room: str | None = Field(default=None, pattern=r"^tl-[0-9a-f]{12}$")  # the caller's live room: when set, the avatar also speaks the reply


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=10, max_length=2000)
    room: str | None = Field(default=None, pattern=r"^tl-[0-9a-f]{12}$")


@router.get("/status")
def status(actor: Actor = Depends(current_actor)):
    """Booleans only. Never returns keys, key fragments or provider details."""
    s = get_settings()
    return {"llm": {"provider": "groq", "configured": service.is_configured(), "model": s.groq_model},
            "voice": {"speech_to_text": voice.configured(), "text_to_speech": voice.configured(), "realtime_audio": s.livekit_ready, "avatar": s.avatar_ready},
            "workflow_execution": n8n.ready()}


@router.post("/chat")
def chat(body: ChatIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    return _speak_result(actor, body.room, lambda: service.handle_chat(db, actor, body.message, body.page or "overview", [t.model_dump() for t in body.history]))


def _speak_result(actor: Actor, room: str | None, produce) -> dict:
    """Runs the normal (authorized, audited) chat/confirm logic, then asks the avatar to say the backend's own `spoken` line. If the logic fails with a safe user-facing
    error (for example the AI service is rate limited), the avatar says that message instead of staying silent, and the error still reaches the panel as usual."""
    try:
        out = produce()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if room and detail.get("message"):
            live.say(actor, room, str(detail["message"]))
        raise
    out["speech"] = live.say(actor, room, out.get("spoken") or out.get("reply", "")) if room else {"requested": False, "reason": "no live session"}
    return out


class SpeakIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=voice.MAX_TTS_CHARS)
    language: str | None = None


@router.post("/voice/transcribe")
async def transcribe(request: Request, language: str | None = Query(None), actor: Actor = Depends(current_actor)):
    """Raw audio body (Content-Type audio/*) -> {text, language}. The text is only returned to the caller, who reviews it before sending."""
    limiter.check(f"voice:{actor.username}", 30, 60)
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in voice.AUDIO_TYPES:
        raise HTTPException(415, {"code": "voice_bad_audio", "message": "Unsupported audio type."})
    if language is not None and language not in voice.STT_LANGUAGES:
        raise HTTPException(422, {"code": "voice_bad_language", "message": "Unsupported language."})
    if int(request.headers.get("content-length") or 0) > voice.MAX_AUDIO_BYTES:
        raise HTTPException(413, {"code": "voice_too_large", "message": "That recording is too long. Keep it under about 30 seconds."})
    audio = await request.body()
    if not audio:
        raise HTTPException(400, {"code": "voice_empty", "message": "No audio was received."})
    if len(audio) > voice.MAX_AUDIO_BYTES:
        raise HTTPException(413, {"code": "voice_too_large", "message": "That recording is too long. Keep it under about 30 seconds."})
    return await voice.transcribe(audio, ctype, language)


@router.post("/voice/speak")
async def speak(body: SpeakIn, actor: Actor = Depends(current_actor)):
    limiter.check(f"voice:{actor.username}", 30, 60)
    if body.language is not None and body.language not in voice.TTS_LANGUAGES:
        raise HTTPException(422, {"code": "voice_bad_language", "message": "Unsupported language."})
    wav = await voice.synthesize(body.text, body.language)
    return {"mime": "audio/wav", "audio_base64": base64.b64encode(wav).decode()}


@router.post("/live/session")
def live_session(actor: Actor = Depends(current_actor)):
    """Short-lived LiveKit token + room for this user. Reveals only the public room URL and the user's own token."""
    limiter.check(f"live:{actor.username}", 6, 60)
    return live.create_session(actor)


class AgentChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(min_length=10, max_length=2000)
    message: str = Field(min_length=1, max_length=500)
    page: Page | None = None
    history: list[Turn] = Field(default_factory=list, max_length=12)


@router.post("/agent/chat")
def agent_chat(body: AgentChatIn, x_trustlayer_voice_agent_key: str | None = Header(default=None), db: Session = Depends(get_session)):
    """The voice agent worker's only entry point. It runs the SAME router, permissions and audit as the typed chat, as the ticket's user.
    Confirmations are returned for the browser to approve with the user's own session; the agent cannot confirm anything."""
    live.check_agent_key(x_trustlayer_voice_agent_key)
    claims = live.verify_ticket(body.ticket)
    user = db.scalar(select(User).where(User.username == claims["sub"], User.active.is_(True)))  # current role, not the one at ticket time
    if user is None:
        raise HTTPException(401, {"code": "ticket_invalid", "message": "The voice session ticket is invalid or has expired."})
    return service.handle_chat(db, Actor(user.username, user.role), body.message, body.page or "overview", [t.model_dump() for t in body.history])


@router.get("/workflow-status")
def workflow_status(workflow: str = Query(..., max_length=40), since: dt.datetime | None = None,
                    actor: Actor = Depends(require("view_automation")), db: Session = Depends(get_session)):
    """What an approved workflow reported to TrustLayer after `since`. `pending` means nothing has reported yet, which is not a failure."""
    return n8n.run_status(db, workflow, since)


@router.post("/confirm")
def confirm(body: ConfirmIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    return _speak_result(actor, body.room, lambda: service.handle_confirm(db, actor, body.token))
