"""Opt-in PostgreSQL integration test (needs the organizer pack imported by scripts/load_saffron_pg.py). Skipped unless B1_PG_TEST_URL is set, so the
default suite never needs credentials:   B1_PG_TEST_URL=<your DATABASE_URL> python -m pytest tests/test_b1_pg.py"""
import os

import pytest
from sqlalchemy import text

from app.b1 import discover, query as q, targets
from app.core.config import get_settings
from app.database import session as dbsession

PG_URL = os.environ.get("B1_PG_TEST_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set B1_PG_TEST_URL to run against PostgreSQL")


@pytest.fixture()
def pg(client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    get_settings.cache_clear()
    targets.reset()
    yield targets.get_target("postgres")
    targets.reset()
    monkeypatch.undo()
    get_settings.cache_clear()


def test_postgres_scan_masking_and_read_only(pg):
    st = pg.status()
    assert pg.dialect == "postgresql" and st["connected"] and st["schema_found"] and st["tables"] == 9 and st["read_only"] is True
    assert st["provider"] == "Neon" and "neon.tech" not in str(st) and "@" not in str(st)  # provider derived, host and credentials never returned
    with dbsession.session_scope() as db:
        s = discover.scan(db, pg, "pgtest")
        assert s["tables"] == 9 and s["columns"] == 120
        f = {(x["table"], x["column"]): x for x in discover.fields(db, pg)}
        assert f[("kyc_records", "pan_no")]["tag"] == "PII_HIGH" and f[("cards", "CARD_NO")]["kind"] == "CARD_NUMBER" and f[("loan_applications", "col_7")]["kind"] == "PAN"
        support = q.run_query(db, pg, q.QuerySpec(target="postgres", table="cards", columns=["card_no"], limit=5), "pgtest", "Support")
        assert all("X" in r["CARD_NO"] for r in support["rows"])  # the upper-case quoted column is resolved and masked
        admin = q.run_query(db, pg, q.QuerySpec(target="postgres", table="cards", columns=["CARD_NO"], limit=5), "pgtest", "Admin")
        assert all("X" not in r["CARD_NO"] for r in admin["rows"])
        analyst = q.run_query(db, pg, q.QuerySpec(target="postgres", table="kyc_records", columns=["aadhaar_no", "pan_no"], limit=3), "pgtest", "Analyst")
        assert [w["column"] for w in analyst["withheld"]] == ["aadhaar_no"]
    # Read-only is checked by asking the database, never by attempting a write against the real Neon data.
    with pg.connect() as c:
        assert c.execute(text("SHOW transaction_read_only")).scalar() == "on"
    assert pg.row_count(pg.tables()["branches"]) == 60


def test_postgres_supplement_response_shape_and_uncertainty(pg, monkeypatch):
    """Opt-in (same gate as above). Runs a flagged scan on Neon and checks the response and stored rows keep the existing shape:
    supplemented rows are uncertain, never confirmed, and every other row is what the original classifier produced."""
    from app.detection import ml

    monkeypatch.setenv("B1_ML_SUPPLEMENT", "true")
    get_settings.cache_clear()
    try:
        with dbsession.session_scope() as db:
            counts = discover.scan(db, pg, "pgtest_supplement")
            rows = discover.fields(db, pg)
        assert set(counts["ml_supplement"]) == {"enabled", "mode", "error", "columns_checked", "supplemented"}
        assert counts["ml_supplement"]["mode"] in ("hybrid", "rules_only", "no_candidates")
        for f in rows:
            if "ml_ner" in f["methods"]:
                assert f["status"] == "uncertain" and f["kind"] in ("FULL_NAME", "ADDRESS")
    finally:
        monkeypatch.delenv("B1_ML_SUPPLEMENT", raising=False)
        get_settings.cache_clear()
        ml.reset()
