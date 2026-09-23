# Dialect-specific code paths (Postgres + SQLite) without a live server.
#
# The only places the production Postgres dialect diverges from the
# test-time SQLite dialect are (a) the {PK} substitution in the DDL and
# (b) the ? → %s placeholder translation. Both are pure and tested here so
# the Postgres path has local coverage even when no Postgres is reachable
# (the CI smoke gate exercises a real postgres:16 service container too).

from __future__ import annotations

import unittest
from importlib import resources

from session_analytics.relational import db


class TestDialect(unittest.TestCase):
    def test_translate_sqlite_keeps_question_marks(self) -> None:
        d = db.Database(conn=None, dialect=db.DIALECT_SQLITE)
        self.assertEqual(d._translate("INSERT INTO t VALUES (?, ?)"), "INSERT INTO t VALUES (?, ?)")

    def test_translate_postgres_rewrites_to_percent_s(self) -> None:
        d = db.Database(conn=None, dialect=db.DIALECT_POSTGRES)
        self.assertEqual(d._translate("INSERT INTO t VALUES (?, ?)"), "INSERT INTO t VALUES (%s, %s)")

    def test_pk_substitution_per_dialect(self) -> None:
        self.assertIn("BIGSERIAL", db._PK_SQL[db.DIALECT_POSTGRES])
        self.assertIn("AUTOINCREMENT", db._PK_SQL[db.DIALECT_SQLITE])

    def test_ddl_has_no_unsubstituted_placeholder(self) -> None:
        # Every {PK} must be replaced; a stray placeholder would be a
        # syntax error on first apply against a real server.
        for fname in db._DDL_FILES:
            text = resources.files(db._DDL_PACKAGE).joinpath(fname).read_text(encoding="utf-8")
            for dialect, pk in db._PK_SQL.items():
                rendered = text.replace("{PK}", pk)
                self.assertNotIn("{PK}", rendered, f"{fname}/{dialect}")
                stmts = db._statements(rendered)
                self.assertTrue(stmts, fname)

    def test_statement_splitter_drops_comments(self) -> None:
        sql = "-- a comment\nCREATE TABLE x (id INTEGER);\n-- another\nCREATE INDEX i ON x(id);"
        stmts = db._statements(sql)
        self.assertEqual(len(stmts), 2)
        self.assertTrue(all("--" not in s for s in stmts))


if __name__ == "__main__":
    unittest.main()


class TestSchemaMismatch(unittest.TestCase):
    """A store from before schema 8 lacks copilot_tool_result.completed_at,
    which create-if-absent cannot add (#371 A1). apply_ddl must refuse it
    with the remedy and record nothing, never stamp it current."""

    def _old_store(self) -> str:
        import sqlite3
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp(prefix="cct-sa-old-")) / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE schema_version (version INTEGER, applied_at TEXT);"
            "INSERT INTO schema_version VALUES (7, 'x');"
            "CREATE TABLE copilot_tool_result (id INTEGER PRIMARY KEY, tool_call_id INTEGER,"
            " status TEXT, is_error INTEGER, output_length INTEGER, error_message TEXT);"
        )
        conn.commit()
        conn.close()
        return f"sqlite:///{path}"

    def test_pre_8_store_is_refused_with_the_remedy(self) -> None:
        store = db.Database.connect(self._old_store())
        with self.assertRaises(db.SchemaMismatch) as ctx:
            db.apply_ddl(store)
        message = str(ctx.exception)
        self.assertIn("schema version 7", message)
        self.assertIn("completed_at", message)
        self.assertIn("ingest --full", message)
        self.assertEqual(store.query("SELECT version FROM schema_version"), [(7,)])

    def test_partial_store_without_a_version_table_is_still_refused(self) -> None:
        import sqlite3
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp(prefix="cct-sa-partial-")) / "partial.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE copilot_tool_result (id INTEGER PRIMARY KEY, tool_call_id INTEGER,"
            " status TEXT, is_error INTEGER, output_length INTEGER, error_message TEXT);"
        )
        conn.commit()
        conn.close()
        store = db.Database.connect(f"sqlite:///{path}")
        with self.assertRaises(db.SchemaMismatch) as ctx:
            db.apply_ddl(store)
        self.assertIn("schema version unknown", str(ctx.exception))

    def test_fresh_store_is_stamped_current(self) -> None:
        from session_analytics.tests.support import RegistryResetTestCase

        store = db.Database.connect(RegistryResetTestCase.sqlite_dsn(self))  # type: ignore[arg-type]
        db.apply_ddl(store)
        self.assertEqual(store.query("SELECT MAX(version) FROM schema_version"), [(8,)])

    def test_pre_8_store_refused_by_the_api_and_the_cli(self) -> None:
        """The refusal must reach the person, not be logged as a flaky
        database at API startup (create_app) or shown as a traceback
        (the CLI): one message with the remedy, exit code EXIT_RUNTIME."""
        import io
        from contextlib import redirect_stderr

        from session_analytics import constants as C
        from session_analytics.cli import main

        dsn = self._old_store()
        try:
            from session_analytics.api.server import create_app
        except ImportError:  # fastapi absent: the CLI half still runs
            create_app = None
        if create_app is not None:
            with self.assertRaises(db.SchemaMismatch):
                create_app(dsn)
        # ingest is the command the remedy names, and the one a person runs
        # first; doctor reports the same error inside its JSON by design.
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["ingest", "--db", dsn, "--copilot", "claude-code"])
        self.assertEqual(rc, C.EXIT_RUNTIME)
        self.assertIn("ingest --full", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        # A handler with its own catch-all (kpis logs a traceback and returns
        # on any exception) must let the refusal through to the same place.
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["kpis", "--db", dsn])
        self.assertEqual(rc, C.EXIT_RUNTIME)
        self.assertIn("ingest --full", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
