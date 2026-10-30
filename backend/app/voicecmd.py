"""Voice Command Control: turns what the user said into ONE validated intent from a closed list. Pure parsing: this module never touches the
database and never decides access. The API layer (app/api/voicecmd.py) checks the caller's real role for the intent, records it in the audit trail
and returns an approved action for the dashboard to carry out; anything touching policy additionally needs a signed, single-use confirmation.

Speech -> text (Sarvam, server side) -> parse() -> intent -> permission check -> approved action -> existing endpoints (identity, policy engine, masking).
Nothing here widens access: opening a table by voice shows it under the caller's own policy, exactly like clicking it."""
import re
from dataclasses import dataclass, field

PAGES = {  # route id -> (spoken names)
    "overview": r"overview|home|dashboard|summary",
    "discovery": r"(data )?discovery|discover",
    "explorer": r"(database|data) explorer|explorer|database browser",
    "policies": r"(access )?polic(y|ies)|masking rules",
    "access": r"users?( (and|&) access)?|user access|accounts|who has access",
    "audit": r"audit( (center|centre|logs?|trail|events?))?|activity log",
    "voice": r"voice assistant|assistant",
    "automation": r"automation|workflows?|n8n",
    "settings": r"settings|configuration",
}
TABLES = {  # table -> spoken names (more specific ones first)
    "international_customers": r"international customers?|us customers?|foreign customers?",
    "support_tickets": r"support tickets?|tickets?",
    "loan_applications": r"loan applications?|loans?",
    "kyc_records": r"kyc( records?)?|know your customer",
    "transactions": r"transactions?|payments? history",
    "customers": r"customers?",
    "accounts": r"bank accounts?|accounts(?! and)",
    "branches": r"branch(es)?",
    "cards": r"cards?",
}
KINDS = {  # classification kind -> spoken names
    "AADHAAR": r"aadhaar|aadhar|adhaar", "PAN": r"\bpan\b|pan number|pan card", "SSN": r"\bssn\b|social security",
    "CARD_NUMBER": r"card numbers?|credit card|debit card|\bcards?\b", "EMAIL": r"e-?mail", "PHONE": r"phone|mobile",
    "FULL_NAME": r"full names?|\bnames?\b", "DOB": r"date of birth|\bdob\b|birth ?date", "ADDRESS": r"address",
    "ACCOUNT_NUMBER": r"account numbers?", "FINANCIAL_AMOUNT": r"balances?|amounts?",
}
STRATEGIES = {
    "PARTIAL": r"partial(ly)?( mask(ed|ing)?)?|mask partially|partial masking",
    "REDACT": r"redact(ed|ion)?",
    "HASH": r"hash(ed)?",
    "DENY": r"deny|withhold|withheld|block(ed)?|hide completely",
    "ALLOW": r"allow|full access|real values?|unmasked|no masking",
}
ROLES = {"Admin": r"admins?|administrators?", "Support": r"support", "Analyst": r"analysts?"}
FILLER = re.compile(r"\b(hey|ok|okay|hi|trustlayer|trust layer|please|kindly|can you|could you|would you|will you|i want to|i would like to|i'd like to|i need to|let us|let's|lets|for me|now)\b")
VERB = r"(open|go to|goto|take me to|navigate to|switch to|show|display|bring up|pull up|launch|view|see|list|browse)"


@dataclass
class Intent:
    name: str
    label: str
    params: dict = field(default_factory=dict)
    hint: str | None = None  # set for UNKNOWN / incomplete commands


def normalize(text: str) -> str:
    t = text.lower().replace("’", "'").replace("&", " and ")
    t = re.sub(r"'s\b", "", t)
    t = re.sub(r"[^a-z0-9\s\-]", " ", t)
    t = FILLER.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _first(table: dict, t: str):
    for key, pat in table.items():
        if re.search(rf"(?<![a-z]){pat}(?![a-z])", t):
            return key
    return None


def _strategy_after_to(t: str):
    m = re.search(r"\bto\b\s+(.*)$", t)
    if m:
        for key, pat in STRATEGIES.items():
            if re.search(rf"\b(?:{pat})\b", m.group(1)):
                return key
    found = [(m.start(), key) for key, pat in STRATEGIES.items() for m in re.finditer(rf"\b(?:{pat})\b", t)]
    return max(found)[1] if found else None


def match_user(t: str, users: list[dict]) -> tuple[dict | None, bool]:
    """(user, ambiguous). Matches a full name, a unique first or last name, or a username in the normalized text."""
    def names(u):
        n = re.sub(r"\(.*?\)", "", u["display_name"]).strip().lower()
        return n, n.split()
    exact = [u for u in users if names(u)[0] and re.search(rf"(?<![a-z]){re.escape(names(u)[0])}(?![a-z])", t)]
    if len(exact) == 1:
        return exact[0], False
    by_user = [u for u in users if u["username"].lower() in t.replace(" ", "_") or u["username"].lower() in t]
    if len(by_user) == 1:
        return by_user[0], False
    parts: dict[str, list[dict]] = {}
    for u in users:
        for p in names(u)[1]:
            if len(p) > 2:
                parts.setdefault(p, []).append(u)
    hits = {id(us[0]): us[0] for p, us in parts.items() if len(us) == 1 and re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", t)}
    ambiguous = any(len(us) > 1 and re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", t) for p, us in parts.items())
    if len(hits) == 1:
        return next(iter(hits.values())), False
    return None, ambiguous or len(hits) > 1 or len(exact) > 1


HELP = ('Try: "Show high risk PII", "Open audit center", "Open the cards table", "Show denied requests", "Show analyst policies", "Scan the database", '
        '"Run the masking demo" or "Change Kavya Hegde\'s PAN policy to partial mask".')


def parse(text: str, users: list[dict] | None = None) -> Intent:
    """`users`: [{username, display_name}] of accounts a policy can target (non-Admin); only needed to resolve names."""
    t = normalize(text)
    users = users or []
    unknown = Intent("UNKNOWN", "Not understood", hint=HELP)
    if not t:
        return unknown

    # Voice can never modify or delete data: anything that sounds like it is refused outright, before any other rule can match.
    if re.search(r"\b(drop|delete|remove|truncate|erase|wipe|destroy|insert|alter|purge)\b", t):
        return Intent("UNKNOWN", "Not understood", hint="Voice commands never modify or delete data. " + HELP)

    # --- policy change (always confirmed by the API; incomplete or ambiguous requests never change anything) ---
    if re.search(r"\b(change|set|update|modify|switch|make|edit)\b", t) and re.search(r"polic|masking|\bpan\b|aadhaar|aadhar|\bssn\b|card|e-?mail|phone|mobile|name|address|dob", t):
        kind, strategy = _first(KINDS, t), _strategy_after_to(t)
        user, ambiguous = match_user(t, users)
        role = None if user else next((r for r, p in ROLES.items() if re.search(rf"\b(?:{p})\b", t) and r != "Admin"), None)
        admin_role = bool(not user and re.search(rf"\b(?:{ROLES['Admin']})\b", t))
        if admin_role:
            return Intent("CHANGE_POLICY_REFUSED", "Change policy", hint="Admin accounts always see real values; their policy cannot be restricted.")
        if kind and strategy and (user or role):
            return Intent("CHANGE_POLICY", "Change masking policy", {"scope": "user" if user else "role", "subject": user["username"] if user else role,
                                                                   "display_name": user["display_name"] if user else role, "kind": kind, "strategy": strategy})
        why = "which user or role" if not (user or role) else "which kind of data" if not kind else "which masking (partial mask, redact, hash, deny or allow)"
        if ambiguous:
            why = "which user (that name matches more than one person)"
        return Intent("CHANGE_POLICY_INCOMPLETE", "Change policy", hint=f'I need to know {why}. Say, for example: "Change Kavya Hegde\'s PAN policy to partial mask". I changed nothing.')

    if re.search(r"\b(help|what can i say|what can you do|commands|examples)\b", t):
        return Intent("HELP", "Help", hint=HELP)

    # --- actions ---
    if re.search(r"\b(scan|rescan|re-?scan)\b.*\b(database|data|db|tables?|schema)\b|\b(run|start|launch|trigger)\b.*\bscan\b|\bdiscover\b.*\b(database|data)\b", t):
        return Intent("SCAN_DATABASE", "Scan the database")
    if re.search(r"masking demo|run the demo|start the demo|demo of masking|hero demo|same query", t):
        return Intent("RUN_MASKING_DEMO", "Run the masking demo")
    role_in = next((r for r, p in ROLES.items() if re.search(rf"(?<![a-z])(?:{p})(?![a-z])", t)), None)
    if role_in and re.search(r"\bpolic(y|ies)\b|masking|rules", t) and not re.search(r"activity|requests?|events?", t):
        return Intent("SHOW_ROLE_POLICIES", f"Show {role_in} policy", {"role": role_in})
    if role_in and re.search(rf"{VERB}.*\baccess\b|\baccess\b.*(view|level)", t) and not re.search(r"\busers?\b|activity|audit", t):
        return Intent("SHOW_ROLE_ACCESS", f"Show {role_in} access", {"role": role_in})

    # --- one person's history (before the generic audit rules, so "Kavya's recent activity" is about Kavya) ---
    who, _ = match_user(t, users)
    if who and re.search(r"history|activity|activities|accessed|queried|what did|recent|last", t) and not re.search(r"polic", t):
        return Intent("SHOW_USER_ACTIVITY", f"Show {re.sub(r'[(].*?[)]', '', who['display_name']).strip()}'s activity", {"username": who["username"], "display_name": who["display_name"]})

    # --- audit ---
    if re.search(r"\b(denied|blocked|refused|rejected)\b", t) and re.search(r"request|event|access|attempt|quer|audit|log|decision", t):
        return Intent("SHOW_DENIED_REQUESTS", "Show denied requests")
    if re.search(r"\bmasked\b|\bmasking events\b", t) and re.search(r"request|event|quer|audit|log|decision", t):
        return Intent("SHOW_MASKED_REQUESTS", "Show masked requests")
    if role_in and re.search(r"activity|requests?|events?|audit|queries|log", t):
        return Intent("SHOW_ROLE_ACTIVITY", f"Show {role_in} activity", {"role": role_in})
    if re.search(r"policy changes?|who changed", t):
        return Intent("SHOW_POLICY_CHANGES", "Show policy changes")
    if re.search(r"(recent|latest|last)\b.*(audit|events?|activity|access)|audit (events?|logs?|trail)|audit (center|centre)", t):
        return Intent("SHOW_RECENT_AUDIT", "Show recent audit events") if re.search(r"recent|latest|last|events?", t) else Intent("OPEN_AUDIT", "Open the Audit Center")

    # --- discovery filters ---
    if re.search(r"embedded|hidden|free ?text|inside (text|tickets?)|pii in (tickets?|text|notes)|ticket text", t) and re.search(r"pii|fields?|data|sensitive|identifiers?|text", t):
        return Intent("SHOW_EMBEDDED_PII", "Show embedded PII")
    if re.search(r"high[- ]risk|risky|critical|most sensitive", t):
        return Intent("SHOW_HIGH_RISK_FIELDS", "Show high risk fields")
    if re.search(r"financial|money|balances?|amounts?", t) and re.search(r"sensitive|fields?|data|confidential|columns?", t):
        return Intent("SHOW_FINANCIAL_FIELDS", "Show financial sensitive fields")
    if re.search(r"payment|card data|cardholder", t) and re.search(r"sensitive|fields?|data", t):
        return Intent("SHOW_PAYMENT_FIELDS", "Show payment sensitive fields")
    if re.search(r"\bpii\b|personal(ly)? (identifiable )?(data|information|identifiers?)|personal fields", t):
        return Intent("SHOW_PII_FIELDS", "Show PII fields")
    if re.search(r"sensitive (fields?|columns?|data)|protected (fields?|columns?)|all (the )?sensitive", t):
        return Intent("SHOW_SENSITIVE_FIELDS", "Show sensitive fields")

    # --- users and tables ---
    user, _amb = match_user(t, users)
    if user and re.search(r"access|polic|permissions?|user|profile|account", t):
        return Intent("OPEN_USER_ACCESS", f"Open {re.sub(r'[(].*?[)]', '', user['display_name']).strip()}'s access", {"username": user["username"], "display_name": user["display_name"]})
    table = _first(TABLES, t)
    explorer_word = bool(re.search(PAGES["explorer"], t))
    if table and re.search(rf"{VERB}|table|records?|data|rows?", t) and not re.search(r"polic|audit|discovery", t):
        return Intent("OPEN_TABLE", f"Open {table.replace('_', ' ')}", {"table": table})

    # --- plain navigation ---
    for page, pat in (("explorer", PAGES["explorer"]), ("audit", PAGES["audit"]), ("discovery", PAGES["discovery"]), ("policies", PAGES["policies"]), ("access", PAGES["access"]),
                      ("automation", PAGES["automation"]), ("settings", PAGES["settings"]), ("voice", PAGES["voice"]), ("overview", PAGES["overview"])):
        if re.search(rf"(?<![a-z])(?:{pat})(?![a-z])", t) and (re.search(VERB, t) or len(t.split()) <= 4):
            return Intent("OPEN_PAGE", f"Open {page}", {"page": page})
    if explorer_word:
        return Intent("OPEN_PAGE", "Open explorer", {"page": "explorer"})
    return unknown


def strategy_phrase(s: str) -> str:
    return {"PARTIAL": "PARTIAL MASK", "REDACT": "REDACT", "HASH": "HASH", "DENY": "DENY (withhold)", "ALLOW": "ALLOW (real value)"}.get(s, s)


def is_yes(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(yes|yeah|yep|yup|sure|confirm|confirmed|apply( it| that| the change)?|do it|go ahead|approve|ok|okay|proceed)[.! ]*", text.strip().lower()))


def is_no(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(no|nope|nah|cancel|stop|don'?t|do not|abort|never mind|negative)[.! ]*", text.strip().lower()))
