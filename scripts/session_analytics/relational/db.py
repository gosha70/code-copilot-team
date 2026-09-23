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
# READ-ONLY open. The probe (#101 / CodeQL py/path-injection) must not be
# able to write to a caller-named database AT ALL: `rw` refuses to CREATE
# but still permits writes to an existing file, which let a connection
# test add the CCT schema to somebody else's database.
SQLITE_MODE_RO = "ro"


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
    "ddl/postgres/004_metadata.sql",
    "ddl/postgres/005_heartbeat.sql",
    "ddl/postgres/006_session_analysis.sql",
    "ddl/postgres/007_human_label.sql",
    "ddl/postgres/008_session_flag.sql",
    "ddl/postgres/009_auto_build_verdict.sql",
)
# 3: + local_heartbeat (Slice B1, #187)
# 4: + trace search index (E10 Slice B, #65). NOTE that apply_ddl creates
#    what is absent and runs no migration step, so a bump alone would
#    leave an existing store's index empty and its archived traces
#    silently unsearchable — search_index.ensure_index backfills, and is
#    called from apply_ddl for exactly that reason.
# 5: + session_analysis (#65 Phase 1) — a new table, so create-if-absent
#    is the whole migration.
# 6: + human_label (#313, judge validation) — likewise a new table.
# 7: + auto_build_verdict (#190 §12, auto-build-run-surface) — a new table.
# 8: + copilot_tool_result.completed_at (#371 A1, the trace tree). A COLUMN
#    on an existing table, which create-if-absent cannot add: apply_ddl
#    refuses a store that has the table without the column, and says how
#    to recreate it. Session Analytics is unreleased; there is no
#    migration path by the owner's ruling.
_SCHEMA_VERSION = 8

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

        ``sqlite_mode`` is an OPT-IN SQLite open mode (``SQLITE_MODE_RW``
        to refuse creation, ``SQLITE_MODE_RO`` to refuse writing at all)
        for callers that must not modify the database — the probe.
        The default is unchanged: ingest, tests and setup still auto-create
        a SQLite file, which is how a fresh install gets its store.
        """
        if not dsn:
            raise ValueError(
                "no database configured; pass --db, set CCT_SA_DB, or run "
                "`session-analytics start` which configures one for you."
            )
        # A value that is not a database URL fails DEEP inside the driver
        # otherwise — an operator who passed the SERVER address here got a
        # psycopg connection error, which names neither the mistake nor the
        # fix. Catch it at the boundary and say what was expected.
        if not is_sqlite_dsn(dsn) and "://" in dsn:
            scheme = dsn.split("://", 1)[0].lower()
            if scheme in ("http", "https"):
                raise ValueError(
                    f"--db expects a DATABASE, not a URL: got {scheme}://…\n"
                    "  The server address is not configured here; it is always "
                    "127.0.0.1 (change the port with --api-port).\n"
                    "  Examples:  sqlite:////absolute/path/to/store.db\n"
                    "             postgresql://user:pass@localhost:5432/dbname"
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


class SchemaMismatch(RuntimeError):
    """The store predates the current schema in a way create-if-absent
    cannot repair. The message names the remedy."""


# Columns that create-if-absent cannot add to a store that already has the
# table. Checked before anything is recorded, so an old store is refused
# with a remedy rather than stamped current and then failing on a query.
_REQUIRED_COLUMNS = (("copilot_tool_result", "completed_at"),)


def _has_table(db: Database, table: str) -> bool:
    if db.dialect == DIALECT_SQLITE:
        row = db.query_one(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        )
    else:
        # The store's own schema only: a same-named table elsewhere on the
        # search_path must not answer for it.
        row = db.query_one(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        )
    return row is not None


def _has_column(db: Database, table: str, column: str) -> bool:
    if db.dialect == DIALECT_SQLITE:
        return any(r[1] == column for r in db.query(f"PRAGMA table_info({table})"))
    row = db.query_one(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ? AND column_name = ?",
        (table, column),
    )
    return row is not None


def check_schema(db: Database) -> None:
    """Refuse a store whose existing tables lack a column the current
    schema needs. Raises SchemaMismatch; a fresh store passes."""
    for table, column in _REQUIRED_COLUMNS:
        if _has_table(db, table) and not _has_column(db, table, column):
            # A store can have the table and no version row at all (a
            # partial creation); the refusal must still be this one.
            found = (
                db.query_one("SELECT MAX(version) FROM schema_version")
                if _has_table(db, "schema_version")
                else None
            )
            found_version = found[0] if found and found[0] is not None else "unknown"
            raise SchemaMismatch(
                f"this store was created with schema version {found_version}; "
                f"version {_SCHEMA_VERSION} adds {table}.{column}, which cannot be "
                "added in place. Session Analytics is unreleased and has no "
                "migration: recreate the store (delete the SQLite file, or drop the "
                "Postgres schema), then run `session-analytics ingest --full`."
            )


def apply_ddl(db: Database) -> None:
    """Create all tables + indexes if absent. Idempotent for a store at the
    current schema; refuses one that predates it (see check_schema).

    Substitutes the ``{PK}`` placeholder for the dialect's auto-increment
    primary-key declaration, then runs each statement.
    """
    check_schema(db)
    pk = _PK_SQL[db.dialect]
    for fname in _DDL_FILES:
        text = resources.files(_DDL_PACKAGE).joinpath(fname).read_text(encoding="utf-8")
        text = text.replace("{PK}", pk)
        for stmt in _statements(text):
            db.execute(stmt)
    _record_version(db)
    db.commit()
    # Imported here, not at module scope: search_index imports Database
    # from this module, and the search index is a consumer of the schema
    # rather than part of it.
    from ..search_index import ensure_index

    ensure_index(db)


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
