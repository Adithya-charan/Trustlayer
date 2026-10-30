"""End-to-end verification of the B1 engine on the REAL Saffron Bank dataset in every backend that is configured and reachable: Neon PostgreSQL
(DATABASE_URL), the organizer's SQLite file (B1_SQLITE_PATH) and MySQL (B1_MYSQL_URL). A backend that is not configured or not connected is reported as
SKIPPED, never as passed. Prints booleans, counts and column names only; never data values. Read-only against the dataset: every connection is read-only.
(Running a scan stores column tags in TrustLayer's own tables, exactly like the "Scan now" button.)

Checks per backend: health check (connected, schema found, read-only reported by the database); discovery of the key sensitive columns; per-role masking
correctness; zero leakage of real sensitive values to Support/Analyst across every table; full-table checksums unchanged after all queries; an Admin policy
edit changes the next result for that user and is reverted afterwards.
Usage (from backend/):  python -m scripts.verify_b1_backends [postgres|sqlite|mysql ...]"""
import hashlib
import pathlib
import re
import sys

from sqlalchemy import select, text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.b1 import discover, query as q, targets  # noqa: E402
from app.database.session import session_scope  # noqa: E402

OK = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK
    OK &= bool(cond)
    print(f"{'PASS' if cond else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))


def checksums(t) -> dict:
    """Full-table content hashes: computed inside PostgreSQL, and in Python (streamed, ordered by primary key) for the other engines."""
    out = {}
    with t.connect() as c:
        for name, tbl in sorted(t.tables().items()):
            if t.dialect == "postgresql":
                out[name] = c.execute(text(f'select md5(string_agg(x::text, \'\' order by x::text)) from "{t.schema}"."{name}" x')).scalar()
                continue
            pk = list(tbl.primary_key.columns) or [tbl.columns[0]]
            h = hashlib.sha256()
            for row in c.execute(select(tbl).order_by(*pk)).yield_per(5000):
                h.update(repr(tuple(row)).encode())
            out[name] = h.hexdigest()
    return out


def verify(name: str) -> None:
    print(f"\n=== backend: {name} ===")
    try:
        pg = targets.get_target(name)
    except LookupError:
        print(f"SKIPPED | {name} is not configured on this machine")
        return
    st = pg.status()
    check("health check: connected, schema found", st["connected"] and st["schema_found"], f"provider={st['provider']} schema={st['schema']} tables={st['tables']}")
    check("the database reports the connection as read-only", st["read_only"] is True)
    if not (st["connected"] and st["schema_found"]):
        return
    try:
        with pg.connect() as c:
            c.execute(text("create table trustlayer_write_probe (x int)"))
        check("a write attempt is refused by the database", False, "the write SUCCEEDED")
    except Exception as exc:  # noqa: BLE001
        check("a write attempt is refused by the database", True, type(exc).__name__)
    before = checksums(pg)
    with session_scope() as db:
        s = discover.scan(db, pg, "verify_script")
        print("scan:", s)
        check("discovered every table and column", s["tables"] == st["tables"] and s["columns"] > 0 and s["errors"] == 0, f"{s['tables']} tables / {s['columns']} columns")
        f = {(x["table"], x["column"]): x for x in discover.fields(db, pg)}
        pii = {k for k, v in f.items() if v["tag"] != "NON_SENSITIVE"}
        check("sensitive columns found", len(pii) >= 40, f"{len(pii)} tagged columns")
        for key in [("kyc_records", "pan_no"), ("kyc_records", "aadhaar_no"), ("cards", "CARD_NO"), ("international_customers", "ssn"), ("customers", "mob_no"),
                    ("customers", "emailid"), ("customers", "cust_nm"), ("accounts", "curr_bal"), ("loan_applications", "col_7"), ("transactions", "narration")]:
            check(f"tagged and confirmed: {key[0]}.{key[1]}", key in f and f[key]["status"] == "confirmed", f[key]["kind"] if key in f else "missing")

        # Raw sensitive values (kept in memory only) to prove they never reach restricted roles. Values the legacy system already masked
        # (e.g. "XXXX XXXX 1234") are not secrets, so they are excluded.
        premasked = re.compile(r"[Xx*]{3,}")
        secret_cols = [("kyc_records", "pan_no"), ("kyc_records", "aadhaar_no"), ("cards", "CARD_NO"), ("international_customers", "ssn"), ("customers", "emailid"),
                       ("customers", "mob_no"), ("customers", "cust_nm")]
        from sqlalchemy import select

        def col(tbl, wanted):
            return next(c for c in tbl.columns if c.name.lower() == wanted.lower())

        tables = pg.tables()
        with pg.connect() as c:
            secrets = {str(v) for t, name in secret_cols
                       for (v,) in c.execute(select(col(tables[t], name)).where(col(tables[t], name).is_not(None)).limit(400))
                       if len(str(v)) >= 9 and not premasked.search(str(v))}
        leaks, ran = 0, 0
        for table in sorted(pg.tables()):
            for role in ("Support", "Analyst"):
                res = q.run_query(db, pg, q.QuerySpec(target=pg.name, table=table, columns=["*"], limit=100), "verify_script", role)
                ran += 1
                blob = repr(res["rows"])
                leaks += sum(1 for v in secrets if v in blob)
        check(f"no real sensitive value reached Support/Analyst ({ran} table x role queries, {len(secrets)} real values checked)", leaks == 0, f"leaks={leaks}")
        sup = q.run_query(db, pg, q.QuerySpec(target=pg.name, table="cards", columns=["CARD_NO"], limit=5), "verify_script", "Support")["rows"]
        check("Support card format 4111-XXXX-XXXX-1111 style", all(re.fullmatch(r"\d{4}\D?(X{4}\D?){2}\d{4}", r["CARD_NO"]) or "X" in r["CARD_NO"] for r in sup))
        ana = q.run_query(db, pg, q.QuerySpec(target=pg.name, table="kyc_records", columns=["pan_no", "aadhaar_no", "kyc_status"], limit=5), "verify_script", "Analyst")
        check("Analyst: PAN hashed, Aadhaar withheld", all(r["pan_no"].startswith("h_") for r in ana["rows"] if r["pan_no"]) and [w["column"] for w in ana["withheld"]] == ["aadhaar_no"])
        adm = q.run_query(db, pg, q.QuerySpec(target=pg.name, table="cards", columns=["CARD_NO"], limit=5), "verify_script", "Admin")["rows"]
        check("Admin receives real card numbers", all("X" not in r["CARD_NO"] for r in adm))

        from app.b1 import policy
        saved = policy.current(db, "user", "analyst_kavya", "PAN")
        policy.set_policy(db, "user", "analyst_kavya", "PAN", "PARTIAL", "verify_script")
        try:
            edited = q.run_query(db, pg, q.QuerySpec(target=pg.name, table="kyc_records", columns=["pan_no"], limit=3), "analyst_kavya", "Analyst")["rows"]
            check("an Admin policy edit changes that user's very next result (HASH -> PARTIAL)", saved[0] == "HASH" and all("X" in (r["pan_no"] or "X") for r in edited))
        finally:
            policy.reset_policy(db, "user", "analyst_kavya", "PAN", "verify_script")
        again = q.run_query(db, pg, q.QuerySpec(target=pg.name, table="kyc_records", columns=["pan_no"], limit=3), "analyst_kavya", "Analyst")["rows"]
        check("resetting the policy restores the default (hash)", all((r["pan_no"] or "h_").startswith("h_") for r in again))

    check(f"full-table checksums unchanged ({len(before)} tables)", checksums(pg) == before)


def main() -> int:
    names = sys.argv[1:] or list(targets.NAMES)
    for n in names:
        verify(n)
    print("\nOVERALL:", "ALL CHECKS PASSED (skipped backends are not counted as passed)" if OK else "SOME CHECKS FAILED")
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
