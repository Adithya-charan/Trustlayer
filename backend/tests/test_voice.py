"""Voice endpoint tests. httpx.MockTransport stands in for Sarvam: no network, no real key."""
import base64

import httpx
import pytest

from app.assistant import voice
from app.core.config import get_settings
from tests.conftest import login

KEY = "sk_test_sarvam_key_do_not_leak_0123456789"
WAV = b"RIFF....WAVEfmt fake-wav-bytes"


@pytest.fixture()
def sarvam(monkeypatch):
    """Configure a fake key and route Sarvam calls to a handler; returns the list of requests Sarvam saw."""
    monkeypatch.setenv("SARVAM_API_KEY", KEY)
    get_settings.cache_clear()
    seen: list[httpx.Request] = []
    state = {"handler": None}

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return state["handler"](request)

    def use(handler):
        state["handler"] = handler

    monkeypatch.setattr(voice, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond), headers={"api-subscription-key": get_settings().sarvam_api_key}))
    use(lambda r: httpx.Response(200, json={"transcript": "show me the high severity events", "language_code": "en-IN"}) if r.url.path == "/speech-to-text"
        else httpx.Response(200, json={"audios": [base64.b64encode(WAV).decode()]}))
    seen_api = type("S", (), {"requests": seen, "use": staticmethod(use)})
    yield seen_api
    monkeypatch.undo()
    get_settings.cache_clear()


def post_audio(client, headers, body=b"audio-bytes", ctype="audio/webm;codecs=opus", qs=""):
    return client.post(f"/api/assistant/voice/transcribe{qs}", content=body, headers={**headers, "Content-Type": ctype})


# ---------- success ----------
def test_transcribe_returns_text_and_sends_key_only_to_sarvam(client, sarvam):
    h = login(client, "sec.admin")
    r = post_audio(client, h, qs="?language=en-IN")
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "show me the high severity events", "language": "en-IN"}
    sent = sarvam.requests[0]
    assert sent.headers["api-subscription-key"] == KEY and str(sent.url) == voice.STT_URL
    assert b"saaras:v4" in sent.content and b"en-IN" in sent.content
    assert KEY not in r.text


def test_speak_returns_playable_audio(client, sarvam):
    h = login(client, "analyst1")
    r = client.post("/api/assistant/voice/speak", json={"text": "Here is what I found."}, headers=h)
    assert r.status_code == 200, r.text
    assert base64.b64decode(r.json()["audio_base64"]) == WAV and r.json()["mime"] == "audio/wav"
    body = sarvam.requests[0].content
    assert b"bulbul:v3" in body and b"priya" in body and b"en-IN" in body


def test_status_flags_follow_configuration(client, sarvam, monkeypatch):
    h = login(client, "sec.admin")
    assert client.get("/api/assistant/status", headers=h).json()["voice"]["speech_to_text"] is True
    monkeypatch.setenv("SARVAM_API_KEY", "")
    get_settings.cache_clear()
    v = client.get("/api/assistant/status", headers=h).json()["voice"]
    assert v["speech_to_text"] is False and v["text_to_speech"] is False and v["realtime_audio"] is False and v["avatar"] is False


# ---------- missing key / provider failures ----------
def test_missing_key(client, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "")
    get_settings.cache_clear()
    try:
        h = login(client, "sec.admin")
        r = post_audio(client, h)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "voice_not_configured"
        assert client.post("/api/assistant/voice/speak", json={"text": "hi"}, headers=h).status_code == 503
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


@pytest.mark.parametrize("upstream,status,code", [(429, 429, "voice_rate_limited"), (401, 503, "voice_not_configured"), (402, 503, "voice_no_credit"), (422, 422, "voice_rejected"), (500, 502, "voice_unavailable")])
def test_provider_failures_are_mapped_without_provider_text(client, sarvam, upstream, status, code):
    sarvam.use(lambda r: httpx.Response(upstream, json={"error": {"message": "secret upstream detail"}}))
    h = login(client, "sec.admin")
    for r in (post_audio(client, h), client.post("/api/assistant/voice/speak", json={"text": "hi"}, headers=h)):
        assert r.status_code == status and r.json()["detail"]["code"] == code
        assert "secret upstream detail" not in r.text and KEY not in r.text


def test_network_failure(client, sarvam):
    def boom(_):
        raise httpx.ConnectError("no route")
    sarvam.use(boom)
    h = login(client, "sec.admin")
    assert post_audio(client, h).json()["detail"]["code"] == "voice_unavailable"


# ---------- input validation / authorization ----------
def test_rejects_bad_audio_inputs(client, sarvam):
    h = login(client, "sec.admin")
    assert post_audio(client, h, ctype="text/plain").status_code == 415
    assert post_audio(client, h, body=b"").status_code == 400
    assert post_audio(client, h, qs="?language=xx-XX").status_code == 422
    assert post_audio(client, h, body=b"x" * (voice.MAX_AUDIO_BYTES + 1)).status_code == 413
    assert not sarvam.requests  # nothing reached the provider


def test_rejects_bad_speak_inputs(client, sarvam):
    h = login(client, "sec.admin")
    assert client.post("/api/assistant/voice/speak", json={"text": "x" * (voice.MAX_TTS_CHARS + 1)}, headers=h).status_code == 422
    assert client.post("/api/assistant/voice/speak", json={"text": "hi", "language": "unknown"}, headers=h).status_code == 422
    assert client.post("/api/assistant/voice/speak", json={"text": "hi", "extra": 1}, headers=h).status_code == 422
    assert not sarvam.requests


def test_voice_requires_authentication(client, sarvam):
    assert client.post("/api/assistant/voice/transcribe", content=b"a", headers={"Content-Type": "audio/webm"}).status_code == 401
    assert client.post("/api/assistant/voice/speak", json={"text": "hi"}).status_code == 401
    assert not sarvam.requests


def test_voice_rate_limit(client, sarvam):
    h = login(client, "sec.admin")
    codes = [client.post("/api/assistant/voice/speak", json={"text": "hi"}, headers=h).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[-1] == 429


def test_key_never_in_logs(client, sarvam, caplog):
    caplog.set_level("DEBUG")
    sarvam.use(lambda r: httpx.Response(500, json={}))
    h = login(client, "sec.admin")
    post_audio(client, h)
    assert KEY not in caplog.text
