"""Synthetic SQLite database for database-discovery tests. Every value is invented. Covers names, e-mails, phones, valid and invalid card numbers,
locations, organisations, ordinary columns, nulls and empty strings. Opened through the same read-only fixture target as the Saffron tests."""
import sqlite3

DDL = """
CREATE TABLE contacts (
  contact_ref VARCHAR(12) PRIMARY KEY,
  customer_name VARCHAR(60),
  email_addr VARCHAR(80),
  phone_no VARCHAR(20),
  card_text VARCHAR(30),
  approver_note VARCHAR(120),
  city_text VARCHAR(40),
  employer_text VARCHAR(40),
  qty INTEGER,
  note VARCHAR(60)
);
"""

ROWS = [
    ("C-0001", "Priya Sharma", "priya.s@example.com", "+91 98765 43210", "4111 1111 1111 1111", "Approved by Priya Sharma, Pune", "Bengaluru", "Infosys", 3, "ok"),
    ("C-0002", "Rahul Verma", "rahul.v@example.org", "98765 43211", "4111 1111 1111 1112", "Reviewed by Rahul Verma (manager)", "Mumbai", "Initech", 5, None),
    ("C-0003", "Maria Garcia", "maria.g@example.net", "+1 415-555-0132", "5500 0000 0000 0004", "Escalated to Maria Garcia, Madrid", "Madrid", "Globex", 1, ""),
    ("C-0004", "David Okafor", None, None, None, "Chen Wei sent the file", "London", "Acme", 2, "pending"),
    ("C-0005", None, "ananya@example.com", "(212) 555-0198", "", "Ananya Iyer signed off", "Chennai", None, None, None),
]


def build(path) -> None:
    con = sqlite3.connect(path)
    con.executescript(DDL)
    con.executemany("INSERT INTO contacts VALUES (?,?,?,?,?,?,?,?,?,?)", ROWS)
    con.commit()
    con.close()
