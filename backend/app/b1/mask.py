"""Role-based dynamic masking for the B1 engine. Masking is applied to the RETURNED copy of each value; stored data is never modified.

Roles (the organizer's sample users): Admin sees real values; Support sees partially masked values (e.g. 4111-XXXX-XXXX-1111); Analyst sees
redacted values or stable keyed hashes (so identifiers can still be joined/deduplicated without being disclosed) and is denied the most
restricted identifiers entirely. Anything unknown fails closed."""
import hashlib
import hmac
import re
from decimal import Decimal

from app.b1.detect import AADHAAR_RE, CARD_RE, EMAIL_RE, PAN_RE, PHONE_RE, SSN_RE, luhn_ok
from app.core.config import get_settings

ROLES = ("Admin", "Support", "Analyst")
STRATEGIES = ("ALLOW", "PARTIAL", "REDACT", "HASH", "DENY")
ROLE_ALIASES = {"Admin": "Admin", "security_admin": "Admin", "Support": "Support", "Analyst": "Analyst", "analyst": "Analyst"}
REDACTED = "[REDACTED]"
SENSITIVE_TAGS = ("PII_HIGH", "PII_MEDIUM", "FINANCIAL_CONFIDENTIAL", "PAYMENT_SENSITIVE")

# Analyst policy: hashes for identifiers usable as join keys, outright denial for the most restricted national IDs, redaction for the rest.
ANALYST_HASH = {"PAN", "CARD_NUMBER", "ACCOUNT_NUMBER", "TXN_REFERENCE"}
ANALYST_DENY = {"AADHAAR", "SSN"}


def normalize_role(role: str) -> str:
    """Maps an authenticated account role to a B1 role. Unknown roles are refused, never defaulted to a more permissive one."""
    if role not in ROLE_ALIASES:
        raise PermissionError("role is not permitted to use the data protection engine")
    return ROLE_ALIASES[role]


def default_strategy(role: str, kind: str, tag: str) -> str:
    """The built-in policy (used when no Admin-edited policy exists)."""
    role = normalize_role(role)
    if role == "Admin":
        return "ALLOW"
    if tag == "NON_SENSITIVE":
        return "ALLOW"
    if role == "Support":
        return "PARTIAL"
    if kind in ANALYST_DENY:
        return "DENY"
    if kind in ANALYST_HASH:
        return "HASH"
    return "REDACT"


def strategy_for(role: str, kind: str, tag: str, overrides: dict | None = None) -> str:
    """Effective strategy: Admin always ALLOW, non-sensitive columns always ALLOW, otherwise an Admin-edited policy (`overrides`: kind -> (strategy,
    source), already resolved user-over-role by app.b1.policy.load) else the built-in default. Anything unknown fails closed."""
    role = normalize_role(role)
    if role == "Admin" or tag == "NON_SENSITIVE":
        return "ALLOW"
    if overrides and kind in overrides:
        strategy = overrides[kind][0]
        if strategy not in STRATEGIES:
            raise PermissionError("unknown masking strategy")
        return strategy
    return default_strategy(role, kind, tag)


def policy_matrix(kinds: list[str], role_overrides: dict | None = None) -> dict:
    """role -> kind -> strategy. `role_overrides` is role -> {kind: (strategy, source)} (see app.b1.policy.load_roles)."""
    from app.b1.detect import TAG_OF

    role_overrides = role_overrides or {}
    return {role: {k: strategy_for(role, k, TAG_OF[k], role_overrides.get(role)) for k in kinds} for role in ROLES}


def _hash_key() -> bytes:
    return hmac.new(get_settings().jwt_secret.encode(), b"b1-hash-key", hashlib.sha256).digest()


def hash_value(kind: str, value) -> str:
    """Keyed, stable and not reversible: the same input gives the same hash (joinable), but it cannot be recomputed without the server key."""
    norm = re.sub(r"[\s-]", "", str(value)).upper() if kind in ("PAN", "CARD_NUMBER", "ACCOUNT_NUMBER", "AADHAAR", "SSN") else str(value).strip()
    return "h_" + hmac.new(_hash_key(), f"{kind}:{norm}".encode(), hashlib.sha256).hexdigest()[:16]


def _keep_alnum(text: str, head: int, tail: int) -> str:
    """Replace letters/digits with X except the first `head` and last `tail` alphanumerics; separators and spacing stay in place."""
    idx = [i for i, ch in enumerate(text) if ch.isalnum()]
    keep = set(idx[:head]) | set(idx[len(idx) - tail:] if tail else [])
    return "".join(ch if (not ch.isalnum() or i in keep) else "X" for i, ch in enumerate(text))


def _band(value) -> str:
    try:
        v = abs(Decimal(str(value)))
    except Exception:  # noqa: BLE001
        return REDACTED
    if v < 10_000:
        return "under 10,000"
    for lo, hi in ((10_000, 100_000), (100_000, 1_000_000), (1_000_000, 10_000_000), (10_000_000, 100_000_000)):
        if lo <= v < hi:
            return f"{lo:,}-{hi - 1:,}"
    return "100,000,000 or more"


def _partial(kind: str, value, names: frozenset[str] | None = None):
    if value is None:
        return None
    s = str(value)
    if kind == "CARD_NUMBER":
        return _keep_alnum(s, 4, 4)  # 4111-1111-1111-1111 -> 4111-XXXX-XXXX-1111
    if kind == "PAN":
        return _keep_alnum(s, 0, 4)
    if kind in ("AADHAAR", "SSN", "ACCOUNT_NUMBER", "TXN_REFERENCE", "PHONE"):
        return _keep_alnum(s, 0, 4)
    if kind == "EMAIL":
        local, _, domain = s.partition("@")
        return f"{local[:1]}***@{domain}" if domain else REDACTED
    if kind == "FULL_NAME":
        return " ".join(w[:1] + "*" * max(len(w) - 1, 2) for w in s.split())
    if kind == "DOB":
        return f"{s[:4]}-XX-XX" if re.match(r"\d{4}", s) else REDACTED
    if kind == "ADDRESS":
        parts = [p.strip() for p in s.split(",")]
        return ", ".join(["X" * 6] * (len(parts) - 1) + [parts[-1]]) if len(parts) > 1 else "X" * min(len(s), 12)
    if kind == "POSTAL_CODE":
        return _keep_alnum(s, 3, 0)
    if kind in ("FINANCIAL_AMOUNT", "CARD_META"):
        return _band(value) if kind == "FINANCIAL_AMOUNT" else "XX"
    if kind == "FREE_TEXT_PII":
        return scrub_text(s, "PARTIAL", names)
    return REDACTED  # unknown kind: fail closed


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z.'-]*")


def scrub_names(text: str, names: frozenset[str] | None, strategy: str) -> str:
    """Masks full names that appear in free text and are known from the database's own name columns (dictionary-based, whole-name match, 2-4 words,
    case-insensitive). Regexes cannot recognise a person's name inside a sentence; this closes that gap for names the database itself holds.
    Limits: a single first name or a misspelling is not recognised."""
    if not names or not text:
        return text
    toks = [(m.start(), m.end(), m.group().lower().strip(".'-")) for m in TOKEN_RE.finditer(text)]
    spans, i = [], 0
    while i < len(toks):
        hit = None
        for n in (4, 3, 2):
            if i + n > len(toks):
                continue
            window = toks[i:i + n]
            if any(not text[window[k][1]:window[k + 1][0]].isspace() for k in range(n - 1)):
                continue  # words must be separated by plain whitespace to count as one name
            if " ".join(t[2] for t in window) in names:
                hit = (window[0][0], window[-1][1], n)
                break
        if hit:
            spans.append(hit)
            i += hit[2]
        else:
            i += 1
    for start, end, _ in reversed(spans):
        original = text[start:end]
        text = text[:start] + (_partial("FULL_NAME", original) if strategy == "PARTIAL" else "[REDACTED:NAME]") + text[end:]
    return text


def scrub_text(text: str, strategy: str, names: frozenset[str] | None = None) -> str:
    """Masks identifiers embedded in free text (PAN, card, Aadhaar-style, SSN, e-mail, phone, and known full names). PARTIAL keeps the last digits; others redact."""
    text = scrub_names(text, names, strategy)
    def card_sub(t):
        def _r(m):
            digits = re.sub(r"[ -]", "", m.group())
            if not luhn_ok(digits):
                return m.group()
            return _keep_alnum(m.group(), 4, 4) if strategy == "PARTIAL" else "[REDACTED:CARD_NUMBER]"
        return CARD_RE.sub(_r, t)

    text = card_sub(text)
    for rx, kind in ((PAN_RE, "PAN"), (EMAIL_RE, "EMAIL"), (SSN_RE, "SSN"), (AADHAAR_RE, "AADHAAR"), (PHONE_RE, "PHONE")):
        def _r(m, kind=kind):
            # No "already masked" shortcut: a real identifier may legitimately contain the letter X. The masked forms produced below
            # (XXXX…, [REDACTED:…], a***@…) cannot match any of these patterns, so the passes never re-mask each other.
            if strategy == "PARTIAL":
                return f"{m.group()[:1]}***@{m.group().partition('@')[2]}" if kind == "EMAIL" else _keep_alnum(m.group(), 0, 4)
            return f"[REDACTED:{kind}]"
        text = rx.sub(_r, text)
    return text


def apply_strategy(strategy: str, kind: str, value, names: frozenset[str] | None = None):
    """Returns the value as the given role may see it. None (NULL) stays None under every strategy."""
    if value is None or strategy == "ALLOW":
        return value
    if strategy == "PARTIAL":
        return _partial(kind, value, names)
    if strategy == "HASH":
        return hash_value(kind, value)
    if strategy == "REDACT":
        return scrub_text(str(value), "REDACT", names) if kind == "FREE_TEXT_PII" else REDACTED
    raise PermissionError("column is restricted for this role")  # DENY is handled by withholding the column before values are read
