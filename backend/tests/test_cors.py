"""CORS: the deployed frontend origin must be allowed, and nothing else gets through."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.config import Settings

VERCEL = "https://trustlayer-eight-mocha.vercel.app"


def test_cors_list_trims_spaces_and_trailing_slashes():
    s = Settings(cors_origins=f" {VERCEL}/ , http://localhost:5173,, ")
    assert s.cors_list == [VERCEL, "http://localhost:5173"]


def _client(origins):
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])

    @app.post("/api/auth/login")
    def login():
        return {"ok": True}

    return TestClient(app)


def _preflight(client, origin):
    return client.options("/api/auth/login", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})


def test_configured_origin_is_allowed_and_others_are_not():
    c = _client(Settings(cors_origins=VERCEL + "/").cors_list)
    ok = _preflight(c, VERCEL)
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == VERCEL
    bad = _preflight(c, "https://evil.example")
    assert bad.status_code == 400 and "access-control-allow-origin" not in bad.headers


def test_app_uses_cors_list_from_settings():
    from app.main import app
    mw = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    assert mw.kwargs["allow_origins"] == [o for o in mw.kwargs["allow_origins"] if "*" not in o]
