"""Tests run on an isolated in-memory SQLite database. They never touch the
configured Neon database (DATABASE_URL)."""
import os

os.environ["DATABASE_URL"] = "sqlite://"  # overrides .env so the real DB is never used
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef"
os.environ["N8N_SHARED_SECRET"] = "test-n8n-secret-0123456789abcdef"
os.environ["USE_PRESIDIO"] = "false"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["DEMO_PASSWORD"] = "Test-Pass-1234"

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings

get_settings.cache_clear()

from app.core.security import limiter
from app.database import session as dbsession
from app.database.models import Base
from app.main import app
from scripts.seed import main as seed_main

PW = "Test-Pass-1234"


@pytest.fixture()
def client():
    engine = dbsession.init_engine("sqlite://")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    limiter.hits.clear()
    seed_main(n_customers=8)
    with TestClient(app) as c:
        yield c


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def scanned(client):
    h = login(client, "sec.admin")
    assert client.post("/api/scans", headers=h).json()["status"] == "COMPLETED"
    return client


AUTOMATION = {"X-TrustLayer-Automation-Key": "test-n8n-secret-0123456789abcdef"}
