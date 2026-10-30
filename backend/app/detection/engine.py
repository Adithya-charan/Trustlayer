"""Column-level hybrid analysis used by dataset upload (and reusable for database samples). Returns findings only: counts, categories, sources, risk.
No cell value is returned, logged or stored. Rules inspect EVERY value (exact counts); the ML model inspects up to DETECTION_ML_MAX_VALUES unique
text values per column, and its counts are marked estimates when that cap is hit."""
import re
from collections import Counter

from app.core.config import get_settings
from app.detection import ml, risk
from app.detection.hybrid import Finding, merge
from app.detection.rules import ML_CATEGORIES, column_name_category, detect_rules

DETECTED = 0.6  # share of inspected values that must contain a category for the column to count as "detected" (below that: "suspected")
_NUMERIC = re.compile(r"^[\d\s.,+\-()/:]*$")


def _wholly_structured(text: str, spans) -> bool:
    return bool(spans) and any(s.start == 0 and s.end == len(text.strip()) for s in spans)


def detect_text(text: str, use_ml: bool = True, ml_error: list | None = None, use_rules: bool = True) -> list[Finding]:
    """Hybrid detection on one string. If ML fails the policy `rules_only` falls back to rules and records the reason in `ml_error`.
    `use_rules=False` (evaluation's ML-only configuration) skips the rule detectors."""
    rule_spans = detect_rules(text) if use_rules else []
    ml_spans = []
    if use_ml and not _wholly_structured(text, rule_spans):
        try:
            ml_spans = ml.detect_ml(text)
        except ml.MLUnavailable as e:
            if get_settings().detection_ml_fallback == "fail":
                raise
            if ml_error is not None and not ml_error:
                ml_error.append(str(e))
    return merge(rule_spans, ml_spans)[0]


def _evidence_kind(ev: set) -> str:
    return "validated checksum/range" if "validated" in ev else "format pattern" if "pattern" in ev else "model prediction"


def analyze(columns: list[str], rows: list[list], *, use_ml: bool = True, use_rules: bool = True, use_name: bool = True, protected: set[str] | None = None) -> dict:
    s = get_settings()
    protected = protected or set()
    ml_err: list[str] = []
    out_cols = []
    totals: Counter = Counter()
    exact_total: dict[str, bool] = {}
    ml_touched = False
    for idx, name in enumerate(columns):
        vals = [str(r[idx]).strip() for r in rows if r[idx] is not None and str(r[idx]).strip() != ""]
        inspected, nulls = len(vals), len(rows) - len(vals)
        freq = Counter(vals)
        cat_cells: Counter = Counter()  # category -> cells containing it (value-level: each cell counted once per category)
        cat_sources: dict[str, set] = {}
        cat_evidence: dict[str, set] = {}
        ml_scores: list[float] = []
        textual = [v for v in freq if not _NUMERIC.match(v)]
        pool = set(textual[: s.detection_ml_max_values]) if use_ml else set()
        cap_hit = use_ml and len(textual) > s.detection_ml_max_values
        ml_checked = 0
        for v, n in freq.items():
            fs = detect_text(v, use_ml=v in pool, ml_error=ml_err, use_rules=use_rules)
            if v in pool:
                ml_checked += n
                ml_touched = True
            for f in fs:
                cat_sources.setdefault(f.category, set()).update(f.sources)
                cat_evidence.setdefault(f.category, set()).add(f.evidence)
                if f.score is not None:
                    ml_scores.append(f.score)
            for c in {f.category for f in fs}:
                cat_cells[c] += n
        if cap_hit and ml_checked:  # extrapolate ML categories to the text cells the model did not see
            scale = sum(freq[v] for v in textual) / ml_checked
            for c in ML_CATEGORIES:
                if cat_cells.get(c):
                    cat_cells[c] = min(inspected, round(cat_cells[c] * scale))
        name_hit = column_name_category(name) if use_name else None
        top = cat_cells.most_common(1)
        ratio = top[0][1] / inspected if top and inspected else 0.0
        cat = top[0][0] if top else None
        if cat and ratio >= DETECTED:
            status = "detected"
        elif cat:
            status = "suspected"
        elif name_hit:
            cat, status = name_hit[0], "suspected"
        else:
            status = "unclassified"
        sources = set(cat_sources.get(cat, ())) if top else set()
        if name_hit and cat == name_hit[0]:
            sources.add("column_name")
        conflict = bool(name_hit and top and name_hit[0] != top[0][0])
        if conflict:
            sources.add("column_name")
        uncertain = status != "detected" or conflict
        rk = risk.assess(cat, ratio, status == "detected" and not conflict, name in protected)
        if status == "unclassified":
            ev = "No rule or model matched. This does not prove the column is non-sensitive."
        elif top:
            ev = f"{top[0][1]:,} of {inspected:,} values contain {cat} ({ratio:.0%}); evidence: {_evidence_kind(cat_evidence.get(cat, set()))}"
        else:
            ev = f"Column name suggests {cat}; no values confirmed it" + ("" if inspected else " (column is empty)")
        if conflict:
            ev += f"; the column name suggests {name_hit[0]}"
        exact = not (cap_hit and cat in ML_CATEGORIES)
        for c, n in cat_cells.items():
            totals[c] += n
            exact_total[c] = exact_total.get(c, True) and not (cap_hit and c in ML_CATEGORIES)
        out_cols.append({
            "column": name, "category": cat, "status": status, "sources": sorted(sources),
            "values_inspected": inspected, "null_count": nulls, "match_count": top[0][1] if top else 0, "match_ratio": round(ratio, 3), "exact": exact,
            "categories": {c: {"matches": n, "sources": sorted(cat_sources.get(c, []))} for c, n in cat_cells.most_common()},
            "evidence": ev, "uncertain": uncertain, "needs_review": uncertain,
            "ml_score_mean": round(sum(ml_scores) / len(ml_scores), 3) if ml_scores else None,
            "risk": rk["level"], "risk_points": rk["points"], "risk_explanation": rk["explanation"],
            "recommended_protection": rk["recommended_protection"], "protection_note": rk["protection_note"],
        })
    st = ml.status()
    used = bool(use_ml and ml_touched and not ml_err and st["state"] == "ready")
    err = (ml_err[0] if ml_err else (st["error"] if use_ml and st["state"] in ("failed", "disabled") else None)) if use_ml else "ML detection was not requested"
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Unclassified": 4}
    return {
        "columns": out_cols,
        "ml": {"requested": use_ml, "used": used, "mode": "hybrid" if used else "rules_only", "model": s.detection_ml_model if use_ml else None, "error": err},
        "summary": {
            "rows": len(rows), "columns": len(columns),
            "sensitive_columns": sum(1 for c in out_cols if c["status"] == "detected"),
            "suspected_columns": sum(1 for c in out_cols if c["status"] == "suspected"),
            "unclassified_columns": sum(1 for c in out_cols if c["status"] == "unclassified"),
            "by_category": {c: {"value_matches": n, "exact": exact_total.get(c, True)} for c, n in totals.most_common() if n},
            "highest_risk": min((c["risk"] for c in out_cols), key=lambda r: order.get(r, 9), default=None),
        },
    }
