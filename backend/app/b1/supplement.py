"""Compatibility layer: lets the hybrid detector's contextual ML evidence supplement the B1 database classifier (see docs/DB_DISCOVERY_ML.md).

Rules of the mapping (conservative by design):
  * Only columns the original classifier left UNCLASSIFIED (status "none") are considered. Its confirmed and uncertain results are never changed.
  * Only the model's PERSON and LOCATION labels map to existing B1 kinds (FULL_NAME, ADDRESS), because those kinds exist and mean the same thing.
    ORGANIZATION has no B1 kind and is not personal data by itself, so it is not stored. IP_ADDRESS and GOVERNMENT_ID are rule categories with no
    model involved and no unambiguous B1 kind, so they are not mapped.
  * An ML-supplemented column is stored as UNCERTAIN (confidence 0.6, status "uncertain"), never "confirmed". Its methods include "ml_ner".
  * The model must label at least MIN_SHARE of the column's distinct sampled text values with the category, to avoid one stray match deciding a column.
  * Shape checks (found on the organizer SQLite data): values under 3 characters are not considered (codes such as DR/CR were read as places), and a
    PERSON suggestion needs most values to be two or more words, the same shape the original classifier uses for full names.
  * Names and address pieces are never guessed from column names here: this module reads values only.
Confidence is not a probability; the score is not stored. Masking and risk follow the stored kind/tag exactly as for any other uncertain field.
"""
from app.b1.detect import CONFIRMED, Detection, TAG_OF, UNCERTAIN
from app.detection import ml

MAP = {"PERSON": "FULL_NAME", "LOCATION": "ADDRESS"}
MIN_SHARE = 0.6
TEXT_TYPES = ("CHAR", "TEXT", "CLOB", "STRING")
EXCLUDED_TABLES = ("branches",)  # branch addresses and phones are organisation contact data, not personal data (see detect.BUSINESS_CONTACT)
ML_METHOD = "ml_ner"


def eligible(table: str, data_type: str, det: Detection) -> bool:
    if det.status != "none" or table in EXCLUDED_TABLES:
        return False
    return any(t in data_type.upper() for t in TEXT_TYPES)


def distinct_text(values: list, cap: int) -> list[str]:
    seen: list[str] = []
    for v in values:
        s = str(v).strip() if v is not None else ""
        if len(s) >= 3 and not s.replace(" ", "").replace(".", "").replace(",", "").replace("-", "").isdigit() and s not in seen:  # 1-2 character codes are not places
            seen.append(s)
            if len(seen) >= cap:
                break
    return seen


def apply(det: Detection, values: list, cap: int) -> tuple[Detection, bool]:
    """Returns (detection, supplemented). Raises ml.MLUnavailable when the model cannot be used; the caller falls back to the original result."""
    pool = distinct_text(values, cap)
    if not pool:
        return det, False
    hits: dict[str, int] = {}
    for v in pool:
        cats = {s.category for s in ml.detect_ml(v) if s.category in MAP}
        for c in cats:
            hits[c] = hits.get(c, 0) + 1
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked or ranked[0][1] / len(pool) < MIN_SHARE:
        return det, False
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return det, False  # two categories tie: the column is ambiguous, so the model decides nothing
    cat, n = ranked[0]
    if cat == "PERSON" and sum(1 for v in pool if len(v.split()) >= 2) / len(pool) < MIN_SHARE:
        return det, False  # the original classifier's own FULL_NAME shape is two or more words; single words (relationships, codes) are not names
    share = n / len(pool)
    kind = MAP[cat]
    det.kind, det.tag = kind, TAG_OF[kind]
    det.confidence = UNCERTAIN + 0.1  # inside the uncertain band: never reaches CONFIRMED
    det.status = "uncertain"
    det.methods = [ML_METHOD]
    det.match_ratio = round(share, 3)
    det.rationale = f"ML model suggests {cat.lower()} in {share:.0%} of sampled values; not confirmed, needs human review"[:200]
    assert det.confidence < CONFIRMED
    return det, True
