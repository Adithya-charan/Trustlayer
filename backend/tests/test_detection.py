"""Hybrid detection: rules, merge, ML fallback, risk, CSV intake, upload API, assistant dataset answers and evaluation maths.
The real GLiNER model is never loaded here (slow, needs a download): a fake stands in. Synthetic data only."""
import json
import os

import pytest

from app.assistant import service
from app.core.config import get_settings
from app.detection import engine, eval_data, evaluation, hybrid, ml, qa, risk, store
from app.detection.csvio import CSVError, parse_csv
from app.detection.rules import Span, column_name_category, detect_rules
from tests.conftest import login
from tests.test_assistant import FakeClient, call

CSV = "name,email,phone,card_no,notes\nPriya Sharma,a@example.com,+1 415-555-0132,4111 1111 1111 1111,ok\nRahul Verma,b@example.org,98765 43210,,call a@example.com\n"


def cats(text):
    return [(text[s.start:s.end], s.category) for s in detect_rules(text)]


@pytest.fixture(autouse=True)
def _reset():
    ml.reset()
    store.clear()
    yield
    ml.reset()


@pytest.fixture()
def fake_ml(monkeypatch):
    """A stand-in model: tags capitalised 'First Last' as PERSON with a fixed score."""
    import re

    def detect(text):
        return [Span(m.start(), m.end(), "PERSON", "ml", "model", 0.9) for m in re.finditer(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", text)]
    monkeypatch.setattr(ml, "detect_ml", detect)
    monkeypatch.setattr(ml, "status", lambda: {"enabled": True, "model": "fake", "state": "ready", "error": None, "load_seconds": 0, "categories": ["PERSON"], "threshold": 0.5})
    return detect


# ---------- rules ----------
def test_email_valid_and_invalid():
    assert cats("mail a.b+c@mail.example.co.uk now") == [("a.b+c@mail.example.co.uk", "EMAIL")]
    assert cats("john.doe@ is broken") == []


def test_phone_formats_and_non_phones():
    assert cats("call +1 415-555-0132") == [("+1 415-555-0132", "PHONE")]
    assert cats("call 98765 43210") == [("98765 43210", "PHONE")]
    assert cats("order 12345 on 2024-01-15") == []


def test_card_requires_luhn():
    assert cats("4111 1111 1111 1111") == [("4111 1111 1111 1111", "CARD_NUMBER")]
    assert cats("4111 1111 1111 1112") == []


def test_card_beats_phone_shaped_digits():
    assert [c for _, c in cats("pay 4111111111111111")] == ["CARD_NUMBER"]


def test_ipv4_range_checked():
    assert cats("host 192.168.1.10 down") == [("192.168.1.10", "IP_ADDRESS")]
    assert cats("host 300.1.1.1 down") == []


@pytest.mark.parametrize("v", [None, "", "   ", 42, ["a@b.co"]])
def test_unexpected_inputs_do_not_crash(v):
    assert detect_rules(v) == []


def test_column_name_heuristic_is_only_a_hint():
    assert column_name_category("customer_email")[0] == "EMAIL"
    assert column_name_category("salary")[0] == "FINANCIAL"
    assert column_name_category("quantity") is None


# ---------- merge ----------
def test_ml_inside_rule_span_is_suppressed():
    rule = [Span(8, 30, "EMAIL", "rule", "pattern")]
    ml_span = [Span(8, 20, "PERSON", "ml", "model", 0.99)]
    found, dropped = hybrid.merge(rule, ml_span)
    assert [f.category for f in found] == ["EMAIL"] and len(dropped) == 1


def test_overlapping_ml_spans_keep_one_and_nothing_double_counts():
    a, b = Span(0, 5, "PERSON", "ml", "model", 0.9), Span(0, 12, "PERSON", "ml", "model", 0.8)
    found, dropped = hybrid.merge([], [a, b])
    assert len(found) == 1 and (found[0].start, found[0].end) == (0, 12) and len(dropped) == 1


def test_disjoint_findings_all_kept_with_sources():
    found, _ = hybrid.merge([Span(0, 5, "EMAIL", "rule", "pattern")], [Span(10, 15, "PERSON", "ml", "model", 0.7)])
    assert [(f.category, f.sources) for f in found] == [("EMAIL", ("rule",)), ("PERSON", ("ml",))]


# ---------- ML availability ----------
def test_missing_model_falls_back_to_rules_and_says_so(monkeypatch):
    monkeypatch.setattr(get_settings(), "detection_ml_model", "does/not-exist", raising=False)
    monkeypatch.setattr(ml, "_load", lambda: (_ for _ in ()).throw(ml.MLUnavailable("model could not be loaded (OSError)")))
    errs: list = []
    fs = engine.detect_text("Priya Sharma wrote to a@example.com", ml_error=errs)
    assert [f.category for f in fs] == ["EMAIL"] and errs == ["model could not be loaded (OSError)"]
    res = engine.analyze(["n"], [["Priya Sharma"]])
    assert res["ml"]["mode"] == "rules_only" and res["ml"]["error"]


def test_fail_policy_raises(monkeypatch):
    monkeypatch.setenv("DETECTION_ML_FALLBACK", "fail")
    get_settings.cache_clear()
    monkeypatch.setattr(ml, "_load", lambda: (_ for _ in ()).throw(ml.MLUnavailable("down")))
    try:
        with pytest.raises(ml.MLUnavailable):
            engine.detect_text("Priya Sharma")
    finally:
        monkeypatch.delenv("DETECTION_ML_FALLBACK")
        get_settings.cache_clear()


def test_inference_error_is_reported_without_input(monkeypatch):
    class Boom:
        def predict_entities(self, *a, **k):
            raise RuntimeError("secret input 4111111111111111")
    monkeypatch.setattr(ml, "_load", lambda: Boom())
    with pytest.raises(ml.MLUnavailable) as e:
        ml.detect_ml("some text")
    assert "4111" not in str(e.value) and "RuntimeError" in str(e.value)


def test_disabled_model_is_reported(monkeypatch):
    monkeypatch.setenv("DETECTION_ML_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert ml.available() is False and ml.status()["state"] == "disabled"
    finally:
        monkeypatch.delenv("DETECTION_ML_ENABLED")
        get_settings.cache_clear()


# ---------- hybrid / column analysis ----------
def test_hybrid_adds_ml_categories_and_counts_exactly(fake_ml):
    cols, rows, _ = parse_csv(CSV.encode())
    res = engine.analyze(cols, rows)
    by = {c["column"]: c for c in res["columns"]}
    assert res["ml"]["mode"] == "hybrid"
    assert by["name"]["category"] == "PERSON" and by["name"]["match_count"] == 2 and "ml" in by["name"]["sources"]
    assert by["email"]["match_count"] == 2 and by["email"]["status"] == "detected"
    assert res["summary"]["by_category"]["EMAIL"]["value_matches"] == 3  # 2 in `email` + 1 embedded in `notes`
    assert by["notes"]["status"] == "suspected" and by["notes"]["needs_review"]


def test_rule_only_mode_cannot_see_names_so_it_says_unclassified(fake_ml):
    cols, rows, _ = parse_csv(CSV.encode())
    res = engine.analyze(cols, rows, use_ml=False)
    name = next(c for c in res["columns"] if c["column"] == "name")
    assert res["ml"]["mode"] == "rules_only" and name["status"] == "unclassified" and name["sources"] == []


def test_unmatched_column_is_unclassified_not_safe():
    res = engine.analyze(["quantity"], [["1"], ["2"]], use_ml=False)
    c = res["columns"][0]
    assert c["status"] == "unclassified" and c["risk"] == "Unclassified" and "not prove" in c["evidence"]


def test_nulls_empty_and_duplicates():
    res = engine.analyze(["email"], [["a@example.com"], ["a@example.com"], [None], [""]], use_ml=False)
    c = res["columns"][0]
    assert c["values_inspected"] == 2 and c["null_count"] == 2 and c["match_count"] == 2
    assert engine.analyze(["email"], [], use_ml=False)["columns"][0]["status"] == "suspected"


def test_no_cell_values_in_the_result(fake_ml):
    cols, rows, _ = parse_csv(CSV.encode())
    blob = json.dumps(engine.analyze(cols, rows))
    for secret in ("a@example.com", "4111 1111 1111 1111", "Priya", "98765"):
        assert secret not in blob


# ---------- risk ----------
def test_risk_is_deterministic_and_not_driven_by_confidence():
    a = risk.assess("CARD_NUMBER", 0.9, True)
    assert a["level"] == "Critical" and risk.assess("CARD_NUMBER", 0.9, True) == a
    assert risk.assess("EMAIL", 0.9, True)["level"] == "Medium"
    assert risk.assess("ORGANIZATION", 0.9, True)["level"] == "Medium" and risk.assess("ORGANIZATION", 0.1, True)["level"] == "Low"
    assert risk.assess("CARD_NUMBER", 0.9, False)["level"] == "Medium"      # suspected -> capped
    assert risk.assess("EMAIL", 0.9, True, protected=True)["level"] == "Low"
    assert "base sensitivity" in a["explanation"]
    assert risk.assess(None, 0, False)["level"] == "Unclassified"


# ---------- CSV intake ----------
@pytest.mark.parametrize("raw,msg", [(b"", "empty"), (b"a,a\n1,2\n", "Duplicate"), (b"a,\n1,2\n", "blank column"), (b"\xff\xfe\x00a", "binary"), (b"caf\xe9,b\n1,2\n", "UTF-8")])
def test_csv_rejections(raw, msg):
    with pytest.raises(CSVError, match=msg):
        parse_csv(raw)


def test_csv_malformed_rows_counted_and_size_limit(monkeypatch):
    _, rows, info = parse_csv(b"a,b\n1,2\n3\n\n4,5\n")
    assert info["malformed_rows"] == 1 and info["blank_rows"] == 1 and len(rows) == 3
    monkeypatch.setenv("UPLOAD_MAX_BYTES", "10")
    get_settings.cache_clear()
    try:
        with pytest.raises(CSVError, match="larger"):
            parse_csv(b"a,b\n" + b"1,2\n" * 10)
    finally:
        monkeypatch.delenv("UPLOAD_MAX_BYTES")
        get_settings.cache_clear()


# ---------- upload API + authorization ----------
def up(client, h, body=CSV, name="people.csv", ctype="text/csv", use_ml=True):
    return client.post(f"/api/b1/upload/analyze?filename={name}&use_ml={str(use_ml).lower()}", content=body, headers={**h, "Content-Type": ctype})


def test_upload_requires_auth_and_scan_role(client):
    assert client.post("/api/b1/upload/analyze", content=CSV, headers={"Content-Type": "text/csv"}).status_code == 401
    assert up(client, login(client, "analyst1")).status_code == 403


def test_upload_analyzes_and_audits_without_values(client, fake_ml):
    h = login(client, "sec.admin")
    r = up(client, h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ml"]["mode"] == "hybrid" and body["input"]["rows"] == 2
    assert "Priya" not in r.text and "a@example.com" not in r.text
    ev = client.get("/api/risk/events", headers=h)
    assert ev.status_code == 200


def test_upload_validation_errors(client):
    h = login(client, "sec.admin")
    assert up(client, h, body="").status_code == 422
    assert up(client, h, name="x.exe").status_code == 415
    assert up(client, h, ctype="application/json").status_code == 415
    assert up(client, h, body="a,a\n1,2\n").json()["detail"]["code"] == "invalid_csv"


def test_upload_size_limit_413(client, monkeypatch):
    monkeypatch.setenv("UPLOAD_MAX_BYTES", "50")
    get_settings.cache_clear()
    try:
        assert up(client, login(client, "sec.admin"), body="a,b\n" + "1,2\n" * 50).status_code == 413
    finally:
        monkeypatch.delenv("UPLOAD_MAX_BYTES")
        get_settings.cache_clear()


def test_upload_rule_only_when_model_down(client, monkeypatch):
    monkeypatch.setattr(ml, "_load", lambda: (_ for _ in ()).throw(ml.MLUnavailable("model could not be loaded (OSError)")))
    r = up(client, login(client, "sec.admin"))
    assert r.status_code == 200 and r.json()["ml"]["mode"] == "rules_only" and r.json()["ml"]["error"]


# ---------- assistant: exact counts from backend ----------
@pytest.fixture()
def ask(client, monkeypatch, fake_ml):
    def go(who, **args):
        fake = FakeClient(tool_calls=[call("ask_about_dataset", args)], content="I count 9999 of them.")  # a model-invented number must not surface
        monkeypatch.setattr(service, "get_llm_client", lambda: fake)
        return client.post("/api/assistant/chat", json={"message": "q", "page": "discovery"}, headers=login(client, who))
    return go


def test_assistant_answers_exact_count_from_findings(client, ask):
    up(client, login(client, "sec.admin"))
    r = ask("sec.admin", question="count_category", category="email")
    assert r.status_code == 200
    body = r.json()
    assert "3" in body["reply"] and "9999" not in body["reply"] and body["result"]["facts"]["exact"] is True
    assert "people.csv" in body["result"]["facts"]["scope"]


def test_assistant_without_dataset_and_unknown_category(client, ask):
    assert "Upload a CSV" in ask("sec.admin", question="summary").json()["reply"]
    up(client, login(client, "sec.admin"))
    assert "not a category" in ask("sec.admin", question="count_category", category="blood type").json()["reply"]


def test_assistant_dataset_tool_denied_to_restricted_role_and_other_users(client, ask):
    up(client, login(client, "sec.admin"))
    r = ask("analyst1", question="summary")
    assert r.json().get("refused") is True or "not permitted" in r.json()["reply"]


def test_store_is_per_owner():
    aid = store.put("alice", "a.csv", {"x": 1})
    assert store.get("alice", aid) and store.get("bob", aid) is None and store.get("bob") is None


def test_qa_exact_vs_estimate_flag():
    item = {"name": "d.csv", "result": {"summary": {"rows": 10, "columns": 1, "by_category": {"PERSON": {"value_matches": 4, "exact": False}}}, "columns": [{"column": "n", "categories": {"PERSON": {}}}]}}
    assert qa.count_category(item, "people")["exact"] is False and "Estimate" in qa.count_category(item, "people")["note"]


# ---------- evaluation maths ----------
def test_prf_and_zero_denominators():
    assert evaluation.prf(0, 0, 0) == {"tp": 0, "fp": 0, "fn": 0, "precision": None, "recall": None, "f1": None}
    m = evaluation.prf(8, 2, 8)
    assert (m["precision"], m["recall"], m["f1"]) == (0.8, 0.5, 0.6154)
    assert evaluation.prf(0, 3, 0)["f1"] is None or evaluation.prf(0, 3, 0)["f1"] == 0.0


def test_aggregate_micro_macro():
    per = {"A": evaluation.prf(1, 0, 0), "B": evaluation.prf(0, 0, 1)}
    agg = evaluation.aggregate(per)
    assert agg["micro"]["tp"] == 1 and agg["micro"]["fn"] == 1 and agg["macro"]["recall"] == 0.5


def test_exact_span_vs_overlap_matching():
    per = {"EMAIL": {"tp": 0, "fp": 0, "fn": 0}}
    evaluation._count({(0, 10, "EMAIL")}, {(0, 8, "EMAIL")}, {"EMAIL"}, per)
    assert per["EMAIL"] == {"tp": 0, "fp": 1, "fn": 1}
    per2 = {"EMAIL": {"tp": 0, "fp": 0, "fn": 0}}
    evaluation._count({(0, 10, "EMAIL")}, {(0, 8, "EMAIL")}, {"EMAIL"}, per2, overlap=True)
    assert per2["EMAIL"]["tp"] == 1


def test_dataset_markup_parses_to_exact_spans():
    text, spans = eval_data.parse("Mail [[EMAIL|a@b.co]] now")
    assert text == "Mail a@b.co now" and spans == [(5, 11, "EMAIL")] and eval_data.parse(None) == ("", [])
    for split in ("dev", "held"):
        for t, sp in eval_data.text_items(split):
            assert all(0 <= s < e <= len(t) for s, e, _ in sp)


def test_rules_only_evaluation_is_reproducible_and_covers_rule_categories():
    cfg = evaluation.CONFIGS["rules_only"]
    a = evaluation.eval_entities(cfg, "dev")
    assert a == evaluation.eval_entities(cfg, "dev")
    assert a["full"]["per_category"]["PERSON"]["fn"] > 0          # rules cannot find names: counted as misses, not hidden
    assert "PERSON" not in a["in_scope"]["per_category"]


def test_comparison_with_fake_model_runs_all_three_configs(fake_ml, monkeypatch):
    monkeypatch.setattr(ml, "available", lambda: True)
    rep = evaluation.run("dev", "test")
    assert set(rep["configs"]) == {"rules_only", "ml_only", "hybrid"} and all(c["available"] for c in rep["configs"].values())
    hy = rep["configs"]["hybrid"]["splits"]["dev"]["entity_exact"]["full"]["micro"]
    ru = rep["configs"]["rules_only"]["splits"]["dev"]["entity_exact"]["full"]["micro"]
    assert hy["tp"] >= ru["tp"]


def test_evaluation_reports_unavailable_model_instead_of_inventing_numbers(monkeypatch):
    monkeypatch.setattr(ml, "available", lambda: False)
    rep = evaluation.run("dev", "t")
    assert rep["configs"]["ml_only"]["available"] is False and rep["configs"]["hybrid"]["available"] is False and rep["configs"]["rules_only"]["available"]


@pytest.mark.skipif(os.environ.get("RUN_ML_TESTS") != "1", reason="loads the real GLiNER checkpoint; set RUN_ML_TESTS=1")
def test_real_model_finds_a_person_and_a_place():
    found = {(f.category) for f in engine.detect_text("Priya Sharma moved to Bengaluru")}
    assert "PERSON" in found and "LOCATION" in found


def test_rules_only_entity_counts_match_an_independent_recount():
    """Recount rules-only exact-span TP/FP/FN straight from detect_rules, bypassing evaluation.py's counting code."""
    for split in ("dev", "held"):
        tp = fp = fn = 0
        for text, gold in eval_data.text_items(split):
            pred = {(s.start, s.end, s.category) for s in detect_rules(text)}
            g = set(gold)
            tp += len(pred & g)
            fp += len(pred - g)
            fn += len(g - pred)
        got = evaluation.eval_entities(evaluation.CONFIGS["rules_only"], split)["full"]["micro"]
        assert (got["tp"], got["fp"], got["fn"]) == (tp, fp, fn)
        if tp:
            assert got["precision"] == round(tp / (tp + fp), 4) and got["recall"] == round(tp / (tp + fn), 4)


# ---------- verification round: card column, denied audit, limits, logging, lifetime ----------
def test_card_column_counts_luhn_invalid_value_as_a_miss_not_a_bug():
    """The browser-test column: two Luhn-valid test cards, one deliberately Luhn-invalid, one blank cell -> 2 of 3 inspected, Critical, PARTIAL."""
    rows = [["4111 1111 1111 1111"], ["4111 1111 1111 1112"], ["5500 0000 0000 0004"], [None]]
    c = engine.analyze(["card_no"], rows, use_ml=False)["columns"][0]
    assert (c["match_count"], c["values_inspected"], c["null_count"]) == (2, 3, 1)
    assert c["risk"] == "Critical" and c["recommended_protection"] == "PARTIAL" and c["status"] == "detected"


def test_denied_upload_is_audited_without_content(client):
    h = login(client, "analyst1")
    secret_name = "jane.doe@example.com.csv"
    r = up(client, h, body="name\nJane Doe 4111111111111111\n", name=secret_name)
    assert r.status_code == 403
    from app.database import session as dbsession
    from app.database.models import AuditEvent
    from sqlalchemy import select
    with next(dbsession.get_session()) as db:
        rows = list(db.scalars(select(AuditEvent).where(AuditEvent.operation == "b1_upload_analyze")))
    assert rows and rows[-1].decision == "DENY" and rows[-1].actor == "analyst1"
    blob = json.dumps([(e.reason, e.subject_ref, e.fields) for e in rows])
    assert "Jane" not in blob and "4111" not in blob and "jane.doe" not in blob


def test_row_and_column_limits_enforced(client, monkeypatch):
    h = login(client, "sec.admin")
    monkeypatch.setenv("UPLOAD_MAX_ROWS", "3")
    monkeypatch.setenv("UPLOAD_MAX_COLUMNS", "2")
    get_settings.cache_clear()
    try:
        assert up(client, h, body="a,b\n" + "1,2\n" * 4).status_code == 422
        assert "Too many rows" in up(client, h, body="a,b\n" + "1,2\n" * 4).json()["detail"]["message"]
        assert "Too many columns" in up(client, h, body="a,b,c\n1,2,3\n").json()["detail"]["message"]
        assert up(client, h, body="a,b\n1,2\n").status_code == 200
    finally:
        monkeypatch.delenv("UPLOAD_MAX_ROWS")
        monkeypatch.delenv("UPLOAD_MAX_COLUMNS")
        get_settings.cache_clear()


def test_declared_content_length_over_limit_is_refused_before_reading(client, monkeypatch):
    monkeypatch.setenv("UPLOAD_MAX_BYTES", "20")
    get_settings.cache_clear()
    try:
        r = client.post("/api/b1/upload/analyze?filename=a.csv", content=b"a,b\n" + b"1,2\n" * 100, headers={**login(client, "sec.admin"), "Content-Type": "text/csv"})
        assert r.status_code == 413 and r.json()["detail"]["code"] == "file_too_large"
    finally:
        monkeypatch.delenv("UPLOAD_MAX_BYTES")
        get_settings.cache_clear()


def test_nothing_from_the_file_is_logged_or_written(client, fake_ml, caplog, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    caplog.set_level("DEBUG")
    r = up(client, login(client, "sec.admin"), body="full_name,email\nPriya Sharma,priya.s@example.com\n", name="people.csv")
    assert r.status_code == 200
    assert "Priya" not in caplog.text and "priya.s@example.com" not in caplog.text
    assert list(tmp_path.iterdir()) == []                      # no temp files in the working directory
    item = store.get("sec.admin")
    assert "Priya" not in json.dumps(item["result"]) and set(item) == {"id", "owner", "name", "at", "result"}


def test_results_expire_and_are_not_shared_across_users(monkeypatch):
    import time as _t
    aid = store.put("alice", "a.csv", {"x": 1})
    assert store.get("bob") is None and store.get("bob", aid) is None
    real = _t.time()
    monkeypatch.setattr(store.time, "time", lambda: real + store.TTL + 5)
    assert store.get("alice", aid) is None and store.get("alice") is None


def test_dataset_question_cannot_reach_another_users_analysis(client, monkeypatch, fake_ml):
    up(client, login(client, "sec.admin"))
    fake = FakeClient(tool_calls=[call("ask_about_dataset", {"question": "summary"})])
    monkeypatch.setattr(service, "get_llm_client", lambda: fake)
    other = login(client, "compliance1")                         # a different signed-in user (no analysis of their own)
    r = client.post("/api/assistant/chat", json={"message": "q", "page": "discovery"}, headers=other)
    assert "people.csv" not in r.text


@pytest.mark.parametrize("who", ["compliance1", "advisor1", "analyst1"])
def test_every_non_admin_role_gets_403_and_an_audit_row(client, who):
    h = login(client, who)
    r = up(client, h)
    assert r.status_code == 403, (who, r.status_code)
    from app.database import session as dbsession
    from app.database.models import AuditEvent
    from sqlalchemy import select
    with next(dbsession.get_session()) as db:
        rows = list(db.scalars(select(AuditEvent).where(AuditEvent.operation == "b1_upload_analyze", AuditEvent.actor == who)))
    assert rows and rows[-1].decision == "DENY"
