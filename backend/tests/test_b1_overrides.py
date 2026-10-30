"""Manual overrides in database discovery, with the ML supplement on and off. Synthetic SQLite fixture only; the model is a fake unless RUN_ML_TESTS=1.
A reviewer's decision must stay authoritative across rescans, flag changes and model failures; must drop only the superseded ML method; must never make a
model suggestion look model-confirmed; and must be audited without values. Masking is checked per role after each operation."""
from sqlalchemy import select

from app.b1 import discover, query as q, targets
from app.database import session as dbsession
from app.database.models import AuditEvent, B1FieldTag
from app.detection import ml
from tests.conftest import login
from tests.test_b1_ml_supplement import (  # noqa: F401  (fixtures and helpers reused from the supplement tests)
    fake_detect, fake_model, fake_status, run_scan, target,
)

CITY, NOTE, NAME = ("contacts", "city_text"), ("contacts", "approver_note"), ("contacts", "customer_name")


def review(target_obj, table, column, kind, reviewer="reviewer_a"):
    with dbsession.session_scope() as db:
        return discover.override(db, target_obj, table, column, kind, reviewer)


def query_as(target_obj, column, user_role, table="contacts"):
    with dbsession.session_scope() as db:
        return q.run_query(db, target_obj, q.QuerySpec(target=target_obj.name, table=table, columns=[column], limit=5), "tester", user_role)


# ---------- 1-2: overriding ML-supplemented columns ----------
def test_override_of_ml_address_is_authoritative_across_rescans(target, fake_model, monkeypatch):
    _, on = run_scan(target, monkeypatch, True)
    assert on[CITY]["kind"] == "ADDRESS" and on[CITY]["status"] == "uncertain" and on[CITY]["methods"] == ["ml_ner"]
    review(target, "contacts", "city_text", "NON_SENSITIVE")
    for _ in range(2):
        counts, f = run_scan(target, monkeypatch, True)
        assert counts["kept_overrides"] >= 1
        assert f[CITY]["kind"] == "NON_SENSITIVE" and f[CITY]["reviewed"] and f[CITY]["status"] == "confirmed"
        assert f[CITY]["methods"] == ["manual_review"]  # superseded ml_ner removed; no ML method left on a reviewed field


def test_override_of_ml_full_name_is_authoritative(target, fake_model, monkeypatch):
    _, on = run_scan(target, monkeypatch, True)
    assert on[NOTE]["kind"] == "FULL_NAME" and on[NOTE]["status"] == "uncertain"
    review(target, "contacts", "approver_note", "NON_SENSITIVE")
    _, f = run_scan(target, monkeypatch, True)
    assert f[NOTE]["kind"] == "NON_SENSITIVE" and f[NOTE]["reviewed"] and "ml_ner" not in f[NOTE]["methods"]


def test_agreeing_with_the_model_is_recorded_as_a_review_not_a_model_detection(target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    review(target, "contacts", "city_text", "ADDRESS")
    _, f = run_scan(target, monkeypatch, True)
    assert f[CITY]["status"] == "confirmed" and f[CITY]["reviewed"]
    assert f[CITY]["methods"] == ["manual_review"]
    assert "ml_ner" not in f[CITY]["methods"]


# ---------- 3: multiple detection methods ----------
def test_override_keeps_legitimate_methods_and_drops_only_ml(target, fake_model, monkeypatch):
    _, before = run_scan(target, monkeypatch, True)
    legit = [m for m in before[NAME]["methods"] if m != "ml_ner"]
    assert legit, before[NAME]["methods"]
    review(target, "contacts", "customer_name", "FULL_NAME")
    _, after = run_scan(target, monkeypatch, True)
    assert set(legit) <= set(after[NAME]["methods"])
    assert "manual_review" in after[NAME]["methods"] and "ml_ner" not in after[NAME]["methods"]


def test_override_on_a_row_with_rule_and_ml_methods_keeps_the_rule(target, monkeypatch):
    """A row that carries a rule method and a superseded ML method (the state rows were left in before the fix) keeps the rule and drops only ML."""
    monkeypatch.setattr(ml, "detect_ml", fake_detect)
    run_scan(target, monkeypatch, False)
    with dbsession.session_scope() as db:
        row = db.scalar(select(B1FieldTag).where(B1FieldTag.target == target.name, B1FieldTag.table_name == "contacts", B1FieldTag.column_name == "email_addr"))
        row.methods = ["value_pattern", "ml_ner", "column_name"]
        db.commit()
    review(target, "contacts", "email_addr", "EMAIL")
    with dbsession.session_scope() as db:
        got = next(f for f in discover.fields(db, target, "contacts") if f["column"] == "email_addr")["methods"]
    assert got == ["column_name", "manual_review", "value_pattern"]


# ---------- 4-6: repeated rescans, changing a decision, clearing ----------
def test_repeated_rescans_after_override_are_stable(target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    review(target, "contacts", "city_text", "NON_SENSITIVE")
    seen = set()
    for _ in range(4):
        counts, f = run_scan(target, monkeypatch, True)
        seen.add((counts["kept_overrides"], f[CITY]["kind"], f[CITY]["status"], tuple(f[CITY]["methods"])))
    assert len(seen) == 1 and next(iter(seen))[0] >= 1


def test_changing_an_existing_override_replaces_the_decision_and_reviewer(target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    review(target, "contacts", "city_text", "NON_SENSITIVE", reviewer="reviewer_a")
    review(target, "contacts", "city_text", "ADDRESS", reviewer="reviewer_b")
    _, f = run_scan(target, monkeypatch, True)
    assert f[CITY]["kind"] == "ADDRESS" and f[CITY]["reviewed_by"] == "reviewer_b" and f[CITY]["reviewed"]


def test_no_endpoint_clears_an_override(client):
    """Clearing is not supported. A reviewed column can be re-classified but never returned to automatic detection (documented limitation)."""
    methods_by_path: dict[str, set] = {}
    for r in client.app.routes:
        if getattr(r, "path", "").startswith("/api/b1/"):
            methods_by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()) or set())
    assert "PATCH" in methods_by_path["/api/b1/fields"]
    assert not any("DELETE" in m for p, m in methods_by_path.items() if "field" in p)


# ---------- 7-8: flag off and model failure must not erase decisions ----------
def test_flag_off_does_not_erase_manual_decisions(target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    review(target, "contacts", "city_text", "NON_SENSITIVE")
    counts, f = run_scan(target, monkeypatch, False)
    assert counts["kept_overrides"] >= 1 and counts["ml_supplement"]["mode"] == "off"
    assert f[CITY]["kind"] == "NON_SENSITIVE" and f[CITY]["reviewed"]


def test_model_failure_does_not_change_manual_decisions(target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    review(target, "contacts", "city_text", "NON_SENSITIVE")
    review(target, "contacts", "approver_note", "FULL_NAME")

    def down(text):
        raise ml.MLUnavailable("model could not be loaded (OSError)")
    monkeypatch.setattr(ml, "detect_ml", down)
    monkeypatch.setattr(ml, "status", fake_status("failed", "model could not be loaded (OSError)"))
    counts, f = run_scan(target, monkeypatch, True)
    assert counts["ml_supplement"]["mode"] == "rules_only"
    assert f[CITY]["kind"] == "NON_SENSITIVE" and f[CITY]["reviewed"]
    assert f[NOTE]["kind"] == "FULL_NAME" and f[NOTE]["reviewed"]


# ---------- 9: audit ----------
def test_override_and_denied_override_are_audited_without_values(client, target, fake_model, monkeypatch):
    monkeypatch.setattr(targets, "get_target", lambda name: target)
    run_scan(target, monkeypatch, True)
    unconfirmed = client.patch("/api/b1/fields", json={"target": target.name, "table": "contacts", "column": "city_text", "kind": "NON_SENSITIVE"}, headers=login(client, "sec.admin"))
    assert unconfirmed.status_code == 409 and unconfirmed.json()["detail"]["code"] == "release_confirmation_required"
    ok = client.patch("/api/b1/fields", json={"target": target.name, "table": "contacts", "column": "city_text", "kind": "NON_SENSITIVE", "confirm_masking_release": True},
                      headers=login(client, "sec.admin"))
    assert ok.status_code == 200, ok.text
    denied = client.patch("/api/b1/fields", json={"target": target.name, "table": "contacts", "column": "city_text", "kind": "NON_SENSITIVE"}, headers=login(client, "analyst1"))
    assert denied.status_code == 403
    with next(dbsession.get_session()) as db:
        rows = list(db.scalars(select(AuditEvent).where(AuditEvent.operation == "b1_review").order_by(AuditEvent.id)))
    allowed = [e for e in rows if e.decision == "ALLOW"]
    refused = [e for e in rows if e.decision == "DENY"]
    assert allowed and allowed[-1].actor == "sec.admin" and "contacts.city_text set to NON_SENSITIVE" in allowed[-1].reason and "MASKING RELEASED" in allowed[-1].reason
    assert any(e.decision == "DENY" and "masking release not confirmed" in e.reason for e in rows)
    assert refused and refused[-1].actor == "analyst1" and "city_text" in refused[-1].reason
    blob = " ".join(e.reason for e in rows)
    assert "Bengaluru" not in blob and "Priya" not in blob and "example.com" not in blob


# ---------- masking and authorization after each override ----------
def test_masking_follows_each_override_per_role(target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    assert query_as(target, "city_text", "Analyst")["columns"][0]["strategy"] == "REDACT"   # supplemented ADDRESS: masked while under review
    review(target, "contacts", "city_text", "NON_SENSITIVE")
    run_scan(target, monkeypatch, True)
    analyst = query_as(target, "city_text", "Analyst")
    assert analyst["columns"][0]["strategy"] == "ALLOW"                # a reviewer's NON_SENSITIVE decision releases the column (Admin-only action)
    assert query_as(target, "city_text", "Support")["columns"][0]["strategy"] == "ALLOW"
    review(target, "contacts", "city_text", "CARD_NUMBER")             # re-classifying as sensitive re-applies masking
    run_scan(target, monkeypatch, True)
    analyst2 = query_as(target, "city_text", "Analyst")
    raw = query_as(target, "city_text", "Admin")
    assert analyst2["columns"][0]["strategy"] != "ALLOW"
    assert all(a["city_text"] != r["city_text"] for a, r in zip(analyst2["rows"], raw["rows"]) if r["city_text"] is not None)


def test_only_admins_can_override_and_masking_is_unaffected_by_refusal(client, target, fake_model, monkeypatch):
    monkeypatch.setattr(targets, "get_target", lambda name: target)
    run_scan(target, monkeypatch, True)
    before = query_as(target, "note", "Analyst")["columns"][0]["strategy"]
    for user in ("analyst1", "advisor1", "compliance1"):
        r = client.patch("/api/b1/fields", json={"target": target.name, "table": "contacts", "column": "note", "kind": "NON_SENSITIVE"}, headers=login(client, user))
        assert r.status_code == 403, user
    assert query_as(target, "note", "Analyst")["columns"][0]["strategy"] == before
