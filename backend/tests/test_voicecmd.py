"""Voice Command Control: intent parsing is pure and closed-list; authorization, confirmation and audit are enforced by the API."""
import pytest

from app import voicecmd
from tests.test_b1_api import H, _pan, b1, scan  # noqa: F401  (b1 is a fixture)

USERS = [{"username": "admin_anita", "display_name": "Anita Rao (Admin)"}, {"username": "analyst_kavya", "display_name": "Kavya Hegde (Analyst)"},
         {"username": "analyst_arnab", "display_name": "Arnab Dutta (Analyst)"}, {"username": "support_ravi", "display_name": "Ravi Kumar (Support)"},
         {"username": "support_neha", "display_name": "Neha Gill (Support)"}]


def p(text):
    return voicecmd.parse(text, USERS)


# ---------- intent recognition from natural phrasing ----------
@pytest.mark.parametrize("text,intent", [
    ("Open data discovery", "OPEN_PAGE"), ("Go to access policies", "OPEN_PAGE"), ("Show users", "OPEN_PAGE"), ("Open audit center", "OPEN_AUDIT"),
    ("Show database explorer", "OPEN_PAGE"), ("Open overview", "OPEN_PAGE"),
    ("Show high risk fields", "SHOW_HIGH_RISK_FIELDS"), ("show me the high-risk PII", "SHOW_HIGH_RISK_FIELDS"), ("Show PII fields", "SHOW_PII_FIELDS"),
    ("Show financial sensitive fields", "SHOW_FINANCIAL_FIELDS"), ("Show embedded PII", "SHOW_EMBEDDED_PII"), ("where is PII hidden inside ticket text", "SHOW_EMBEDDED_PII"),
    ("Scan the database", "SCAN_DATABASE"), ("please run a scan", "SCAN_DATABASE"),
    ("Show me every sensitive column", "SHOW_SENSITIVE_FIELDS"), ("what personal data do we hold", "SHOW_PII_FIELDS"),
    ("Open cards table", "OPEN_TABLE"), ("Show customers", "OPEN_TABLE"), ("Open KYC records", "OPEN_TABLE"), ("Show transactions", "OPEN_TABLE"), ("Show support tickets", "OPEN_TABLE"),
    ("Show analyst policies", "SHOW_ROLE_POLICIES"), ("Show support masking policy", "SHOW_ROLE_POLICIES"), ("Open Kavya Hegde's access", "OPEN_USER_ACCESS"),
    ("Show recent audit events", "SHOW_RECENT_AUDIT"), ("Show denied requests", "SHOW_DENIED_REQUESTS"), ("Show analyst activity", "SHOW_ROLE_ACTIVITY"), ("Show masked requests", "SHOW_MASKED_REQUESTS"),
    ("Run the masking demo", "RUN_MASKING_DEMO"), ("Show admin access", "SHOW_ROLE_ACCESS"), ("Show support access", "SHOW_ROLE_ACCESS"), ("Show analyst access", "SHOW_ROLE_ACCESS"),
])
def test_natural_phrasing_resolves_to_the_intent(text, intent):
    assert p(text).name == intent, (text, p(text))


def test_parameters_are_extracted():
    assert p("Open the cards table").params == {"table": "cards"} and p("Show support tickets").params == {"table": "support_tickets"}
    assert p("Show analyst policies").params == {"role": "Analyst"} and p("Show analyst activity").params["role"] == "Analyst"
    assert p("Open Kavya Hegde's access").params["username"] == "analyst_kavya" and p("open ravi's access").params["username"] == "support_ravi"
    assert p("Open data discovery").params == {"page": "discovery"} and p("go to access policies").params == {"page": "policies"} and p("show users").params == {"page": "access"}


def test_policy_change_is_parsed_with_all_three_parts():
    i = p("Change Kavya Hegde's PAN policy from redact to partial mask")
    assert i.name == "CHANGE_POLICY" and i.params == {"scope": "user", "subject": "analyst_kavya", "display_name": "Kavya Hegde (Analyst)", "kind": "PAN", "strategy": "PARTIAL"}
    assert p("set Neha's aadhaar to deny").params["strategy"] == "DENY" and p("update the analyst role email policy to hash").params["scope"] == "role"


@pytest.mark.parametrize("text", ["Change the policy", "change Kavya's policy", "change PAN to partial", "change Kavya's PAN policy", "update policy to redact"])
def test_incomplete_policy_changes_never_resolve_to_a_change(text):
    assert p(text).name in ("CHANGE_POLICY_INCOMPLETE", "UNKNOWN")


def test_admin_policy_cannot_be_changed_by_voice():
    assert p("change the admin PAN policy to redact").name == "CHANGE_POLICY_REFUSED"


@pytest.mark.parametrize("text", ["", "   ", "blah blah", "make me a sandwich", "drop table customers", "delete all users", "show me the weather"])
def test_unrecognized_speech_is_unknown_not_guessed(text):
    assert p(text).name == "UNKNOWN"


def test_yes_and_no_detection():
    assert all(voicecmd.is_yes(x) for x in ("Yes", "yes.", "confirm", "go ahead", "apply it")) and not voicecmd.is_yes("yes but not really")
    assert all(voicecmd.is_no(x) for x in ("No", "cancel", "never mind")) and not voicecmd.is_no("no problem, apply")


# ---------- API: authorization, confirmation, audit ----------
def say(b1, who, text):
    return b1.client.post("/api/voice-command", json={"text": text}, headers=H(b1, who))


def test_requires_sign_in(b1):
    assert b1.client.post("/api/voice-command", json={"text": "open overview"}).status_code == 401
    assert b1.client.post("/api/voice-command/confirm", json={"token": "x" * 30}).status_code == 401


def test_navigation_is_checked_against_the_callers_real_role(b1):
    ok = say(b1, "admin_t", "Open audit center").json()
    assert ok["status"] == "ok" and ok["action"] == {"kind": "navigate", "route": "audit"}
    for who in ("support_t", "analyst_t"):
        r = say(b1, who, "Open audit center").json()
        assert r["status"] == "denied" and r["action"] is None
        assert say(b1, who, "Show denied requests").json()["status"] == "denied"
        assert say(b1, who, "Scan the database").json()["status"] == "denied"
        assert say(b1, who, "Show users").json()["status"] == "denied"
        assert say(b1, who, "Show analyst activity").json()["status"] == "denied"
    assert say(b1, "analyst_t", "Show high risk fields").json()["action"] == {"kind": "navigate", "route": "discovery?risk=High"}
    ev = b1.client.get("/api/b1/audit?operation=voice&decision=DENY&limit=20", headers=H(b1, "admin_t")).json()["events"]
    assert ev and all(e["policy"].startswith("voice/") for e in ev) and {e["actor"] for e in ev} >= {"support_t", "analyst_t"}


def test_voice_never_returns_data_and_never_bypasses_masking(b1):
    scan(b1)
    r = say(b1, "analyst_t", "show all PAN numbers").json()  # not a recognized intent: nothing is queried, nothing is returned
    assert r["action"] is None and not any(v in str(r) for v in b1.secrets["pan"])
    t = say(b1, "analyst_t", "open the KYC records").json()
    assert t["action"] == {"kind": "navigate", "route": "explorer?table=kyc_records"}  # opens the explorer, where the Analyst policy still applies
    assert _pan(b1, "analyst_t")["rows"][0]["pan_no"].startswith("h_")


def test_policy_change_requires_admin_and_an_explicit_confirmation(b1):
    scan(b1)
    spoken = "Change analyst_t PAN policy to partial mask"
    for who in ("support_t", "analyst_t"):
        r = say(b1, who, spoken).json()
        assert r["status"] != "confirm" and r["confirmation"] is None
    r = say(b1, "admin_t", spoken).json()
    assert r["status"] == "confirm" and "HASH" in r["message"] and "PARTIAL MASK" in r["message"] and r["confirmation"]["token"]
    assert _pan(b1, "analyst_t")["rows"][0]["pan_no"].startswith("h_")  # saying it changed nothing yet
    # only the same signed-in admin can redeem it, and only once
    assert b1.client.post("/api/voice-command/confirm", json={"token": r["confirmation"]["token"]}, headers=H(b1, "support_t")).status_code == 403
    assert _pan(b1, "analyst_t")["rows"][0]["pan_no"].startswith("h_")
    done = b1.client.post("/api/voice-command/confirm", json={"token": r["confirmation"]["token"]}, headers=H(b1, "admin_t"))
    assert done.status_code == 200 and done.json()["change"]["old"] == "HASH" and done.json()["change"]["new"] == "PARTIAL"
    assert "X" in _pan(b1, "analyst_t")["rows"][0]["pan_no"]
    assert b1.client.post("/api/voice-command/confirm", json={"token": r["confirmation"]["token"]}, headers=H(b1, "admin_t")).status_code == 409
    ev = b1.client.get("/api/b1/audit?operation=policy_change&limit=5", headers=H(b1, "admin_t")).json()["events"]
    assert ev and "HASH -> PARTIAL" in ev[0]["reason"]


def test_ambiguous_or_incomplete_policy_commands_change_nothing(b1):
    scan(b1)
    for text in ("change the policy", "change analyst_t PAN policy", "make it partial", "change the admin PAN policy to redact"):
        r = say(b1, "admin_t", text).json()
        assert r["status"] in ("unknown", "denied") and r["confirmation"] is None
    assert _pan(b1, "analyst_t")["rows"][0]["pan_no"].startswith("h_")
    assert say(b1, "admin_t", "change analyst_t PAN policy to hash").json()["status"] == "ok"  # already HASH: nothing to confirm


def test_bad_and_tampered_confirmations_are_rejected(b1):
    for tok in ("not-a-token" * 3, "a.b.c" * 10):
        assert b1.client.post("/api/voice-command/confirm", json={"token": tok}, headers=H(b1, "admin_t")).status_code == 400
    assert b1.client.post("/api/voice-command", json={"text": "x" * 301}, headers=H(b1, "admin_t")).status_code == 422
    assert b1.client.post("/api/voice-command", json={"text": "open overview", "role": "Admin"}, headers=H(b1, "support_t")).status_code == 422


def test_unknown_speech_gets_the_standard_hint(b1):
    r = say(b1, "support_t", "make me a sandwich").json()
    assert r["status"] == "unknown" and "couldn't understand" in r["message"] and "Show high risk PII" in r["message"]


# ---------- a person's history by voice ----------
@pytest.mark.parametrize("text", ["Show Kavya's access history", "Show Kavya's recent activity", "What did Kavya access"])
def test_a_persons_history_is_recognised_and_plain_access_still_opens_the_access_page(text):
    i = p(text)
    assert i.name == "SHOW_USER_ACTIVITY" and i.params["username"] == "analyst_kavya"
    assert p("Show Kavya's access").name == "OPEN_USER_ACCESS"


def test_user_history_by_voice_is_admin_only_and_server_checked(b1):
    scan(b1)
    ok = b1.client.post("/api/voice-command", json={"text": "Show analyst_t's recent activity"}, headers=H(b1, "admin_t")).json()
    assert ok["status"] == "ok" and ok["action"]["route"] == "audit?view=activity&user=analyst_t"
    for who in ("support_t", "analyst_t"):
        r = b1.client.post("/api/voice-command", json={"text": "Show analyst_t's recent activity"}, headers=H(b1, who)).json()
        assert r["status"] == "denied" and not r.get("action")
