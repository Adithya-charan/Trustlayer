"""Controlled query execution with dynamic, role-based masking.

Requests are a structured spec (or one tightly validated SELECT parsed with sqlglot into the same spec). Table and column names are checked
against the reflected schema (an allow-list), values are bound parameters, and masking is applied to the rows that are RETURNED. Non-admin roles
cannot filter or sort on sensitive columns (that would let them confirm or rank masked values). No joins, aggregates, sub-queries or raw SQL."""
import datetime as dt
import hashlib
import re
import time
import uuid
from decimal import Decimal
from typing import Literal

import sqlglot
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlglot import exp

from app.audit import logger as audit
from app.b1 import activity, mask, policy
from app.b1.detect import TAG_OF
from app.b1.targets import Target
from app.core.config import get_settings
from app.database.models import B1FieldTag

MAX_LIMIT = 100


class ScanRequired(Exception):
    """The table has not been scanned yet, so its columns are unclassified. The engine fails closed instead of guessing."""


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(min_length=1, max_length=64)
    op: Literal["=", "!=", "<", "<=", ">", ">="]
    value: str | int | float

    @field_validator("value")
    @classmethod
    def _short(cls, v):
        if isinstance(v, str) and len(v) > 200:
            raise ValueError("filter value is too long")
        return v


class QuerySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["postgres", "sqlite", "mysql"]
    table: str = Field(min_length=1, max_length=64)
    columns: list[str] = Field(min_length=1, max_length=60)
    filters: list[Filter] = Field(default_factory=list, max_length=5)
    order_by: str | None = Field(default=None, max_length=64)
    descending: bool = False
    limit: int = Field(20, ge=1, le=MAX_LIMIT)


def _resolve(names, wanted: str) -> str:
    """Exact match, else a unique case-insensitive match (the pack's `cards` table has UPPER-CASE columns). Anything else is unknown."""
    if wanted in names:
        return wanted
    hits = [n for n in names if n.lower() == wanted.lower()]
    if len(hits) == 1:
        return hits[0]
    raise LookupError("unknown column")


def parse_sql(sql: str, target: str) -> QuerySpec:
    """One SELECT on one table: columns or *, AND-ed comparisons against literals, one ORDER BY, LIMIT <= 100. Everything else is rejected."""
    if len(sql) > 600:
        raise ValueError("The query is too long.")
    try:
        trees = sqlglot.parse(sql)
    except Exception:  # noqa: BLE001
        raise ValueError("The query could not be parsed.") from None
    if len(trees) != 1 or not isinstance(trees[0], exp.Select):
        raise ValueError("Only a single SELECT statement is supported.")
    sel: exp.Select = trees[0]
    for bad in ("joins", "with", "group", "having", "distinct", "windows", "offset", "lateral", "qualify", "into", "locks"):
        if sel.args.get(bad):
            raise ValueError(f"{bad.upper()} is not supported.")
    if sel.find(exp.Subquery) or sel.find(exp.Union) or sel.find(exp.Func):
        raise ValueError("Sub-queries and functions are not supported.")
    frm = sel.args.get("from")
    if frm is None or not isinstance(frm.this, exp.Table) or frm.this.args.get("db") or frm.this.args.get("catalog"):
        raise ValueError("Query exactly one table by name (no schema prefix, joins or sub-queries).")
    table = frm.this.name
    cols: list[str] = []
    for e in sel.expressions:
        if isinstance(e, exp.Star):
            cols = ["*"]
        elif isinstance(e, exp.Column) and not e.args.get("db") and (not e.table or e.table == table):
            cols.append(e.name)
        else:
            raise ValueError("Select plain columns or *. Expressions, functions and aliases are not supported.")
    filters: list[Filter] = []
    where = sel.args.get("where")
    if where:
        stack = [where.this]
        ops = {exp.EQ: "=", exp.NEQ: "!=", exp.LT: "<", exp.LTE: "<=", exp.GT: ">", exp.GTE: ">="}
        while stack:
            node = stack.pop()
            if isinstance(node, exp.And):
                stack += [node.right, node.left]
            elif type(node) in ops and isinstance(node.left, exp.Column) and isinstance(node.right, (exp.Literal, exp.Neg)):
                lit = node.right
                val = lit.to_py() if hasattr(lit, "to_py") else (float(lit.name) if not lit.is_string else lit.name)
                filters.append(Filter(column=node.left.name, op=ops[type(node)], value=val))
            else:
                raise ValueError("WHERE supports only AND-ed comparisons (=, !=, <, <=, >, >=) of a column with a literal.")
        filters.reverse()
    order = sel.args.get("order")
    order_by, desc = None, False
    if order:
        if len(order.expressions) != 1 or not isinstance(order.expressions[0].this, exp.Column):
            raise ValueError("ORDER BY supports a single plain column.")
        order_by, desc = order.expressions[0].this.name, bool(order.expressions[0].args.get("desc"))
    limit = 20
    lim = sel.args.get("limit")
    if lim is not None:
        try:
            limit = int(lim.expression.name)
        except Exception:  # noqa: BLE001
            raise ValueError("LIMIT must be a number.") from None
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"LIMIT must be between 1 and {MAX_LIMIT}.")
    return QuerySpec(target=target, table=table, columns=cols, filters=filters, order_by=order_by, descending=desc, limit=limit)


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return "<binary>"
    return v


def _tags(db: Session, target: Target, table: str) -> dict[str, tuple[str, str]]:
    rows = db.scalars(select(B1FieldTag).where(B1FieldTag.target == target.name, B1FieldTag.table_name == table)).all()
    if not rows:
        raise ScanRequired(table)
    return {r.column_name: (r.kind, TAG_OF.get(r.kind, r.tag)) for r in rows}  # the tag always follows the current taxonomy for the stored kind


def _plan(db: Session, target: Target, spec: QuerySpec):
    tables = target.tables()
    tname = _resolve(tables, spec.table) if spec.table not in tables else spec.table
    table = tables[tname]
    colnames = [c.name for c in table.columns]
    wanted = colnames if spec.columns == ["*"] else [_resolve(colnames, c) for c in spec.columns]
    tags = _tags(db, target, tname)
    filters = [(_resolve(colnames, f.column), f) for f in spec.filters]
    order = _resolve(colnames, spec.order_by) if spec.order_by else None
    return tname, table, wanted, tags, filters, order


def _meta(tags, col):
    return tags.get(col, ("UNCLASSIFIED", "PII_HIGH"))  # a column nobody classified is treated as sensitive


def _fetch(target: Target, table, cols, filters, order, desc, limit):
    stmt = select(*[table.c[c] for c in cols])
    for col, f in filters:
        c = table.c[col]
        stmt = stmt.where({"=": c == f.value, "!=": c != f.value, "<": c < f.value, "<=": c <= f.value, ">": c > f.value, ">=": c >= f.value}[f.op])
    if order:
        stmt = stmt.order_by(table.c[order].desc() if desc else table.c[order].asc())
    with target.connect() as conn:
        return conn.execute(stmt.limit(limit)).all()


_NAMES: dict[str, tuple[float, frozenset[str]]] = {}
NAME_TTL = 600.0


def clear_name_cache() -> None:
    _NAMES.clear()


def _names(db: Session, target: Target) -> frozenset[str]:
    """Full names held in the database's own name columns (confirmed or reviewed FULL_NAME columns), lower-cased, 2-4 words. Kept in memory only, for scrubbing
    names that appear inside free text. Never returned, logged or stored."""
    now = time.monotonic()
    hit = _NAMES.get(target.name)
    if hit and now - hit[0] < NAME_TTL:
        return hit[1]
    found: set[str] = set()
    cols = db.scalars(select(B1FieldTag).where(B1FieldTag.target == target.name, B1FieldTag.kind == "FULL_NAME", B1FieldTag.status == "confirmed")).all()
    tables = target.tables()
    for c in cols:
        table = tables.get(c.table_name)
        if table is None or c.column_name not in table.c:
            continue
        with target.connect() as conn:
            for (v,) in conn.execute(select(table.c[c.column_name]).where(table.c[c.column_name].is_not(None)).distinct().limit(20000)):
                words = re.findall(r"[A-Za-z][A-Za-z.'-]*", str(v))
                if 2 <= len(words) <= 4 and all(len(w.strip(".'-")) >= 2 for w in words):
                    found.add(" ".join(w.lower().strip(".'-") for w in words))
    result = frozenset(found)
    _NAMES[target.name] = (now, result)
    return result


def _needs_names(role: str, wanted, tags) -> bool:
    return role != "Admin" and any(_meta(tags, c)[0] == "FREE_TEXT_PII" for c in wanted)


def _masked(role: str, wanted, tags, rows, names=None, overrides=None, username: str = ""):
    """Returns (columns, withheld, masked_rows) for one role. DENY columns are dropped before any value is formatted. `overrides` are the
    Admin-edited policies in force for the caller (kind -> (strategy, source)); each column reports which policy source decided it."""
    cols_meta, keep = [], []
    withheld = []
    for i, c in enumerate(wanted):
        kind, tag = _meta(tags, c)
        strat = mask.strategy_for(role, kind, tag, overrides)
        source = policy.source_for(overrides, kind) if tag != "NON_SENSITIVE" and role != "Admin" else "default"
        if strat == "DENY":
            withheld.append({"column": c, "kind": kind, "tag": tag, "source": source, "why": activity.why_field(role, username, kind, tag, strat, source)})
            continue
        keep.append((i, kind, strat))
        cols_meta.append({"name": c, "kind": kind, "tag": tag, "strategy": strat, "source": source, "why": activity.why_field(role, username, kind, tag, strat, source)})
    out = [{wanted[i]: _jsonable(mask.apply_strategy(strat, kind, row[i], names)) for i, kind, strat in keep} for row in rows]
    return cols_meta, withheld, out


def _audit(db: Session, actor: str, role: str, tname: str, cols_meta, n_rows: int, n_filters: int, decision: str, reason: str | None = None,
           withheld=(), policy_for: tuple[str, str] | None = None, attempts: bool = True) -> str:
    rid = audit.new_request_id()
    fields = {c["name"]: {"category": c["kind"], "strategy": c["strategy"]} for c in cols_meta}
    fields.update({w["column"]: {"category": w["kind"], "strategy": "DENY"} for w in withheld})
    sources = {c.get("source") for c in cols_meta} | {w.get("source") for w in withheld}
    source = "user" if "user" in sources else "role" if "role" in sources else "default"
    plabel = policy.describe(*(policy_for[0], source, policy_for[1]) if policy_for else (role, source, actor))
    explained = [{"name": c["name"], **c["why"]} for c in cols_meta if c.get("why")] + [{"name": w["column"], **w["why"]} for w in withheld if w.get("why")]
    audit.record(db, request_id=rid, actor=actor, role=role, operation="b1_query", purpose="b1_demo", fields=fields, policy=plabel,
                 decision=decision, reason=reason or f"{tname}: {n_rows} rows, {len(cols_meta)} columns, {n_filters} filters", subject_ref=tname[:64],
                 detail={"table": tname, "rows": n_rows, "fields": explained})
    if withheld and attempts:  # a request for a column the policy withholds is a recorded access attempt of its own, not just a masked result
        denied = [{"name": w["column"], **w["why"]} for w in withheld if w.get("why")]
        audit.record(db, request_id=audit.new_request_id(), actor=actor, role=role, operation="b1_access_denied", purpose="b1_demo",
                     fields={w["column"]: {"category": w["kind"], "strategy": "DENY"} for w in withheld}, policy=plabel, decision="DENY", subject_ref=tname[:64],
                     reason=f"{tname}: {', '.join(w['column'] for w in withheld)} withheld by {role} policy; query {rid[:8]}",
                     detail={"table": tname, "query_request_id": rid, "fields": denied})
    return rid


def run_query(db: Session, target: Target, spec: QuerySpec, actor: str, account_role: str) -> dict:
    role = mask.normalize_role(account_role)
    tname, table, wanted, tags, filters, order = _plan(db, target, spec)
    if role != "Admin":  # filtering/sorting on a sensitive column would let a restricted role confirm or rank masked values
        for col, _ in filters:
            if _meta(tags, col)[1] != "NON_SENSITIVE":
                _audit(db, actor, role, tname, [], 0, len(filters), "DENY", "filter on a sensitive column refused")
                raise PermissionError(f"Your role cannot filter by '{col}' because it holds sensitive data.")
        if order and _meta(tags, order)[1] != "NON_SENSITIVE":
            _audit(db, actor, role, tname, [], 0, len(filters), "DENY", "ordering by a sensitive column refused")
            raise PermissionError(f"Your role cannot sort by '{order}' because it holds sensitive data.")
    rows = _fetch(target, table, wanted, filters, order, spec.descending, spec.limit)
    ov = policy.load(db, actor, account_role)
    cols_meta, withheld, masked_rows = _masked(role, wanted, tags, rows, _names(db, target) if _needs_names(role, wanted, tags) else None, ov, actor)
    decision = "ALLOW" if all(c["strategy"] == "ALLOW" for c in cols_meta) and not withheld else "MASK"
    rid = _audit(db, actor, role, tname, cols_meta, len(masked_rows), len(filters), decision, withheld=withheld)
    return {"request_id": rid, "role": role, "target": target.name, "dialect": target.dialect, "table": tname, "row_count": len(masked_rows),
            "columns": cols_meta, "withheld": withheld, "rows": masked_rows, "source_unchanged": True}


def run_preview(db: Session, target: Target, spec: QuerySpec, admin: str, username: str, user_role: str) -> dict:
    """Admin-only policy preview: the result `username` would receive right now, computed by the same engine and that user's policy. The Admin sees only
    what the user sees (never more), and the audit trail records the preview under the Admin's name with the previewed user's policy."""
    role = mask.normalize_role(user_role)
    tname, table, wanted, tags, filters, order = _plan(db, target, spec)
    for col, _ in filters:
        if role != "Admin" and _meta(tags, col)[1] != "NON_SENSITIVE":
            raise PermissionError(f"{username} cannot filter by '{col}' because it holds sensitive data.")
    if order and role != "Admin" and _meta(tags, order)[1] != "NON_SENSITIVE":
        raise PermissionError(f"{username} cannot sort by '{order}' because it holds sensitive data.")
    rows = _fetch(target, table, wanted, filters, order, spec.descending, spec.limit)
    ov = policy.load(db, username, role)
    cols_meta, withheld, masked_rows = _masked(role, wanted, tags, rows, _names(db, target) if _needs_names(role, wanted, tags) else None, ov, username)
    rid = _audit(db, admin, "Admin", tname, cols_meta, len(masked_rows), len(filters), "MASK" if role != "Admin" else "ALLOW",
                 f"preview as {username} ({role}): {tname}, {len(masked_rows)} rows", withheld=withheld, policy_for=(role, username), attempts=False)
    return {"request_id": rid, "role": role, "as_user": username, "target": target.name, "dialect": target.dialect, "table": tname, "row_count": len(masked_rows),
            "columns": cols_meta, "withheld": withheld, "rows": masked_rows, "source_unchanged": True}


def run_compare(db: Session, target: Target, spec: QuerySpec, actor: str) -> dict:
    """Admin-only: the SAME rows shown to every role, so evaluators can compare masking side by side. Includes a before/after source fingerprint."""
    tname, table, wanted, tags, filters, order = _plan(db, target, spec)
    before = fingerprint(target, tname)
    rows = _fetch(target, table, wanted, filters, order, spec.descending, spec.limit)
    views = {}
    names = _names(db, target) if _needs_names("Support", wanted, tags) else None
    role_ov = policy.load_roles(db)
    for role in mask.ROLES:
        cols_meta, withheld, out = _masked(role, wanted, tags, rows, names, role_ov.get(role), "")
        views[role] = {"columns": cols_meta, "withheld": withheld, "rows": out}
    after = fingerprint(target, tname)
    _audit(db, actor, "Admin", tname, [{"name": c, "kind": _meta(tags, c)[0], "strategy": "ALLOW"} for c in wanted], len(rows), len(filters), "ALLOW",
           f"{tname}: role comparison, {len(rows)} rows")
    return {"target": target.name, "dialect": target.dialect, "table": tname, "row_count": len(rows), "views": views,
            "integrity": {"before": before, "after": after, "unchanged": before == after}}


def fingerprint(target: Target, tname: str) -> dict:
    """Cheap, deterministic source fingerprint: row count + hash of the first 200 rows by primary key. Used to show that querying changes nothing."""
    table = target.tables()[tname]
    pk = list(table.primary_key.columns) or [table.columns[0]]
    with target.connect() as conn:
        n = conn.execute(select(func.count()).select_from(table)).scalar()
        rows = conn.execute(select(table).order_by(*pk).limit(200)).all()
    h = hashlib.sha256("\x1f".join("|".join("" if v is None else str(v) for v in r) for r in rows).encode()).hexdigest()[:16]
    return {"rows": int(n), "sample_hash": h}
