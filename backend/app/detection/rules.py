"""Rule-based detectors (regex + validation). Each returns Spans; none stores or logs the matched text.

evidence: "validated" = a checksum/range check passed (Luhn card, IPv4 octets); "pattern" = format only (phone, e-mail, government-id shapes)."""
import re
from dataclasses import dataclass

from app.b1.detect import CARD_RE, EMAIL_RE, NAME_RULES, luhn_ok

CATEGORIES = ("EMAIL", "PHONE", "CARD_NUMBER", "IP_ADDRESS", "GOVERNMENT_ID", "PERSON", "LOCATION", "ORGANIZATION")
RULE_CATEGORIES = ("EMAIL", "PHONE", "CARD_NUMBER", "IP_ADDRESS", "GOVERNMENT_ID")
ML_CATEGORIES = ("PERSON", "LOCATION", "ORGANIZATION")
# Column-name-only categories (no value detector): they can be flagged by metadata but never "found" in values.
NAME_ONLY = ("FINANCIAL", "DATE_OF_BIRTH")
KIND_TO_CATEGORY = {
    "PAN": "GOVERNMENT_ID", "AADHAAR": "GOVERNMENT_ID", "SSN": "GOVERNMENT_ID", "EMAIL": "EMAIL", "PHONE": "PHONE", "CARD_NUMBER": "CARD_NUMBER", "CARD_META": "CARD_NUMBER",
    "FULL_NAME": "PERSON", "ADDRESS": "LOCATION", "POSTAL_CODE": "LOCATION", "DOB": "DATE_OF_BIRTH",
    "ACCOUNT_NUMBER": "FINANCIAL", "FINANCIAL_AMOUNT": "FINANCIAL", "TXN_REFERENCE": "FINANCIAL",
}
# Higher wins when two rule spans of different categories overlap (a Luhn-valid card beats a phone-shaped digit run).
PRIORITY = {"CARD_NUMBER": 5, "IP_ADDRESS": 4, "EMAIL": 4, "GOVERNMENT_ID": 3, "PHONE": 2}


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    category: str
    source: str            # "rule" | "ml"
    evidence: str          # "validated" | "pattern" | "model"
    score: float | None = None  # model score only; not a calibrated probability

    def overlaps(self, o: "Span") -> bool:
        return self.start < o.end and o.start < self.end


# Grouped identifiers only (bare digit runs are too ambiguous), and never a slice of a longer digit group such as a 16-digit card number.
AADHAAR_GROUPED = re.compile(r"(?<![\d])(?<!\d[ -])\d{4}[ -]\d{4}[ -]\d{4}(?![ -]?\d)")
SSN_GROUPED = re.compile(r"(?<![\d])(?<!\d[ -])\d{3}-\d{2}-\d{4}(?![ -]?\d)")
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
PHONE_PATTERNS = (
    re.compile(r"(?<![\w+])\+\d{1,3}[ -]?(?:\(?\d{2,5}\)?[ -]?)?\d{3,5}[ -]?\d{3,5}(?!\d)"),   # international +CC ...
    re.compile(r"(?<![\w+])\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)"),                            # US/CA 555-123-4567
    re.compile(r"(?<![\w+])[6-9]\d{4}[ -]?\d{5}(?!\d)"),                                       # Indian mobile
)


def _valid_ipv4(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 and (p == "0" or not p.startswith("0")) for p in parts)


def _phone_ok(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    return 10 <= len(digits) <= 13


def detect_rules(text: str) -> list[Span]:
    """All rule spans in `text`, already de-overlapped by PRIORITY (documented in docs/DETECTION.md)."""
    if not text or not isinstance(text, str):
        return []
    found: list[Span] = []
    for m in EMAIL_RE.finditer(text):
        found.append(Span(m.start(), m.end(), "EMAIL", "rule", "pattern"))
    for m in CARD_RE.finditer(text):
        raw = m.group()
        if luhn_ok(re.sub(r"[ -]", "", raw)):
            found.append(Span(m.start(), m.end(), "CARD_NUMBER", "rule", "validated"))
    for m in IPV4_RE.finditer(text):
        if _valid_ipv4(m.group()):
            found.append(Span(m.start(), m.end(), "IP_ADDRESS", "rule", "validated"))
    for m in re.finditer(r"(?<![A-Z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Z0-9])", text):
        found.append(Span(m.start(), m.end(), "GOVERNMENT_ID", "rule", "pattern"))
    for rx in (AADHAAR_GROUPED, SSN_GROUPED):
        for m in rx.finditer(text):
            found.append(Span(m.start(), m.end(), "GOVERNMENT_ID", "rule", "pattern"))
    for rx in PHONE_PATTERNS:
        for m in rx.finditer(text):
            if _phone_ok(m.group()):
                found.append(Span(m.start(), m.end(), "PHONE", "rule", "pattern"))
    return resolve_rule_overlaps(found)


def resolve_rule_overlaps(spans: list[Span]) -> list[Span]:
    """Keep the highest-priority span; on a tie the longer one; identical duplicates collapse."""
    ranked = sorted(spans, key=lambda s: (-PRIORITY.get(s.category, 0), -(s.end - s.start), s.start))
    kept: list[Span] = []
    for s in ranked:
        if not any(s.overlaps(k) for k in kept):
            kept.append(s)
    return sorted(kept, key=lambda s: s.start)


def column_name_category(name: str) -> tuple[str, str] | None:
    """Metadata heuristic: (category, b1 kind) from the column name alone, or None. Never proof of the column's contents."""
    low = (name or "").lower().strip()
    for kind, rx, _ in NAME_RULES:
        if rx.search(low):
            return KIND_TO_CATEGORY[kind], kind
    if re.search(r"organi[sz]ation|company|employer|(^|_)org(_|$)", low):
        return "ORGANIZATION", "ORGANIZATION"
    if re.search(r"(^|_)ip(_?addr(ess)?)?$|ipv4", low):
        return "IP_ADDRESS", "IP_ADDRESS"
    if re.search(r"city|country|state_|location|street", low):
        return "LOCATION", "LOCATION"
    return None
