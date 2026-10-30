"""Creates the organizer's sample users (data/users.csv: username, display_name, role, email) as TrustLayer accounts. Additive only: users that
already exist are left untouched. Every account gets the DEMO_PASSWORD from backend/.env (hashed with bcrypt); no password is printed or stored in plain text.

Usage (from backend/):  python -m scripts.seed_b1 --users-csv "<path to users.csv>" """
import argparse
import csv
import pathlib
import sys

from sqlalchemy import select

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.models import User  # noqa: E402
from app.database.session import session_scope  # noqa: E402

ROLES = {"Admin", "Support", "Analyst"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--users-csv", required=True)
    a = ap.parse_args()
    pw = get_settings().demo_password
    if len(pw) < 8:
        raise SystemExit("Set DEMO_PASSWORD (min 8 chars) in backend/.env first.")
    rows = list(csv.DictReader(pathlib.Path(a.users_csv).read_text(encoding="utf-8").splitlines()))
    added = 0
    with session_scope() as db:
        for r in rows:
            if r["role"] not in ROLES:
                raise SystemExit(f"Unexpected role in users file: {r['role']!r}")
            if db.scalar(select(User).where(User.username == r["username"])):
                continue
            db.add(User(username=r["username"], display_name=r["display_name"], role=r["role"], password_hash=hash_password(pw)))
            added += 1
        db.commit()
    print(f"{len(rows)} users in file, {added} added, {len(rows) - added} already existed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
