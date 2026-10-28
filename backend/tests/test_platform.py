"""Policy management, metrics, filters, structured access, risk scenario, automation visibility."""
import datetime as dt

import pytest
from sqlalchemy import select

from app.database import session as dbsession
from app.database.models import AlertDelivery, AuditEvent, Customer, Policy, SecurityEvent
from tests.conftest import AUTOMATION, login


def H(client, user):
    return login(client, user)


# ---------- policy management ----------
def test_policies_seeded_and_listed_by_role(scanned):
    r = scanned.get("/api/policies/all", headers=H(scanned, "compliance1")).json()
    assert r["items"] and r["can_manage"] is False
    assert {"identifier", "name", "role", "purpose", "category", "strategy", "decision", "enabled", "updated_at"} <= set(r["items"][0])
    assert scanned.get("/api/policies/all", headers=H(scanned, "advisor1")).status_code == 403
    mine = scanned.get("/api/policies", headers=H(scanned, "advisor1")).json()
    assert {p["purpose"] for p in mine["purposes"]} == {"insurance_assessment", "customer_service"}


def _rule(client, role="advisor", purpose="insurance_assessment", category="FINANCIAL"):
    items = client.get("/api/policies/all", headers=H(client, "sec.admin")).json()["items"]
    return next(p for p in items if (p["role"], p["purpose"], p["category"]) == (role, purpose, category))


def test_policy_edit_changes_enforcement_and_is_audited(scanned):
    admin = H(scanned, "sec.admin")
    rule = _rule(scanned)
    sql = "SELECT id, annual_income FROM customers LIMIT 1"

    def row():
        return scanned.post("/api/query", json={"sql": sql, "purpose": "insurance_assessment"}, headers=H(scanned, "advisor1")).json()["rows"][0]

    assert "–" in row()["annual_income"]  # band
    r = scanned.patch(f"/api/policies/{rule['id']}", json={"strategy": "FULL_MASK"}, headers=admin)
    assert r.status_code == 200 and r.json()["strategy"] == "FULL_MASK"
    assert row()["annual_income"] == "********"
    scanned.patch(f"/api/policies/{rule['id']}", json={"enabled": False}, headers=admin)
    denied = scanned.post("/api/query", json={"sql": sql, "purpose": "insurance_assessment"}, headers=H(scanned, "advisor1"))
    assert denied.status_code in (200, 403)
    assert "annual_income" not in (denied.json().get("rows") or [{}])[0]  # disabled rule => default deny
    events = scanned.get("/api/audit?operation=policy_change", headers=H(scanned, "compliance1")).json()
    assert events["total"] >= 2


def test_policy_mutation_requires_admin_and_validates(scanned):
    comp, admin = H(scanned, "compliance1"), H(scanned, "sec.admin")
    rule = _rule(scanned)
    assert scanned.patch(f"/api/policies/{rule['id']}", json={"enabled": False}, headers=comp).status_code == 403
    assert scanned.post("/api/policies", json={"role": "analyst", "purpose": "analytics", "category": "CONTACT", "strategy": "FULL_MASK"}, headers=comp).status_code == 403
    assert scanned.delete(f"/api/policies/{rule['id']}").status_code == 401
    bad = {"role": "analyst", "purpose": "analytics", "category": "GOVERNMENT_ID", "strategy": "ALLOW"}
    assert scanned.post("/api/policies", json=bad, headers=admin).status_code in (409, 422)
    assert scanned.patch(f"/api/policies/{_rule(scanned, 'analyst', 'analytics', 'GOVERNMENT_ID')['id']}", json={"strategy": "ALLOW"}, headers=admin).status_code == 422
    assert scanned.post("/api/policies", json={**bad, "strategy": "NOPE"}, headers=admin).status_code == 422
    assert scanned.post("/api/policies", json={**bad, "role": "root"}, headers=admin).status_code == 422
    dup = {"role": "analyst", "purpose": "analytics", "category": "CONTACT", "strategy": "FULL_MASK"}
    assert scanned.post("/api/policies", json=dup, headers=admin).status_code == 409


def test_policy_create_and_delete(scanned):
    admin = H(scanned, "sec.admin")
    created = scanned.post("/api/policies", json={"role": "analyst", "purpose": "customer_service", "category": "NON_SENSITIVE", "strategy": "ALLOW"}, headers=admin)
    assert created.status_code == 201
    pid = created.json()["id"]
    assert scanned.delete(f"/api/policies/{pid}", headers=admin).json()["deleted"].startswith("POL-")
    assert scanned.delete(f"/api/policies/{pid}", headers=admin).status_code == 404
    with dbsession.session_scope() as db:
        assert db.get(Policy, pid) is None


def test_policy_simulation_uses_synthetic_data_only(scanned):
    r = scanned.post("/api/policies/simulate", json={"role": "advisor", "purpose": "insurance_assessment", "field": "pan"}, headers=H(scanned, "advisor1")).json()
    assert r["synthetic"] is True and r["strategy"] == "DENY" and r["output"] is None
    r = scanned.post("/api/policies/simulate", json={"role": "analyst", "purpose": "analytics", "field": "pan"}, headers=H(scanned, "compliance1")).json()
    assert r["strategy"] == "HASH" and r["output"].startswith("h_") and r["original"] == "ABCDE1234F"
    with dbsession.session_scope() as db:
        assert r["original"] not in {c.pan for c in db.scalars(select(Customer))}  # never a real stored value
    # cannot simulate another role unless an auditor
    assert scanned.post("/api/policies/simulate", json={"role": "analyst", "purpose": "analytics", "field": "pan"}, headers=H(scanned, "advisor1")).status_code == 403
    assert scanned.post("/api/policies/simulate", json={"role": "advisor", "purpose": "insurance_assessment", "field": "nope"}, headers=H(scanned, "advisor1")).status_code == 422


# ---------- scans, sources, field detail ----------
def test_sources_scan_history_and_audit_link(client):
    admin = H(client, "sec.admin")
    src = client.get("/api/sources", headers=admin).json()
    assert src[0]["id"] == "customers" and src[0]["records"] == 8 and src[0]["last_scan"] is None
    scan = client.post("/api/scans", json={"source": "customers"}, headers=admin).json()
    assert scan["status"] == "COMPLETED" and scan["mode"] == "synchronous" and scan["audit_request_id"]
    ev = client.get(f"/api/decisions/{scan['audit_request_id']}", headers=admin).json()
    assert ev["operation"] == "scan" and ev["decision"] == "ALLOW"
    assert client.get("/api/scans", headers=admin).json()[0]["id"] == scan["id"]
    assert client.post("/api/scans", json={"source": "users"}, headers=admin).status_code == 422


def test_field_filters_and_detail(scanned):
    h = H(scanned, "compliance1")
    crit = scanned.get("/api/fields?sensitivity=CRITICAL", headers=h).json()
    assert {f["column"] for f in crit} == {"pan", "account_number"}
    assert [f["column"] for f in scanned.get("/api/fields?category=CONTACT&q=mail", headers=h).json()] == ["email"]
    assert scanned.get("/api/fields?source=nothing", headers=h).json() == []
    pan = next(f for f in crit if f["column"] == "pan")
    scanned.post("/api/query", json={"sql": "SELECT id, pan FROM customers", "purpose": "insurance_assessment"}, headers=H(scanned, "advisor1"))
    d = scanned.get(f"/api/fields/{pan['id']}", headers=h).json()
    assert d["evidence"]["signals"] and {o["strategy"] for o in d["policy_outcomes"]} >= {"DENY", "HASH"}
    assert d["related_audit_events"] and d["scan"]["status"] == "COMPLETED"
    # a non-auditor only sees policy for their own role and no audit trail
    da = scanned.get(f"/api/fields/{pan['id']}", headers=H(scanned, "advisor1")).json()
    assert {o["role"] for o in da["policy_outcomes"]} == {"advisor"} and da["related_audit_events"] == []
    assert scanned.get("/api/fields/9999", headers=h).status_code == 404


# ---------- access: structured requests ----------
def test_access_evaluate_uses_token_role_not_payload(scanned):
    h = H(scanned, "advisor1")
    r = scanned.post("/api/access/evaluate", json={"purpose": "insurance_assessment", "fields": ["id", "pan", "annual_income"], "customer_id": 1, "role": "security_admin"}, headers=h)
    body = r.json()
    assert r.status_code == 200 and body["row_count"] == 1 and "pan" not in body["rows"][0]
    assert body["trace"]["policy"] == "advisor/insurance_assessment"  # extra 'role' key is ignored
    assert scanned.post("/api/access/evaluate", json={"purpose": "analytics", "fields": ["id"]}, headers=h).status_code == 403
    assert scanned.post("/api/access/evaluate", json={"purpose": "insurance_assessment", "fields": ["nope"]}, headers=h).status_code == 422
    assert scanned.post("/api/access/evaluate", json={"purpose": "insurance_assessment", "fields": []}, headers=h).status_code == 422
    assert scanned.post("/api/access/evaluate", json={"purpose": "insurance_assessment", "fields": ["id"]}).status_code == 401
    schema = scanned.get("/api/access/schema", headers=h).json()
    assert schema["purposes"] == ["insurance_assessment", "customer_service"] and len(schema["fields"]) == 14


# ---------- audit filters / pagination ----------
def test_audit_filter_and_pagination(scanned):
    h = H(scanned, "advisor1")
    for _ in range(3):
        scanned.post("/api/access/evaluate", json={"purpose": "insurance_assessment", "fields": ["id"]}, headers=h)
    comp = H(scanned, "compliance1")
    page1 = scanned.get("/api/audit?operation=query&limit=2", headers=comp).json()
    page2 = scanned.get("/api/audit?operation=query&limit=2&offset=2", headers=comp).json()
    assert page1["total"] == 3 and len(page1["events"]) == 2 and len(page2["events"]) == 1
    assert not {e["request_id"] for e in page1["events"]} & {e["request_id"] for e in page2["events"]}
    assert scanned.get("/api/audit?actor=analyst1", headers=comp).json()["total"] == 0
    assert scanned.get("/api/audit?decision=ALLOW&operation=query", headers=comp).json()["total"] == 3
    assert scanned.get("/api/audit?q=advisor1&limit=500", headers=comp).json()["limit"] == 100
    assert scanned.get("/api/audit?q=zzz-no-match", headers=comp).json()["total"] == 0


# ---------- metrics ----------
def test_metrics_reflect_real_events_and_scope(scanned):
    adv = H(scanned, "advisor1")
    scanned.post("/api/access/evaluate", json={"purpose": "insurance_assessment", "fields": ["id", "pan"]}, headers=adv)
    scanned.post("/api/access/evaluate", json={"purpose": "analytics", "fields": ["id"]}, headers=adv)
    m = scanned.get("/api/metrics/overview?days=7", headers=H(scanned, "compliance1")).json()
    assert m["range"]["days"] == 7 and len(m["decisions"]["series"]) == 7 and m["scope"] == "all activity"
    assert m["decisions"]["totals"]["PARTIAL"] == 1 and m["decisions"]["totals"]["DENY"] == 1
    assert m["scans"]["completed"] == 1 and m["fields"]["total"] == 14 and m["fields"]["sensitive"] == 13
    assert m["masking"]["strategies_applied"]["DENY"] >= 1
    mine = scanned.get("/api/metrics/overview", headers=adv).json()
    assert mine["scope"] == "your own activity" and mine["risk"]["available"] is False and mine["automation"]["available"] is False
    # an analyst sees none of the advisor's activity
    other = scanned.get("/api/metrics/overview", headers=H(scanned, "analyst1")).json()
    assert other["decisions"]["events_counted"] == 0
    assert scanned.get("/api/metrics/overview?days=1000", headers=adv).status_code == 422
    assert scanned.get("/api/metrics/overview").status_code == 401


def test_metrics_empty_state_is_zeros_not_fabricated(client):
    m = client.get("/api/metrics/overview?days=3", headers=H(client, "sec.admin")).json()
    assert m["fields"]["total"] == 0 and m["decisions"]["events_counted"] == 0 and m["scans"]["last"] is None
    assert all(p["ALLOW"] == p["DENY"] == p["PARTIAL"] == 0 for p in m["decisions"]["series"])


# ---------- risk ----------
def test_risk_scenario_generates_real_events(scanned):
    assert scanned.post("/api/risk/scenarios/reconstruction", headers=H(scanned, "advisor1")).status_code == 403
    admin = H(scanned, "sec.admin")
    r = scanned.post("/api/risk/scenarios/reconstruction", headers=admin).json()
    assert r["principal"] == "scenario-sec.admin" and [s["outcome"] for s in r["steps"]][:3] == ["ALLOWED"] * 3 and r["steps"][3]["outcome"] == "BLOCKED"
    ev = scanned.get("/api/risk/events?severity=HIGH", headers=admin).json()
    assert ev["total"] >= 1 and ev["items"][0]["actor"] == "scenario-sec.admin"
    assert scanned.get("/api/risk/evaluations", headers=admin).json()["total"] >= 1
    assert scanned.get("/api/risk/events", headers=H(scanned, "analyst1")).status_code == 403
    # the admin's own account is unaffected
    assert scanned.post("/api/access/evaluate", json={"purpose": "security_admin", "fields": ["id"]}, headers=admin).status_code == 200


# ---------- insurance helpers ----------
def test_insurance_config_customers_estimate(scanned):
    adv = H(scanned, "advisor1")
    cfg = scanned.get("/api/insurance/config", headers=adv).json()
    assert cfg["assumptions"]["replacement_years"] == {"default": 10, "min": 1, "max": 30} and "Illustrative" in cfg["disclaimer"]
    cust = scanned.get("/api/insurance/customers", headers=adv).json()
    assert len(cust) == 8 and set(cust[0]) == {"id", "label"}
    good = dict(annual_income=1_000_000, total_liabilities=500_000, dependents=2, age=35, existing_cover=1_000_000, liquid_assets=400_000, education_goal=1_000_000)
    r = scanned.post("/api/insurance/estimate", json={"inputs": good}, headers=adv).json()["result"]
    assert r["recommended_additional_cover"] == 10_700_000 and r["status"] == "additional_cover_indicated"
    none = scanned.post("/api/insurance/estimate", json={"inputs": {**good, "existing_cover": 5e9}}, headers=adv).json()["result"]
    assert none["recommended_additional_cover"] == 0 and none["status"] == "no_additional_cover_indicated"
    for bad in ({**good, "annual_income": -5}, {**good, "extra": 1}, {"annual_income": 1}):
        assert scanned.post("/api/insurance/estimate", json={"inputs": bad}, headers=adv).status_code == 422
    assert scanned.post("/api/insurance/estimate", json={"inputs": good}, headers=H(scanned, "analyst1")).status_code == 403
    assert scanned.get("/api/insurance/customers", headers=H(scanned, "analyst1")).status_code == 403
    with dbsession.session_scope() as db:  # audit holds categories, never the supplied numbers
        assert "1000000" not in " ".join(str(e.fields) + e.reason for e in db.scalars(select(AuditEvent)))


# ---------- automation ----------
def test_automation_workflows_visibility_is_real(client):
    comp = H(client, "compliance1")
    wf = client.get("/api/automation/workflows", headers=comp).json()
    assert [w["key"] for w in wf["workflows"]] == ["scheduled-scan", "security-alerts", "summary-report"]
    assert all(w["last_status"] is None and w["recent_runs"] == [] for w in wf["workflows"])  # nothing fabricated
    assert wf["workflows"][0]["schedule"].startswith("Every")
    client.post("/api/automation/workflow-runs", json={"workflow": "scheduled-scan", "status": "SUCCESS", "detail": "ok"}, headers={**AUTOMATION, "Idempotency-Key": "k1"})
    client.post("/api/automation/workflow-runs", json={"workflow": "scheduled-scan", "status": "FAILED", "attempt": 3, "detail": "boom"}, headers={**AUTOMATION, "Idempotency-Key": "k2"})
    w = client.get("/api/automation/workflows", headers=comp).json()["workflows"][0]
    assert w["last_status"] == "FAILED" and w["success_count"] == 1 and w["failure_count"] == 1 and len(w["recent_runs"]) == 2
    assert client.get("/api/automation/workflows", headers=H(client, "advisor1")).status_code == 403


def test_alert_delivery_idempotent_and_derives_from_stored_event(scanned):
    sql = "SELECT id, {} FROM customers WHERE id = 1"
    for c in ["pan", "account_number", "email", "phone"]:
        scanned.post("/api/query", json={"sql": sql.format(c), "purpose": "insurance_assessment"}, headers=H(scanned, "advisor1"))
    evs = scanned.get("/api/automation/security-events?severity=HIGH", headers=AUTOMATION).json()
    assert evs and all(e["severity"] == "HIGH" for e in evs)
    eid = evs[0]["id"]
    a = scanned.post("/api/automation/alerts", json={"event_id": eid}, headers=AUTOMATION).json()
    b = scanned.post("/api/automation/alerts", json={"event_id": eid}, headers=AUTOMATION).json()
    assert a["duplicate"] is False and b["duplicate"] is True and a["id"] == b["id"]
    with dbsession.session_scope() as db:
        assert len(db.scalars(select(AlertDelivery)).all()) == 1
    assert scanned.post("/api/automation/alerts", json={"event_id": 99999}, headers=AUTOMATION).status_code == 404
    assert scanned.post("/api/automation/alerts", json={"event_id": eid, "channel": "email"}, headers=AUTOMATION).status_code == 422
    assert scanned.post("/api/automation/alerts", json={"event_id": eid}).status_code == 401
    items = scanned.get("/api/alerts", headers=H(scanned, "compliance1")).json()
    assert "not sent" in items["channel_note"] and len(items["items"]) == 1


def test_report_storage_idempotent_and_protected(client):
    now = dt.datetime.now(dt.timezone.utc)
    body = {"period_key": "2026-10-28", "period_start": (now - dt.timedelta(hours=24)).isoformat(), "period_end": now.isoformat(), "report": {"decisions": {"ALLOW": 3}}}
    assert client.post("/api/automation/reports", json=body).status_code == 401
    assert client.post("/api/automation/reports", json=body, headers=AUTOMATION).json()["duplicate"] is False
    assert client.post("/api/automation/reports", json=body, headers=AUTOMATION).json()["duplicate"] is True
    assert client.post("/api/automation/reports", json={**body, "period_key": "big", "report": {"x": "y" * 5000}}, headers=AUTOMATION).status_code == 422
    r = client.get("/api/reports", headers=H(client, "compliance1")).json()
    assert len(r) == 1 and r[0]["report"] == {"decisions": {"ALLOW": 3}}
    assert client.get("/api/reports", headers=H(client, "analyst1")).status_code == 403


def test_summary_period_is_bounded(client):
    assert client.get("/api/automation/summary?hours=0", headers=AUTOMATION).status_code == 422
    assert client.get("/api/automation/summary?hours=9999", headers=AUTOMATION).status_code == 422
    s = client.get("/api/automation/summary?hours=6", headers=AUTOMATION).json()
    assert s["window_hours"] == 6


def test_automation_scan_is_audited_once(client):
    h = {**AUTOMATION, "Idempotency-Key": "scan-audit-1"}
    client.post("/api/automation/scans", headers=h)
    client.post("/api/automation/scans", headers=h)
    with dbsession.session_scope() as db:
        scans = [e for e in db.scalars(select(AuditEvent)) if e.operation == "scan"]
    assert len(scans) == 1 and scans[0].actor == "n8n-automation" and scans[0].role == "automation"


# ---------- settings ----------
def test_settings_expose_no_secrets(client):
    s = client.get("/api/settings", headers=H(client, "advisor1"))
    assert s.status_code == 200
    text = s.text.lower()
    for forbidden in ("secret", "password", "token", "postgres", "test-jwt", "n8n-secret"):
        assert forbidden not in text.replace("n8n_editor_url", "")
    assert client.get("/api/settings").status_code == 401
