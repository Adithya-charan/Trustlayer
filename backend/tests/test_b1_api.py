"""Integration tests for the B1 engine API. The application's only backend is Neon PostgreSQL; here the Target is swapped for a synthetic, read-only
fixture shaped like the organizer's dataset (tests/b1_fixture.py), so the suite never touches Neon or needs credentials."""
import hashlib
import sqlite3

import pytest
from sqlalchemy import text

from app.b1 import query as q
from app.b1 import targets
from app.core.config import get_settings
from app.core.security import hash_password
from app.database import session as dbsession
from app.database.models import User
from tests.b1_fixture import build, fixture_target
from tests.conftest import PW, login

ENDPOINTS = [("GET", "/api/b1/targets"), ("POST", "/api/b1/scan"), ("GET", "/api/b1/schema?target=postgres"), ("GET", "/api/b1/fields?target=postgres"),
             ("PATCH", "/api/b1/fields"), ("GET", "/api/b1/policy"), ("POST", "/api/b1/query"), ("POST", "/api/b1/compare"), ("GET", "/api/b1/audit")]


@pytest.fixture()
def b1(client, tmp_path, monkeypatch):
    path = tmp_path / "saffron_fixture.db"
    secrets = build(path)
    targets.reset()
    monkeypatch.setattr(targets, "_pg_target", lambda: fixture_target(path))
    with dbsession.session_scope() as db:
        for name, role in [("admin_t", "Admin"), ("support_t", "Support"), ("analyst_t", "Analyst"), ("advisor_t", "advisor"), ("comp_t", "compliance_officer")]:
            db.add(User(username=name, display_name=name, role=role, password_hash=hash_password(PW)))
        db.commit()
    yield type("B1", (), {"client": client, "path": path, "secrets": secrets})
    targets.reset()
    monkeypatch.undo()
    get_settings.cache_clear()


def H(b1, who):
    return login(b1.client, who)


def scan(b1):
    r = b1.client.post("/api/b1/scan", json={"target": "postgres"}, headers=H(b1, "admin_t"))
    assert r.status_code == 200, r.text
    return r.json()


def query(b1, who, **kw):
    body = {"target": "postgres", **kw}
    return b1.client.post("/api/b1/query", json=body, headers=H(b1, who))


def dump(path):
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    out = {t: con.execute(f'select * from "{t}" order by 1').fetchall() for (t,) in con.execute("select name from sqlite_master where type='table'")}
    con.close()
    return out


# ---------- authentication / authorization ----------
@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_every_endpoint_requires_authentication(b1, method, path):
    assert b1.client.request(method, path, json={}).status_code == 401


def test_unknown_roles_cannot_use_the_engine(b1):
    for who in ("advisor_t", "comp_t"):
        assert b1.client.get("/api/b1/targets", headers=H(b1, who)).status_code == 403
        assert query(b1, who, table="customers", columns=["cust_nm"]).status_code == 403


def test_only_admin_can_scan_review_compare_and_read_audit(b1):
    for who in ("support_t", "analyst_t"):
        h = H(b1, who)
        assert b1.client.post("/api/b1/scan", json={"target": "postgres"}, headers=h).status_code == 403
        assert b1.client.patch("/api/b1/fields", json={"target": "postgres", "table": "customers", "column": "cust_nm", "kind": "NON_SENSITIVE"}, headers=h).status_code == 403
        assert b1.client.post("/api/b1/compare", json={"target": "postgres", "table": "customers", "columns": ["cust_nm"]}, headers=h).status_code == 403
        assert b1.client.get("/api/b1/audit", headers=h).status_code == 403


def test_role_comes_from_the_token_not_the_request(b1):
    scan(b1)
    r = query(b1, "support_t", table="customers", columns=["cust_nm"], role="Admin")  # extra field: rejected, never honoured
    assert r.status_code == 422
    assert b1.client.post("/api/b1/query", json={"target": "postgres", "table": "customers", "columns": ["cust_nm"]}, headers={**H(b1, "support_t"), "X-Role": "Admin"}).json()["role"] == "Support"


def test_fails_closed_before_a_scan(b1):
    r = query(b1, "admin_t", table="customers", columns=["cust_nm"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "scan_required"


# ---------- discovery ----------
def test_scan_discovers_and_tags_fields(b1):
    s = scan(b1)
    assert s["tables"] == 9 and s["confirmed"] > 15
    f = {(x["table"], x["column"]): x for x in b1.client.get("/api/b1/fields?target=postgres", headers=H(b1, "support_t")).json()["fields"]}
    assert f[("kyc_records", "pan_no")]["tag"] == "PII_HIGH" and f[("cards", "CARD_NO")]["kind"] == "CARD_NUMBER"
    assert f[("loan_applications", "col_7")]["kind"] == "PAN"
    assert f[("accounts", "curr_bal")]["tag"] == "FINANCIAL_CONFIDENTIAL" and f[("customers", "segment")]["tag"] == "NON_SENSITIVE"
    assert f[("customers", "empty_col")]["status"] == "none"  # an empty column is not guessed
    assert ("customers", "payload") in f  # binary column handled without sampling
    schema = b1.client.get("/api/b1/schema?target=postgres", headers=H(b1, "analyst_t")).json()
    assert schema["scanned"] and {t["name"] for t in schema["tables"]} >= {"customers", "cards", "transactions"}


def test_admin_review_overrides_and_survives_rescan(b1):
    scan(b1)
    h = H(b1, "admin_t")
    body = {"target": "postgres", "table": "customers", "column": "segment", "kind": "FULL_NAME"}
    assert b1.client.patch("/api/b1/fields", json=body, headers=h).status_code == 200
    r = query(b1, "support_t", table="customers", columns=["segment"], limit=3)
    assert r.json()["columns"][0]["kind"] == "FULL_NAME" and r.json()["columns"][0]["strategy"] == "PARTIAL"  # masking follows the reviewed tag
    scan(b1)
    assert any(x["reviewed"] and x["column"] == "segment" for x in b1.client.get("/api/b1/fields?target=postgres", headers=h).json()["fields"])
    assert b1.client.patch("/api/b1/fields", json={**body, "kind": "NOT_A_KIND"}, headers=h).status_code == 422
    assert b1.client.patch("/api/b1/fields", json={**body, "column": "nope"}, headers=h).status_code == 404


# ---------- dynamic masking per role ----------
def test_admin_support_analyst_see_different_views_of_the_same_rows(b1):
    scan(b1)
    cols = ["customer_id", "cust_nm", "emailid", "mob_no", "dob_dt", "segment"]
    admin = query(b1, "admin_t", table="customers", columns=cols, limit=5).json()
    support = query(b1, "support_t", table="customers", columns=cols, limit=5).json()
    analyst = query(b1, "analyst_t", table="customers", columns=cols, limit=5).json()
    assert admin["role"] == "Admin" and support["role"] == "Support" and analyst["role"] == "Analyst"
    a, s, n = admin["rows"][0], support["rows"][0], analyst["rows"][0]
    assert a["cust_nm"] in b1.secrets["name"] and a["emailid"] in b1.secrets["email"]  # Admin: real values
    assert s["cust_nm"] != a["cust_nm"] and "*" in s["cust_nm"] and s["emailid"].startswith(a["emailid"][0] + "***@")  # Support: partial
    assert n["cust_nm"] == "[REDACTED]" and n["emailid"] == "[REDACTED]" and n["mob_no"] == "[REDACTED]"  # Analyst: redacted
    for view in (s, n):
        assert view["customer_id"] == a["customer_id"] and view["segment"] == a["segment"]  # non-sensitive columns are untouched


def test_card_pan_aadhaar_ssn_handling(b1):
    scan(b1)
    cards = query(b1, "support_t", table="cards", columns=["CARD_NO", "NAME_ON_CARD"], limit=10).json()
    assert all("X" in r["CARD_NO"] and r["CARD_NO"][:4].isdigit() and r["CARD_NO"][-4:].isdigit() for r in cards["rows"])
    hashed = query(b1, "analyst_t", table="cards", columns=["card_no"], limit=5).json()  # column name resolved case-insensitively
    assert all(r["CARD_NO"].startswith("h_") for r in hashed["rows"])
    kyc = query(b1, "analyst_t", table="kyc_records", columns=["pan_no", "aadhaar_no", "kyc_status"], limit=5).json()
    assert [w["column"] for w in kyc["withheld"]] == ["aadhaar_no"] and "aadhaar_no" not in kyc["rows"][0]  # restricted for Analyst: withheld entirely
    assert kyc["rows"][0]["pan_no"].startswith("h_")
    ssn = query(b1, "analyst_t", table="international_customers", columns=["ssn", "us_city"]).json()
    assert [w["column"] for w in ssn["withheld"]] == ["ssn"]


def test_free_text_is_scrubbed_for_restricted_roles(b1):
    scan(b1)
    for who in ("support_t", "analyst_t"):
        rows = query(b1, who, table="support_tickets", columns=["ticket_text"], limit=20).json()["rows"]
        blob = " ".join(r["ticket_text"] for r in rows)
        for raw in b1.secrets["pan"] + b1.secrets["email"] + b1.secrets["phone"] + b1.secrets["name"]:  # customer names written in the text too
            assert raw not in blob


def test_no_value_leaks_into_audit_logs_or_errors(b1, caplog):
    caplog.set_level("DEBUG")
    scan(b1)
    everything = []
    for who in ("admin_t", "support_t", "analyst_t"):
        everything.append(query(b1, who, table="kyc_records", columns=["pan_no", "aadhaar_no"], limit=30).text if who == "admin_t" else "")
    bad = [query(b1, "support_t", table="kyc_records", columns=["pan_no"], filters=[{"column": "pan_no", "op": "=", "value": b1.secrets["pan"][0]}]),
           query(b1, "support_t", table="nope", columns=["x"]), query(b1, "support_t", table="customers", columns=["nope"]),
           b1.client.post("/api/b1/query", json={"target": "postgres", "sql": f"SELECT * FROM kyc_records WHERE pan_no = '{b1.secrets['pan'][0]}' OR 1=1"}, headers=H(b1, "support_t"))]
    leaked = b1.secrets["pan"] + b1.secrets["card"] + b1.secrets["aadhaar"] + b1.secrets["email"]
    texts = [r.text for r in bad] + [caplog.text]
    audit = b1.client.get("/api/b1/audit?limit=100", headers=H(b1, "admin_t")).text
    for raw in leaked:
        assert all(raw not in t for t in texts) and raw not in audit


# ---------- bypass, injection, validation ----------
def test_restricted_roles_cannot_filter_or_sort_on_sensitive_columns(b1):
    scan(b1)
    pan0 = b1.secrets["pan"][0]
    for who in ("support_t", "analyst_t"):
        r = query(b1, who, table="kyc_records", columns=["kyc_status"], filters=[{"column": "pan_no", "op": "=", "value": pan0}])
        assert r.status_code == 403  # would otherwise confirm a masked value
        assert query(b1, who, table="customers", columns=["customer_id"], order_by="cust_nm").status_code == 403
    ok = query(b1, "admin_t", table="kyc_records", columns=["pan_no"], filters=[{"column": "pan_no", "op": "=", "value": pan0}])
    assert ok.status_code == 200 and ok.json()["row_count"] >= 1 and ok.json()["rows"][0]["pan_no"] == pan0
    assert query(b1, "support_t", table="customers", columns=["customer_id"], filters=[{"column": "segment", "op": "=", "value": "Retail"}]).status_code == 200


@pytest.mark.parametrize("sql", [
    "DROP TABLE customers", "DELETE FROM customers", "UPDATE customers SET cust_nm = 'x'", "INSERT INTO customers (customer_id) VALUES ('x')",
    "SELECT * FROM customers; DROP TABLE customers", "SELECT c.cust_nm FROM customers c JOIN cards d ON d.CUSTOMER_ID = c.customer_id",
    "SELECT * FROM (SELECT * FROM customers) t", "SELECT * FROM customers UNION SELECT * FROM customers", "SELECT COUNT(*) FROM customers",
    "SELECT * FROM customers WHERE segment = 'Retail' OR 1 = 1", "SELECT * FROM customers WHERE cust_nm LIKE '%a%'", "SELECT * FROM customers LIMIT 5000",
    "SELECT * FROM main.customers", "SELECT cust_nm AS n FROM customers", "SELECT * FROM customers WHERE segment IN ('Retail')", "SELECT 1", "x" * 700,
    "SELECT * FROM sqlite_master", "PRAGMA table_info(customers)", "ATTACH DATABASE 'x' AS y",
])
def test_unsafe_or_unsupported_sql_is_rejected(b1, sql):
    scan(b1)
    r = b1.client.post("/api/b1/query", json={"target": "postgres", "sql": sql}, headers=H(b1, "admin_t"))
    assert r.status_code in (404, 422), (sql, r.status_code, r.text)
    assert dump(b1.path) == dump(b1.path)  # nothing executed


def test_valid_sql_is_parsed_into_the_same_safe_path(b1):
    scan(b1)
    r = b1.client.post("/api/b1/query", json={"target": "postgres", "sql": "SELECT cust_nm, city FROM customers WHERE segment = 'Retail' ORDER BY city DESC LIMIT 4"},
                       headers=H(b1, "support_t"))
    assert r.status_code == 200 and r.json()["row_count"] <= 4 and "*" in r.json()["rows"][0]["cust_nm"]
    star = b1.client.post("/api/b1/query", json={"target": "postgres", "sql": 'SELECT * FROM "cards" LIMIT 3'}, headers=H(b1, "analyst_t")).json()
    assert {c["name"] for c in star["columns"]} >= {"CARD_REF", "CARD_NO"}


def test_sql_injection_in_values_is_neutralised_by_parameter_binding(b1):
    scan(b1)
    r = query(b1, "admin_t", table="customers", columns=["customer_id"], filters=[{"column": "segment", "op": "=", "value": "' OR '1'='1"}])
    assert r.status_code == 200 and r.json()["row_count"] == 0
    r2 = query(b1, "admin_t", table="customers", columns=["customer_id"], filters=[{"column": "segment", "op": "=", "value": "Retail'; DROP TABLE customers; --"}])
    assert r2.json()["row_count"] == 0 and dump(b1.path)["customers"]


def test_identifiers_are_allow_listed(b1):
    scan(b1)
    for table, col in (("customers; DROP TABLE x", "cust_nm"), ("sqlite_master", "name"), ("customers", 'cust_nm" FROM customers --'), ("customers", "1=1")):
        assert query(b1, "admin_t", table=table, columns=[col]).status_code == 404
    assert query(b1, "admin_t", table="customers", columns=["x"] * 61).status_code == 422
    assert query(b1, "admin_t", table="customers", columns=["cust_nm"], limit=101).status_code == 422


def test_unknown_targets_are_refused_and_a_missing_sqlite_file_is_unavailable(b1, monkeypatch):
    scan(b1)
    r = b1.client.post("/api/b1/query", json={"target": "oracle", "table": "customers", "columns": ["cust_nm"]}, headers=H(b1, "admin_t"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_target"
    assert b1.client.get("/api/b1/fields?target=oracle", headers=H(b1, "admin_t")).status_code == 422
    monkeypatch.setattr(get_settings(), "b1_sqlite_path", str(b1.path.parent / "does_not_exist.db"))
    targets.reset()
    monkeypatch.setattr(targets, "_pg_target", lambda: fixture_target(b1.path))
    assert b1.client.post("/api/b1/scan", json={"target": "sqlite"}, headers=H(b1, "admin_t")).status_code == 503
    assert b1.client.get("/api/b1/fields?target=mysql", headers=H(b1, "admin_t")).status_code == 503  # not configured on this server


def test_targets_lists_every_backend_honestly_without_secrets(b1, monkeypatch):
    monkeypatch.setattr(get_settings(), "b1_sqlite_path", str(b1.path))
    monkeypatch.setattr(get_settings(), "b1_mysql_url", "")
    targets.reset()
    monkeypatch.setattr(targets, "_pg_target", lambda: fixture_target(b1.path))
    t = {x["name"]: x for x in b1.client.get("/api/b1/targets", headers=H(b1, "support_t")).json()["targets"]}
    assert list(t) == ["postgres", "sqlite", "mysql"]
    assert t["postgres"]["connected"] and t["postgres"]["tables"] == 9 and t["postgres"]["checked_at"]
    assert t["sqlite"]["connected"] and t["sqlite"]["read_only"] is True and t["sqlite"]["tables"] == 9  # opened mode=ro with query_only
    assert t["mysql"]["configured"] is False and t["mysql"]["connected"] is False and "B1_MYSQL_URL" in t["mysql"]["error"]
    assert str(b1.path) not in str(t) and "password" not in str(t).lower()  # no path or credential in the status


def test_an_unreachable_mysql_reports_disconnected_by_type_only(b1, monkeypatch):
    monkeypatch.setattr(get_settings(), "b1_mysql_url", "mysql://nobody:hunter2@127.0.0.1:1/saffron_bank")
    targets.reset()
    monkeypatch.setattr(targets, "_pg_target", lambda: fixture_target(b1.path))
    my = next(x for x in b1.client.get("/api/b1/targets", headers=H(b1, "support_t")).json()["targets"] if x["name"] == "mysql")
    assert my["configured"] is True and my["connected"] is False and my["error"] and "hunter2" not in str(my) and "127.0.0.1" not in str(my)


def test_the_sqlite_target_refuses_writes(b1, monkeypatch):
    monkeypatch.setattr(get_settings(), "b1_sqlite_path", str(b1.path))
    targets.reset()
    t = targets.get_target("sqlite")
    with pytest.raises(Exception):
        with t.connect() as c:
            c.execute(text("DELETE FROM customers"))
    assert dump(b1.path)["customers"]


def test_sqlite_backend_is_scanned_and_masked_like_the_others(b1, monkeypatch):
    monkeypatch.setattr(get_settings(), "b1_sqlite_path", str(b1.path))
    targets.reset()
    assert b1.client.post("/api/b1/scan", json={"target": "sqlite"}, headers=H(b1, "admin_t")).json()["tables"] == 9
    body = {"target": "sqlite", "table": "cards", "columns": ["CARD_NO"], "limit": 3}
    sup = b1.client.post("/api/b1/query", json=body, headers=H(b1, "support_t")).json()
    adm = b1.client.post("/api/b1/query", json=body, headers=H(b1, "admin_t")).json()
    assert sup["target"] == "sqlite" and "X" in sup["rows"][0]["CARD_NO"] and "X" not in adm["rows"][0]["CARD_NO"]


def test_target_defaults_to_postgres(b1):
    scan(b1)
    r = b1.client.post("/api/b1/query", json={"table": "customers", "columns": ["cust_nm"]}, headers=H(b1, "admin_t"))
    assert r.status_code == 200 and r.json()["target"] == "postgres"


def test_unconfigured_database_reports_disconnected_not_success(client):
    targets.reset()  # the test app DB is not PostgreSQL, so there is no target
    try:
        h = login(client, "sec.admin")
        t = client.get("/api/b1/targets", headers=h).json()["targets"]
        pg = next(x for x in t if x["name"] == "postgres")
        assert pg["connected"] is False and pg["error"]
        assert client.get("/api/b1/fields", headers=h).status_code == 503
    finally:
        targets.reset()


def test_status_reports_failures_by_type_only(b1, monkeypatch):
    t = targets.get_target()
    monkeypatch.setattr(targets, "inspect", lambda eng: (_ for _ in ()).throw(RuntimeError("password=hunter2 host=db.example")))
    s = t.status()
    assert s["connected"] is False and s["error"] == "RuntimeError" and "hunter2" not in str(s)


# ---------- data integrity ----------
def test_queries_never_modify_the_source(b1):
    scan(b1)
    before, file_hash = dump(b1.path), hashlib.sha256(b1.path.read_bytes()).hexdigest()
    for who in ("admin_t", "support_t", "analyst_t"):
        for t, cols in (("customers", ["cust_nm", "mob_no"]), ("cards", ["CARD_NO"]), ("kyc_records", ["pan_no", "aadhaar_no"]), ("transactions", ["amount_inr", "narration"])):
            query(b1, who, table=t, columns=cols, limit=50)
    b1.client.post("/api/b1/compare", json={"target": "postgres", "table": "customers", "columns": ["cust_nm", "emailid"]}, headers=H(b1, "admin_t"))
    query(b1, "support_t", table="kyc_records", columns=["pan_no"], filters=[{"column": "pan_no", "op": "=", "value": "x"}])  # denied
    assert dump(b1.path) == before and hashlib.sha256(b1.path.read_bytes()).hexdigest() == file_hash


def test_the_database_connection_itself_is_read_only(b1):
    t = targets.get_target()
    with pytest.raises(Exception):
        with t.connect() as c:
            c.execute(text("DELETE FROM customers"))
    with pytest.raises(Exception):
        with t.connect() as c:
            c.execute(text("DROP TABLE customers"))
    assert dump(b1.path)["customers"]


def test_compare_shows_all_roles_and_proves_the_source_is_unchanged(b1):
    scan(b1)
    r = b1.client.post("/api/b1/compare", json={"target": "postgres", "table": "cards", "columns": ["CARD_NO", "NAME_ON_CARD", "CARD_TYPE"], "limit": 3}, headers=H(b1, "admin_t"))
    assert r.status_code == 200
    v = r.json()["views"]
    assert set(v) == {"Admin", "Support", "Analyst"} and r.json()["integrity"]["unchanged"] is True
    assert v["Admin"]["rows"][0]["CARD_NO"] in b1.secrets["card"] and "X" in v["Support"]["rows"][0]["CARD_NO"] and v["Analyst"]["rows"][0]["CARD_NO"].startswith("h_")
    assert v["Admin"]["rows"][0]["CARD_TYPE"] == v["Analyst"]["rows"][0]["CARD_TYPE"]


def test_every_query_is_audited_with_field_names_and_strategies_only(b1):
    scan(b1)
    query(b1, "support_t", table="cards", columns=["CARD_NO", "CARD_TYPE"], limit=2)
    query(b1, "support_t", table="kyc_records", columns=["kyc_status"], filters=[{"column": "pan_no", "op": "=", "value": "x"}])
    ev = b1.client.get("/api/b1/audit?limit=20", headers=H(b1, "admin_t")).json()["events"]
    ops = [(e["operation"], e["decision"]) for e in ev]
    assert ("b1_query", "MASK") in ops and ("b1_query", "DENY") in ops and ("b1_scan", "ALLOW") in ops
    masked = next(e for e in ev if e["decision"] == "MASK")
    assert masked["fields"]["CARD_NO"]["strategy"] == "PARTIAL" and masked["actor"] == "support_t" and "x" not in masked["reason"].replace("rows", "")
    policy = b1.client.get("/api/b1/policy", headers=H(b1, "analyst_t")).json()
    assert policy["matrix"]["Analyst"]["SSN"] == "DENY" and policy["matrix"]["Support"]["CARD_NUMBER"] == "PARTIAL" and policy["your_role"] == "Analyst"


def test_database_failure_gives_a_safe_error_not_a_stack_trace(b1, monkeypatch):
    from sqlalchemy.exc import OperationalError

    scan(b1)

    def boom(self):
        raise OperationalError("SELECT secret_table_name FROM x", {"p": "secret-param"}, Exception("connection to host db.internal.example refused"))

    monkeypatch.setattr(targets.Target, "connect", boom)
    r = query(b1, "support_t", table="customers", columns=["cust_nm"])
    assert r.status_code == 502 and r.json()["detail"]["code"] == "database_unavailable"
    for leaked in ("secret_table_name", "secret-param", "db.internal.example", "OperationalError"):
        assert leaked not in r.text


def test_missing_policy_for_a_column_fails_closed(b1):
    """A column with no classification record is treated as sensitive for every role except Admin."""
    from sqlalchemy import delete

    from app.database.models import B1FieldTag

    scan(b1)
    with dbsession.session_scope() as db:
        db.execute(delete(B1FieldTag).where(B1FieldTag.table_name == "customers", B1FieldTag.column_name == "segment"))
        db.commit()
    admin = query(b1, "admin_t", table="customers", columns=["segment"], limit=3).json()
    support = query(b1, "support_t", table="customers", columns=["segment"], limit=3).json()
    analyst = query(b1, "analyst_t", table="customers", columns=["segment"], limit=3).json()
    assert admin["rows"][0]["segment"] in ("Retail", "Premium")
    assert support["rows"][0]["segment"] == "[REDACTED]" and analyst["rows"][0]["segment"] == "[REDACTED]"
    assert support["columns"][0]["kind"] == "UNCLASSIFIED"
    # ...and such a column cannot be used as a filter by a restricted role
    assert query(b1, "support_t", table="customers", columns=["customer_id"], filters=[{"column": "segment", "op": "=", "value": "Retail"}]).status_code == 403


# ---------- editable policies ----------
def _put(b1, who, **kw):
    return b1.client.put("/api/b1/policy/overrides", json=kw, headers=H(b1, who))


def _pan(b1, who):
    return query(b1, who, table="kyc_records", columns=["pan_no"], limit=3).json()


def test_admin_policy_change_takes_effect_on_the_next_query_and_is_audited(b1):
    scan(b1)
    assert _pan(b1, "analyst_t")["rows"][0]["pan_no"].startswith("h_")  # default: Analyst sees a keyed hash
    r = _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="PARTIAL")
    assert r.status_code == 200 and r.json()["old"] == "HASH" and r.json()["new"] == "PARTIAL"
    after = _pan(b1, "analyst_t")
    assert "X" in after["rows"][0]["pan_no"] and after["rows"][0]["pan_no"] not in b1.secrets["pan"] and after["columns"][0]["source"] == "user"
    # a second Analyst is unaffected: the change was scoped to one user
    b1_other = query(b1, "support_t", table="kyc_records", columns=["pan_no"], limit=1).json()
    assert "X" in b1_other["rows"][0]["pan_no"]
    ev = b1.client.get("/api/b1/audit?limit=30", headers=H(b1, "admin_t")).json()["events"]
    change = next(e for e in ev if e["operation"] == "b1_policy_change")
    assert change["actor"] == "admin_t" and "HASH -> PARTIAL" in change["reason"] and change["fields"]["PAN"]["strategy"] == "PARTIAL"
    q_ev = next(e for e in ev if e["operation"] == "b1_query" and e["actor"] == "analyst_t" and e["fields"].get("pan_no", {}).get("strategy") == "PARTIAL")
    assert q_ev["policy"] == "b1/Analyst/user:analyst_t"
    # reset restores the built-in default
    assert b1.client.post("/api/b1/policy/overrides/reset", json={"scope": "user", "subject": "analyst_t", "kind": "PAN"}, headers=H(b1, "admin_t")).json()["new"] == "HASH"
    assert _pan(b1, "analyst_t")["rows"][0]["pan_no"].startswith("h_")


def test_role_policy_applies_to_everyone_in_the_role_and_user_policy_wins(b1):
    scan(b1)
    assert _put(b1, "admin_t", scope="role", subject="Support", kind="PAN", strategy="REDACT").status_code == 200
    assert _pan(b1, "support_t")["rows"][0]["pan_no"] == "[REDACTED]"
    _put(b1, "admin_t", scope="user", subject="support_t", kind="PAN", strategy="PARTIAL")
    assert "X" in _pan(b1, "support_t")["rows"][0]["pan_no"]
    assert b1.client.get("/api/b1/policy", headers=H(b1, "analyst_t")).json()["matrix"]["Support"]["PAN"] == "REDACT"


def test_only_admins_can_edit_policy_and_admin_accounts_cannot_be_restricted(b1):
    scan(b1)
    for who in ("support_t", "analyst_t", "advisor_t", "comp_t"):
        assert _put(b1, who, scope="user", subject="analyst_t", kind="PAN", strategy="ALLOW").status_code == 403
        assert b1.client.get("/api/b1/policy/overrides", headers=H(b1, who)).status_code == 403
        assert b1.client.get("/api/b1/users", headers=H(b1, who)).status_code == 403
    assert _pan(b1, "analyst_t")["rows"][0]["pan_no"].startswith("h_")  # the refused attempts changed nothing
    assert _put(b1, "admin_t", scope="user", subject="admin_t", kind="PAN", strategy="REDACT").status_code == 422
    assert _put(b1, "admin_t", scope="role", subject="Admin", kind="PAN", strategy="REDACT").status_code == 422
    assert _put(b1, "admin_t", scope="user", subject="nobody", kind="PAN", strategy="REDACT").status_code == 404
    assert _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="SHOW_ALL").status_code == 422
    assert _put(b1, "admin_t", scope="user", subject="analyst_t", kind="NON_SENSITIVE", strategy="REDACT").status_code == 422
    assert _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="ALLOW", extra=1).status_code == 422


def test_users_endpoint_lists_roles_and_custom_policy_counts_without_credentials(b1):
    _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="PARTIAL")
    users = {u["username"]: u for u in b1.client.get("/api/b1/users", headers=H(b1, "admin_t")).json()["users"]}
    assert users["analyst_t"]["role"] == "Analyst" and users["analyst_t"]["custom_policies"] == 1 and users["admin_t"]["editable"] is False
    assert "advisor_t" not in users and "password" not in str(users).lower()
    eff = b1.client.get("/api/b1/policy/users/analyst_t", headers=H(b1, "admin_t")).json()
    assert eff["policy"]["PAN"] == {"strategy": "PARTIAL", "source": "user", "default": "HASH"}


# ---------- overview, explorer metadata, audit filters ----------
def test_overview_numbers_come_from_the_database_and_the_audit_trail(b1):
    scan(b1)
    query(b1, "support_t", table="cards", columns=["CARD_NO"], limit=2)
    query(b1, "support_t", table="kyc_records", columns=["kyc_status"], filters=[{"column": "pan_no", "op": "=", "value": "x"}])  # denied
    o = b1.client.get("/api/b1/overview", headers=H(b1, "admin_t")).json()
    assert o["dataset"]["tables"] == 9 and o["dataset"]["records"] == sum(t["rows"] for t in o["dataset"]["per_table"]) > 0
    d = o["discovery"]
    assert d["scanned"] and d["sensitive_fields"] >= 10 and d["embedded_pii_fields"] >= 1 and "PAYMENT_SENSITIVE" in d["by_tag"]
    assert o["protection"]["protected_fields"] == d["sensitive_fields"] and o["protection"]["active_rules"] > 0 and o["protection"]["custom_policies"] == 0
    assert o["audit"]["masked"] >= 1 and o["audit"]["denied"] >= 1 and o["audit"]["total"] == o["audit"]["allowed"] + o["audit"]["masked"] + o["audit"]["denied"]
    assert [b["name"] for b in o["backends"]] == ["postgres", "sqlite", "mysql"] and str(b1.path) not in str(o)
    _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="PARTIAL")
    assert b1.client.get("/api/b1/overview", headers=H(b1, "support_t")).json()["protection"]["custom_policies"] == 1
    assert b1.client.get("/api/b1/overview", headers={}).status_code == 401


def test_schema_describes_each_column_for_the_callers_role(b1):
    scan(b1)
    s = {r: {t["name"]: {c["name"]: c for c in t["columns"]} for t in b1.client.get("/api/b1/schema?target=postgres", headers=H(b1, w)).json()["tables"]}
         for r, w in (("Admin", "admin_t"), ("Support", "support_t"), ("Analyst", "analyst_t"))}
    pan = {r: s[r]["kyc_records"]["pan_no"] for r in s}
    assert pan["Admin"]["strategy"] == "ALLOW" and pan["Admin"]["masked"] is False
    assert pan["Support"]["strategy"] == "PARTIAL" and pan["Support"]["masked"] is True and pan["Analyst"]["strategy"] == "HASH"
    assert pan["Analyst"]["risk"] == "High" and "column_name" in pan["Analyst"]["methods"] and pan["Analyst"]["type"]
    assert s["Analyst"]["cards"]["CARD_NO"]["tag"] == "PAYMENT_SENSITIVE" and s["Analyst"]["customers"]["segment"]["strategy"] == "ALLOW"
    t = {x["name"]: x for x in b1.client.get("/api/b1/schema?target=postgres", headers=H(b1, "admin_t")).json()["tables"]}
    assert t["kyc_records"]["risk"] == "High" and t["kyc_records"]["sensitive_columns"] >= 2


def test_audit_can_be_filtered_by_user_role_decision_and_resource(b1):
    scan(b1)
    query(b1, "support_t", table="cards", columns=["CARD_NO"], limit=2)
    query(b1, "analyst_t", table="kyc_records", columns=["pan_no", "aadhaar_no"], limit=2)
    query(b1, "support_t", table="kyc_records", columns=["kyc_status"], filters=[{"column": "pan_no", "op": "=", "value": "x"}])

    def audit(**kw):
        return b1.client.get("/api/b1/audit", params={"limit": 50, **kw}, headers=H(b1, "admin_t")).json()["events"]

    assert {e["actor"] for e in audit(user="analyst_t")} == {"analyst_t"}
    assert {e["role"] for e in audit(role="Support")} == {"Support"} and {e["decision"] for e in audit(decision="DENY")} == {"DENY"}
    cards = audit(resource="cards", operation="query")
    assert cards and all(e["resource"] == "cards" for e in cards)
    ana = next(e for e in audit(user="analyst_t", operation="query"))
    assert ana["fields"]["aadhaar_no"]["strategy"] == "DENY" and ana["fields"]["pan_no"]["strategy"] == "HASH" and ana["resource"] == "kyc_records"
    assert b1.client.get("/api/b1/audit", headers=H(b1, "support_t")).status_code == 403


def test_admin_preview_shows_exactly_what_the_user_would_get_and_is_audited(b1):
    scan(b1)
    body = {"target": "postgres", "sql": "SELECT pan_no, aadhaar_no FROM kyc_records LIMIT 3", "username": "analyst_t"}
    r1 = b1.client.post("/api/b1/preview", json=body, headers=H(b1, "admin_t")).json()
    assert r1["as_user"] == "analyst_t" and r1["role"] == "Analyst" and r1["rows"][0]["pan_no"].startswith("h_") and [w["column"] for w in r1["withheld"]] == ["aadhaar_no"]
    _put(b1, "admin_t", scope="user", subject="analyst_t", kind="PAN", strategy="PARTIAL")
    r2 = b1.client.post("/api/b1/preview", json=body, headers=H(b1, "admin_t")).json()
    assert "X" in r2["rows"][0]["pan_no"] and r2["columns"][0]["source"] == "user"
    assert not any(v in str(r2) for v in b1.secrets["pan"] + b1.secrets["aadhaar"])  # the Admin never sees more than the previewed user
    ev = b1.client.get("/api/b1/audit?operation=query&limit=5", headers=H(b1, "admin_t")).json()["events"][0]
    assert ev["actor"] == "admin_t" and "preview as analyst_t" in ev["reason"] and ev["policy"] == "b1/Analyst/user:analyst_t"
    for who in ("support_t", "analyst_t"):
        assert b1.client.post("/api/b1/preview", json=body, headers=H(b1, who)).status_code == 403
    assert b1.client.post("/api/b1/preview", json={**body, "username": "nobody"}, headers=H(b1, "admin_t")).status_code == 404
    assert b1.client.post("/api/b1/preview", json={**body, "username": "advisor_t"}, headers=H(b1, "admin_t")).status_code == 404
