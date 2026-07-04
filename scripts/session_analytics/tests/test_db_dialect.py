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
