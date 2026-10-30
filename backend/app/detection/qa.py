"""Deterministic answers about an analysis. Every number is computed from stored findings; the LLM may only phrase the result."""
from app.detection.rules import CATEGORIES

KNOWN = CATEGORIES + ("FINANCIAL", "DATE_OF_BIRTH")
ALIASES = {"email": "EMAIL", "emails": "EMAIL", "phone": "PHONE", "phones": "PHONE", "card": "CARD_NUMBER", "cards": "CARD_NUMBER", "ip": "IP_ADDRESS",
           "person": "PERSON", "people": "PERSON", "name": "PERSON", "names": "PERSON", "location": "LOCATION", "address": "LOCATION", "organization": "ORGANIZATION"}


def norm_category(c: str | None) -> str | None:
    if not c:
        return None
    key = c.strip().upper().replace(" ", "_")
    return key if key in KNOWN else ALIASES.get(c.strip().lower())


def count_category(item: dict, category: str) -> dict:
    res, cat = item["result"], norm_category(category)
    if cat is None:
        return {"found": False, "message": "That is not a category TrustLayer detects."}
    info = res["summary"]["by_category"].get(cat)
    scope = f"{res['summary']['rows']:,} rows x {res['summary']['columns']} columns in {item['name']}"
    if not info:
        return {"found": True, "category": cat, "matches": 0, "columns": [], "exact": True, "scope": scope,
                "note": "No values matched. Detectors have limits, so this is not proof the data is free of it."}
    cols = [c["column"] for c in res["columns"] if cat in c["categories"]]
    return {"found": True, "category": cat, "matches": info["value_matches"], "columns": cols, "exact": info["exact"], "scope": scope,
            "note": "Exact count of values (cells) containing it." if info["exact"] else "Estimate: the ML model checked a capped sample of unique values."}


def highest_risk(item: dict, limit: int = 3) -> list[dict]:
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    cols = [c for c in item["result"]["columns"] if c["risk"] in order]
    cols.sort(key=lambda c: (order[c["risk"]], -(c["risk_points"] or 0), -c["match_ratio"]))
    return [{k: c[k] for k in ("column", "category", "risk", "status", "risk_explanation", "recommended_protection")} for c in cols[:limit]]


def column_info(item: dict, column: str) -> dict | None:
    for c in item["result"]["columns"]:
        if c["column"].lower() == column.strip().lower():
            return {k: c[k] for k in ("column", "category", "status", "sources", "evidence", "risk", "risk_explanation", "recommended_protection", "protection_note", "uncertain", "exact")}
    return None


def summary(item: dict) -> dict:
    r = item["result"]
    return {"name": item["name"], **r["summary"], "mode": r["ml"]["mode"], "ml_error": r["ml"]["error"], "top_risks": highest_risk(item, 3)}
