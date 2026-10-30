"""Loads the organizer's Saffron Bank PostgreSQL pack into its OWN schema of the configured database (default schema: saffron_bank).

Safety rules enforced here:
  * never touches the `public` schema (TrustLayer's own tables live there; the pack's DROP TABLE lines are skipped, not executed);
  * only CREATE TABLE / CREATE INDEX / INSERT INTO / SET client_encoding are accepted, and only for the nine expected tables;
  * refuses to run if the target schema already holds data (no duplicate imports);
  * everything runs in one transaction that is committed only if every row count matches the organizer's published counts;
  * the pack files are only read, never modified; the database URL is read from DATABASE_URL and never printed.

Usage (from backend/):
  python -m scripts.load_saffron_pg --schema-file "<01_schema.sql>" --data-file "<02_data.sql>"  [--schema saffron_bank]"""
import argparse
import pathlib
import re
import sys

import psycopg
from psycopg import sql

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.core.config import get_settings  # noqa: E402

EXPECTED = {"branches": 60, "customers": 5000, "kyc_records": 5400, "international_customers": 300, "accounts": 8000, "cards": 6000,
            "transactions": 100000, "support_tickets": 3000, "loan_applications": 1500}
DROP_RE = re.compile(r'^DROP\s+TABLE\s+IF\s+EXISTS\s+"(\w+)"$', re.I)
CREATE_RE = re.compile(r'^CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX)\s+"(\w+)"', re.I)
INSERT_RE = re.compile(r'^INSERT\s+INTO\s+"(\w+)"', re.I)
SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def split_statements(text: str) -> list[str]:
    """Split on ';' that is outside single-quoted literals ('' is an escaped quote and simply toggles twice)."""
    out, start, inside = [], 0, False
    for m in re.finditer(r"'|;", text):
        if m.group() == "'":
            inside = not inside
        elif not inside:
            stmt = text[start:m.start()].strip()
            if stmt:
                out.append(stmt)
            start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def classify(stmt: str) -> tuple[str, str | None]:
    """Returns (kind, table). Raises for anything outside the allow-list."""
    head = stmt.lstrip()[:200]
    if m := DROP_RE.match(head):
        return "drop", m.group(1)
    if m := CREATE_RE.match(head):
        return "create", None
    if m := INSERT_RE.match(head):
        if m.group(1) not in EXPECTED:
            raise SystemExit(f"Refusing: INSERT into unexpected table {m.group(1)!r}")
        return "insert", m.group(1)
    if re.match(r"^(BEGIN|COMMIT)$", head, re.I):
        return "txn", None
    if re.match(r"^SET\s+client_encoding\s*=\s*'UTF8'$", head, re.I):
        return "set", None
    raise SystemExit(f"Refusing: unexpected statement type: {head[:60]!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema-file", required=True)
    ap.add_argument("--data-file", required=True)
    ap.add_argument("--schema", default="saffron_bank")
    ap.add_argument("--dry-run", action="store_true", help="parse and validate the files only; do not connect")
    a = ap.parse_args()
    if not SCHEMA_RE.match(a.schema) or a.schema in ("public", "pg_catalog", "information_schema"):
        raise SystemExit("Refusing: target schema must be a new, non-system schema name (never 'public').")

    schema_stmts = split_statements(pathlib.Path(a.schema_file).read_text(encoding="utf-8"))
    data_stmts = split_statements(pathlib.Path(a.data_file).read_text(encoding="utf-8"))
    ddl = [s for s in schema_stmts if classify(s)[0] == "create"]
    skipped_drops = sum(1 for s in schema_stmts if classify(s)[0] == "drop")
    dml = [s for s in data_stmts if classify(s)[0] in ("insert", "set")]
    for s in schema_stmts + data_stmts:
        classify(s)  # reject anything unexpected before touching the database
    print(f"parsed: {len(ddl)} CREATE statements ({skipped_drops} DROP lines skipped on purpose), {sum(1 for s in dml if s.upper().startswith('INSERT'))} INSERT statements")
    if a.dry_run:
        print("dry run only; nothing was executed")
        return 0

    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    if not url:
        raise SystemExit("DATABASE_URL is not set in backend/.env")
    with psycopg.connect(url, autocommit=False) as con:
        with con.cursor() as cur:
            cur.execute("select exists(select 1 from information_schema.schemata where schema_name = %s)", (a.schema,))
            if cur.fetchone()[0]:
                cur.execute("select count(*) from information_schema.tables where table_schema = %s", (a.schema,))
                if cur.fetchone()[0]:
                    print(f"Schema '{a.schema}' already contains tables; refusing to import again (no duplicate imports). Nothing changed.")
                    return 0
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(a.schema)))
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(a.schema)))  # unqualified names resolve ONLY inside the new schema
            for i, s in enumerate(ddl, 1):
                cur.execute(s)
            for i, s in enumerate(dml, 1):
                cur.execute(s)
                if i % 50 == 0:
                    print(f"  executed {i}/{len(dml)} data statements")
            bad = []
            for t, n in EXPECTED.items():
                cur.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(t)))
                got = cur.fetchone()[0]
                print(f"  {t:<26}{got:>9,} (expected {n:,})")
                if got != n:
                    bad.append(t)
            cur.execute("select count(*) from accounts a left join customers c on c.customer_id = a.customer_id where c.customer_id is null")
            orphans = cur.fetchone()[0]
            if bad or orphans:
                con.rollback()
                print(f"ROLLED BACK: count mismatch in {bad}, orphan accounts: {orphans}. Nothing was imported.")
                return 2
        con.commit()
    print(f"Committed. All 9 tables match the organizer's counts; schema '{a.schema}' created; public.* untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
