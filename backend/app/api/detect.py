"""Dataset upload + hybrid PII analysis. The CSV is parsed in memory and discarded; only the analysis (counts, categories, risk - no cell values) is kept,
briefly and per user, so the assistant can answer questions about it. Requires the same role as a database scan (Admin / Security Admin)."""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.audit import logger as audit
from app.b1 import mask
from app.core.config import get_settings
from app.core.security import Actor, current_actor, limiter, require
from app.policies.engine import has_permission
from app.database.session import get_session
from app.detection import engine, ml, store
from app.detection.csvio import CSVError, parse_csv

log = logging.getLogger("trustlayer.detection")
router = APIRouter(prefix="/api/b1")


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


async def _read_capped(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise _err(413, "file_too_large", f"The file is larger than the {limit // 1_000_000} MB limit.")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise _err(413, "file_too_large", f"The file is larger than the {limit // 1_000_000} MB limit.")
    return bytes(buf)


def _role_label(role: str) -> str:
    """Audit label for any account role. Roles outside the B1 alias map must not raise here: a refusal has to produce a 403, not a 500."""
    try:
        return mask.normalize_role(role)
    except PermissionError:
        return "unmapped"


def _safe_name(name: str | None) -> str:
    """Display label only: the base name, never used as a path."""
    base = re.split(r"[\\/]", name or "dataset.csv")[-1]
    return re.sub(r"[^\w .\-]", "_", base)[:80] or "dataset.csv"


@router.get("/detection/status")
def detection_status(actor: Actor = Depends(require("b1_query"))):
    """Model availability for the Discovery page. Loading is lazy: `state` is not_loaded until the first analysis that needs the model."""
    s = get_settings()
    return {**ml.status(), "fallback": s.detection_ml_fallback, "upload_max_mb": s.upload_max_bytes // 1_000_000, "upload_max_rows": s.upload_max_rows}


@router.post("/upload/analyze")
async def analyze_upload(request: Request, filename: str = Query("dataset.csv", max_length=200), use_ml: bool = True,
                         actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    if not has_permission(actor.role, "b1_scan"):  # checked here (not via require()) so a refused attempt is audited
        audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=_role_label(actor.role), operation="b1_upload_analyze", purpose="dataset_upload",
                     fields={}, policy="detection/upload", decision="DENY", reason="upload refused: role not permitted to analyse datasets")
        raise HTTPException(403, "Your role is not permitted to perform this operation")
    limiter.check(f"upload:{actor.username}", 6, 60)
    s = get_settings()
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in ("text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"):
        raise _err(415, "unsupported_type", "Upload a .csv file (text/csv).")
    if not filename.lower().endswith(".csv"):
        raise _err(415, "unsupported_type", "Only .csv files are supported.")
    raw = await _read_capped(request, s.upload_max_bytes)
    role = mask.normalize_role(actor.role)
    rid = audit.new_request_id()
    try:
        columns, rows, info = parse_csv(raw)
    except CSVError as e:
        audit.record(db, request_id=rid, actor=actor.username, role=role, operation="b1_upload_analyze", purpose="dataset_upload", fields={}, policy="detection/upload",
                     decision="DENY", reason="upload rejected: " + str(e)[:120])
        raise _err(422, "invalid_csv", str(e)) from None
    finally:
        del raw
    try:
        result = await run_in_threadpool(engine.analyze, columns, rows, use_ml=use_ml)
    except ml.MLUnavailable as e:  # only when DETECTION_ML_FALLBACK=fail
        raise _err(503, "ml_unavailable", str(e)) from None
    except Exception as e:  # noqa: BLE001
        log.warning("analysis failed: %s", type(e).__name__)
        raise _err(500, "analysis_failed", "The dataset could not be analysed.") from None
    result["input"] = info
    name = _safe_name(filename)
    aid = store.put(actor.username, name, result)
    sm = result["summary"]
    audit.record(db, request_id=rid, actor=actor.username, role=role, operation="b1_upload_analyze", purpose="dataset_upload", fields={}, policy="detection/" + result["ml"]["mode"],
                 decision="ALLOW", reason=f"analysed {info['rows']} rows x {info['columns']} columns: {sm['sensitive_columns']} sensitive, {sm['suspected_columns']} suspected, "
                 f"highest risk {sm['highest_risk']}; mode {result['ml']['mode']}", subject_ref=aid)
    return {"id": aid, "name": name, **result}


@router.get("/upload/latest")
def latest_upload(actor: Actor = Depends(require("b1_scan"))):
    item = store.get(actor.username)
    if item is None:
        raise _err(404, "no_analysis", "No dataset has been analysed in this session. Upload a CSV first.")
    return {"id": item["id"], "name": item["name"], **item["result"]}
