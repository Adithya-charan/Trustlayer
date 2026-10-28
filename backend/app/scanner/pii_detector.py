"""Field-level PII detection: column-name heuristics + value-pattern checks
(+ Microsoft Presidio when available). Raw sample values are examined in memory
only; the result carries ratios and rationale text, never values."""
import datetime as dt
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("trustlayer.scanner")

NAME_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"(^|_)pan($|_)|tax_?id|ssn|aadhaar|passport"), "GOVERNMENT_ID", "column name suggests a government/tax ID"),
    (re.compile(r"account|iban|card_?n|acct"), "ACCOUNT_IDENTIFIER", "column name suggests an account identifier"),
    (re.compile(r"email|e_mail|phone|mobile|msisdn|address|pincode|zip"), "CONTACT", "column name suggests contact details"),
    (re.compile(r"(full_|first_|last_|sur)?name$|^name"), "DIRECT_IDENTIFIER", "column name suggests a person's name"),
    (re.compile(r"income|salary|wage|liabilit|loan|debt|cover|assets?|goal|balance|premium|net_worth"), "FINANCIAL", "column name suggests a financial attribute"),
    (re.compile(r"birth|dob|dependent|gender|age$|city|religion|marital"), "DEMOGRAPHIC", "column name suggests a demographic attribute"),
]

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^(\+\d[\d \-]{8,14}|\d{10})$")  # needs + prefix or exactly 10 digits
ACCOUNT_RE = re.compile(r"^[0-9]{9,18}$")

VALUE_RULES = [
    (PAN_RE, "GOVERNMENT_ID", "values match the PAN format (AAAAA9999A)"),
    (EMAIL_RE, "CONTACT", "values match an email pattern"),
    (PHONE_RE, "CONTACT", "values match a phone-number pattern"),
    (ACCOUNT_RE, "ACCOUNT_IDENTIFIER", "values are long digit strings typical of account numbers"),
]

PRESIDIO_MAP = {
    "PERSON": "DIRECT_IDENTIFIER",
    "EMAIL_ADDRESS": "CONTACT",
    "PHONE_NUMBER": "CONTACT",
    "IN_PAN": "GOVERNMENT_ID",
    "US_SSN": "GOVERNMENT_ID",
    "IBAN_CODE": "ACCOUNT_IDENTIFIER",
    "CREDIT_CARD": "ACCOUNT_IDENTIFIER",
}


@dataclass
class Detection:
    category: str
    confidence: float
    rationale: list[str] = field(default_factory=list)


_presidio = None
_presidio_tried = False


def get_presidio():
    """Lazy-load Presidio; returns None if unavailable so scans degrade gracefully."""
    global _presidio, _presidio_tried
    if _presidio_tried:
        return _presidio
    _presidio_tried = True
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
        )
        _presidio = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
    except Exception as exc:  # noqa: BLE001
        log.warning("Presidio unavailable (%s); using deterministic rules only", type(exc).__name__)
        _presidio = None
    return _presidio


def _presidio_vote(samples: list[str]) -> tuple[str | None, float]:
    engine = get_presidio()
    if engine is None or not samples:
        return None, 0.0
    votes: dict[str, int] = {}
    for s in samples[:10]:
        try:
            for r in engine.analyze(text=s, language="en", score_threshold=0.5):
                cat = PRESIDIO_MAP.get(r.entity_type)
                if cat:
                    votes[cat] = votes.get(cat, 0) + 1
        except Exception:  # noqa: BLE001
            return None, 0.0
    if not votes:
        return None, 0.0
    cat = max(votes, key=votes.get)
    return cat, votes[cat] / min(len(samples), 10)


def detect_field(column: str, data_type: str, samples: list, use_presidio: bool = True) -> Detection:
    col = column.lower()
    rationale: list[str] = []
    scores: dict[str, float] = {}

    for pattern, category, why in NAME_RULES:
        if pattern.search(col):
            scores[category] = max(scores.get(category, 0), 0.65)
            rationale.append(f"{why} ('{column}')")
            break

    str_samples = [str(s) for s in samples if s is not None]
    if str_samples:
        for rx, category, why in VALUE_RULES:
            ratio = sum(1 for s in str_samples if rx.match(s.strip())) / len(str_samples)
            if ratio >= 0.8:
                scores[category] = max(scores.get(category, 0), 0.9 if category in ("GOVERNMENT_ID", "CONTACT") else 0.7)
                rationale.append(f"{why} ({int(ratio * 100)}% of sampled rows)")
                break
        if all(isinstance(s, dt.date) for s in samples if s is not None) and "DEMOGRAPHIC" not in scores:
            scores["DEMOGRAPHIC"] = 0.5
            rationale.append("values are dates (possible date of birth)")
        if use_presidio and data_type.upper().startswith(("VARCHAR", "TEXT", "STRING")):
            cat, ratio = _presidio_vote(str_samples)
            if cat and ratio >= 0.5:
                scores[cat] = max(scores.get(cat, 0), 0.5 + 0.4 * ratio)
                rationale.append(f"Presidio recognised {cat.lower().replace('_', ' ')} entities in {int(ratio * 100)}% of samples")

    if not scores:
        return Detection("NON_SENSITIVE", 0.6, ["no sensitive name or value pattern found"])
    best = max(scores, key=scores.get)
    conf = scores[best]
    if len(scores) > 1 and len({c for c in scores}) > 1:
        # agreeing signals strengthen confidence; disagreeing ones are surfaced for review
        rationale.append("multiple signals considered; review recommended" if len(set(scores)) > 1 and scores[best] < 0.9 else "signals agree")
    return Detection(best, round(min(conf + (0.05 if len(rationale) > 1 else 0), 0.99), 2), rationale)
