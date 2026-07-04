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

_log = logging.getLogger(__name__)

DIALECT_POSTGRES = "postgres"
DIALECT_SQLITE = "sqlite"

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
    def connect(cls, dsn: str) -> "Database":
        if not dsn:
            raise ValueError(
                "no DSN configured; set --dsn, CCT_SA_DSN, or 'dsn' in config. "
                "For local dev, docker-compose up brings up Postgres; for tests "
                "use a sqlite:/// DSN."
            )
        if dsn.startswith("sqlite://"):
            import sqlite3

            path = dsn[len("sqlite://"):]
            # sqlite:///abs/path → '/abs/path'; sqlite:// → '' (in-memory)
            target = path[1:] if path.startswith("/") and path != "/" else path
            if path == "" or path == "/":
                target = ":memory:"
            conn = sqlite3.connect(target or ":memory:")
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
            (_SCHEMA_VERSION, _now_iso()),
        )


def _now_iso() -> str:
    # Local import keeps the module import-time side-effect-free; datetime is
    # only needed when actually recording a schema-version row.
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
