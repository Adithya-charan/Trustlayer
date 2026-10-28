"""Seed SYNTHETIC demo users and customers (idempotent). Run: python -m scripts.seed
Deterministic (seeded RNG); every value is fabricated and not tied to real people."""
import datetime as dt
import random

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.database.models import Customer, User
from app.database.session import session_scope
from app.policies.store import seed_defaults

USERS = [
    ("sec.admin", "Sana Security (Admin)", "security_admin"),
    ("compliance1", "Chitra Compliance", "compliance_officer"),
    ("advisor1", "Arjun Advisor", "advisor"),
    ("analyst1", "Anika Analyst", "analyst"),
]
FIRST = ["Aarav", "Diya", "Vihaan", "Isha", "Kabir", "Meera", "Rohan", "Saanvi", "Aditya", "Nisha", "Karthik", "Priya"]
LAST = ["Sharma", "Iyer", "Reddy", "Mehta", "Nair", "Gupta", "Das", "Patel", "Rao", "Singh"]
CITIES = ["Hyderabad", "Pune", "Chennai", "Mumbai", "Kolkata", "Jaipur"]


def make_customer(rng: random.Random, i: int) -> Customer:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    letters = lambda n: "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(n))
    dependents = rng.randint(0, 4)
    income = rng.choice([420_000, 650_000, 900_000, 1_200_000, 1_800_000, 2_600_000])
    return Customer(
        full_name=f"{first} {last}",
        email=f"{first.lower()}.{last.lower()}{i}@example.test",
        phone=f"+91 9{rng.randint(100000000, 999999999)}",
        pan=f"{letters(5)}{rng.randint(1000, 9999)}{letters(1)}",
        account_number=str(rng.randint(10**11, 10**12 - 1)),
        date_of_birth=dt.date(rng.randint(1970, 1999), rng.randint(1, 12), rng.randint(1, 28)),
        city=rng.choice(CITIES),
        annual_income=income,
        total_liabilities=rng.choice([0, 300_000, 1_200_000, 3_500_000]),
        dependents=dependents,
        existing_cover=rng.choice([0, 500_000, 2_000_000, 5_000_000]),
        liquid_assets=rng.choice([50_000, 250_000, 800_000, 2_000_000]),
        education_goal=0 if dependents == 0 else rng.choice([500_000, 1_500_000, 3_000_000]),
    )


def main(n_customers: int = 12) -> None:
    pw = get_settings().demo_password
    if len(pw) < 8:
        raise SystemExit("Set DEMO_PASSWORD (min 8 chars) in backend/.env before seeding.")
    with session_scope() as db:
        for username, display, role in USERS:
            if not db.scalar(select(User).where(User.username == username)):
                db.add(User(username=username, display_name=display, role=role, password_hash=hash_password(pw)))
        if not db.scalar(select(Customer).limit(1)):
            rng = random.Random(2026)
            db.add_all([make_customer(rng, i) for i in range(1, n_customers + 1)])
        db.commit()
        seed_defaults(db)
    print("seed complete (synthetic data)")


if __name__ == "__main__":
    main()
