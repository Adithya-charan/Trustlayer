import datetime as dt

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.database import session as dbsession
from app.database.models import AuditEvent, Customer
from app.insurance import calculator
from app.masking.strategies import apply_strategy
from app.policies import engine as pe
from app.policies.sql_gateway import UnsupportedQuery, parse_query
from app.scanner.pii_detector import detect_field
from tests.conftest import AUTOMATION, login


# ---------- config / startup ----------
def test_health_and_config(client):
    r = client.get("/api/health").json()
    assert r["status"] == "ok" and r["config_ok"] is True
    assert "postgres" not in str(r).lower() and "password" not in str(r).lower()


def test_config_validation_flags_missing_secrets():
    s = Settings(_env_file=None, database_url="", jwt_secret="", n8n_shared_secret="")
    assert len(s.config_problems()) == 3


def test_neon_url_driver_normalised_and_not_in_repr():
    s = Settings(_env_file=None, database_url="postgresql://u:secretpw@h/db?sslmode=require", jwt_secret="x" * 20)
    assert s.database_url.startswith("postgresql+psycopg://")
    assert "x" * 20 not in repr(s)


def test_db_failure_is_safe(monkeypatch):
    dbsession.init_engine("sqlite:////nonexistent_dir/x/y.db")
    st = dbsession.db_status()
    assert st == {"connected": False, "error": "database unreachable"}


# ---------- discovery ----------
def test_detection_heuristics():
    assert detect_field("pan", "VARCHAR(16)", ["ABCDE1234F", "QWERT9876Z"], use_presidio=False).category == "GOVERNMENT_ID"
    assert detect_field("email", "VARCHAR", ["a@b.test"], use_presidio=False).category == "CONTACT"
    assert detect_field("annual_income", "FLOAT", [1.0], use_presidio=False).category == "FINANCIAL"
    assert detect_field("foo", "VARCHAR", ["123456789012"], use_presidio=False).category == "ACCOUNT_IDENTIFIER"
    assert detect_field("created_flag", "INTEGER", [1], use_presidio=False).category == "NON_SENSITIVE"


def test_scan_classifies_and_review_override(scanned):
    h = login(scanned, "sec.admin")
    fields = {f["column"]: f for f in scanned.get("/api/fields", headers=h).json()}
    assert fields["pan"]["category"] == "GOVERNMENT_ID" and fields["pan"]["sensitivity"] == "CRITICAL"
    assert fields["full_name"]["category"] == "DIRECT_IDENTIFIER"
    assert fields["annual_income"]["category"] == "FINANCIAL"
    assert fields["id"]["category"] == "NON_SENSITIVE"
    assert all("ABCDE" not in str(f["rationale"]) for f in fields.values())
    r = scanned.patch(f"/api/fields/{fields['city']['id']}", json={"category": "CONTACT"}, headers=h)
    assert r.json()["category"] == "CONTACT" and r.json()["overridden"] is True
    scanned.post("/api/scans", headers=h)  # rescan keeps the human correction
    again = {f["column"]: f for f in scanned.get("/api/fields", headers=h).json()}
    assert again["city"]["category"] == "CONTACT"


def test_scan_requires_admin(client):
    assert client.post("/api/scans").status_code == 401
    assert client.post("/api/scans", headers=login(client, "advisor1")).status_code == 403


# ---------- masking ----------
def test_masking_strategies():
    assert apply_strategy("FULL_MASK", "ABCDE1234F") == "********"
    assert apply_strategy("PARTIAL_MASK", "ABCDE1234F") == "XXXXXX234F"
    assert apply_strategy("PARTIAL_MASK", "asha.rao@bank.test", "CONTACT") == "a***@bank.test"
    assert apply_strategy("PARTIAL_MASK", "Asha Rao", "DIRECT_IDENTIFIER") == "A*** R***"
    assert apply_strategy("PARTIAL_MASK", 900000.0) == "500,000–1,000,000"
    assert apply_strategy("PARTIAL_MASK", dt.date(1990, 5, 6)) == "1990"
    assert apply_strategy("REDACT", "x") == "[REDACTED]"
    h1, h2 = apply_strategy("HASH", "ABCDE1234F"), apply_strategy("HASH", "ABCDE1234F")
    assert h1 == h2 and h1.startswith("h_") and "ABCDE" not in h1


# ---------- policy ----------
def test_policy_outcomes():
    f = {"pan": "GOVERNMENT_ID", "annual_income": "FINANCIAL", "id": "NON_SENSITIVE"}
    d = pe.evaluate("advisor", "insurance_assessment", f)
    assert d.plan["pan"]["strategy"] == "DENY" and d.plan["annual_income"]["strategy"] == "PARTIAL_MASK" and d.decision == "PARTIAL"
    assert pe.evaluate("analyst", "analytics", f).plan["pan"]["strategy"] == "HASH"
    assert pe.evaluate("analyst", "insurance_assessment", f).decision == "DENY"  # unlisted pair
    assert pe.evaluate("advisor", "insurance_assessment", {"pan": "GOVERNMENT_ID"}).decision == "DENY"
    el = pe.evaluate("advisor", "insurance_assessment", f, elevated=True)
    assert el.plan["annual_income"]["strategy"] == "FULL_MASK" and el.plan["id"]["strategy"] == "ALLOW"
    assert pe.evaluate("advisor", "insurance_assessment", f) == pe.evaluate("advisor", "insurance_assessment", f)


# ---------- query gateway ----------
def q(client, user, sql, purpose):
    return client.post("/api/query", json={"sql": sql, "purpose": purpose}, headers=login(client, user))


def test_query_masks_response_and_preserves_originals(scanned):
    with dbsession.session_scope() as db:
        before = db.execute(select(Customer.pan, Customer.annual_income).order_by(Customer.id)).all()
    r = q(scanned, "advisor1", "SELECT id, full_name, pan, annual_income FROM customers LIMIT 3", "insurance_assessment")
    assert r.status_code == 200
    body = r.json()
    row = body["rows"][0]
    assert "pan" not in row and body["trace"]["denied_fields"] == ["pan"]
    assert row["full_name"] == "[REDACTED]" and "–" in row["annual_income"]
    with dbsession.session_scope() as db:
        assert db.execute(select(Customer.pan, Customer.annual_income).order_by(Customer.id)).all() == before


def test_query_unauthorized_and_wrong_purpose(scanned):
    assert scanned.post("/api/query", json={"sql": "SELECT id FROM customers", "purpose": "analytics"}).status_code == 401
    assert q(scanned, "advisor1", "SELECT id FROM customers", "analytics").status_code == 403


@pytest.mark.parametrize("sql", [
    "SELECT * FROM customers; DROP TABLE customers",
    "SELECT id FROM customers -- x",
    "DELETE FROM customers",
    "SELECT id FROM customers c JOIN users u ON c.id=u.id",
    "SELECT id FROM (SELECT id FROM customers) t",
    "SELECT id FROM customers UNION SELECT id FROM customers",
    "SELECT upper(full_name) FROM customers",
    "SELECT pan AS id FROM customers",
    "SELECT id FROM users",
    "SELECT id FROM customers WHERE id = 1 OR id = 2",
    "WITH a AS (SELECT 1) SELECT id FROM customers",
    "SELECT id FROM customers GROUP BY id",
])
def test_unsupported_sql_rejected(scanned, sql):
    with pytest.raises(UnsupportedQuery):
        parse_query(sql)
    assert q(scanned, "sec.admin", sql, "security_admin").status_code == 400


def test_sql_injection_in_literal_is_parameterized(scanned):
    r = q(scanned, "analyst1", "SELECT id FROM customers WHERE id = '1 OR 1=1' LIMIT 5", "analytics")
    assert r.status_code == 400  # literal is bound as a typed parameter, never concatenated into SQL
    r = q(scanned, "analyst1", "SELECT id FROM customers WHERE id = 1 LIMIT 5", "analytics")
    assert r.status_code == 200 and r.json()["row_count"] == 1


def test_filter_on_protected_column_blocked(scanned):
    r = q(scanned, "advisor1", "SELECT id FROM customers WHERE annual_income > 1000000", "insurance_assessment")
    assert r.status_code == 403  # would let a user bisect a value that is only shown as a band


def test_filter_on_denied_column_blocked(scanned):
    r = q(scanned, "advisor1", "SELECT id FROM customers WHERE pan = 'ABCDE1234F'", "insurance_assessment")
    assert r.status_code == 403


def test_limit_capped(scanned):
    assert q(scanned, "analyst1", "SELECT id FROM customers LIMIT 1000", "analytics").json()["row_count"] <= 50


# ---------- risk ----------
def test_risk_escalates_then_blocks_and_is_deterministic(scanned):
    probes = ["pan", "account_number", "email", "phone", "pan, email", "full_name, pan"]
    codes = [q(scanned, "advisor1", f"SELECT id, {c} FROM customers WHERE id = 1", "insurance_assessment").status_code for c in probes]
    assert codes[:3] == [200, 200, 200]  # a few weak signals are not treated as malicious
    assert codes[3] == 429 and set(codes[3:]) == {429}  # probing one record with varying fields is blocked
    h = login(scanned, "compliance1")
    ev = scanned.get("/api/security-events", headers=h).json()
    assert ev and {e["rule"] for e in ev} & {"REPEATED_RESTRICTED_ACCESS", "RECONSTRUCTION_PATTERN"}
    # another user is unaffected (no false positive across actors)
    assert q(scanned, "analyst1", "SELECT id FROM customers LIMIT 2", "analytics").status_code == 200


def test_normal_usage_not_flagged(scanned):
    for _ in range(10):
        assert q(scanned, "analyst1", "SELECT id, city FROM customers LIMIT 5", "analytics").status_code == 200
    assert scanned.get("/api/security-events", headers=login(scanned, "sec.admin")).json() == []


# ---------- audit ----------
def test_audit_has_no_raw_pii_and_is_protected(scanned):
    with dbsession.session_scope() as db:
        pan, email = db.scalar(select(Customer.pan)), db.scalar(select(Customer.email))
    q(scanned, "advisor1", f"SELECT id FROM customers WHERE city = '{pan}'", "insurance_assessment")
    q(scanned, "advisor1", "SELECT id, pan, full_name FROM customers", "insurance_assessment")
    with dbsession.session_scope() as db:
        dump = " ".join(str((e.fields, e.reason, e.risk_signals, e.subject_ref)) for e in db.scalars(select(AuditEvent)))
    assert pan not in dump and email not in dump
    assert scanned.get("/api/audit", headers=login(scanned, "advisor1")).status_code == 403
    r = scanned.get("/api/audit", headers=login(scanned, "compliance1"))
    assert r.status_code == 200 and r.json()["events"]


def test_decision_trace_access_control(scanned):
    r = q(scanned, "advisor1", "SELECT id FROM customers", "insurance_assessment").json()
    rid = r["trace"]["request_id"]
    assert scanned.get(f"/api/decisions/{rid}", headers=login(scanned, "advisor1")).status_code == 200
    assert scanned.get(f"/api/decisions/{rid}", headers=login(scanned, "analyst1")).status_code == 403
    assert scanned.get(f"/api/decisions/{rid}", headers=login(scanned, "compliance1")).status_code == 200


# ---------- insurance ----------
GOOD = dict(annual_income=1_000_000, total_liabilities=500_000, dependents=2, age=35, existing_cover=1_000_000, liquid_assets=400_000, education_goal=1_000_000)


def test_calculator_formula():
    r = calculator.assess(GOOD)
    # 1,000,000*10 + 500,000 + 1,000,000 + 2*200,000 = 11,900,000 ; offsets = 1,000,000 + 0.5*400,000 = 1,200,000
    assert r["recommended_additional_cover"] == 10_700_000 and r["illustrative"] is True
    assert calculator.assess({**GOOD, "existing_cover": 99_000_000})["recommended_additional_cover"] == 0


@pytest.mark.parametrize("bad", [
    {**GOOD, "annual_income": -1}, {**GOOD, "age": 10}, {**GOOD, "dependents": 0},
    {k: v for k, v in GOOD.items() if k != "age"}, {**GOOD, "name": "leak"},
])
def test_calculator_rejects_bad_input(bad):
    with pytest.raises(calculator.InputError):
        calculator.assess(bad)


def test_assessment_payload_is_minimized(scanned, monkeypatch):
    seen = {}
    real = calculator.assess
    monkeypatch.setattr(calculator, "assess", lambda p, a=None: seen.update(p) or real(p, a))
    r = scanned.post("/api/insurance/assess", json={"customer_id": 1}, headers=login(scanned, "advisor1"))
    assert r.status_code == 200, r.text
    assert set(seen) == {"annual_income", "total_liabilities", "dependents", "age", "existing_cover", "liquid_assets", "education_goal"}
    ex = r.json()["minimization"]["attributes_excluded"]
    assert {"full_name", "pan", "account_number", "email", "phone", "id", "city"} <= set(ex) and "date_of_birth" not in ex
    assert "full_name" not in str(r.json()["result"]) and "pan" not in r.json()["result"]


def test_assessment_authz_and_errors(scanned):
    assert scanned.post("/api/insurance/assess", json={"customer_id": 1}).status_code == 401
    assert scanned.post("/api/insurance/assess", json={"customer_id": 1}, headers=login(scanned, "analyst1")).status_code == 403
    h = login(scanned, "advisor1")
    assert scanned.post("/api/insurance/assess", json={"customer_id": 9999}, headers=h).status_code == 404
    assert scanned.post("/api/insurance/assess", json={"customer_id": 1, "assumptions": {"replacement_years": 500}}, headers=h).status_code == 422
    assert scanned.post("/api/insurance/assess", json={"customer_id": "x"}, headers=h).status_code == 422


def test_assessment_requires_scan(client):
    assert client.post("/api/insurance/assess", json={"customer_id": 1}, headers=login(client, "advisor1")).status_code == 403


# ---------- automation / n8n ----------
def test_automation_unauthorized(client):
    assert client.post("/api/automation/scans").status_code == 401
    assert client.post("/api/automation/scans", headers={"X-TrustLayer-Automation-Key": "wrong"}).status_code == 401
    assert client.get("/api/automation/summary").status_code == 401
    assert client.post("/api/automation/workflow-runs", json={"workflow": "w", "status": "SUCCESS"}).status_code == 401


def test_automation_scan_idempotent(client):
    h = {**AUTOMATION, "Idempotency-Key": "scan-2026-01-01"}
    a = client.post("/api/automation/scans", headers=h).json()
    b = client.post("/api/automation/scans", headers=h).json()
    assert a["status"] == "COMPLETED" and a["id"] == b["id"]


def test_automation_failure_reporting_and_dedupe(client):
    h = {**AUTOMATION, "Idempotency-Key": "run-1"}
    body = {"workflow": "scheduled-scan", "status": "FAILED", "attempt": 3, "detail": "gave up after 3 attempts"}
    assert client.post("/api/automation/workflow-runs", json=body, headers=h).json()["duplicate"] is False
    assert client.post("/api/automation/workflow-runs", json=body, headers=h).json()["duplicate"] is True
    assert client.post("/api/automation/workflow-runs", json={**body, "attempt": 99}, headers=AUTOMATION).status_code == 422
    d = client.get("/api/dashboard", headers=login(client, "compliance1")).json()
    assert d["workflows"][0]["status"] == "FAILED"


def test_automation_payloads_are_minimized(scanned):
    q(scanned, "advisor1", "SELECT id, pan FROM customers", "insurance_assessment")
    s = scanned.get("/api/automation/summary", headers=AUTOMATION).json()
    assert set(s) == {"window_hours", "period_start", "period_end", "decisions", "operations", "security_events", "scans", "sensitive_fields", "generated_at"}  # aggregates only


def test_core_works_without_n8n(scanned):
    assert q(scanned, "analyst1", "SELECT id FROM customers LIMIT 1", "analytics").status_code == 200


# ---------- errors ----------
def test_validation_error_does_not_echo_values(client):
    r = client.post("/api/auth/login", json={"username": "a", "password": 12345})
    assert r.status_code == 422 and "12345" not in r.text


def test_login_rejects_bad_password_and_rate_limits(client):
    for _ in range(10):
        assert client.post("/api/auth/login", json={"username": "advisor1", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "advisor1", "password": "nope"}).status_code == 429
