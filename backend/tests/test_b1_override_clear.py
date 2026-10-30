"""Clear-override and masking-release guard. Synthetic SQLite fixture and a fake model by default; no Neon, no real model download.
A cleared override goes back through the normal detection path and is never forced to NON_SENSITIVE. A clear that would release masking needs the same
explicit confirmation as setting NON_SENSITIVE. Refusals and actions are audited with names and classifications only, never values."""
import pytest
from sqlalchemy import select

from app.b1 import discover, query as q, targets
from app.core.config import get_settings
from app.database import session as dbsession
from app.database.models import AuditEvent
from app.detection import ml
from tests.conftest import login
from tests.test_b1_ml_supplement import (  # noqa: F401  (fixtures and helpers reused from the supplement tests)
    fake_detect, fake_model, fake_status, run_scan, target,
)

CITY, NOTE, NAME, EMAIL = ("contacts", "city_text"), ("contacts", "approver_note"), ("contacts", "customer_name"), ("contacts", "email_addr")
CLEAR, REVIEW = "/api/b1/fields/clear", "/api/b1/fields"
SAMPLE_VALUES = ("Bengaluru", "Mumbai", "Priya", "Maria Garcia", "priya.s@example.com", "4111 1111 1111 1111")


@pytest.fixture()
def flag_on(monkeypatch):
    """The supplement enabled for the duration of one test (the clear path reads the flag when it runs)."""
    monkeypatch.setenv("B1_ML_SUPPLEMENT", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("B1_ML_SUPPLEMENT", raising=False)
    get_settings.cache_clear()


@pytest.fixture()
def api(client, target, monkeypatch):
    monkeypatch.setattr(targets, "get_target", lambda name: target)
    return client


def set_override(client, column, kind, confirm=False, user="sec.admin"):
    body = {"target": "postgres", "table": "contacts", "column": column, "kind": kind}
    if confirm:
        body["confirm_masking_release"] = True
    return client.patch(REVIEW, json=body, headers=login(client, user))


def clear(client, column, confirm=False, user="sec.admin"):
    body = {"target": "postgres", "table": "contacts", "column": column}
    if confirm:
        body["confirm_masking_release"] = True
    return client.post(CLEAR, json=body, headers=login(client, user))


def fields(target_obj):
    with dbsession.session_scope() as db:
        return {(f["table"], f["column"]): f for f in discover.fields(db, target_obj)}


def audit_reasons(operation="b1_review"):
    with next(dbsession.get_session()) as db:
        return [(e.actor, e.decision, e.reason) for e in db.scalars(select(AuditEvent).where(AuditEvent.operation == operation).order_by(AuditEvent.id))]


def query_as(target_obj, column, role, user):
    with dbsession.session_scope() as db:
        return q.run_query(db, target_obj, q.QuerySpec(target=target_obj.name, table="contacts", columns=[column], limit=5), user, role)


# ---------- ADDRESS and FULL_NAME ----------
def test_clearing_an_address_override_restores_the_supplement_when_enabled(api, target, fake_model, monkeypatch, flag_on):
    run_scan(target, monkeypatch, True)
    assert set_override(api, "city_text", "NON_SENSITIVE", confirm=True).status_code == 200
    r = clear(api, "city_text")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["previous"]["kind"] == "NON_SENSITIVE" and out["previous"]["reviewed"] is True
    assert out["restored"]["kind"] == "ADDRESS" and out["restored"]["status"] == "uncertain" and out["restored"]["methods"] == ["ml_ner"]
    assert out["released"] is False and out["ml_supplement"]["mode"] == "hybrid"
    f = fields(target)[CITY]
    assert f["kind"] == "ADDRESS" and f["status"] == "uncertain" and not f["reviewed"] and "manual_review" not in f["methods"]


def test_clearing_an_address_override_with_the_supplement_disabled_uses_the_original_classifier(api, target, monkeypatch, fake_model):
    run_scan(target, monkeypatch, True)
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
    monkeypatch.setenv("B1_ML_SUPPLEMENT", "false")
    get_settings.cache_clear()
    try:
        out = clear(api, "city_text").json()
    finally:
        monkeypatch.delenv("B1_ML_SUPPLEMENT", raising=False)
        get_settings.cache_clear()
    assert out["restored"]["kind"] == "NON_SENSITIVE" and out["ml_supplement"]["mode"] == "off"
    assert fields(target)[CITY]["kind"] == "NON_SENSITIVE"


def test_clearing_a_full_name_override_restores_the_model_suggestion(api, target, fake_model, monkeypatch, flag_on):
    run_scan(target, monkeypatch, True)
    assert set_override(api, "approver_note", "NON_SENSITIVE", confirm=True).status_code == 200
    out = clear(api, "approver_note").json()
    assert out["restored"]["kind"] == "FULL_NAME" and out["restored"]["status"] == "uncertain" and out["restored"]["methods"] == ["ml_ner"]


# ---------- missing, repeated, rescans ----------
def test_clearing_a_nonexistent_override_is_refused_and_audited_without_change(api, target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    before = fields(target)[CITY]
    r = clear(api, "city_text")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_override"
    assert fields(target)[CITY] == before
    assert any(d == "ALLOW" and "no manual override present" in reason for _, d, reason in audit_reasons())


def test_repeated_clear_is_safe_and_the_second_attempt_changes_nothing(api, target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
    assert clear(api, "city_text").status_code == 200
    after_first = fields(target)[CITY]
    second = clear(api, "city_text")
    assert second.status_code == 409
    assert fields(target)[CITY] == after_first


def test_rescanning_after_a_clear_classifies_the_column_normally(api, target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
    clear(api, "city_text")
    counts, f = run_scan(target, monkeypatch, True)
    assert counts["kept_overrides"] == 0
    assert f[CITY]["kind"] == "ADDRESS" and f[CITY]["status"] == "uncertain" and not f[CITY]["reviewed"]


# ---------- unrelated methods and evidence ----------
def test_clear_keeps_the_legitimate_methods_the_normal_pipeline_gives(api, target, fake_model, monkeypatch):
    _, before = run_scan(target, monkeypatch, True)
    legit = [m for m in before[NAME]["methods"] if m != "ml_ner"]
    set_override(api, "customer_name", "FULL_NAME")
    out = clear(api, "customer_name").json()
    assert set(legit) <= set(out["restored"]["methods"])
    assert "manual_review" not in out["restored"]["methods"]
    assert fields(target)[NAME]["methods"] == out["restored"]["methods"]


def test_clear_writes_the_restored_evidence_not_a_stale_copy(api, target, fake_model, monkeypatch, flag_on):
    run_scan(target, monkeypatch, True)
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
    out = clear(api, "city_text").json()
    f = fields(target)[CITY]
    assert f["confidence"] == out["restored"]["confidence"] and f["methods"] == out["restored"]["methods"]
    assert "reviewer" not in (f["rationale"] or "")


# ---------- masking-release guard ----------
def test_clear_that_releases_masking_needs_confirmation(api, target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    set_override(api, "note", "EMAIL")                                   # reviewer protects a column detection leaves alone
    refused = clear(api, "note")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "release_confirmation_required"
    assert fields(target)[("contacts", "note")]["reviewed"] is True     # nothing changed
    assert any(d == "DENY" and "would release masking without confirmation" in reason for _, d, reason in audit_reasons())
    ok = clear(api, "note", confirm=True)
    assert ok.status_code == 200 and ok.json()["released"] is True
    assert any("MASKING RELEASED for every role" in reason for _, _, reason in audit_reasons())


def test_clearing_a_non_sensitive_override_never_needs_release_confirmation(api, target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
    assert clear(api, "city_text").status_code == 200


def test_setting_non_sensitive_without_confirmation_is_refused_and_audited(api, target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    r = set_override(api, "city_text", "NON_SENSITIVE")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "release_confirmation_required"
    assert fields(target)[CITY]["reviewed"] is False
    assert any(d == "DENY" and "masking release not confirmed" in reason for _, d, reason in audit_reasons())


def test_confirmed_non_sensitive_decision_releases_masking_for_every_role(api, target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    assert query_as(target, "city_text", "Analyst", "analyst1")["columns"][0]["strategy"] == "REDACT"
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
    run_scan(target, monkeypatch, True)
    for role, user in [("Admin", "admin_t"), ("Support", "support_t"), ("Analyst", "analyst1")]:
        assert query_as(target, "city_text", role, user)["columns"][0]["strategy"] == "ALLOW", role
    reasons = [reason for _, d, reason in audit_reasons() if d == "ALLOW" and "city_text set to NON_SENSITIVE" in reason]
    assert reasons and "MASKING RELEASED" in reasons[-1]


# ---------- authorization ----------
@pytest.mark.parametrize("user", ["analyst1", "advisor1", "compliance1"])
def test_non_admin_cannot_clear_and_the_attempt_is_audited(api, target, fake_model, monkeypatch, user):
    run_scan(target, monkeypatch, True)
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
    r = clear(api, "city_text", user=user)
    assert r.status_code == 403
    assert fields(target)[CITY]["reviewed"] is True                   # decision untouched
    assert any(a == user and d == "DENY" and "clear refused" in reason for a, d, reason in audit_reasons())


# ---------- model failure, sampling failure ----------
def test_clear_with_the_model_unavailable_falls_back_to_rules_and_reports_it(api, target, monkeypatch):
    def down(text):
        raise ml.MLUnavailable("model could not be loaded (OSError)")
    monkeypatch.setattr(ml, "detect_ml", down)
    monkeypatch.setattr(ml, "status", fake_status("failed", "model could not be loaded (OSError)"))
    monkeypatch.setenv("B1_ML_SUPPLEMENT", "true")
    get_settings.cache_clear()
    try:
        with dbsession.session_scope() as db:
            discover.scan(db, target, "setup")
        set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
        r = clear(api, "city_text")
    finally:
        monkeypatch.delenv("B1_ML_SUPPLEMENT", raising=False)
        get_settings.cache_clear()
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ml_supplement"]["mode"] == "rules_only" and "OSError" in out["ml_supplement"]["error"]
    assert out["restored"]["kind"] == "NON_SENSITIVE"                 # no model suggestion; the protection is not invented


def test_clear_when_the_table_cannot_be_sampled_reports_name_only_classification(api, target, monkeypatch):
    with dbsession.session_scope() as db:
        discover.scan(db, target, "setup")
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)

    def broken(table, size):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(target, "sample_rows", broken)
    r = clear(api, "city_text")
    assert r.status_code == 200, r.text
    assert r.json()["sampled"] is False


# ---------- audit content ----------
def test_clear_audit_records_previous_and_restored_classification_without_values(api, target, fake_model, monkeypatch, flag_on):
    run_scan(target, monkeypatch, True)
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
    clear(api, "city_text")
    cleared = [reason for _, d, reason in audit_reasons() if "override cleared on contacts.city_text" in reason]
    assert cleared
    reason = cleared[-1]
    assert "previously NON_SENSITIVE (confirmed" in reason and "restored by detection to ADDRESS (uncertain" in reason
    assert "ml_ner" in reason and "sampled=yes" in reason
    everything = " ".join(r for _, _, r in audit_reasons()) + " ".join(r for _, _, r in audit_reasons("b1_scan"))
    assert not any(v in everything for v in SAMPLE_VALUES)


def test_audit_never_contains_sampled_values_for_any_review_path(api, target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    set_override(api, "city_text", "NON_SENSITIVE")                    # refused
    set_override(api, "city_text", "NON_SENSITIVE", confirm=True)
    clear(api, "city_text")
    clear(api, "city_text")                                              # no override now
    clear(api, "city_text", user="analyst1")                             # refused
    blob = " ".join(r for _, _, r in audit_reasons())
    assert not any(v in blob for v in SAMPLE_VALUES)
    assert len(audit_reasons()) >= 5
