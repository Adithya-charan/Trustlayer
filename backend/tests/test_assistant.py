"""Assistant tests. A fake model client stands in for Groq: no network, no real key."""
import json
from types import SimpleNamespace

import pytest

from app.assistant import service
from app.core.config import get_settings
from tests.conftest import login

SECRET = "gsk_test_secret_value_do_not_leak_123456"


def call(name, args=None, raw=None):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=raw if raw is not None else json.dumps(args or {})))


class FakeClient:
    def __init__(self, tool_calls=None, content="", error=None):
        self.error = error
        msg = SimpleNamespace(content=content, tool_calls=tool_calls or [])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        self.seen_tools: list[str] = []

    def _create(self, **kw):
        self.seen_tools = [t["function"]["name"] for t in kw["tools"]]
        if self.error:
            raise self.error
        return self._resp


class ProviderError(Exception):
    def __init__(self, status_code):
        super().__init__("provider said: secret request details")
        self.status_code = status_code


@pytest.fixture()
def llm(monkeypatch):
    """Install a fake model client; returns a setter."""
    def use(**kw):
        fake = FakeClient(**kw)
        monkeypatch.setattr(service, "get_llm_client", lambda: fake)
        return fake
    return use


def chat(client, headers, message="hi", page="overview"):
    return client.post("/api/assistant/chat", json={"message": message, "page": page}, headers=headers)


# ---------- successful requests ----------
def test_read_tool_returns_real_backend_data(scanned, llm):
    h = login(scanned, "sec.admin")
    llm(tool_calls=[call("list_security_events", {"severity": "HIGH", "limit": 3})], content="I'll retrieve the high-severity security events.")
    r = chat(scanned, h, "Show me the high-severity security events.", "overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"].startswith("I'll retrieve")
    assert body["result"]["kind"] == "security_events"
    real = scanned.get("/api/risk/events?severity=HIGH&limit=3", headers=h).json()
    assert body["result"]["total"] == real["total"]  # numbers come from the backend, not from model text
    assert [e["id"] for e in body["result"]["items"]] == [e["id"] for e in real["items"]]


def test_navigation_and_explain(client, llm):
    h = login(client, "analyst1")
    llm(tool_calls=[call("navigate_to_page", {"page": "discovery"})])
    assert chat(client, h).json()["result"] == {"kind": "navigate", "page": "discovery"}
    llm(tool_calls=[call("explain_page", {"page": "policies"})])
    assert "Access Policies" in chat(client, h).json()["result"]["text"]


def test_plain_text_reply_without_tool(client, llm):
    h = login(client, "analyst1")
    llm(content="I can help with the dashboard.")
    body = chat(client, h).json()
    assert body["result"] is None and body["confirmation"] is None


def test_model_only_sees_tools_its_role_may_use(client, llm):
    h = login(client, "analyst1")
    fake = llm(content="ok")
    chat(client, h)
    assert "start_sensitive_data_scan" not in fake.seen_tools and "list_security_events" not in fake.seen_tools
    assert "navigate_to_page" in fake.seen_tools


# ---------- confirmation for consequential operations ----------
def test_scan_needs_confirmation_and_runs_once(client, llm):
    h = login(client, "sec.admin")
    assert client.get("/api/scans", headers=h).json() == []
    llm(tool_calls=[call("start_sensitive_data_scan")], content="Would you like me to start the scan now?")
    body = chat(client, h, "Start a sensitive-data scan.").json()
    assert body["result"] is None and body["confirmation"]["tool"] == "start_sensitive_data_scan"
    assert client.get("/api/scans", headers=h).json() == []  # nothing ran from the model response alone
    token = body["confirmation"]["token"]
    done = client.post("/api/assistant/confirm", json={"token": token}, headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["result"]["kind"] == "scan_started" and done.json()["result"]["scan"]["status"] == "COMPLETED"
    assert len(client.get("/api/scans", headers=h).json()) == 1
    again = client.post("/api/assistant/confirm", json={"token": token}, headers=h)
    assert again.status_code == 409  # single use


def test_confirmation_is_bound_to_the_user(client, llm):
    admin, other = login(client, "sec.admin"), login(client, "compliance1")
    llm(tool_calls=[call("start_sensitive_data_scan")])
    token = chat(client, admin).json()["confirmation"]["token"]
    r = client.post("/api/assistant/confirm", json={"token": token}, headers=other)
    assert r.status_code == 403
    assert client.post("/api/assistant/confirm", json={"token": "x" * 40}, headers=admin).status_code == 400


# ---------- invalid / unauthorised tool requests ----------
@pytest.mark.parametrize("name,args,raw", [
    ("run_sql", {"sql": "DROP TABLE customers"}, None),
    ("execute_shell", {"cmd": "dir"}, None),
    ("run_workflow", {"workflow": "scheduled-scan"}, None),
    ("list_security_events", {"severity": "HIGH", "sql": "x"}, None),  # extra field
    ("list_security_events", {"limit": 9999}, None),  # out of bounds
    ("list_security_events", None, "{not json"),
    ("navigate_to_page", {"page": "../../etc"}, None),
])
def test_invalid_tool_requests_are_refused(client, llm, name, args, raw):
    h = login(client, "sec.admin")
    llm(tool_calls=[call(name, args, raw)])
    body = chat(client, h).json()
    assert body["refused"] is True and body["result"] is None and body["confirmation"] is None


def test_role_cannot_use_tools_it_lacks(client, llm):
    h = login(client, "analyst1")
    llm(tool_calls=[call("start_sensitive_data_scan")])  # the model asks anyway
    body = chat(client, h).json()
    assert body["refused"] is True and body["confirmation"] is None
    llm(tool_calls=[call("list_security_events")])
    assert chat(client, h).json()["refused"] is True
    h2 = login(client, "advisor1")
    llm(tool_calls=[call("navigate_to_page", {"page": "automation"})])
    assert chat(client, h2).json()["refused"] is True


def test_requests_are_audited(client, llm):
    h = login(client, "sec.admin")
    llm(tool_calls=[call("run_sql", {})])
    chat(client, h)
    rows = client.get("/api/audit?operation=assistant_tool&limit=20", headers=h).json()
    assert rows["total"] == 1
    assert rows["events"][0]["decision"] == "DENY" and rows["events"][0]["policy"] == "assistant/run_sql"


def test_requires_authentication(client):
    assert client.post("/api/assistant/chat", json={"message": "hi"}).status_code == 401
    assert client.get("/api/assistant/status").status_code == 401


# ---------- missing key / provider failures ----------
def test_missing_api_key(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()
    try:
        h = login(client, "sec.admin")
        r = chat(client, h)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "assistant_not_configured"
        assert client.get("/api/assistant/status", headers=h).json()["llm"]["configured"] is False
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_provider_rate_limit_maps_to_429_without_provider_text(client, llm):
    h = login(client, "sec.admin")
    llm(error=ProviderError(429))
    r = chat(client, h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "assistant_rate_limited"
    assert "secret request details" not in r.text


def test_provider_auth_and_outage(client, llm):
    h = login(client, "sec.admin")
    llm(error=ProviderError(401))
    assert chat(client, h).json()["detail"]["code"] == "assistant_not_configured"
    llm(error=ProviderError(500))
    r = chat(client, h)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "assistant_unavailable"


def test_local_rate_limit(client, llm):
    h = login(client, "sec.admin")
    llm(content="ok")
    codes = [chat(client, h).status_code for _ in range(22)]
    assert codes[:20] == [200] * 20 and codes[-1] == 429


# ---------- the key is never exposed ----------
def test_key_never_appears_in_responses_or_logs(client, llm, monkeypatch, caplog):
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    get_settings.cache_clear()
    try:
        h = login(client, "sec.admin")
        llm(error=ProviderError(500))
        caplog.set_level("DEBUG")
        texts = [client.get("/api/assistant/status", headers=h).text, chat(client, h).text, client.get("/api/settings", headers=h).text,
                 client.get("/api/health").text, repr(get_settings())]
        assert all(SECRET not in t for t in texts)
        assert SECRET not in caplog.text
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
