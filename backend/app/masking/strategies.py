"""Masking strategies. Each returns a NEW value; stored originals are never touched.
Any failure falls back to REDACT (fail safe)."""
import datetime as dt
import hashlib
import hmac

from app.core.config import get_settings

STRATEGIES = ("ALLOW", "FULL_MASK", "PARTIAL_MASK", "REDACT", "HASH", "DENY")
FULL_MASK_TEXT = "********"  # fixed width so length is not leaked
REDACTED_TEXT = "[REDACTED]"

NUMERIC_BANDS = [0, 100_000, 500_000, 1_000_000, 2_500_000, 5_000_000, 10_000_000, 25_000_000]


def _hash_key() -> bytes:
    return (get_settings().jwt_secret or "dev").encode()


def full_mask(_value, _category=None):
    return FULL_MASK_TEXT


def redact(_value, _category=None):
    return REDACTED_TEXT


def hash_value(value, _category=None):
    digest = hmac.new(_hash_key(), str(value).encode(), hashlib.sha256).hexdigest()
    return f"h_{digest[:16]}"


def _band(n: float) -> str:
    lo = 0
    for b in NUMERIC_BANDS:
        if n >= b:
            lo = b
    idx = NUMERIC_BANDS.index(lo)
    if idx + 1 < len(NUMERIC_BANDS):
        return f"{lo:,}–{NUMERIC_BANDS[idx + 1]:,}"
    return f"{lo:,}+"


def partial_mask(value, category=None):
    if value is None:
        return None
    if isinstance(value, bool):
        return FULL_MASK_TEXT
    if isinstance(value, (int, float)):
        return _band(float(value))  # numeric -> range band
    if isinstance(value, dt.date):
        return str(value.year)  # date -> year only
    s = str(value)
    if "@" in s:  # email
        local, _, domain = s.partition("@")
        return f"{local[:1]}***@{domain}"
    if category == "DIRECT_IDENTIFIER":  # name -> initials
        return " ".join(f"{p[0]}***" for p in s.split() if p)
    if len(s) <= 4:
        return FULL_MASK_TEXT
    return "X" * (len(s) - 4) + s[-4:]  # ids/phones -> keep last 4


def apply_strategy(strategy: str, value, category: str | None = None):
    """Returns (ok, value). DENY is handled by the caller (field omitted)."""
    try:
        if strategy == "ALLOW":
            return value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else value
        if strategy == "FULL_MASK":
            return full_mask(value)
        if strategy == "PARTIAL_MASK":
            return partial_mask(value, category)
        if strategy == "HASH":
            return hash_value(value)
        return redact(value)
    except Exception:  # noqa: BLE001
        return REDACTED_TEXT
