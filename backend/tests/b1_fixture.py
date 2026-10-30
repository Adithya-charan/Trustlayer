"""A small SQLite database shaped like the organizer's Saffron Bank pack, filled with synthetic values in the same formats (Luhn-valid cards,
PAN/Aadhaar/SSN styles, mixed phone formats, PII embedded in free text, a generically named column that holds PANs). Lets the whole suite run
anywhere without the real dataset or any credentials. Real-dataset integration tests are separate and skip when the pack is absent."""
import random
import sqlite3
import string

NAMES = ["Anita Rao", "Farhan Qureshi", "Meera Iyer", "Ravi Kumar", "Neha Gill", "Joseph Pinto", "Kavya Hegde", "Arnab Dutta", "Hetal Shah", "Sana Khan"]
CITIES = [("Mumbai", "Maharashtra"), ("Pune", "Maharashtra"), ("Chennai", "Tamil Nadu"), ("Kolkata", "West Bengal")]

DDL = """
CREATE TABLE branches (branch_code VARCHAR(6) PRIMARY KEY, ifsc VARCHAR(11) UNIQUE, branch_nm VARCHAR(80), addr VARCHAR(160), city VARCHAR(40), branch_phone VARCHAR(20), branch_email VARCHAR(80));
CREATE TABLE customers (customer_id VARCHAR(16) PRIMARY KEY, cust_nm VARCHAR(80) NOT NULL, gender VARCHAR(8), dob_dt DATE, mob_no VARCHAR(20), emailid VARCHAR(80),
  addr_line1 VARCHAR(120), city VARCHAR(40), state VARCHAR(40), segment VARCHAR(20), home_branch VARCHAR(6) REFERENCES branches(branch_code), empty_col VARCHAR(10), payload BLOB);
CREATE TABLE kyc_records (kyc_id VARCHAR(16) PRIMARY KEY, customer_id VARCHAR(16) REFERENCES customers(customer_id), pan_no VARCHAR(10), aadhaar_no VARCHAR(16),
  kyc_status VARCHAR(12), kyc_meta TEXT);
CREATE TABLE international_customers (customer_id VARCHAR(16) PRIMARY KEY REFERENCES customers(customer_id), ssn VARCHAR(11), us_city VARCHAR(40));
CREATE TABLE accounts (account_no VARCHAR(16) PRIMARY KEY, customer_id VARCHAR(16) REFERENCES customers(customer_id), acct_type VARCHAR(12), curr_bal DECIMAL(15,2), extra_info TEXT);
CREATE TABLE cards (CARD_REF VARCHAR(16) PRIMARY KEY, CUSTOMER_ID VARCHAR(16) REFERENCES customers(customer_id), CARD_NO VARCHAR(19), NAME_ON_CARD VARCHAR(26), CARD_TYPE VARCHAR(8));
CREATE TABLE transactions (txn_id VARCHAR(16) PRIMARY KEY, account_no VARCHAR(16) REFERENCES accounts(account_no), amount_inr DECIMAL(15,2), channel VARCHAR(12), narration TEXT, rrn VARCHAR(12));
CREATE TABLE support_tickets (ticket_id VARCHAR(16) PRIMARY KEY, customer_id VARCHAR(16), category VARCHAR(32), ticket_text TEXT);
CREATE TABLE loan_applications (app_id VARCHAR(16) PRIMARY KEY, customer_id VARCHAR(16), loan_type VARCHAR(16), col_7 VARCHAR(12), declared_income_inr DECIMAL(15,2));
"""


def luhn_card(rng: random.Random, prefix: str = "4111") -> str:
    body = prefix + "".join(rng.choice(string.digits) for _ in range(11))
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return body + str((10 - total % 10) % 10)


def pan(rng: random.Random) -> str:
    return "".join(rng.choice(string.ascii_uppercase) for _ in range(5)) + "0000" + rng.choice(string.ascii_uppercase)


def build(path, n: int = 40, seed: int = 7) -> dict:
    """Creates the database file and returns the set of raw sensitive strings it contains (for leak assertions)."""
    rng = random.Random(seed)
    con = sqlite3.connect(path)
    con.executescript(DDL)
    secrets = {"pan": [], "card": [], "aadhaar": [], "ssn": [], "email": [], "phone": [], "name": []}
    con.executemany("INSERT INTO branches VALUES (?,?,?,?,?,?,?)", [(f"B00{i}", f"SAFF000000{i}", f"Branch {i}", f"Ground Floor, {i} Palm Road", "Mumbai", f"+91 99999 0000{i}", f"b{i}@saffronbank.example") for i in range(1, 4)])
    for i in range(1, n + 1):
        name = f"{rng.choice(NAMES).split()[0]} {rng.choice(NAMES).split()[1]}"
        mob = rng.choice([f"+91 99999 {rng.randint(10000, 99999)}", f"+91-9999{rng.randint(100000, 999999)}", f"9000{rng.randint(100000, 999999)}"])
        email = f"{name.split()[0].lower()}.{name.split()[1].lower()}{i}@mail.example"
        city, state = rng.choice(CITIES)
        cid = f"CIF-{i:08d}"
        con.execute("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (cid, name, rng.choice(["M", "F"]), f"19{rng.randint(60, 99)}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}", mob, email,
                    f"Ground Floor, {i} Palm Road, Sagar Nagar", city, state, rng.choice(["Retail", "Premium"]), f"B00{rng.randint(1, 3)}", None, None))
        secrets["name"].append(name), secrets["email"].append(email), secrets["phone"].append(mob)
        p, aad = pan(rng), f"{rng.randint(1000, 9999)} {rng.randint(1000, 9999)} {rng.randint(1000, 9999)}"
        meta = f'{{"src":"web","pan":"{p}"}}' if i % 3 == 0 else '{"src":"branch"}'
        con.execute("INSERT INTO kyc_records VALUES (?,?,?,?,?,?)", (f"KYC-{i:06d}", cid, p, aad, rng.choice(["VERIFIED", "PENDING"]), meta))
        secrets["pan"].append(p), secrets["aadhaar"].append(aad)
        if i % 4 == 0:
            ssn = rng.choice([f"9{rng.randint(10, 99)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}", f"9{rng.randint(10, 99)}{rng.randint(100000, 999999)}"])
            con.execute("INSERT INTO international_customers VALUES (?,?,?)", (cid, ssn, "Austin"))
            secrets["ssn"].append(ssn)
        acct = "".join(rng.choice(string.digits) for _ in range(14))
        extra = f"nominee contact {mob}" if i % 5 == 0 else None
        con.execute("INSERT INTO accounts VALUES (?,?,?,?,?)", (acct, cid, rng.choice(["SAVINGS", "SALARY"]), round(rng.uniform(1000, 9_000_000), 2), extra))
        card = luhn_card(rng)
        shown = rng.choice([f"{card[:4]}-{card[4:8]}-{card[8:12]}-{card[12:]}", f"{card[:4]} {card[4:8]} {card[8:12]} {card[12:]}", card])
        con.execute("INSERT INTO cards VALUES (?,?,?,?,?)", (f"CRD-{i:06d}", cid, shown, name.upper(), rng.choice(["DEBIT", "CREDIT"])))
        secrets["card"].append(shown)
        for j in range(5):
            narr = rng.choice(["UPI payment to merchant", f"UPI/{rng.randint(100000, 999999)}/Rent", f"NEFT from {name} PAN {p}" if j == 0 else "ATM cash withdrawal", "Salary credit"])
            con.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?)", (f"{i:05d}{j:011d}", acct, round(rng.uniform(10, 500_000), 2), rng.choice(["UPI", "NEFT", "ATM"]), narr,
                                                                           "".join(rng.choice(string.digits) for _ in range(12))))
        if i % 2 == 0:
            con.execute("INSERT INTO support_tickets VALUES (?,?,?,?)", (f"TKT-{i:06d}", cid, rng.choice(["Cards", "Accounts", "Loans"]), f"Hello, this is {name}. please call me on {mob} or mail {email}, my PAN is {p}"))
        con.execute("INSERT INTO loan_applications VALUES (?,?,?,?,?)", (f"APP-{i:06d}", cid, rng.choice(["HOME", "PERSONAL"]), p if i % 10 else None, round(rng.uniform(100_000, 3_000_000), 2)))
    con.commit()
    con.close()
    return secrets


def fixture_target(path):
    """TEST-ONLY stand-in for the Neon target: the same Target class (discovery, masking, read-only connection) over the synthetic file above,
    opened read-only (mode=ro + query_only). The application itself has no SQLite backend; this keeps the suite offline and credential-free."""
    from sqlalchemy import create_engine, event

    from app.b1.targets import NAME, Target

    def creator():
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)

    eng = create_engine("sqlite://", creator=creator)

    @event.listens_for(eng, "connect")
    def _ro(dbapi_con, _):
        dbapi_con.execute("PRAGMA query_only = ON")

    return Target(NAME, "Test fixture (synthetic Saffron data)", "sqlite", eng, None, "Test fixture")
