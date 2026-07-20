# session_analytics.relational.db — dialect-aware DB-API wrapper + DDL apply.
#
# Production target is PostgreSQL (psycopg); unit tests run against embedded
# SQLite so idempotency/parsing tests need zero infra. Both speak DB-API 2.0;
# the only meaningful differences are:
#   - placeholder style: psycopg ``%s`` vs sqlite3 ``?``  → write SQL with
#     ``?`` and translate for postgres.
#   - auto-increment PK declaration → the ``{PK}`` placeholder in the DDL.
# RETURNING, ON CONFLICT, and CREATE … IF NOT EXISTS work on both (Postgres
# always; SQLite ≥ 3.35 for RETURNING, ≥ 3.24 for ON CONFLICT).

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import quote

_log = logging.getLogger(__name__)

DIALECT_POSTGRES = "postgres"
DIALECT_SQLITE = "sqlite"

SQLITE_PREFIX = "sqlite://"
SQLITE_MEMORY = ":memory:"

# Opt-in open mode for callers that must NOT bring a database into being.
# SQLite's URI form refuses to create the file in ``rw`` (only ``rwc``
# creates), so this enforces "must already exist" at the open itself rather
# than pre-checking and racing (#101).
SQLITE_MODE_RW = "rw"


def is_sqlite_dsn(dsn: str) -> bool:
    """Whether ``dsn`` is a SQLite URL.

    Case-INSENSITIVE: URL schemes are case-insensitive per RFC 3986, and
    routing must not diverge from the probe's admission policy just because
    someone wrote ``SQLITE://`` — that divergence would let a DSN skip the
    SQLite rules and be handled as PostgreSQL (#101).
    """
    return dsn[:len(SQLITE_PREFIX)].lower() == SQLITE_PREFIX


def _sqlite_uri(target: str) -> str:
    """``target`` as a SQLite ``file:`` URI.

    Two hazards, both load-bearing:
    - ``quote`` escapes ``?``/``#``/``%`` (which would otherwise be read as
      query/fragment delimiters) while leaving ``/`` alone.
    - An ABSOLUTE path is emitted with an explicit empty authority
      (``file://`` + ``/path``). Without it a path that begins with ``//``
      turns its first segment into a URI authority, and SQLite rejects it
      with "invalid uri authority" — a DSN that opens fine in the default
      mode. Relative paths take no authority marker at all.
    """
    prefix = "file://" if target.startswith("/") else "file:"
    return f"{prefix}{quote(target)}"


def sqlite_target(dsn: str) -> str:
    """Resolve a ``sqlite://`` DSN to the path sqlite3 will actually open.

    The rule is non-obvious, so it lives here ONCE and every caller reuses
    it (#101): the text after ``sqlite://`` has a single leading ``/``
    stripped, which makes ``sqlite:////abs/path`` the absolute form and
    ``sqlite:///rel/path`` relative. An empty path (``sqlite://`` or
    ``sqlite:///``) means in-memory.

    Callers that need to know whether a DSN touches the filesystem should
    compare the result against ``SQLITE_MEMORY`` rather than re-parsing.
    """
    path = dsn[len(SQLITE_PREFIX):]
    if path in ("", "/"):
        return SQLITE_MEMORY
    target = path[1:] if path.startswith("/") else path
    return target or SQLITE_MEMORY

_DDL_PACKAGE = "session_analytics.config_data"
_DDL_FILES = (
    "ddl/postgres/001_core.sql",
    "ddl/postgres/002_analytics.sql",
    "ddl/postgres/003_indexes.sql",
)
_SCHEMA_VERSION = 1

_PK_SQL = {
    DIALECT_POSTGRES: "BIGSERIAL PRIMARY KEY",
    DIALECT_SQLITE: "INTEGER PRIMARY KEY AUTOINCREMENT",
}


class Database:
    """Thin wrapper over a DB-API connection that knows its dialect.

    Use ``Database.connect(dsn)``. SQLite DSNs are ``sqlite:///abs/path`` or
    ``sqlite://`` (in-memory). Everything else is treated as a PostgreSQL
    DSN handed verbatim to psycopg.
    """

    def __init__(self, conn: Any, dialect: str) -> None:
        self.conn = conn
        self.dialect = dialect

    # ── construction ───────────────────────────────────────────────────

    @classmethod
    def connect(cls, dsn: str, sqlite_mode: str = "") -> "Database":
        """Open ``dsn``.

        ``sqlite_mode`` is an OPT-IN SQLite open mode (``SQLITE_MODE_RW``)
        for callers that must not create the database — the probe (#101).
        The default is unchanged: ingest, tests and setup still auto-create
        a SQLite file, which is how a fresh install gets its store.
        """
        if not dsn:
            raise ValueError(
                "no DSN configured; set --dsn, CCT_SA_DSN, or 'dsn' in config. "
                "For local dev, docker-compose up brings up Postgres; for tests "
                "use a sqlite:/// DSN."
            )
        if is_sqlite_dsn(dsn):
            import sqlite3

            target = sqlite_target(dsn)
            if sqlite_mode and target != SQLITE_MEMORY:
                conn = sqlite3.connect(
                    f"{_sqlite_uri(target)}?mode={sqlite_mode}", uri=True
                )
            else:
                conn = sqlite3.connect(target)
            conn.execute("PRAGMA foreign_keys = ON")
            return cls(conn, DIALECT_SQLITE)

        import psycopg  # imported lazily so sqlite-only test runs need no psycopg

        conn = psycopg.connect(dsn)
        return cls(conn, DIALECT_POSTGRES)

    # ── helpers ────────────────────────────────────────────────────────

    def _translate(self, sql: str) -> str:
        """Translate ``?`` placeholders to ``%s`` for psycopg."""
        if self.dialect == DIALECT_POSTGRES:
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self.conn.cursor()
        cur.execute(self._translate(sql), tuple(params))
        return cur

    def insert_returning_id(self, sql: str, params: Sequence[Any]) -> int:
        """Execute an INSERT … RETURNING id and return the new id."""
        cur = self.execute(sql, params)
        row = cur.fetchone()
        return int(row[0])

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        cur = self.execute(sql, params)
        return list(cur.fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[tuple]:
        cur = self.execute(sql, params)
        return cur.fetchone()

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001 — close must never raise
            pass

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()


# ── DDL application ────────────────────────────────────────────────────


def _statements(sql_text: str) -> list[str]:
    """Split a DDL file into individual statements, dropping comment lines."""
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def apply_ddl(db: Database) -> None:
    """Create all tables + indexes if absent. Idempotent.

    Substitutes the ``{PK}`` placeholder for the dialect's auto-increment
    primary-key declaration, then runs each statement.
    """
    pk = _PK_SQL[db.dialect]
    for fname in _DDL_FILES:
        text = resources.files(_DDL_PACKAGE).joinpath(fname).read_text(encoding="utf-8")
        text = text.replace("{PK}", pk)
        for stmt in _statements(text):
            db.execute(stmt)
    _record_version(db)
    db.commit()


def _record_version(db: Database) -> None:
    row = db.query_one("SELECT version FROM schema_version WHERE version = ?", (_SCHEMA_VERSION,))
    if row is None:
        db.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (_SCHEMA_VERSION, now_iso()),
        )


def now_iso() -> str:
    """UTC ISO-8601 timestamp — the package's shared now-stamp helper.

    Public (E9 outcomes, #92): reused by callers that stamp rows (e.g.
    ``benchmark_result.ingested_at``) so the timestamp format can't drift
    between tables. The local import keeps the module import-time
    side-effect-free.
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
