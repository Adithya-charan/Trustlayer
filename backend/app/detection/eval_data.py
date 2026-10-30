"""Synthetic labelled data for evaluation. No real person's data: every name, number and address is invented or a published test value.

ANNOTATION RULES (applied identically to every example)
  1. Text items mark gold spans inline as [[CATEGORY|text]]; the span is exactly the identifier, without surrounding words or punctuation.
  2. EMAIL: any syntactically valid address. PHONE: a 10-13 digit telephone number in a common national/international layout.
     CARD_NUMBER: 13-19 digits that pass the Luhn check (published test numbers). A digit run that fails Luhn is NOT a card.
     GOVERNMENT_ID: a PAN (5 letters, 4 digits, 1 letter), or a grouped 12-digit (4-4-4) / SSN-style (3-2-4) national id.
     IP_ADDRESS: a dotted-quad IPv4 with every octet 0-255, whatever its context (a version string like 1.2.3.4 counts; this is deliberate).
  3. PERSON: a named individual. LOCATION: a place name (city, country, region, street address). ORGANIZATION: a company/institution used as an organisation.
     A common noun or a word used in a non-entity sense (a fruit, a planet) is NOT labelled.
  4. A value nested in another value is labelled once, as the outer one (the local part of an e-mail is not also a PERSON).
  5. Null/empty values carry no labels. Order numbers, ticket ids, dates and amounts are not PII categories here.
  6. Column items: sensitive = the column semantically holds personal/financial data, judged from its meaning; `category` is the dominant category.

SPLITS: DEV was used while writing the rules. HELD_OUT was written before any evaluation was run and must not be used for tuning.
Limits: ~100 short, clean, mostly English items. This measures relative behaviour on synthetic data, not production accuracy."""
import re

DATASET_VERSION = "3"
# v1 -> v2: added GOVERNMENT_ID items (v1 hid false positives of that category).
# v2 -> v3: one label correction. "UK" in 'Dial +44 ... for the UK desk.' is a country name, which annotation rule 3 labels LOCATION; v1/v2 omitted it by mistake.
#           No other label was changed: the remaining disagreements (boundary choices, ambiguous words) are model behaviour, not annotation errors.
CATS = ("EMAIL", "PHONE", "CARD_NUMBER", "IP_ADDRESS", "GOVERNMENT_ID", "PERSON", "LOCATION", "ORGANIZATION")
_MARK = re.compile(r"\[\[([A-Z_]+)\|(.+?)\]\]")


def parse(marked: str | None) -> tuple[str, list[tuple[int, int, str]]]:
    """'Mail [[EMAIL|a@b.co]] now' -> ('Mail a@b.co now', [(5, 11, 'EMAIL')])."""
    if marked is None:
        return "", []
    out, spans, last, pos = [], [], 0, 0
    for m in _MARK.finditer(marked):
        out.append(marked[last:m.start()])
        pos += m.start() - last
        spans.append((pos, pos + len(m.group(2)), m.group(1)))
        out.append(m.group(2))
        pos += len(m.group(2))
        last = m.end()
    out.append(marked[last:])
    return "".join(out), spans


DEV_TEXT = [
    "Reach me at [[EMAIL|john.doe@example.com]] tomorrow.",
    "Send the invoice to [[EMAIL|accounts+q3@mail.example.co.uk]] please.",
    "Write to john.doe@ and we will reply.",                                  # malformed: no label
    "Call [[PHONE|+1 415-555-0132]] after lunch.",
    "Office line: [[PHONE|(212) 555-0198]].",
    "Mobile [[PHONE|98765 43210]] is the primary contact.",
    "Order 12345 shipped on 2024-01-15.",                                     # numbers that are not phones
    "Reference 55-1234 was closed.",
    "Card on file: [[CARD_NUMBER|4111 1111 1111 1111]].",
    "Amex test [[CARD_NUMBER|378282246310005]] was declined.",
    "The number 4111 1111 1111 1112 failed validation.",                       # Luhn-invalid: no label
    "Server at [[IP_ADDRESS|192.168.1.10]] stopped responding.",
    "Blocked [[IP_ADDRESS|10.0.0.254]] and [[IP_ADDRESS|10.0.0.255]] overnight.",
    "Address 300.1.1.1 is not routable.",                                      # octet > 255: no label
    "[[PERSON|Priya Sharma]] joined the finance team.",
    "Our manager [[PERSON|Rahul Verma]] approved it.",
    "[[PERSON|Maria Garcia]] lives in [[LOCATION|Madrid]].",
    "The branch in [[LOCATION|Bengaluru]], [[LOCATION|India]] opened.",
    "Ship to [[LOCATION|221B Baker Street]], [[LOCATION|London]].",
    "[[ORGANIZATION|Infosys]] reported strong results.",
    "She works at [[ORGANIZATION|Acme Corporation]] now.",
    "Contact [[PERSON|Rahul Verma]] on [[PHONE|+91 98765 43210]] or [[EMAIL|rahul.v@example.org]].",
    "Mail [[EMAIL|dup@example.com]] then again [[EMAIL|dup@example.com]].",     # duplicates: both labelled
    "Contact [[EMAIL|priya.sharma@infosys.com]] for access.",                  # nested name/org inside an e-mail: labelled once
    "I ate an apple on Mercury Street.",                                       # ambiguous words: Mercury Street is a place
    "The quarterly report is ready for review.",
    "Temperature reached 36.6 degrees at 10:45.",
    "",                                                                         # empty
    None,                                                                       # null
    "Meeting notes: discuss roadmap, hiring and budget.",
    "PAN [[GOVERNMENT_ID|ABCDE1234F]] was verified.",
    "Aadhaar [[GOVERNMENT_ID|2345 6789 0123]] is on file.",
    "Code ABCDE12345 is a reference, not a PAN.",
]
DEV_TEXT = [t for t in DEV_TEXT]
# Fix the ambiguous example's label explicitly (kept readable above)
DEV_TEXT[24] = "I ate an apple on [[LOCATION|Mercury Street]]."

HELD_OUT_TEXT = [
    "Please email [[EMAIL|support_team@bank-example.com]] with the details.",
    "Her address is [[EMAIL|a.b-c@sub.domain.example]] for billing.",
    "Contact me at name@@example.com if needed.",                              # malformed
    "Dial [[PHONE|+44 20 7946 0958]] for the [[LOCATION|UK]] desk.",
    "Fax [[PHONE|415.555.0177]] or call [[PHONE|(646) 555-0143]].",
    "Case 20240115 and invoice 778899 are linked.",
    "Visa [[CARD_NUMBER|4012 8888 8888 1881]] was charged.",
    "Mastercard [[CARD_NUMBER|5555 5555 5555 4444]] expires soon.",
    "Digits 1234 5678 9012 3456 do not form a valid card.",                    # Luhn-invalid
    "Gateway [[IP_ADDRESS|172.16.254.1]] and DNS [[IP_ADDRESS|8.8.8.8]] responded.",
    "Build 999.10.10.10 is a typo, not an address.",
    "Escalated to [[PERSON|Ananya Iyer]] and [[PERSON|David Okafor]].",
    "[[PERSON|Chen Wei]] moved to [[LOCATION|Singapore]] last year.",
    "Delivery to [[LOCATION|Park Avenue]] in [[LOCATION|New York]] was late.",
    "Headquarters are in [[LOCATION|Mumbai]].",
    "[[ORGANIZATION|Reserve Bank of India]] issued a circular.",
    "The partnership with [[ORGANIZATION|Globex Limited]] was renewed.",
    "[[PERSON|Neha Gupta]] (neha.g@example.net) called from [[PHONE|+1 202-555-0171]].",
    "Log: [[IP_ADDRESS|203.0.113.77]] used card [[CARD_NUMBER|4111111111111111]].",
    "Ticket from [[EMAIL|k.lee@example.com]] about [[ORGANIZATION|Initech]] hardware.",
    "Jordan is a country and a name, but here it is just a word in a list: red, jordan, blue.",
    "Total balance is 12,500.75 after fees.",
    "Version 2.4 released, see changelog for details.",
    "Tax id [[GOVERNMENT_ID|QWERT9876Z]] and SSN [[GOVERNMENT_ID|123-45-6789]] were submitted.",
    "Ref 1234-5678-9012-3456 is only a batch code.",
    "Standard operating procedure was updated.",
    "",
    None,
]
HELD_OUT_TEXT[17] = "[[PERSON|Neha Gupta]] ([[EMAIL|neha.g@example.net]]) called from [[PHONE|+1 202-555-0171]]."
HELD_OUT_TEXT[20] = "Jordan is only a word in this list: red, jordan, blue."

# Value-level: (cell value, set of categories it contains). Structured identifiers only.
DEV_VALUES = [
    ("alice@example.com", {"EMAIL"}), ("bob.smith@mail.example.org", {"EMAIL"}), ("not-an-email", set()), ("carol@", set()),
    ("+1 415-555-0132", {"PHONE"}), ("98765 43210", {"PHONE"}), ("12345", set()), ("2024-01-15", set()),
    ("4111 1111 1111 1111", {"CARD_NUMBER"}), ("4111 1111 1111 1112", set()), ("5500 0000 0000 0004", {"CARD_NUMBER"}),
    ("ABCDE1234F", {"GOVERNMENT_ID"}), ("ABCDE12345", set()), ("192.168.0.1", {"IP_ADDRESS"}), ("256.1.1.1", set()), ("hello world", set()), ("", set()), (None, set()),
]
HELD_OUT_VALUES = [
    ("QWERT9876Z", {"GOVERNMENT_ID"}), ("2345 6789 0123", {"GOVERNMENT_ID"}),
    ("dana_k@example.net", {"EMAIL"}), ("a@b", set()), ("(646) 555-0143", {"PHONE"}), ("+44 20 7946 0958", {"PHONE"}), ("987654", set()),
    ("378282246310005", {"CARD_NUMBER"}), ("0000 0000 0000 0000", set()), ("10.10.10.10", {"IP_ADDRESS"}), ("1.2.3", set()), ("n/a", set()), ("", set()), (None, set()),
]

# Column-level: (column name, values, sensitive?, dominant category or None)
DEV_COLUMNS = [
    ("email", ["a@example.com", "b@example.org", "c@example.net"], True, "EMAIL"),
    ("contact", ["+1 415-555-0132", "+1 415-555-0133", "98765 43210"], True, "PHONE"),
    ("customer_name", ["Priya Sharma", "Rahul Verma", "Maria Garcia"], True, "PERSON"),
    ("salary", ["52000", "61000.50", "48000"], True, "FINANCIAL"),
    ("city", ["Bengaluru", "Madrid", "London"], True, "LOCATION"),
    ("remarks", ["ok", "see ticket", "write to a@example.com", "fine", "call +1 415-555-0199", "ok", "pending", "ok", "n/a", "done"], True, "EMAIL"),
    ("product_name", ["Widget", "Gadget", "Sprocket"], False, None),
    ("status", ["open", "closed", "pending"], False, None),
    ("quantity", ["1", "5", "12"], False, None),
    ("phone_model", ["Pixel 8", "iPhone 14", "Galaxy S23"], False, None),   # name looks sensitive, contents are not
]
HELD_OUT_COLUMNS = [
    ("mail", ["x@example.com", "y@example.org"], True, "EMAIL"),
    ("card_no", ["4111 1111 1111 1111", "5500 0000 0000 0004"], True, "CARD_NUMBER"),
    ("src_ip", ["10.0.0.1", "10.0.0.2", "172.16.0.9"], True, "IP_ADDRESS"),
    ("full_name", ["Ananya Iyer", "David Okafor", "Chen Wei"], True, "PERSON"),
    ("account_balance", ["1200.50", "88000", "15"], True, "FINANCIAL"),
    ("company", ["Globex Limited", "Initech", "Acme Corporation"], True, "ORGANIZATION"),
    ("email", [], True, "EMAIL"),                                           # empty column: metadata only
    ("category", ["books", "toys", "garden"], False, None),
    ("rating", ["4", "5", "3"], False, None),
    ("description", ["durable", "lightweight", "blue"], False, None),
]


def text_items(split: str):
    """[(text, [(start, end, category)])] with None rendered as ''."""
    return [parse(m) for m in (DEV_TEXT if split == "dev" else HELD_OUT_TEXT)]
