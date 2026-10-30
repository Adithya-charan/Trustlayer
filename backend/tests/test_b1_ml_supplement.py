"""Database discovery with the hybrid detector as a supplement. Synthetic SQLite only; the model is replaced by a fake unless RUN_ML_TESTS=1.
Covers: flag off = original behaviour, flag on = uncertain supplement only, model failure fallback, card validation, overrides, masking and audit."""
import os
import re

import pytest

from app.b1 import discover, query as q, supplement, targets
from app.b1.detect import Detection, TAG_OF, classify_column
from app.core.config import get_settings
from app.database import session as dbsession
from app.database.models import AuditEvent, B1FieldTag
from app.detection import ml
from app.detection.rules import Span
from sqlalchemy import select
from tests.b1_fixture import fixture_target
from tests.conftest import login
from tests.discovery_db_fixture import build

CITIES = ("Bengaluru", "Mumbai", "Madrid", "London", "Chennai", "Pune")
NAME_RX = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")


def fake_detect(text):
    out = [Span(m.start(), m.end(), "PERSON", "ml", "model", 0.9) for m in NAME_RX.finditer(text)]
    out += [Span(m.start(), m.end(), "ORGANIZATION", "ml", "model", 0.9) for m in re.finditer(r"\b(Infosys|Initech|Globex|Acme)\b", text)]
    out += [Span(m.start(), m.end(), "LOCATION", "ml", "model", 0.9) for m in re.finditer(r"\b(%s)\b" % "|".join(CITIES), text)]
    return out


def fake_status(state="ready", error=None):
    return lambda: {"enabled": True, "model": "fake", "state": state, "error": error, "load_seconds": 0, "categories": [], "threshold": 0.5}


@pytest.fixture(autouse=True)
def _reset():
    ml.reset()
    yield
    ml.reset()


@pytest.fixture()
def target(client, tmp_path, monkeypatch):  # `client` creates the application tables in the isolated test database
    path = tmp_path / "contacts.db"
    build(path)
    t = fixture_target(path)
    monkeypatch.setattr(targets, "_pg_target", lambda: t)
    targets.reset()
    yield t
    targets.reset()


@pytest.fixture()
def fake_model(monkeypatch):
    monkeypatch.setattr(ml, "detect_ml", fake_detect)
    monkeypatch.setattr(ml, "status", fake_status())


def run_scan(target, monkeypatch, on: bool):
    previous = os.environ.get("B1_ML_SUPPLEMENT")  # only the flag is touched: other patches made by the test stay in force
    monkeypatch.setenv("B1_ML_SUPPLEMENT", "true" if on else "false")
    get_settings.cache_clear()
    try:
        with dbsession.session_scope() as db:
            counts = discover.scan(db, target, "scan_test")
            fields = {(f["table"], f["column"]): f for f in discover.fields(db, target)}
        return counts, fields
    finally:
        if previous is None:
            monkeypatch.delenv("B1_ML_SUPPLEMENT", raising=False)
        else:
            monkeypatch.setenv("B1_ML_SUPPLEMENT", previous)
        get_settings.cache_clear()


# ---------- mapping rules (unit) ----------
def test_supplement_maps_person_to_fullname_uncertain_only(monkeypatch):
    monkeypatch.setattr(ml, "detect_ml", fake_detect)
    d, did = supplement.apply(Detection(), ["Approved by Priya Sharma", "Escalated to Maria Garcia, Madrid", "Chen Wei sent it"], 40)
    assert did and d.kind == "FULL_NAME" and d.tag == TAG_OF["FULL_NAME"]
    assert d.status == "uncertain" and d.methods == ["ml_ner"] and 0.5 <= d.confidence < 0.8


def test_location_maps_to_address_and_organisation_is_not_stored(monkeypatch):
    monkeypatch.setattr(ml, "detect_ml", fake_detect)
    d, did = supplement.apply(Detection(), ["Bengaluru", "Mumbai", "Madrid", "London"], 40)
    assert did and d.kind == "ADDRESS" and d.status == "uncertain"
    d2, did2 = supplement.apply(Detection(), ["Infosys", "Initech", "Globex", "Acme"], 40)
    assert not did2 and d2.kind == "NON_SENSITIVE" and d2.status == "none"


def test_tied_categories_are_ambiguous_and_decide_nothing(monkeypatch):
    monkeypatch.setattr(ml, "detect_ml", fake_detect)
    d, did = supplement.apply(Detection(), ["Priya Sharma, Pune", "Maria Garcia, Madrid"], 40)  # two PERSON and two LOCATION hits
    assert not did and d.status == "none"


def test_short_codes_and_single_word_names_are_not_mapped(monkeypatch):
    monkeypatch.setattr(ml, "detect_ml", fake_detect)
    codes = ["DR", "CR", "DR", "CR", "DR"]                       # 2-character codes: never considered
    d, did = supplement.apply(Detection(), codes, 40)
    assert not did and d.status == "none"
    relations = ["Spouse", "Mother", "Father", "Son", "Daughter"]  # single words: a PERSON reading needs two-word names
    monkeypatch.setattr(ml, "detect_ml", lambda text: [Span(0, len(text), "PERSON", "ml", "model", 0.9)])
    d2, did2 = supplement.apply(Detection(), relations, 40)
    assert not did2 and d2.status == "none"


def test_one_stray_match_does_not_decide_a_column(monkeypatch):
    monkeypatch.setattr(ml, "detect_ml", fake_detect)
    vals = ["Bengaluru"] + [f"ticket {i} open" for i in range(9)]
    d, did = supplement.apply(Detection(), vals, 40)
    assert not did and d.status == "none"


def test_empty_null_and_numeric_values_are_ignored(monkeypatch):
    monkeypatch.setattr(ml, "detect_ml", fake_detect)
    d, did = supplement.apply(Detection(), [None, "", "   ", 42, "12.50"], 40)
    assert not did and d.status == "none"


def test_only_original_unclassified_text_columns_are_eligible():
    none = Detection()
    assert supplement.eligible("contacts", "VARCHAR(40)", none)
    assert not supplement.eligible("contacts", "INTEGER", none)
    assert not supplement.eligible("branches", "VARCHAR(40)", none)
    assert not supplement.eligible("contacts", "VARCHAR(40)", Detection(status="confirmed", kind="EMAIL"))
    assert not supplement.eligible("contacts", "VARCHAR(40)", Detection(status="uncertain", kind="FULL_NAME"))


# ---------- end-to-end scan ----------
def test_flag_off_is_the_original_classifier(target, fake_model, monkeypatch):
    counts, fields = run_scan(target, monkeypatch, False)
    assert counts["ml_supplement"] == {"enabled": False, "mode": "off", "error": None, "columns_checked": 0, "supplemented": 0}
    assert all("ml_ner" not in f["methods"] for f in fields.values())
    # each stored result equals a direct run of the original classifier on the same rows
    rows = list(target.sample_rows(target.tables()["contacts"], 200))
    for idx, col in enumerate(target.tables()["contacts"].columns):
        vals = [r[idx] for r in rows if r[idx] is not None]
        expect = classify_column("contacts", col.name, str(col.type), vals)
        got = fields[("contacts", col.name)]
        assert (got["kind"], got["status"]) == (expect.kind, expect.status), col.name


def test_flag_on_supplements_person_and_location_as_uncertain_only(target, fake_model, monkeypatch):
    _, off = run_scan(target, monkeypatch, False)
    counts, on = run_scan(target, monkeypatch, True)
    assert counts["ml_supplement"]["mode"] == "hybrid" and counts["ml_supplement"]["supplemented"] >= 2
    city, note = on[("contacts", "city_text")], on[("contacts", "approver_note")]
    assert city["kind"] == "ADDRESS" and city["status"] == "uncertain" and city["methods"] == ["ml_ner"]
    assert note["kind"] == "FULL_NAME" and note["status"] == "uncertain"
    # ORGANIZATION-only column stays as the original classifier left it
    assert on[("contacts", "employer_text")]["kind"] == off[("contacts", "employer_text")]["kind"]
    # every column the original classifier decided is unchanged
    for key, f in off.items():
        if f["status"] != "none":
            assert (on[key]["kind"], on[key]["status"]) == (f["kind"], f["status"]), key
    assert all(f["status"] != "confirmed" or "ml_ner" not in f["methods"] for f in on.values())


def test_card_validation_is_unchanged_by_the_model(target, fake_model, monkeypatch):
    _, off = run_scan(target, monkeypatch, False)
    _, on = run_scan(target, monkeypatch, True)
    assert on[("contacts", "card_text")] == off[("contacts", "card_text")]
    assert on[("contacts", "card_text")]["kind"] == "CARD_NUMBER"  # one Luhn-valid value in a column of mixed values


def test_model_unavailable_keeps_original_results_and_discovery_succeeds(target, monkeypatch):
    def down(text):
        raise ml.MLUnavailable("model could not be loaded (OSError)")
    monkeypatch.setattr(ml, "detect_ml", down)
    monkeypatch.setattr(ml, "status", fake_status("failed", "model could not be loaded (OSError)"))
    _, off = run_scan(target, monkeypatch, False)
    counts, on = run_scan(target, monkeypatch, True)
    assert counts["ml_supplement"]["mode"] == "rules_only" and "OSError" in counts["ml_supplement"]["error"]
    assert counts["ml_supplement"]["supplemented"] == 0
    assert {k: (v["kind"], v["status"]) for k, v in on.items()} == {k: (v["kind"], v["status"]) for k, v in off.items()}


def test_unexpected_model_error_affects_only_that_column(target, monkeypatch):
    calls = {"n": 0}

    def flaky(text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the failing text 4111 1111 1111 1111 must not be echoed")
        return fake_detect(text)
    monkeypatch.setattr(ml, "detect_ml", flaky)
    monkeypatch.setattr(ml, "status", fake_status())
    counts, fields = run_scan(target, monkeypatch, True)
    assert counts["tables"] == 1 and counts["columns"] == 10              # discovery completed
    assert "4111" not in str(counts)                                        # the error text is not carried into the result
    assert counts["ml_supplement"]["error"] is None or "RuntimeError" in counts["ml_supplement"]["error"]


def test_manual_override_is_authoritative_on_rescan(target, fake_model, monkeypatch):
    with dbsession.session_scope() as db:
        discover.override(db, target, "contacts", "city_text", "NON_SENSITIVE", "reviewer_x")
    counts, on = run_scan(target, monkeypatch, True)
    assert counts["kept_overrides"] >= 1
    f = on[("contacts", "city_text")]
    assert f["reviewed"] and f["kind"] == "NON_SENSITIVE" and "ml_ner" not in f["methods"]


def test_supplemented_column_is_masked_for_non_admin_and_raw_for_admin(target, fake_model, monkeypatch):
    run_scan(target, monkeypatch, True)
    with dbsession.session_scope() as db:
        admin = q.run_query(db, target, q.QuerySpec(target=target.name, table="contacts", columns=["city_text"], limit=3), "admin_t", "Admin")
        analyst = q.run_query(db, target, q.QuerySpec(target=target.name, table="contacts", columns=["city_text"], limit=3), "analyst_t", "Analyst")
    assert admin["rows"][0]["city_text"] == "Bengaluru"
    assert analyst["rows"][0]["city_text"] != "Bengaluru"


def test_scan_endpoint_audits_the_mode_without_values(client, target, fake_model, monkeypatch):
    monkeypatch.setattr(targets, "get_target", lambda name: target)
    monkeypatch.setenv("B1_ML_SUPPLEMENT", "true")
    get_settings.cache_clear()
    try:
        r = client.post("/api/b1/scan", json={"target": target.name}, headers=login(client, "sec.admin"))
        assert r.status_code == 200, r.text
        assert r.json()["ml_supplement"]["mode"] == "hybrid"
        with next(dbsession.get_session()) as db:
            ev = db.scalars(select(AuditEvent).where(AuditEvent.operation == "b1_scan").order_by(AuditEvent.id.desc())).first()
        assert "ML supplement hybrid" in ev.reason
        assert "Priya" not in ev.reason and "Bengaluru" not in ev.reason and "example.com" not in ev.reason
    finally:
        monkeypatch.delenv("B1_ML_SUPPLEMENT", raising=False)
        get_settings.cache_clear()


@pytest.mark.skipif(os.environ.get("RUN_ML_TESTS") != "1", reason="loads the real GLiNER checkpoint; set RUN_ML_TESTS=1")
def test_real_model_supplements_the_synthetic_sqlite(target, monkeypatch):
    ml.reset()
    counts, on = run_scan(target, monkeypatch, True)
    assert counts["ml_supplement"]["mode"] == "hybrid"
    assert on[("contacts", "city_text")]["kind"] == "ADDRESS" and on[("contacts", "city_text")]["status"] == "uncertain"


def test_overview_counts_follow_the_supplement_consistently(target, fake_model, monkeypatch):
    from app.b1 import overview
    _, off = run_scan(target, monkeypatch, False)
    _, on = run_scan(target, monkeypatch, True)
    supplemented = [k for k, f in on.items() if "ml_ner" in f["methods"]]
    assert supplemented
    with dbsession.session_scope() as db:
        overview.clear_cache()
        after = overview.build(db, target)
    overview.clear_cache()
    with dbsession.session_scope() as db:
        before_rows = [f for f in off.values()]
        # Overview counts every stored non-NON_SENSITIVE row as sensitive and every uncertain, non-reviewed row as needing review.
        expect_sensitive = sum(1 for f in on.values() if f["tag"] != "NON_SENSITIVE")
        expect_review = sum(1 for f in on.values() if f["status"] == "uncertain" and not f["reviewed"])
    assert after["discovery"]["sensitive_fields"] == expect_sensitive
    assert after["discovery"]["needs_review"] == expect_review
    assert expect_sensitive == sum(1 for f in before_rows if f["tag"] != "NON_SENSITIVE") + len(supplemented)


def test_review_removes_the_model_method_from_a_supplemented_field(target, fake_model, monkeypatch):
    """A reviewer's decision replaces an earlier ML suggestion: the field must not keep the 'ml_ner' detection source."""
    _, on = run_scan(target, monkeypatch, True)
    assert "ml_ner" in on[("contacts", "city_text")]["methods"]
    with dbsession.session_scope() as db:
        discover.override(db, target, "contacts", "city_text", "NON_SENSITIVE", "reviewer_x")
    _, after = run_scan(target, monkeypatch, True)
    f = after[("contacts", "city_text")]
    assert f["reviewed"] and f["status"] == "confirmed" and f["kind"] == "NON_SENSITIVE"
    assert "ml_ner" not in f["methods"] and "manual_review" in f["methods"]
