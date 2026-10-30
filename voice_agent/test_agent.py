"""Offline tests for the worker's logic: no LiveKit, Sarvam, Tavus or backend needed."""
import asyncio

import envload
from brain import Brain

OK = {"reply": "Here is what I found.", "spoken": "I found 12 high-severity security events.", "result": {"kind": "security_events", "total": 12},
      "confirmation": None}


def make(post):
    return Brain("http://backend.test/", "agent-key", "ticket-123", post=post)


def run(coro):
    return asyncio.run(coro)


def test_turn_sends_ticket_key_and_history_and_returns_backend_text():
    sent = []

    async def post(url, headers, body):
        sent.append((url, headers, body))
        return 200, OK

    b = make(post)
    out = run(b.turn("  show me the high-severity events  "))
    assert sent[0][0] == "http://backend.test/api/assistant/agent/chat"
    assert sent[0][1] == {"X-TrustLayer-Voice-Agent-Key": "agent-key"}
    assert sent[0][2]["ticket"] == "ticket-123" and sent[0][2]["message"] == "show me the high-severity events" and sent[0][2]["history"] == []
    assert out["spoken"] == OK["spoken"] and out["event"]["result"]["total"] == 12  # what is spoken and shown is the backend's, not invented
    run(b.turn("and again"))
    assert [h["role"] for h in sent[1][2]["history"]] == ["user", "assistant"]  # context carried to the next turn


def test_confirmation_and_refusal_are_passed_through_not_acted_on():
    async def post(url, headers, body):
        return 200, {"reply": "Start a scan?", "spoken": "Start a scan? Please confirm on screen.", "result": None, "confirmation": {"token": "t", "tool": "x"}, "refused": False}

    out = run(make(post).turn("start a scan"))
    assert out["event"]["confirmation"]["tool"] == "x" and out["event"]["result"] is None
    assert "confirm on screen" in out["spoken"]  # the worker has no way to confirm anything itself


def test_failures_are_spoken_honestly():
    async def expired(url, headers, body):
        return 401, {"detail": {"code": "ticket_invalid", "message": "x"}}

    async def limited(url, headers, body):
        return 429, {"detail": "Too many requests"}

    async def broken(url, headers, body):
        raise ConnectionError("secret internal detail")

    async def refused(url, headers, body):
        return 503, {"detail": {"code": "assistant_not_configured", "message": "The AI assistant is not configured yet."}}

    assert "expired" in run(make(expired).turn("hi"))["spoken"]
    assert "rate limiting" in run(make(limited).turn("hi"))["spoken"]
    out = run(make(broken).turn("hi"))
    assert "could not reach" in out["spoken"] and "secret" not in str(out) and out["event"]["type"] == "error"
    assert run(make(refused).turn("hi"))["spoken"] == "The AI assistant is not configured yet."


def test_empty_transcript_is_ignored_and_long_input_is_capped():
    seen = []

    async def post(url, headers, body):
        seen.append(body)
        return 200, OK

    b = make(post)
    assert run(b.turn("   ")) == {"spoken": "", "event": None} and not seen
    run(b.turn("x" * 900))
    assert len(seen[0]["message"]) == 500


def test_history_is_bounded():
    async def post(url, headers, body):
        return 200, OK

    b = make(post)
    for _ in range(10):
        run(b.turn("hello"))
    assert len(b.history) == 6


def test_session_has_an_llm_so_livekit_generates_replies():
    """Regression: with no LLM, LiveKit commits the user's turn and then silently skips the reply (agent_activity: 'skip response if no llm is set')."""
    import pytest
    from livekit.agents import AgentSession, llm

    import agent

    brain = agent.BackendBrain()
    assert isinstance(brain, llm.LLM) and brain.provider == "trustlayer"
    async def build():
        return AgentSession(llm=brain)  # AgentSession needs a running loop

    assert asyncio.run(build()).llm is brain
    with pytest.raises(RuntimeError):  # it must never answer by itself
        brain.chat(chat_ctx=None)


def test_env_parsing_and_requirements_report_names_only():
    env = envload.parse('# c\nLIVEKIT_URL="wss://x"\nexport SARVAM_API_KEY=abc\nEMPTY=\n')
    assert env == {"LIVEKIT_URL": "wss://x", "SARVAM_API_KEY": "abc", "EMPTY": ""}
    names = envload.missing({"LIVEKIT_URL": "wss://x"})
    assert "LIVEKIT_API_SECRET" in names and "LIVEKIT_URL" not in names and all(n.isupper() for n in names)
    assert envload.avatar_configured({"TAVUS_API_KEY": "k", "TAVUS_FACE_ID": "f"}) is True
    assert envload.avatar_configured({"TAVUS_API_KEY": "k"}) is False


# ---- typed/confirmed replies spoken by the avatar (data messages from the backend) ----
import json  # noqa: E402

from saying import MAX_CHARS, SAY_TOPIC, SayGate  # noqa: E402


def pkt(**kw):
    return json.dumps(kw).encode()


def test_say_gate_accepts_a_server_message_once():
    g = SayGate()
    assert g.accept(SAY_TOPIC, None, pkt(id="a1", text="  Scan started.  ")) == ("a1", "Scan started.")
    assert g.accept(SAY_TOPIC, None, pkt(id="a1", text="Scan started.")) is None  # duplicate id: never spoken twice
    assert g.accept(SAY_TOPIC, None, pkt(id="a2", text="Scan started.")) == ("a2", "Scan started.")


def test_say_gate_ignores_participants_other_topics_and_bad_payloads():
    g = SayGate()
    assert g.accept(SAY_TOPIC, object(), pkt(id="b1", text="hi")) is None  # sent by a room participant, not the server API
    assert g.accept("trustlayer.event", None, pkt(id="b2", text="hi")) is None
    for bad in (b"not json", b"\xff\xfe", b"[]", pkt(id="", text="x"), pkt(id="c", text=""), pkt(id="c", text="   "), pkt(id="c", text=5), pkt(text="x"), pkt(id="x" * 65, text="x")):
        assert g.accept(SAY_TOPIC, None, bad) is None


def test_say_gate_caps_length_and_bounds_memory():
    g = SayGate()
    assert len(g.accept(SAY_TOPIC, None, pkt(id="L", text="a" * 5000))[1]) == MAX_CHARS
    for i in range(500):
        g.accept(SAY_TOPIC, None, pkt(id=f"i{i}", text="x"))
    assert len(g._seen) <= 200


# --- language bridge ---------------------------------------------------------------------------------------------------------------------------
def test_translator_english_and_failures_pass_through():
    import asyncio

    from translate import Translator

    async def boom(body):
        raise RuntimeError("down")

    async def none(body):
        return None

    t = Translator(boom)
    assert asyncio.run(t.to_english("show denied requests")) == ("show denied requests", "en-IN")
    assert asyncio.run(t.to_english("आज के अनुरोध")) == ("आज के अनुरोध", "en-IN")  # translator down: original text, English voice
    assert asyncio.run(Translator(none).from_english("Three were refused.", "te-IN")) == ("Three were refused.", "en-IN")
    assert asyncio.run(t.from_english("Three were refused.", "en-IN")) == ("Three were refused.", "en-IN")


def test_translator_uses_detected_language():
    import asyncio

    from translate import Translator

    seen = []

    async def post(body):
        seen.append(body)
        return {"translated_text": "Show today's rejected requests" if body["target_language_code"] == "en-IN" else "आज", "source_language_code": "hi-IN"}

    t = Translator(post)
    assert asyncio.run(t.to_english("आज के अस्वीकृत अनुरोध दिखाओ")) == ("Show today's rejected requests", "hi-IN")
    assert asyncio.run(t.from_english("Done.", "hi-IN")) == ("आज", "hi-IN")
    assert asyncio.run(t.from_english("Done.", "xx-IN")) == ("Done.", "en-IN")  # unsupported language: never sent to the translator
