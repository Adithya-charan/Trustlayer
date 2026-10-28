import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

log = logging.getLogger("trustlayer.db")

_engine: Engine | None = None
_factory: sessionmaker | None = None


def init_engine(url: str | None = None) -> Engine:
    """Create (or replace) the global engine. Tests pass their own URL."""
    global _engine, _factory
    url = url or get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    if url.startswith("sqlite"):  # used only by the isolated test suite
        from sqlalchemy.pool import StaticPool
        _engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    else:
        _engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, future=True)
    _factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine() -> Engine:
    return _engine or init_engine()


def get_session():
    """FastAPI dependency."""
    if _factory is None:
        init_engine()
    with _factory() as session:  # type: ignore[misc]
        yield session


@contextmanager
def session_scope():
    if _factory is None:
        init_engine()
    with _factory() as session:  # type: ignore[misc]
        yield session


def db_status() -> dict:
    """Safe connectivity probe: never returns the URL or driver error text."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"connected": True}
    except Exception as exc:  # noqa: BLE001
        log.warning("database probe failed: %s", type(exc).__name__)
        return {"connected": False, "error": "database unreachable"}
