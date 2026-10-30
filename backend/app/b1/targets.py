"""The B1 engine's target databases. Three read-only backends are supported, each reporting its real state:

  postgres  Neon PostgreSQL (DATABASE_URL), schema B1_PG_SCHEMA (default `saffron_bank`)
  sqlite    the organizer's file (B1_SQLITE_PATH, default data/saffron_bank.db), opened read-only
  mysql     any MySQL server (B1_MYSQL_URL, database = the Saffron schema); not connected until that URL is set

Everything backend-specific lives here (connection setup, schema scoping, random sampling). Read-only is enforced by the connection itself:
PostgreSQL runs every connection with BEGIN READ ONLY, SQLite is opened with mode=ro plus PRAGMA query_only, and MySQL sessions run with
`SET SESSION TRANSACTION READ ONLY`, so the database refuses writes even if a bug let one through. status() asks the database what it reports and
never returns a credential, host, path or connection string."""
import datetime as dt
import pathlib
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy import MetaData, Table, create_engine, event, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url

from app.core.config import get_settings

NAME = "postgres"  # default target (kept so existing clients keep working)
NAMES = ("postgres", "sqlite", "mysql")
BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]


@dataclass
class Target:
    name: str
    label: str
    dialect: str
    engine: Engine
    schema: str | None
    provider: str = "PostgreSQL"
    _meta: MetaData | None = None

    def metadata(self) -> MetaData:
        if self._meta is None:
            m = MetaData(schema=self.schema)
            m.reflect(bind=self.engine, schema=self.schema, views=False)
            self._meta = m
        return self._meta

    def tables(self) -> dict[str, Table]:
        return {t.name: t for t in self.metadata().tables.values()}

    def connect(self):
        conn = self.engine.connect()
        if self.dialect == "postgresql":
            conn = conn.execution_options(postgresql_readonly=True)  # BEGIN READ ONLY: the database refuses any write on this connection
        return conn

    def sample_rows(self, table: Table, size: int) -> list:
        """A bounded random sample of whole rows: one query per table, however many columns it has. The caller keeps it in memory only
        for classification; it is never logged, stored or returned."""
        with self.connect() as c:
            return c.execute(select(table).order_by(func.random()).limit(size)).all()

    def row_count(self, table: Table) -> int:
        with self.connect() as c:
            return int(c.execute(select(func.count()).select_from(table)).scalar() or 0)

    def read_only(self) -> bool | None:
        """What the database reports for this connection (None if it cannot be asked, e.g. an unknown test fixture)."""
        probe = {"postgresql": "SHOW transaction_read_only", "sqlite": "PRAGMA query_only", "mysql": "SELECT @@session.transaction_read_only"}.get(self.dialect)
        if probe is None:
            return None
        with self.connect() as c:
            v = str(c.execute(text(probe)).scalar()).lower()
        return v in ("on", "1", "true")

    def status(self) -> dict:
        """A live health check: connects, verifies the schema exists, counts its tables and asks whether the connection is read-only.
        Contains no credential, host or path; errors are reported by type only."""
        base = {"name": self.name, "label": self.label, "provider": self.provider, "engine": ENGINE_LABEL.get(self.dialect, self.dialect), "configured": True,
                "dialect": self.dialect, "schema": self.schema, "checked_at": _now()}
        try:
            if self.dialect == "postgresql":  # one round trip: Neon is remote, so every extra query is a second of latency
                with self.connect() as c:
                    found, n, ro = c.execute(text("select exists(select 1 from information_schema.schemata where schema_name = :s), "
                                                  "(select count(*) from information_schema.tables where table_schema = :s and table_type = 'BASE TABLE'), "
                                                  "current_setting('transaction_read_only')"), {"s": self.schema}).one()
                if not found:
                    return {**base, "connected": True, "schema_found": False, "tables": 0, "read_only": None, "error": f"Schema {self.schema} was not found in the database."}
                return {**base, "connected": True, "schema_found": True, "tables": int(n), "read_only": str(ro).lower() == "on"}
            insp = inspect(self.engine)
            if self.schema and self.schema not in insp.get_schema_names():
                return {**base, "connected": True, "schema_found": False, "tables": 0, "read_only": None,
                        "error": f"Schema {self.schema} was not found in the database."}
            tables = insp.get_table_names(schema=self.schema)
            return {**base, "connected": True, "schema_found": True, "tables": len(tables), "read_only": self.read_only()}
        except Exception as exc:  # noqa: BLE001
            return {**base, "connected": False, "schema_found": None, "tables": 0, "read_only": None, "error": type(exc).__name__}


ENGINE_LABEL = {"postgresql": "PostgreSQL", "sqlite": "SQLite", "mysql": "MySQL"}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _pg_target() -> Target | None:
    s = get_settings()
    if not s.database_url.startswith("postgresql"):
        return None
    host = make_url(s.database_url).host or ""
    provider = "Neon" if host.endswith(".neon.tech") else "PostgreSQL"  # derived, never returned as the host itself
    return Target("postgres", f"{provider} PostgreSQL", "postgresql", create_engine(s.database_url, pool_pre_ping=True, pool_size=2, max_overflow=2),
                  s.b1_pg_schema, provider)


def sqlite_path() -> pathlib.Path:
    p = pathlib.Path(get_settings().b1_sqlite_path)
    return p if p.is_absolute() else BACKEND_DIR / p


def _sqlite_target() -> Target | None:
    path = sqlite_path()
    if not path.is_file():
        return None

    def creator():
        # mode=ro opens the file read-only at the OS level; query_only additionally makes SQLite refuse any statement that would write.
        con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, check_same_thread=False)
        con.execute("PRAGMA query_only = ON")
        return con

    return Target("sqlite", "SQLite (organizer file)", "sqlite", create_engine("sqlite://", creator=creator), None, "SQLite file")


def _mysql_target() -> Target | None:
    url = get_settings().b1_mysql_url
    if not url:
        return None
    u = make_url(url)
    if u.drivername == "mysql":  # the driver we ship is PyMySQL
        u = u.set(drivername="mysql+pymysql")
    eng = create_engine(u, pool_pre_ping=True, pool_size=2, max_overflow=2, connect_args={"connect_timeout": 5})

    @event.listens_for(eng, "connect")
    def _read_only(dbapi_con, _rec):  # noqa: ANN001
        cur = dbapi_con.cursor()
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        cur.close()

    return Target("mysql", "MySQL", "mysql", eng, u.database, "MySQL")


_cache: dict[str, Target | None] = {}


def reset() -> None:
    for t in _cache.values():
        if t is not None:
            t.engine.dispose()
    _cache.clear()
    _status_cache.clear()


def get_target(name: str = NAME) -> Target:
    """KeyError for an unknown target name; LookupError when that backend is not configured on this server."""
    if name not in NAMES:
        raise KeyError(name)
    if name not in _cache:
        _cache[name] = {"postgres": _pg_target, "sqlite": _sqlite_target, "mysql": _mysql_target}[name]()  # resolved at call time so tests can substitute one
    t = _cache[name]
    if t is None:
        raise LookupError(name)
    return t


_UNCONFIGURED = {
    "postgres": ("PostgreSQL", "PostgreSQL", "postgresql", "DATABASE_URL is not a PostgreSQL connection"),
    "sqlite": ("SQLite (organizer file)", "SQLite", "sqlite", "The SQLite file was not found (set B1_SQLITE_PATH)"),
    "mysql": ("MySQL", "MySQL", "mysql", "Not configured: set B1_MYSQL_URL to connect a MySQL server"),
}


_status_cache: dict[str, tuple[float, dict]] = {}
STATUS_TTL = 10.0  # seconds: short enough that "connected" is never stale for long, long enough that page changes do not each hit Neon


def _status_of(name: str) -> dict:
    try:
        return get_target(name).status()
    except LookupError:
        label, engine, dialect, why = _UNCONFIGURED[name]
        schema = get_settings().b1_pg_schema if name == "postgres" else None
        return {"name": name, "label": label, "provider": label, "engine": engine, "dialect": dialect, "schema": schema, "configured": False, "connected": False,
                "schema_found": None, "tables": 0, "read_only": None, "checked_at": _now(), "error": why}


def available(fresh: bool = False) -> list[dict]:
    """One live status per backend, checked in parallel. A backend that is not configured says so (connected=false, configured=false); nothing is ever
    shown as connected unless a real connection just succeeded. Results are reused for STATUS_TTL seconds unless `fresh` asks for a new check."""
    now = time.monotonic()
    todo = [n for n in NAMES if fresh or n not in _status_cache or now - _status_cache[n][0] > STATUS_TTL]
    if todo:
        with ThreadPoolExecutor(max_workers=len(todo)) as pool:
            for n, st in zip(todo, pool.map(_status_of, todo)):
                _status_cache[n] = (time.monotonic(), st)
    return [_status_cache[n][1] for n in NAMES]
