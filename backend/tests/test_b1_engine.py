"""Unit tests: automatic PII detection and masking strategies (no database, no network)."""
import pytest

from app.b1 import mask
from app.b1.detect import CONFIRMED, TAG_OF, classify_column, luhn_ok
from tests.b1_fixture import luhn_card, pan
import random

RNG = random.Random(3)
PANS = [pan(RNG) for _ in range(60)]
CARDS = [luhn_card(RNG) for _ in range(60)]


def detect(column, values, dtype="VARCHAR(30)", table="t"):
    return classify_column(table, column, dtype, values)


# ---------- detection ----------
def test_pan_detected_by_value_and_name():
    d = detect("pan_no", PANS)
    assert (d.kind, d.tag, d.status) == ("PAN", "PII_HIGH", "confirmed") and "value_pattern" in d.methods and "column_name" in d.methods


def test_generically_named_column_is_found_by_its_values():
    d = detect("col_7", PANS)  # the organizer's pack hides PANs in a column called col_7
    assert d.kind == "PAN" and d.status == "confirmed" and d.methods == ["value_pattern"]


def test_card_numbers_need_the_luhn_check():
    good = detect("CARD_NO", [f"{c[:4]}-{c[4:8]}-{c[8:12]}-{c[12:]}" for c in CARDS])
    assert good.kind == "CARD_NUMBER" and "luhn" in good.methods and good.tag == "PAYMENT_SENSITIVE"
    fake = detect("some_ref", ["1234567890123456"] * 30 + ["9876543210987654"] * 30)
    assert fake.kind != "CARD_NUMBER" and not luhn_ok("1234567890123456")


@pytest.mark.parametrize("values,kind", [
    (["987-65-4321", "912 34 5678", "900123456"] * 10, "SSN"),
    (["a.b@mail.example", "x_y@bank.example", "q@z.example"] * 10, "EMAIL"),
    (["+91 99999 12345", "+91-9999912345", "9000012345", "+1 (510) 555-0165"] * 8, "PHONE"),
    (["1234 5678 9012", "2345 6789 0123", "345678901234"] * 10, "AADHAAR"),
])
def test_value_patterns(values, kind):
    d = detect("mystery", values)
    assert d.kind == kind and d.status == "confirmed"


def test_free_text_with_embedded_identifiers_is_flagged():
    texts = [f"please call me on +91 99999 {i:05d} thanks" for i in range(30)] + ["no personal data here"] * 30
    d = detect("ticket_text", texts, "TEXT")
    assert d.kind == "FREE_TEXT_PII" and d.tag == "PII_HIGH" and "free_text_scan" in d.methods
    clean = detect("notes", ["resolved by agent", "customer was polite"] * 30, "TEXT")
    assert clean.tag == "NON_SENSITIVE"


def test_amounts_and_names_by_column_name():
    amt = detect("curr_bal", [str(x * 1000.55) for x in range(1, 40)], "DECIMAL(15,2)")
    assert amt.kind == "FINANCIAL_AMOUNT" and amt.tag == "FINANCIAL_CONFIDENTIAL" and amt.status == "confirmed"
    names = detect("cust_nm", [f"Name{chr(65 + i % 20)} Surname{chr(70 + i % 15)}" for i in range(60)])
    assert names.kind == "FULL_NAME"
    dob = detect("dob_dt", ["1985-04-12", "1990-11-30"] * 20, "DATE")
    assert dob.kind == "DOB" and dob.status == "confirmed"


def test_uncertain_vs_confirmed_distinction():
    branch = detect("branch_phone", ["+91 99999 00001", "+91 99999 00002"] * 10, table="branches")
    assert branch.status == "uncertain" and "branch" in branch.rationale  # organisation contact data is flagged for human review
    only_name = detect("pan_no", [])  # an empty column: the name is the only evidence
    assert only_name.status == "uncertain" and only_name.methods == ["column_name"] and "empty" in only_name.rationale
    conflicting = detect("pan_no", ["hello", "world"] * 20)
    assert conflicting.confidence < CONFIRMED


def test_false_positive_guards():
    assert detect("txn_id", ["".join(str((i * 7 + j) % 10) for j in range(16)) for i in range(60)]).tag == "NON_SENSITIVE"  # internal key
    assert detect("channel", ["Call Centre", "Mobile App", "Branch Visit"] * 30).tag == "NON_SENSITIVE"  # categorical text, not names
    assert detect("ifsc", ["SAFF0027168", "SAFF0045392"] * 20).tag == "NON_SENSITIVE"  # public bank code
    assert detect("rrn", ["".join(str((i + j) % 10) for j in range(12)) for i in range(60)]).kind == "TXN_REFERENCE"  # not an Aadhaar number


def test_nulls_empty_and_odd_values_do_not_crash():
    assert detect("anything", [None, None, ""]).tag == "NON_SENSITIVE"
    assert detect("anything", [None, 12, 3.5, b"x", {"a": 1}]).status in ("none", "uncertain", "confirmed")
    assert detect("anything", []).sample_size == 0


def test_detection_record_never_contains_sampled_values():
    d = detect("pan_no", PANS)
    dumped = repr(d.__dict__)
    assert not any(p in dumped for p in PANS)


# ---------- masking ----------
def test_card_partial_format_matches_the_brief():
    assert mask.apply_strategy("PARTIAL", "CARD_NUMBER", "4111-1111-1111-1111") == "4111-XXXX-XXXX-1111"
    assert mask.apply_strategy("PARTIAL", "CARD_NUMBER", "4111 1111 1111 1111") == "4111 XXXX XXXX 1111"
    assert mask.apply_strategy("PARTIAL", "CARD_NUMBER", "4111111111111111") == "4111XXXXXXXX1111"


@pytest.mark.parametrize("kind,value,expected", [
    ("PAN", "ABCDE0000F", "XXXXXX000F"),
    ("AADHAAR", "1234 5678 9012", "XXXX XXXX 9012"),
    ("SSN", "987-65-4321", "XXX-XX-4321"),
    ("PHONE", "+91 99999 12345", "+XX XXXXX X2345"),
    ("EMAIL", "anita.rao@saffronbank.example", "a***@saffronbank.example"),
    ("FULL_NAME", "Anita Rao", "A**** R**"),
    ("DOB", "1985-04-12", "1985-XX-XX"),
    ("ACCOUNT_NUMBER", "12345678901234", "XXXXXXXXXX1234"),
])
def test_partial_masks(kind, value, expected):
    assert mask.apply_strategy("PARTIAL", kind, value) == expected


def test_amounts_become_bands_and_text_is_scrubbed():
    assert mask.apply_strategy("PARTIAL", "FINANCIAL_AMOUNT", 13652.3) == "10,000-99,999"
    assert mask.apply_strategy("PARTIAL", "FINANCIAL_AMOUNT", 5) == "under 10,000"
    text = "call +91 99999 12345 or mail a.b@mail.example, PAN ABCDE0000F, card 4111-1111-1111-1111"
    partial, red = mask.apply_strategy("PARTIAL", "FREE_TEXT_PII", text), mask.apply_strategy("REDACT", "FREE_TEXT_PII", text)
    for raw in ("ABCDE0000F", "4111-1111-1111-1111", "a.b@mail.example", "99999 12345"):
        assert raw not in partial and raw not in red
    assert "[REDACTED:PAN]" in red and "[REDACTED:CARD_NUMBER]" in red and "[REDACTED:EMAIL]" in red
    assert "4111-XXXX-XXXX-1111" in partial


def test_hash_is_stable_keyed_and_not_the_value():
    h1, h2 = mask.hash_value("PAN", "ABCDE0000F"), mask.hash_value("PAN", "ABCDE0000F")
    assert h1 == h2 and h1.startswith("h_") and "ABCDE" not in h1
    assert mask.hash_value("PAN", "abcde0000f") == h1  # normalised
    assert mask.hash_value("PAN", "ABCDE0000G") != h1 and mask.hash_value("CARD_NUMBER", "ABCDE0000F") != h1


def test_null_stays_null_for_every_strategy():
    for s in ("ALLOW", "PARTIAL", "REDACT", "HASH"):
        assert mask.apply_strategy(s, "PAN", None) is None


def test_policy_per_role():
    assert all(mask.strategy_for("Admin", k, TAG_OF[k]) == "ALLOW" for k in TAG_OF)
    assert mask.strategy_for("Support", "CARD_NUMBER", "PII_HIGH") == "PARTIAL"
    assert mask.strategy_for("Support", "NON_SENSITIVE", "NON_SENSITIVE") == "ALLOW"
    assert mask.strategy_for("Analyst", "PAN", "PII_HIGH") == "HASH"
    assert mask.strategy_for("Analyst", "FULL_NAME", "PII_MEDIUM") == "REDACT"
    assert mask.strategy_for("Analyst", "SSN", "PII_HIGH") == "DENY" and mask.strategy_for("Analyst", "AADHAAR", "PII_HIGH") == "DENY"
    assert mask.strategy_for("security_admin", "PAN", "PII_HIGH") == "ALLOW" and mask.strategy_for("analyst", "PAN", "PII_HIGH") == "HASH"


@pytest.mark.parametrize("role", ["", "advisor", "compliance_officer", "ADMIN", "root", "Admin ", None])
def test_unknown_roles_fail_closed(role):
    with pytest.raises(PermissionError):
        mask.strategy_for(role, "PAN", "PII_HIGH")


def test_unknown_kind_is_redacted_not_leaked():
    assert mask.apply_strategy("PARTIAL", "UNCLASSIFIED", "secret-value") == mask.REDACTED
    with pytest.raises(PermissionError):
        mask.apply_strategy("DENY", "PAN", "ABCDE0000F")


@pytest.mark.parametrize("pan_value", ["LKCXL0000A", "XXXXX0000X", "ABCDE0000F", "XAXAX0000X"])
def test_identifiers_containing_the_letter_x_are_still_masked_in_free_text(pan_value):
    """Regression: free-text masking once skipped any match containing 'X' (assuming it was already masked), leaking real PANs such as LKCXL0000A."""
    text = f"my PAN is {pan_value} please call"
    for strategy in ("PARTIAL", "REDACT"):
        out = mask.apply_strategy(strategy, "FREE_TEXT_PII", text)
        assert pan_value not in out, (strategy, out)
    assert mask.apply_strategy("REDACT", "FREE_TEXT_PII", text) == "my PAN is [REDACTED:PAN] please call"


def test_known_full_names_are_scrubbed_from_free_text_but_not_other_words():
    names = frozenset({"anita rao", "ravi kumar singh"})
    text = "Hi, Anita Rao called; later RAVI KUMAR SINGH wrote. Rao alone and Anita alone stay. Mr. anita   rao again."
    red = mask.apply_strategy("REDACT", "FREE_TEXT_PII", text, names)
    assert "[REDACTED:NAME]" in red and "Anita Rao" not in red and "RAVI KUMAR SINGH" not in red
    assert "Rao alone and Anita alone stay" in red  # single words are not treated as a full name
    part = mask.apply_strategy("PARTIAL", "FREE_TEXT_PII", "Dear Anita Rao, thanks", names)
    assert "Anita Rao" not in part and "A**** R**" in part
    assert mask.apply_strategy("REDACT", "FREE_TEXT_PII", "Anita, Rao (two separate words)", names) == "Anita, Rao (two separate words)"  # punctuation breaks the name
    assert mask.apply_strategy("REDACT", "FREE_TEXT_PII", "plain text", None) == "plain text"
