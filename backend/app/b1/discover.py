"""Schema discovery + automatic tagging for a B1 target. Reads metadata and a bounded random sample per column, classifies, and stores only the
result (tags/confidence/methods) in `b1_field_tags`. Columns a reviewer corrected (`override`) keep their reviewed classification on re-scan."""
import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.b1 import query as _query, supplement
from app.b1.detect import KINDS, TAG_OF, classify_column
from app.b1.targets import Target
from app.core.config import get_settings
from app.database.models import B1FieldTag
from app.detection import ml

log = logging.getLogger("trustlayer.b1.discover")

SKIP_TYPES = ("BLOB", "BYTEA", "BINARY")


def scan(db: Session, target: Target, actor: str) -> dict:
    size = max(20, min(get_settings().b1_sample_size, 1000))
    existing = {(r.table_name, r.column_name): r for r in db.scalars(select(B1FieldTag).where(B1FieldTag.target == target.name))}
    counts = {"tables": 0, "columns": 0, "confirmed": 0, "uncertain": 0, "untagged": 0, "kept_overrides": 0, "errors": 0}
    now = dt.datetime.now(dt.timezone.utc)
    s = get_settings()
    ml_state = _ml_state()
    for tname, table in sorted(target.tables().items()):
        counts["tables"] += 1
        try:
            sample = target.sample_rows(table, size)  # one bounded random read per table
        except Exception:  # noqa: BLE001 - a table that cannot be sampled is reported, and its columns are classified from their names only
            sample = None
        for idx, col in enumerate(table.columns):
            counts["columns"] += 1
            key = (tname, col.name)
            row = existing.get(key)
            if row is not None and row.override:
                counts["kept_overrides"] += 1
                continue
            det, ml_state, errored = _detect(target, tname, table, col, idx, sample, ml_state, s.b1_ml_supplement_values)
            counts["errors"] += int(errored)
            dtype = str(col.type)
            counts["confirmed" if det.status == "confirmed" else "uncertain" if det.status == "uncertain" else "untagged"] += 1
            if row is None:
                row = B1FieldTag(target=target.name, table_name=tname, column_name=col.name)
                db.add(row)
            row.data_type, row.kind, row.tag = dtype[:64], det.kind, det.tag
            row.confidence, row.status, row.methods = det.confidence, det.status, det.methods
            row.match_ratio, row.sample_size, row.rationale = det.match_ratio, det.sample_size, det.rationale[:200]
            row.override, row.reviewed_by, row.updated_at = False, None, now
    db.commit()
    _query.clear_name_cache()  # the set of name columns may have changed
    counts["ml_supplement"] = _ml_summary(ml_state)
    return counts


def _ml_state() -> dict:
    s = get_settings()
    return {"enabled": s.b1_ml_supplement, "mode": "off", "error": None, "columns_checked": 0, "supplemented": 0, "available": s.b1_ml_supplement}


def _detect(target, tname, table, col, idx, sample, ml_state, cap):
    """THE detection path for one column, used by scan and by clear-override alike: original classifier, then the ML supplement when enabled.
    Returns (detection, ml_state, errored). `sample` is None when the table could not be sampled."""
    dtype = str(col.type)
    if sample is None:
        det = classify_column(tname, col.name, dtype, [])
        det.rationale = "could not be sampled; classified from its name only"
        det.confidence = min(det.confidence, 0.55)
        det.status = "uncertain" if det.confidence >= 0.5 and det.kind != "NON_SENSITIVE" else "none"
        return det, ml_state, True
    values = [] if any(t in dtype.upper() for t in SKIP_TYPES) else [r[idx] for r in sample if r[idx] is not None]
    det = classify_column(tname, col.name, dtype, values)
    if ml_state["available"] and supplement.eligible(tname, dtype, det) and values:
        det, ml_state = _supplement(det, tname, values, ml_state, cap)
    return det, ml_state, False


def _supplement(det, tname, values, ml_state, cap):
    """One column through the ML supplement. Any model failure keeps the original classification and switches the rest of this scan to rules-only:
    discovery itself never fails because of the model. Logs carry the exception TYPE only."""
    try:
        det, did = supplement.apply(det, values, cap)
    except ml.MLUnavailable as e:
        log.warning("B1 ML supplement unavailable; continuing rules-only: %s", str(e)[:120])
        return det, {**ml_state, "available": False, "error": str(e)[:160], "mode": "rules_only"}
    except Exception as e:  # noqa: BLE001 - a model bug must not break database discovery
        log.warning("B1 ML supplement failed for one column (%s); original result kept", type(e).__name__)
        return det, {**ml_state, "available": False, "error": f"inference failed ({type(e).__name__})", "mode": "rules_only"}
    return det, {**ml_state, "columns_checked": ml_state["columns_checked"] + 1, "supplemented": ml_state["supplemented"] + int(did), "mode": "hybrid"}


def _ml_summary(st: dict) -> dict:
    if not st["enabled"]:
        return {"enabled": False, "mode": "off", "error": None, "columns_checked": 0, "supplemented": 0}
    if st["mode"] != "off":
        mode = st["mode"]  # "hybrid" or "rules_only", set by the first column that reached the model or the failure
    else:
        mode = "rules_only" if not st["available"] else "no_candidates"  # enabled, but no column needed the model (or it never ran)
    return {"enabled": True, "mode": mode, "error": st["error"], "columns_checked": st["columns_checked"], "supplemented": st["supplemented"]}


def fields(db: Session, target: Target, table: str | None = None, status: str | None = None) -> list[dict]:
    stmt = select(B1FieldTag).where(B1FieldTag.target == target.name).order_by(B1FieldTag.table_name, B1FieldTag.id)
    if table:
        stmt = stmt.where(B1FieldTag.table_name == table)
    if status:
        stmt = stmt.where(B1FieldTag.status == status)
    return [{"table": r.table_name, "column": r.column_name, "data_type": r.data_type, "kind": r.kind, "tag": TAG_OF.get(r.kind, r.tag), "confidence": round(r.confidence, 2),
             "status": r.status, "methods": r.methods, "match_ratio": round(r.match_ratio, 2), "sample_size": r.sample_size, "rationale": r.rationale,
             "reviewed": r.override, "reviewed_by": r.reviewed_by} for r in db.scalars(stmt)]


class NoOverride(Exception):
    """Raised when a clear is requested for a column that has no manual override (safe to repeat: nothing changes)."""


class ReleaseNeedsConfirmation(Exception):
    """Raised, before any write, when a clear would release masking and the caller has not confirmed it. Carries what detection would restore."""

    def __init__(self, restored: dict):
        super().__init__("release needs confirmation")
        self.restored = restored


def _previous(row) -> dict | None:
    if row is None or row.kind is None:
        return None
    return {"kind": row.kind, "tag": TAG_OF.get(row.kind, row.tag), "status": row.status, "methods": list(row.methods or []), "reviewed_by": row.reviewed_by,
            "reviewed": bool(row.override)}


def releases_masking(previous_tag: str | None, new_tag: str) -> bool:
    """A change is a masking release when a column that was protected (any tag other than NON_SENSITIVE) becomes NON_SENSITIVE: every role then sees it raw."""
    return previous_tag not in (None, "NON_SENSITIVE") and new_tag == "NON_SENSITIVE"


def override(db: Session, target: Target, table: str, column: str, kind: str, reviewer: str) -> dict:
    if kind not in KINDS:
        raise ValueError("unknown classification")
    tbl = target.tables().get(table)
    if tbl is None or column not in tbl.c:
        raise LookupError("unknown table or column")
    row = db.scalar(select(B1FieldTag).where(B1FieldTag.target == target.name, B1FieldTag.table_name == table, B1FieldTag.column_name == column))
    previous = _previous(row)
    if row is None:
        row = B1FieldTag(target=target.name, table_name=table, column_name=column, data_type=str(tbl.c[column].type)[:64], methods=[])
        db.add(row)
    row.kind, row.tag = kind, TAG_OF[kind]
    row.confidence, row.status, row.override, row.reviewed_by = 1.0, "confirmed", True, reviewer
    # a reviewed field keeps the detector methods that still apply, but never the model suggestion that this review just replaced
    row.methods = sorted(set(m for m in (row.methods or []) if m != supplement.ML_METHOD) | {"manual_review"})
    row.rationale = f"classification set by reviewer {reviewer}"[:200]
    row.updated_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    _query.clear_name_cache()
    return {"table": table, "column": column, "kind": kind, "tag": TAG_OF[kind], "reviewed_by": reviewer, "previous": previous,
            "released": releases_masking(previous["tag"] if previous else None, TAG_OF[kind])}


def _redetect(target: Target, table: str, column: str):
    """Runs the normal detection for one column (no database writes). Returns (detection, ml_state, errored)."""
    tbl = target.tables().get(table)
    if tbl is None or column not in tbl.c:
        raise LookupError("unknown table or column")
    size = max(20, min(get_settings().b1_sample_size, 1000))
    try:
        sample = target.sample_rows(tbl, size)
    except Exception:  # noqa: BLE001 - reported as "classified from its name only", exactly as a scan would
        sample = None
    idx = list(tbl.c.keys()).index(column)
    return _detect(target, table, tbl, tbl.c[column], idx, sample, _ml_state(), get_settings().b1_ml_supplement_values)


def clear_override(db: Session, target: Target, table: str, column: str, actor: str, confirm_release: bool = False) -> dict:
    """Removes a manual decision and re-runs the normal detection path for that one column (same code as a scan, including the ML supplement when
    enabled). The result is NOT forced to NON_SENSITIVE: if detection finds nothing, the column becomes unclassified as on a fresh scan."""
    tbl = target.tables().get(table)
    if tbl is None or column not in tbl.c:
        raise LookupError("unknown table or column")
    row = db.scalar(select(B1FieldTag).where(B1FieldTag.target == target.name, B1FieldTag.table_name == table, B1FieldTag.column_name == column))
    if row is None or not row.override:
        raise NoOverride(f"{table}.{column}")
    previous = _previous(row)
    det, ml_state, errored = _redetect(target, table, column)  # the ONE detection result that both decides the release and is written
    if releases_masking(previous["tag"], det.tag) and not confirm_release:
        raise ReleaseNeedsConfirmation({"kind": det.kind, "tag": det.tag, "status": det.status})
    now = dt.datetime.now(dt.timezone.utc)
    row.data_type = str(tbl.c[column].type)[:64]
    row.kind, row.tag = det.kind, det.tag
    row.confidence, row.status, row.methods = det.confidence, det.status, det.methods
    row.match_ratio, row.sample_size, row.rationale = det.match_ratio, det.sample_size, det.rationale[:200]
    row.override, row.reviewed_by, row.updated_at = False, None, now
    db.commit()
    _query.clear_name_cache()
    restored = {"kind": det.kind, "tag": det.tag, "status": det.status, "methods": list(det.methods), "confidence": round(det.confidence, 2)}
    return {"table": table, "column": column, "previous": previous, "restored": restored, "sampled": not errored,
            "ml_supplement": _ml_summary(ml_state), "released": releases_masking(previous["tag"] if previous else None, det.tag)}
