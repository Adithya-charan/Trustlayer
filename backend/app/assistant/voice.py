"""Speech services (Sarvam). The key stays on the server: the browser sends audio or text to TrustLayer, TrustLayer
calls Sarvam. Audio and transcripts are never stored or logged; only sizes and outcomes are.
Docs checked: POST https://api.sarvam.ai/speech-to-text (multipart `file`, `model`, `language_code`; REST is meant for clips under 30 s)
and POST https://api.sarvam.ai/text-to-speech (JSON `text`, `language_code`, `model`, `speaker`; returns base64 WAV in `audios`)."""
import base64
import logging

import httpx
from fastapi import HTTPException

from app.core.config import get_settings

log = logging.getLogger("trustlayer.voice")
STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_URL = "https://api.sarvam.ai/text-to-speech"
MAX_AUDIO_BYTES = 2_000_000  # ~30 s of compressed speech with headroom
MAX_TTS_CHARS = 1000  # Sarvam allows more; shorter keeps spoken replies quick
TTS_LANGUAGES = frozenset({"en-IN", "hi-IN", "bn-IN", "gu-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"})
STT_LANGUAGES = TTS_LANGUAGES | {"unknown"}
AUDIO_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a", "audio/mpeg": "mp3"}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def configured() -> bool:
    return bool(get_settings().sarvam_api_key)


def http_client() -> httpx.AsyncClient:
    """The one place the Sarvam key is attached. Tests replace this to inject a mock transport."""
    s = get_settings()
    return httpx.AsyncClient(timeout=s.sarvam_timeout_seconds, headers={"api-subscription-key": s.sarvam_api_key})


def _require_key() -> None:
    if not configured():
        raise _error(503, "voice_not_configured", "Voice is not configured on the server yet. An administrator needs to set SARVAM_API_KEY.")


def _map_failure(resp: httpx.Response | None, exc: Exception | None = None) -> HTTPException:
    status = resp.status_code if resp is not None else None
    log.warning("sarvam call failed: status=%s error=%s", status, type(exc).__name__ if exc else "-")  # never the body: it may echo input
    if status == 429:
        return _error(429, "voice_rate_limited", "The speech service is busy (quota or rate limit). Please wait a moment and try again.")
    if status == 402:
        return _error(503, "voice_no_credit", "The speech service account has no remaining credit or an inactive plan. Ask an administrator to check the Sarvam account.")
    if status in (401, 403):
        return _error(503, "voice_not_configured", "The speech service rejected the server's credentials. Ask an administrator to check SARVAM_API_KEY.")
    if status in (400, 422):
        return _error(422, "voice_rejected", "The speech service could not process that request. Try a shorter or clearer clip.")
    return _error(502, "voice_unavailable", "The speech service is unavailable right now. Please try again.")


async def transcribe(audio: bytes, content_type: str, language: str | None) -> dict:
    _require_key()
    s = get_settings()
    ext = AUDIO_TYPES[content_type]
    data = {"model": s.sarvam_stt_model, "language_code": language or "unknown"}
    try:
        async with http_client() as c:
            r = await c.post(STT_URL, data=data, files={"file": (f"speech.{ext}", audio, content_type)})
    except httpx.HTTPError as exc:
        raise _map_failure(None, exc) from None
    if r.status_code != 200:
        raise _map_failure(r)
    body = r.json()
    text = (body.get("transcript") or "").strip()
    return {"text": text[:500], "language": body.get("language_code")}


async def synthesize(text: str, language: str | None) -> bytes:
    _require_key()
    s = get_settings()
    payload = {"text": text, "language_code": language or s.sarvam_language, "model": s.sarvam_tts_model,
               "speaker": s.sarvam_tts_speaker, "output_audio_codec": "wav"}
    try:
        async with http_client() as c:
            r = await c.post(TTS_URL, json=payload)
    except httpx.HTTPError as exc:
        raise _map_failure(None, exc) from None
    if r.status_code != 200:
        raise _map_failure(r)
    audios = r.json().get("audios") or []
    if not audios:
        raise _error(502, "voice_unavailable", "The speech service returned no audio. Please try again.")
    return base64.b64decode(audios[0])
