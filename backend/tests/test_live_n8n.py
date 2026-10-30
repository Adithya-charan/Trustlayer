"""n8n on-demand triggers, LiveKit sessions and the voice-agent entry point. Mock transports only: no network, no real keys."""
import json
import datetime as dt

import httpx
import jwt
import pytest

from app.assistant import live, n8n
from app.core.config import get_settings
from app.core.security import Actor
from tests.conftest import AUTOMATION, login
from tests.test_assistant import call, llm  # noqa: F401  (fixtures/helpers shared with the assistant tests)

TRIGGER = "trigger-secret-0123456789abcdefghij"
LK_SECRET = "livekit-secret-0123456789abcdefghijklmnop"
AGENT = "agent-secret-0123456789abcdefghij"


def set_env(monkeypatch, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


@pytest.fixture()
def n8n_on(monkeypatch):
    """n8n trigger configured; returns the list of requests the (mock) n8n received and a setter for its answer."""
    set_env(monkeypatch, N8N_WEBHOOK_BASE_URL="http://n8n.test/webhook", N8N_TRIGGER_SECRET=TRIGGER)
    seen: list[httpx.Request] = []
    state = {"answer": lambda r: httpx.Response(200, json={"message": "Workflow got started"})}

    def respond(request):
        seen.append(request)
        return state["answer"](request)

    monkeypatch.setattr(n8n, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(respond), headers={n8n.TRIGGER_HEADER: get_settings().n8n_trigger_secret}))
    yield type("N", (), {"seen": seen, "answer": staticmethod(lambda f: state.update(answer=f))})
    monkeypatch.undo()
    get_settings.cache_clear()


# ---------- n8n: confirmation, exact request, honest result ----------
def test_workflow_needs_confirmation_then_triggers_fixed_webhook(client, llm, n8n_on):  # noqa: F811
    h = login(client, "sec.admin")
    llm(tool_calls=[call("run_scan_workflow")])
    body = client.post("/api/assistant/chat", json={"message": "run the scan workflow"}, headers=h).json()
    assert body["confirmation"]["tool"] == "run_scan_workflow" and body["result"] is None
    assert "confirm on screen" in body["spoken"].lower()
    assert n8n_on.seen == []  # nothing reached n8n from the model's response alone
    done = client.post("/api/assistant/confirm", json={"token": body["confirmation"]["token"]}, headers=h)
    assert done.status_code == 200, done.text
    r = done.json()["result"]
    assert r["kind"] == "workflow_triggered" and r["accepted_by_n8n"] is True and r["completed"] is None  # started, NOT claimed as succeeded
    req = n8n_on.seen[0]
    assert str(req.url) == "http://n8n.test/webhook/trustlayer-on-demand-scan" and req.headers[n8n.TRIGGER_HEADER] == TRIGGER
    assert TRIGGER not in done.text and "n8n.test" not in done.text  # secret and internal URL never reach the browser
    assert "accepted the request" in done.json()["spoken"]


def test_duplicate_trigger_is_rejected(client, llm, n8n_on):  # noqa: F811
    h = login(client, "sec.admin")
    for i in range(2):
        llm(tool_calls=[call("generate_audit_summary")])
        token = client.post("/api/assistant/chat", json={"message": "audit summary"}, headers=h).json()["confirmation"]["token"]
        r = client.post("/api/assistant/confirm", json={"token": token}, headers=h)
        assert r.status_code == (200 if i == 0 else 429)
    assert len(n8n_on.seen) == 1


@pytest.mark.parametrize("answer,status,code", [
    (lambda r: httpx.Response(404, json={}), 409, "workflow_not_published"),
    (lambda r: httpx.Response(403, json={}), 503, "workflow_not_configured"),
    (lambda r: httpx.Response(500, json={"x": "secret upstream detail"}), 502, "workflow_unavailable"),
])
def test_n8n_failures_are_reported_not_hidden(client, llm, n8n_on, answer, status, code):  # noqa: F811
    n8n_on.answer(answer)
    h = login(client, "sec.admin")
    llm(tool_calls=[call("run_security_alert_workflow")])
    token = client.post("/api/assistant/chat", json={"message": "run alerts"}, headers=h).json()["confirmation"]["token"]
    r = client.post("/api/assistant/confirm", json={"token": token}, headers=h)
    assert r.status_code == status and r.json()["detail"]["code"] == code
    assert "secret upstream detail" not in r.text and TRIGGER not in r.text


def test_n8n_unreachable(client, llm, n8n_on):  # noqa: F811
    def boom(_):
        raise httpx.ConnectError("refused")
    n8n_on.answer(boom)
    h = login(client, "sec.admin")
    llm(tool_calls=[call("run_scan_workflow")])
    token = client.post("/api/assistant/chat", json={"message": "x"}, headers=h).json()["confirmation"]["token"]
    r = client.post("/api/assistant/confirm", json={"token": token}, headers=h)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "workflow_unavailable"


def test_workflow_tools_hidden_and_refused_when_not_configured(client, llm, monkeypatch):  # noqa: F811
    set_env(monkeypatch, N8N_WEBHOOK_BASE_URL="", N8N_TRIGGER_SECRET="")
    try:
        h = login(client, "sec.admin")
        fake = llm(tool_calls=[call("run_scan_workflow")])
        body = client.post("/api/assistant/chat", json={"message": "x"}, headers=h).json()
        assert not any(t.startswith("run_") or t == "generate_audit_summary" for t in fake.seen_tools if t != "run_scan_workflow") and "run_scan_workflow" not in fake.seen_tools
        assert body["refused"] is True and body["confirmation"] is None and "not configured" in body["reply"]
        assert client.get("/api/assistant/status", headers=h).json()["workflow_execution"] is False
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


@pytest.mark.parametrize("user", ["compliance1", "advisor1", "analyst1"])
def test_only_security_admin_may_run_workflows(client, llm, n8n_on, user):  # noqa: F811
    h = login(client, user)
    llm(tool_calls=[call("run_scan_workflow")])
    body = client.post("/api/assistant/chat", json={"message": "x"}, headers=h).json()
    assert body["refused"] is True and body["confirmation"] is None and n8n_on.seen == []


def test_workflow_status_reports_pending_then_actual_result(client, n8n_on):  # noqa: F811
    h = login(client, "sec.admin")
    since = dt.datetime.now(dt.timezone.utc).isoformat()
    url = f"/api/assistant/workflow-status?workflow=scheduled-scan&since={since.replace('+', '%2B')}"
    assert client.get(url, headers=h).json()["state"] == "pending"  # no report yet: not a failure, not a success
    client.post("/api/automation/workflow-runs", json={"workflow": "scheduled-scan", "status": "SUCCESS", "attempt": 1, "detail": "scan ok"}, headers=AUTOMATION)
    assert client.get(url, headers=h).json()["state"] == "SUCCESS"
    assert client.get("/api/assistant/workflow-status?workflow=not-approved", headers=h).status_code == 400
    assert client.get("/api/assistant/workflow-status?workflow=scheduled-scan", headers=login(client, "advisor1")).status_code == 403


# ---------- LiveKit sessions ----------
@pytest.fixture()
def lk_on(monkeypatch):
    set_env(monkeypatch, LIVEKIT_URL="wss://tl.livekit.test", LIVEKIT_API_KEY="APIkeyfake", LIVEKIT_API_SECRET=LK_SECRET, VOICE_AGENT_SECRET=AGENT)
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def test_live_not_configured(client, monkeypatch):
    set_env(monkeypatch, LIVEKIT_URL="", LIVEKIT_API_KEY="", LIVEKIT_API_SECRET="")
    try:
        h = login(client, "sec.admin")
        r = client.post("/api/assistant/live/session", headers=h)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "live_not_configured"
        assert client.get("/api/assistant/status", headers=h).json()["voice"]["realtime_audio"] is False
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_live_session_token_is_least_privilege_and_leaks_no_secret(client, lk_on):
    h = login(client, "analyst1")
    r = client.post("/api/assistant/live/session", headers=h)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["url"] == "wss://tl.livekit.test" and s["avatar"] is False
    assert LK_SECRET not in r.text and AGENT not in r.text and get_settings().jwt_secret not in r.text
    c = jwt.decode(s["token"], LK_SECRET, algorithms=["HS256"])
    v = c["video"]
    assert c["sub"] == "analyst1" and c["iss"] == "APIkeyfake" and c["exp"] - c["nbf"] <= 600
    assert v["room"] == s["room"] and v["roomJoin"] is True and v["canSubscribe"] is True and v["canPublish"] is True
    assert v["canPublishSources"] == ["microphone"] and v["canPublishData"] is False
    assert not {"roomAdmin", "roomCreate", "roomList", "roomRecord", "ingressAdmin"} & set(v)  # no admin powers
    dispatch = c["roomConfig"]["agents"][0]
    assert dispatch["agentName"] == "trustlayer-voice"
    ticket = live.verify_ticket(dispatch["metadata"])
    assert ticket["sub"] == "analyst1" and ticket["room"] == s["room"]


def test_live_session_requires_sign_in_and_is_rate_limited(client, lk_on):
    assert client.post("/api/assistant/live/session").status_code == 401
    h = login(client, "sec.admin")
    codes = [client.post("/api/assistant/live/session", headers=h).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[-1] == 429


def test_avatar_flag_needs_tavus_config(client, lk_on, monkeypatch):
    h = login(client, "sec.admin")
    assert client.get("/api/assistant/status", headers=h).json()["voice"]["avatar"] is False
    set_env(monkeypatch, TAVUS_API_KEY="tavus-fake-key", TAVUS_FACE_ID="rface123")
    v = client.get("/api/assistant/status", headers=h).json()["voice"]
    assert v["avatar"] is True and v["realtime_audio"] is True
    assert "tavus-fake-key" not in client.get("/api/assistant/status", headers=h).text


# ---------- agent entry point ----------
def agent_post(client, ticket, message="Show me the high-severity security events.", key=AGENT):
    headers = {"X-TrustLayer-Voice-Agent-Key": key} if key else {}
    return client.post("/api/assistant/agent/chat", json={"ticket": ticket, "message": message}, headers=headers)


def test_agent_runs_the_same_router_as_the_user(scanned, lk_on, llm):  # noqa: F811
    ticket = live.mint_ticket(Actor("sec.admin", "security_admin"), "tl-x")
    llm(tool_calls=[call("list_security_events", {"severity": "HIGH"})])
    r = agent_post(scanned, ticket)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["result"]["kind"] == "security_events" and "security event" in b["spoken"]
    audit = scanned.get("/api/audit?operation=assistant_tool", headers=login(scanned, "sec.admin")).json()
    assert audit["total"] >= 1


def test_agent_cannot_exceed_the_users_role_or_self_confirm(client, lk_on, llm):  # noqa: F811
    ticket = live.mint_ticket(Actor("advisor1", "advisor"), "tl-x")
    llm(tool_calls=[call("start_sensitive_data_scan")])
    assert agent_post(client, ticket).json()["refused"] is True
    admin = live.mint_ticket(Actor("sec.admin", "security_admin"), "tl-x")
    llm(tool_calls=[call("start_sensitive_data_scan")])
    b = agent_post(client, admin).json()
    assert b["result"] is None and b["confirmation"]["tool"] == "start_sensitive_data_scan"  # proposed, not run
    assert client.get("/api/scans", headers=login(client, "sec.admin")).json() == []
    # only the user's own session can approve it
    assert client.post("/api/assistant/confirm", json={"token": b["confirmation"]["token"]}, headers=login(client, "sec.admin")).status_code == 200


@pytest.mark.parametrize("key,ticket_ok", [(None, True), ("wrong-agent-key-0123456789abcdef", True), (AGENT, False)])
def test_agent_endpoint_rejects_bad_credentials(client, lk_on, llm, key, ticket_ok):  # noqa: F811
    llm(content="hi")
    ticket = live.mint_ticket(Actor("sec.admin", "security_admin"), "tl-x") if ticket_ok else "not-a-valid-ticket"
    assert agent_post(client, ticket, key=key).status_code == 401


def test_agent_ticket_expiry_and_unknown_user(client, lk_on, llm, monkeypatch):  # noqa: F811
    llm(content="hi")
    assert agent_post(client, live.mint_ticket(Actor("ghost.user", "analyst"), "tl-x")).status_code == 401  # no such active user
    monkeypatch.setattr(live, "TICKET_TTL", dt.timedelta(seconds=-5))
    assert agent_post(client, live.mint_ticket(Actor("sec.admin", "security_admin"), "tl-x")).status_code == 401


def test_agent_endpoint_disabled_without_agent_secret(client, llm, monkeypatch):  # noqa: F811
    set_env(monkeypatch, VOICE_AGENT_SECRET="")
    try:
        llm(content="hi")
        assert agent_post(client, live.mint_ticket(Actor("sec.admin", "security_admin"), "tl-x"), key="").status_code == 401
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# ---------- typed replies spoken by the avatar ----------
@pytest.fixture()
def sent(monkeypatch):
    """Captures what would be handed to LiveKit instead of calling it."""
    box = []

    async def fake(room, payload):
        box.append((room, json.loads(payload)))

    monkeypatch.setattr(live, "_send_say", fake)
    return box


def open_room(client, user="analyst1"):
    h = login(client, user)
    return h, client.post("/api/assistant/live/session", headers=h).json()["room"]


def test_typed_reply_is_sent_to_the_avatar_in_the_callers_own_room(client, lk_on, llm, sent):  # noqa: F811
    llm(content="Hello there.")
    h, room = open_room(client)
    r = client.post("/api/assistant/chat", json={"message": "hi", "room": room}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["speech"]["requested"] is True and body["reply"]  # the text is still returned for the side panel
    assert sent == [(room, {"id": body["speech"]["id"], "text": body["spoken"]})]  # the avatar says the backend's own line


def test_no_room_means_text_only_and_nothing_is_sent(client, lk_on, llm, sent):  # noqa: F811
    llm(content="Hello there.")
    r = client.post("/api/assistant/chat", json={"message": "hi"}, headers=login(client, "analyst1"))
    assert r.json()["speech"] == {"requested": False, "reason": "no live session"} and sent == []


def test_cannot_speak_into_someone_elses_or_unknown_room(client, lk_on, llm, sent):  # noqa: F811
    llm(content="Hello there.")
    _, room = open_room(client, "analyst1")
    other = login(client, "sec.admin")
    assert client.post("/api/assistant/chat", json={"message": "hi", "room": room}, headers=other).json()["speech"]["requested"] is False
    assert client.post("/api/assistant/chat", json={"message": "hi", "room": "tl-000000000000"}, headers=other).json()["speech"]["requested"] is False
    assert client.post("/api/assistant/chat", json={"message": "hi", "room": "not-a-room"}, headers=other).status_code == 422
    assert sent == []


def test_speech_needs_livekit_and_failure_keeps_the_text(client, lk_on, llm, monkeypatch):  # noqa: F811
    llm(content="Hello there.")
    h, room = open_room(client)

    async def boom(room, payload):
        raise RuntimeError("secret provider detail")

    monkeypatch.setattr(live, "_send_say", boom)
    r = client.post("/api/assistant/chat", json={"message": "hi", "room": room}, headers=h)
    assert r.status_code == 200 and r.json()["reply"]
    assert r.json()["speech"]["requested"] is False and "secret provider detail" not in r.text


def test_provider_error_is_spoken_too_and_still_reported(client, lk_on, llm, sent):  # noqa: F811
    llm(error=RuntimeError("down"))
    h, room = open_room(client)
    r = client.post("/api/assistant/chat", json={"message": "hi", "room": room}, headers=h)
    assert r.status_code >= 400 and r.json()["detail"]["message"]
    assert len(sent) == 1 and sent[0][1]["text"] == r.json()["detail"]["message"]
