"""Automatic PII / financial-data detection for the B1 engine.

For each column it combines three kinds of evidence and records only the RESULT (kind, tag, confidence, status, methods). Sampled values are used
in memory to compute match ratios and are never stored, logged or returned.
  column_name : abbreviation-aware rules (cust_nm, mob_no, pita_nm = father's name, pan_no, ...)
  value_pattern : regexes on a bounded random sample (PAN, Aadhaar-style 12 digits, SSN, e-mail, phone, ...), with a Luhn check for card numbers
  free_text   : patterns embedded inside long text (ticket text, narration, remarks, JSON blobs)
Confidence >= CONFIRMED means "confirmed"; between UNCERTAIN and CONFIRMED means "uncertain" (an administrator should review); below is untagged."""
import re
from dataclasses import dataclass, field

CONFIRMED, UNCERTAIN = 0.8, 0.5

# kind -> tag
TAG_OF = {
    "PAN": "PII_HIGH", "AADHAAR": "PII_HIGH", "SSN": "PII_HIGH", "FREE_TEXT_PII": "PII_HIGH",
    "FULL_NAME": "PII_MEDIUM", "PHONE": "PII_MEDIUM", "EMAIL": "PII_MEDIUM", "DOB": "PII_MEDIUM", "ADDRESS": "PII_MEDIUM", "POSTAL_CODE": "PII_MEDIUM",
    "ACCOUNT_NUMBER": "FINANCIAL_CONFIDENTIAL", "FINANCIAL_AMOUNT": "FINANCIAL_CONFIDENTIAL", "TXN_REFERENCE": "FINANCIAL_CONFIDENTIAL",
    "CARD_NUMBER": "PAYMENT_SENSITIVE", "CARD_META": "PAYMENT_SENSITIVE",
    "NON_SENSITIVE": "NON_SENSITIVE",
}
KINDS = tuple(TAG_OF)
TAGS = ("PII_HIGH", "PII_MEDIUM", "FINANCIAL_CONFIDENTIAL", "PAYMENT_SENSITIVE", "NON_SENSITIVE")

PAN_RE = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
AADHAAR_RE = re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)|(?<!\d)\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)|\+1[ -]?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
DIGITS_ONLY_RE = re.compile(r"^\d{9,18}$")
PERSON_RE = re.compile(r"^[A-Za-z][A-Za-z.'-]+(?:\s+[A-Za-z][A-Za-z.'-]+){1,3}$")

# Column-name rules, matched against the lower-cased column name. (kind, regex, strength): strong names are 0.7, weak 0.55.
NAME_RULES: list[tuple[str, re.Pattern, float]] = [
    ("CARD_NUMBER", re.compile(r"card_?(no|num|number)$"), 0.7),
    ("PAN", re.compile(r"(^|_)pan(_?no)?$"), 0.7),
    ("AADHAAR", re.compile(r"aadh?aar|uidai"), 0.7),
    ("SSN", re.compile(r"(^|_)ssn$|social_?sec"), 0.7),
    ("EMAIL", re.compile(r"e?mail"), 0.7),
    ("PHONE", re.compile(r"(^|_)(mob|mobile|phone|ph|tel|contact_?no)(_|$)|alt_mob|us_phone"), 0.7),
    ("DOB", re.compile(r"dob|birth"), 0.7),
    ("FULL_NAME", re.compile(r"(^|_)(cust_?nm|name_on_card|nominee_nm|pita_nm|mata_nm|father|mother|spouse|full_?name|first_?name|last_?name)"), 0.7),
    ("ADDRESS", re.compile(r"addr"), 0.7),
    ("POSTAL_CODE", re.compile(r"pincode|zip|postal"), 0.55),
    ("ACCOUNT_NUMBER", re.compile(r"(^|_)(acct|account)_?(no|num|number)$|linked_acct"), 0.7),
    ("FINANCIAL_AMOUNT", re.compile(r"(^|_)(curr_?bal|bal(_after)?|balance|amount|amt|amt_requested|credit_?limit|od_limit|outstanding|income|sanctioned|credit_?score|salary)"), 0.7),
    ("CARD_META", re.compile(r"^exp_(mm|yyyy|date)$"), 0.55),
    ("TXN_REFERENCE", re.compile(r"(^|_)(rrn|ref_?no|utr)(_|$)"), 0.55),
    ("FULL_NAME", re.compile(r"counterparty|payee|beneficiary"), 0.55),
]
FREE_TEXT_NAMES = re.compile(r"narration|remarks?|notes?|ticket_text|description|comment|extra_info|meta|message")
LONG_TEXT_TYPES = ("TEXT", "JSON", "JSONB", "CLOB")
BUSINESS_CONTACT = re.compile(r"^branch_|^(addr)$")  # branch phone/e-mail/address are organisation contact data, not personal data


def luhn_ok(digits: str) -> bool:
    if not 13 <= len(digits) <= 19 or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _is_card(v: str) -> bool:
    digits = re.sub(r"[ -]", "", v)
    return bool(CARD_RE.fullmatch(v)) and luhn_ok(digits)


VALUE_TESTS = {
    "PAN": lambda v: bool(re.fullmatch(PAN_RE, v)),
    "CARD_NUMBER": _is_card,
    "AADHAAR": lambda v: bool(AADHAAR_RE.fullmatch(v)) and not _is_card(v),
    "SSN": lambda v: bool(SSN_RE.fullmatch(v)),
    "EMAIL": lambda v: bool(re.fullmatch(EMAIL_RE, v)),
    "PHONE": lambda v: bool(PHONE_RE.fullmatch(v.strip())),
    "FULL_NAME": lambda v: bool(PERSON_RE.fullmatch(v)) and not any(ch.isdigit() for ch in v),
    "ACCOUNT_NUMBER": lambda v: bool(DIGITS_ONLY_RE.fullmatch(v)),
}
PUBLIC_VALUE_TESTS = {"IFSC": lambda v: bool(IFSC_RE.fullmatch(v))}  # recognised only to avoid mislabelling bank-code columns


@dataclass
class Detection:
    kind: str = "NON_SENSITIVE"
    tag: str = "NON_SENSITIVE"
    confidence: float = 0.0
    status: str = "none"
    methods: list[str] = field(default_factory=list)
    match_ratio: float = 0.0
    sample_size: int = 0
    rationale: str = ""


def _free_text_hits(values: list[str]) -> float:
    """Fraction of sampled texts that contain an embedded high-risk pattern (PAN, card, Aadhaar-style number, SSN, e-mail, phone)."""
    if not values:
        return 0.0
    hit = 0
    for v in values:
        if PAN_RE.search(v) or EMAIL_RE.search(v) or PHONE_RE.search(v) or SSN_RE.search(v) or any(luhn_ok(re.sub(r"[ -]", "", m.group())) for m in CARD_RE.finditer(v)) \
                or AADHAAR_RE.search(v):
            hit += 1
    return hit / len(values)


def classify_column(table: str, column: str, data_type: str, samples: list) -> Detection:
    """`samples` are raw sampled values (may contain None / non-strings). Returns the detection result only."""
    name = column.lower()
    values = [str(s).strip() for s in samples if s is not None and str(s).strip() != ""]
    n = len(values)
    d = Detection(sample_size=n)
    is_text_type = any(t in data_type.upper() for t in LONG_TEXT_TYPES)

    # 1) value evidence
    best_kind, best_ratio = None, 0.0
    distinct_ratio = len(set(values)) / n if n else 1.0
    if n:
        for kind, test in VALUE_TESTS.items():
            if kind == "FULL_NAME" and n >= 20 and distinct_ratio < 0.25:
                continue  # a handful of repeated words is a category (channel, status, mode), not a column of people's names
            ratio = sum(1 for v in values if test(v)) / n
            if ratio > best_ratio or (ratio == best_ratio and best_kind is None and ratio > 0):
                best_kind, best_ratio = kind, ratio
        if best_kind == "ACCOUNT_NUMBER" and best_ratio < 0.9:
            best_kind, best_ratio = None, 0.0  # a bare digit string is only convincing when nearly every value is one
        public = max(((k, sum(1 for v in values if t(v)) / n) for k, t in PUBLIC_VALUE_TESTS.items()), key=lambda x: x[1])
        if public[1] >= 0.9 and best_ratio < 0.5:
            d.methods.append("value_pattern")
            d.match_ratio, d.confidence, d.status = public[1], 0.9, "none"
            d.rationale = "bank code format (IFSC), public information"
            return d

    # 2) column-name evidence
    name_kind, name_strength = None, 0.0
    for kind, rx, strength in NAME_RULES:
        if rx.search(name):
            name_kind, name_strength = kind, strength
            break

    # Weak or generic value shapes never override a specific column name: a name-shaped value says little, and 9-18 digit strings are common
    # (internal ids, retrieval reference numbers). Where the name is silent the values decide, which is how an oddly named column is still found.
    if best_kind and name_kind and best_kind != name_kind and best_kind in ("FULL_NAME", "AADHAAR", "ACCOUNT_NUMBER", "SSN"):
        best_kind, best_ratio = None, 0.0
    if best_kind == "ACCOUNT_NUMBER" and not name_kind and re.search(r"(^|_)id$|_ref$|_code$", name):
        best_kind, best_ratio = None, 0.0  # an identifier column used as a key, not an account number

    # 3) free text (long text types or telling names) with embedded patterns
    looks_free = is_text_type or bool(FREE_TEXT_NAMES.search(name))
    ft_ratio = _free_text_hits(values) if (looks_free and n) else 0.0

    value_conf = 0.0
    if best_kind and best_ratio >= 0.3:
        value_conf = 0.95 if best_ratio >= 0.9 else 0.8 if best_ratio >= 0.6 else 0.6
    if best_kind == "FULL_NAME" and best_ratio < 0.8:
        value_conf = min(value_conf, 0.6)  # a name-shaped value is weak evidence on its own

    if looks_free and ft_ratio > 0 and not (best_kind and best_ratio >= 0.6):
        d.kind, d.tag = "FREE_TEXT_PII", TAG_OF["FREE_TEXT_PII"]
        d.methods = ["free_text_scan"] + (["column_name"] if FREE_TEXT_NAMES.search(name) else [])
        d.match_ratio = ft_ratio
        d.confidence = 0.95 if ft_ratio >= 0.2 else 0.85 if ft_ratio >= 0.05 else 0.6
        d.rationale = f"{ft_ratio:.0%} of sampled texts contain embedded identifiers"
    elif best_kind and value_conf and (not name_kind or name_kind == best_kind or value_conf >= name_strength + 0.1):
        d.kind, d.tag, d.match_ratio = best_kind, TAG_OF[best_kind], best_ratio
        d.methods = ["value_pattern"] + (["luhn"] if best_kind == "CARD_NUMBER" else []) + (["column_name"] if name_kind == best_kind else [])
        d.confidence = min(0.99, max(value_conf, name_strength) + (0.04 if name_kind == best_kind else 0.0))
        if name_kind and name_kind != best_kind:
            d.rationale = f"values look like {best_kind}; the column name suggests {name_kind}"
            d.confidence = min(d.confidence, 0.75)  # conflicting evidence: leave it for review
        else:
            d.rationale = f"{best_ratio:.0%} of sampled values match {best_kind}"
    elif name_kind:
        d.kind, d.tag, d.methods = name_kind, TAG_OF[name_kind], ["column_name"]
        d.confidence = name_strength
        d.rationale = "column name only" + ("" if n else "; column is empty so there is no value evidence")
        if n and name_kind in VALUE_TESTS and best_kind != name_kind:
            d.confidence = 0.55  # the name says one thing but the values disagree
            d.rationale = f"column name suggests {name_kind} but sampled values do not match"
        elif n and name_kind in ("FINANCIAL_AMOUNT",) and all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in values):
            d.methods.append("numeric_values")
            d.confidence = 0.85
            d.rationale = "amount-like column name with numeric values"
        elif n and name_kind == "DOB" and all(re.match(r"\d{4}-\d{2}-\d{2}", v) for v in values):
            d.methods.append("date_values")
            d.confidence = 0.9
            d.rationale = "birth-date column name with ISO dates"
        elif n and name_kind in ("ADDRESS", "FULL_NAME") and sum(1 for v in values if len(v) > 3) / n >= 0.8:
            d.methods.append("text_values")
            d.confidence = min(0.85, d.confidence + 0.15)
    if d.kind != "NON_SENSITIVE" and BUSINESS_CONTACT.search(name) or (table == "branches" and d.kind in ("PHONE", "EMAIL", "ADDRESS")):
        d.confidence = min(d.confidence, 0.6)  # organisation contact data: probably not personal, but worth a human look
        d.rationale = (d.rationale + "; " if d.rationale else "") + "business (branch) contact data, likely not personal"
    d.status = "confirmed" if d.confidence >= CONFIRMED else "uncertain" if d.confidence >= UNCERTAIN else "none"
    if d.status == "none":
        d.kind, d.tag = "NON_SENSITIVE", "NON_SENSITIVE"
    return d
