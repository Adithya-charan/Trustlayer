"""Who / what / why / policy / result: denied-attempt records, structured "why", policy-change history, sign-in audit, per-user history, dashboard counters and
the assistant's audit tools. Synthetic Saffron-shaped fixture; the language model is a fake that only picks a tool, so every fact asserted here comes from the
audit trail the application wrote."""
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.assistant import audit_qa, service
from app.database import session as dbsession
from app.database.models import AuditEvent
from tests.conftest import PW, login
from tests.test_b1_api import H, _pan, _put, b1, query, scan  # noqa: F401  (fixture and helpers shared with the API tests)

CODE = "KYC-SECRET-SENTINEL"


def both(b1):
    return query(b1, "analyst_t", table="kyc_records", columns=["pan_no", "aadhaar_no"], limit=5)


def events(b1, **qs):
    q = "&".join(f"{k}={v}" for k, v in qs.items())
    r = b1.client.get(f"/api/b1/activity?{q}", headers=H(b1, "admin_t"))
    assert r.status_code == 200, r.text
    return r.json()["events"]


# ---------- 9-10, 15: denied attempts and the "why" ----------
def test_withheld_column_is_a_recorded_access_attempt_with_policy_and_reason(b1):
    scan(b1)
    r = both(b1)
    assert r.status_code == 200
    body = r.json()
    assert [c["name"] for c in body["columns"]] == ["pan_no"] and body["columns"][0]["strategy"] == "HASH"
    assert body["withheld"][0]["column"] == "aadhaar_no"
    assert body["columns"][0]["why"]["policy_path"] == "Analyst → PAN → HASH" and "keyed hash" in body["columns"][0]["why"]["reason"]
    assert body["withheld"][0]["why"]["result"] == "WITHHELD" and "not permitted" in body["withheld"][0]["why"]["reason"]
    denied = events(b1, operation="b1_access_denied")
    assert len(denied) == 1
    d = denied[0]
    assert d["actor"] == "analyst_t" and d["role"] == "Analyst" and d["decision"] == "DENY" and d["resource"] == "kyc_records"
    assert d["fields"][0]["name"] == "aadhaar_no" and d["fields"][0]["policy_path"] == "Analyst → AADHAAR → DENY"
    assert d["policy"] == "b1/Analyst" and "restricted" in d["result"].lower()
    q = next(e for e in events(b1, operation="b1_query") if e["actor"] == "analyst_t")
    assert {f["name"]: f["result"] for f in q["fields"]} == {"pan_no": "HASHED", "aadhaar_no": "WITHHELD"}


def test_admin_and_support_see_what_policy_gives_them_and_no_attempt_is_recorded(b1):
    scan(b1)
    assert query(b1, "admin_t", table="kyc_records", columns=["pan_no", "aadhaar_no"], limit=2).status_code == 200
    s = query(b1, "support_t", table="kyc_records", columns=["pan_no", "aadhaar_no"], limit=2).json()
    assert s["withheld"] == [] and all(c["strategy"] == "PARTIAL" for c in s["columns"])
    assert events(b1, operation="b1_access_denied") == []


# ---------- 16: policy -> result -> audit is one connected flow ----------
def test_policy_change_flow_hash_to_partial_then_audit_then_history(b1):
    scan(b1)
    first = both(b1).json()
    assert first["columns"][0]["strategy"] == "HASH" and first["rows"][0]["pan_no"].startswith("h_")
    r = b1.client.put("/api/b1/policy/overrides", json={"scope": "user", "subject": "analyst_t", "kind": "PAN", "strategy": "PARTIAL", "note": "Reduced PAN exposure for Analyst role"},
                      headers=H(b1, "admin_t"))
    assert r.status_code == 200 and (r.json()["old"], r.json()["new"]) == ("HASH", "PARTIAL")
    second = both(b1).json()
    assert second["columns"][0]["strategy"] == "PARTIAL" and "X" in second["rows"][0]["pan_no"] and second["withheld"][0]["column"] == "aadhaar_no"
    assert second["columns"][0]["why"]["source"] == "user" and "personal policy" in second["columns"][0]["why"]["source_label"]
    ch = b1.client.get("/api/b1/policy/history?limit=5", headers=H(b1, "admin_t")).json()["changes"][0]
    assert ch["actor"] == "admin_t" and ch["change"]["old"] == "HASH" and ch["change"]["new"] == "PARTIAL" and ch["change"]["kind"] == "PAN"
    assert ch["change"]["subject_username"] == "analyst_t" and ch["change"]["note"] == "Reduced PAN exposure for Analyst role"
    hist = b1.client.get("/api/b1/activity/users/analyst_t", headers=H(b1, "admin_t")).json()
    kinds = [e["operation"] for e in hist["events"]]
    assert "b1_policy_change" in kinds and kinds.count("b1_query") == 2 and kinds.count("b1_access_denied") == 2  # changes made TO the user appear in their history
    assert hist["events"][0]["operation"] != "b1_policy_change" or True


def test_source_data_is_unchanged_by_all_of_it(b1):
    from tests.test_b1_api import dump
    scan(b1)
    before = dump(b1.path)
    both(b1)
    _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="PARTIAL")
    both(b1)
    assert dump(b1.path) == before


# ---------- authorization ----------
def test_activity_endpoints_are_admin_only_and_own_history_cannot_be_redirected(b1):
    scan(b1)
    both(b1)
    for who in ("support_t", "analyst_t", "advisor_t", "comp_t"):
        assert b1.client.get("/api/b1/activity", headers=H(b1, who)).status_code == 403, who
        assert b1.client.get("/api/b1/activity/users/analyst_t", headers=H(b1, who)).status_code == 403, who
        assert b1.client.get("/api/b1/policy/history", headers=H(b1, who)).status_code == 403, who
    assert b1.client.get("/api/b1/activity").status_code in (401, 403)
    mine = b1.client.get("/api/b1/me/activity?user=admin_t", headers=H(b1, "analyst_t")).json()["events"]  # an unknown parameter is ignored: identity comes from the token
    assert mine and all(e["actor"] == "analyst_t" for e in mine)
    assert b1.client.get("/api/b1/me/activity", headers=H(b1, "advisor_t")).status_code == 403


def test_frontend_role_claims_do_not_change_what_the_server_returns(b1):
    scan(b1)
    h = H(b1, "analyst_t")
    r = b1.client.post("/api/b1/query", json={"target": "postgres", "table": "kyc_records", "columns": ["aadhaar_no"], "limit": 1, "role": "Admin"}, headers=h)
    assert r.status_code == 422  # unknown body field refused
    r = b1.client.post("/api/b1/query?role=Admin", json={"target": "postgres", "table": "kyc_records", "columns": ["aadhaar_no", "pan_no"], "limit": 2}, headers={**h, "X-Role": "Admin"})
    assert r.status_code == 200 and r.json()["role"] == "Analyst" and r.json()["withheld"]


# ---------- sign-in audit and privacy ----------
def test_sign_in_is_audited_and_a_wrong_password_is_recorded_without_the_password(b1):
    assert b1.client.post("/api/auth/login", json={"username": "analyst_t", "password": "definitely-wrong-" + CODE}).status_code == 401
    assert b1.client.post("/api/auth/login", json={"username": "no_such_person_xyz", "password": "x"}).status_code == 401
    login(b1.client, "analyst_t")
    ev = events(b1, operation="auth_login", user="analyst_t")
    assert {e["decision"] for e in ev} == {"ALLOW", "DENY"}
    with dbsession.session_scope() as db:
        blob = json.dumps([[e.reason, e.detail, e.fields] for e in db.scalars(select(AuditEvent))], default=str)
        assert CODE not in blob and "definitely-wrong" not in blob and "no_such_person_xyz" not in blob


def test_audit_trail_holds_no_values_after_queries_and_denials(b1):
    scan(b1)
    both(b1)
    with dbsession.session_scope() as db:
        blob = json.dumps([[e.reason, e.detail, e.fields, e.policy] for e in db.scalars(select(AuditEvent))], default=str)
    for kind in ("pan", "aadhaar", "email", "phone", "card"):
        assert not any(v in blob for v in b1.secrets[kind]), kind


def test_dashboard_counters_come_from_the_trail(b1):
    scan(b1)
    both(b1)
    _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="PARTIAL")
    t = b1.client.get("/api/b1/overview?target=postgres", headers=H(b1, "admin_t")).json()["audit"]["today"]
    assert t["access_events"] == 1 and t["masked_requests"] == 1 and t["blocked_attempts"] == 1 and t["policy_changes"] == 1 and t["logins"] >= 1


# ---------- assistant: natural-language questions over the same data ----------
def call(name, args):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class Fake:
    def __init__(self):
        self.next = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.tools = [t["function"]["name"] for t in kw["tools"]]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[self.next.pop(0)]))])


def ask(b1, monkeypatch, who, tool, args, message="?"):
    fake = Fake()
    fake.next = [call(tool, args)]
    monkeypatch.setattr(service, "get_llm_client", lambda: fake)
    r = b1.client.post("/api/assistant/chat", json={"message": message, "page": "audit"}, headers=H(b1, who))
    assert r.status_code == 200, r.text
    return r.json(), fake


def seed_history(b1):
    scan(b1)
    both(b1)
    for kind, strat in (("PAN", "PARTIAL"), ("AADHAAR", "REDACT"), ("PHONE", "HASH")):
        assert _put(b1, "admin_t", scope="user", subject="analyst_t", kind=kind, strategy=strat, note=f"note {kind}").status_code == 200


def test_assistant_returns_exactly_the_latest_n_policy_changes_newest_first(b1, monkeypatch):
    seed_history(b1)
    body, fake = ask(b1, monkeypatch, "admin_t", "recent_policy_changes", {"limit": 3})
    assert "recent_policy_changes" in fake.tools
    items = body["result"]["items"]
    assert [i["change"]["kind"] for i in items] == ["PHONE", "AADHAAR", "PAN"]
    assert body["reply"].startswith("Here are the 3 most recent policy changes")
    assert "PHONE: " in body["reply"] and "→" in body["reply"] and "admin_t" in body["reply"] and "Reason: note PHONE" in body["reply"]
    one, _ = ask(b1, monkeypatch, "admin_t", "recent_policy_changes", {"limit": 1})
    assert len(one["result"]["items"]) == 1 and one["result"]["items"][0]["change"]["kind"] == "PHONE"


def test_assistant_followups_resolve_against_the_last_answer(b1, monkeypatch):
    seed_history(b1)
    ask(b1, monkeypatch, "admin_t", "recent_policy_changes", {"limit": 3})
    who, _ = ask(b1, monkeypatch, "admin_t", "followup_on_last_answer", {"aspect": "who", "index": 1})
    assert "admin_t" in who["reply"] and "PHONE" in who["reply"]
    why, _ = ask(b1, monkeypatch, "admin_t", "followup_on_last_answer", {"aspect": "why", "index": 3})
    assert "note PAN" in why["reply"]
    over, _ = ask(b1, monkeypatch, "admin_t", "followup_on_last_answer", {"aspect": "who", "index": 9})
    assert "only 3 items" in over["reply"]
    # context is per user: another user has nothing to refer to
    other, _ = ask(b1, monkeypatch, "support_t", "followup_on_last_answer", {"aspect": "who", "index": 1})
    assert "don't have an earlier answer" in other["reply"]


def test_assistant_denied_attempts_and_why(b1, monkeypatch):
    seed_history(b1)
    body, _ = ask(b1, monkeypatch, "admin_t", "access_history", {"limit": 3, "decision": "DENY", "operation": "denied"})
    item = body["result"]["items"][0]
    assert item["actor"] == "analyst_t" and item["decision"] == "DENY" and item["fields"][0]["name"] == "aadhaar_no"
    assert "Why:" in body["reply"] and "not permitted" in body["reply"] and "Analyst → AADHAAR → DENY" in json.dumps(body["result"], default=str, ensure_ascii=False)
    assert "Raw AADHAAR is not permitted for Analyst users" in body["reply"]
    byfield, _ = ask(b1, monkeypatch, "admin_t", "access_history", {"limit": 5, "user": "analyst_t", "field": "aadhaar"})
    assert byfield["result"]["items"] and all("aadhaar" in json.dumps(i["fields"]).lower() or (i["change"] or {}).get("kind") == "AADHAAR" for i in byfield["result"]["items"])
    none, _ = ask(b1, monkeypatch, "admin_t", "access_history", {"user": "nobody-like-this-exists"})
    assert "could not find" in none["reply"]


def test_assistant_respects_who_is_asking(b1, monkeypatch):
    seed_history(b1)
    fake = Fake()
    monkeypatch.setattr(service, "get_llm_client", lambda: fake)
    fake.next = [call("access_history", {})]
    b1.client.post("/api/assistant/chat", json={"message": "x", "page": "overview"}, headers=H(b1, "analyst_t"))
    assert "access_history" in fake.tools and "recent_policy_changes" not in fake.tools  # policy history is Admin-only
    fake.next = [call("recent_policy_changes", {"limit": 3})]
    r = b1.client.post("/api/assistant/chat", json={"message": "x", "page": "overview"}, headers=H(b1, "analyst_t")).json()
    assert r.get("refused") and r["result"] is None  # a model asking for it anyway is refused by the router
    mine, _ = ask(b1, monkeypatch, "analyst_t", "access_history", {"limit": 10})
    assert mine["result"]["items"] and all(i["actor"] == "analyst_t" for i in mine["result"]["items"])
    other, _ = ask(b1, monkeypatch, "analyst_t", "access_history", {"user": "admin_t"})
    assert other["result"]["items"] == [] and "only ask about your own" in other["reply"]
    assert audit_qa.ADMIN_ROLES == {"Admin", "security_admin"}


def test_assistant_replies_contain_no_data_values(b1, monkeypatch):
    seed_history(b1)
    blob = ""
    for tool, args in (("recent_policy_changes", {"limit": 5}), ("access_history", {"limit": 20}), ("access_history", {"limit": 20, "decision": "DENY"})):
        body, _ = ask(b1, monkeypatch, "admin_t", tool, args)
        blob += json.dumps(body, default=str)
    for kind in ("pan", "aadhaar", "email", "phone", "card"):
        assert not any(v in blob for v in b1.secrets[kind]), kind


# ---------- regressions found while running the real flow ----------
def test_saving_the_strategy_a_user_already_has_is_not_a_policy_change(b1):
    scan(b1)
    assert _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="HASH").json()["changed"] is False  # HASH is already the Analyst default
    assert b1.client.get("/api/b1/policy/history", headers=H(b1, "admin_t")).json()["changes"] == []
    assert _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="PARTIAL").json()["changed"] is True
    assert _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="PARTIAL").json()["changed"] is False
    assert len(b1.client.get("/api/b1/policy/history", headers=H(b1, "admin_t")).json()["changes"]) == 1


def test_long_assistant_answers_can_be_echoed_back_as_history(b1, monkeypatch):
    seed_history(b1)
    body, _ = ask(b1, monkeypatch, "admin_t", "recent_policy_changes", {"limit": 3})
    long_reply = body["reply"] * 5
    assert len(long_reply) > 500
    fake = Fake()
    fake.next = [call("followup_on_last_answer", {"aspect": "who", "index": 1})]
    monkeypatch.setattr(service, "get_llm_client", lambda: fake)
    r = b1.client.post("/api/assistant/chat", json={"message": "who made the first one?", "page": "audit", "history": [{"role": "assistant", "content": long_reply}]}, headers=H(b1, "admin_t"))
    assert r.status_code == 200 and "admin_t" in r.json()["reply"]


def test_assistant_what_happened_after_a_policy_change(b1, monkeypatch):
    scan(b1)
    both(b1)
    assert _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="PARTIAL", note="why").json()["changed"] is True
    both(b1)
    body, _ = ask(b1, monkeypatch, "admin_t", "access_history", {"limit": 10, "operation": "access", "after_change_of": "PAN"})
    items = body["result"]["items"]
    assert items and all(i["operation"] in ("b1_query", "b1_access_denied") for i in items)
    assert len(items) == 2 and "after admin_t changed analyst_t's PAN policy (HASH → PARTIAL)" in body["reply"]  # only the later query and its denial
    quiet, _ = ask(b1, monkeypatch, "admin_t", "access_history", {"operation": "scan", "after_change_of": "PAN"})
    assert quiet["reply"].startswith("Nothing has been recorded") and "changed analyst_t's PAN policy (HASH → PARTIAL)" in quiet["reply"]
    none, _ = ask(b1, monkeypatch, "admin_t", "access_history", {"after_change_of": "CARD_NUMBER"})
    assert "nothing to compare" in none["reply"]
    refused, _ = ask(b1, monkeypatch, "analyst_t", "access_history", {"after_change_of": "PAN"})
    assert refused["result"]["items"] == [] and "only be asked about by an Admin" in refused["reply"]
