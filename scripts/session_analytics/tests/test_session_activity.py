from __future__ import annotations

import unittest

from session_analytics import activity as A
from session_analytics import config as cfgmod
from session_analytics import constants as C
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational import db as db_mod
from session_analytics.relational.db import SQLITE_MODE_RO, Database, apply_ddl
from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase, packaged_config

ROWS = (
    f"SELECT session_id, idle_cutoff_seconds, active_seconds, gaps_measured, gaps_unstamped, gaps_negative "
    f"FROM {C.TBL_SESSION_ACTIVITY} ORDER BY session_id, idle_cutoff_seconds"
)


def _isolated(case: unittest.TestCase, env=None) -> None:
    context = packaged_config(env)
    context.__enter__()
    case.addCleanup(context.__exit__, None, None, None)


class TestIdleCutoffConfig(unittest.TestCase):
    def test_the_default_comes_from_defaults_json(self) -> None:
        with packaged_config():
            self.assertEqual(cfgmod.load_config().idle_cutoff_seconds, 900)

    def test_the_environment_overrides_it(self) -> None:
        with packaged_config({cfgmod.ENV_IDLE_CUTOFF: "300"}):
            self.assertEqual(cfgmod.load_config().idle_cutoff_seconds, 300)

    def test_a_cutoff_that_is_not_a_positive_integer_is_refused(self) -> None:
        for value in ("0", "-60", "fifteen", "1.5"):
            with self.subTest(value=value), packaged_config({cfgmod.ENV_IDLE_CUTOFF: value}):
                with self.assertRaises(ValueError) as raised:
                    cfgmod.load_config()
                self.assertIn("sessions.idle_cutoff_seconds", str(raised.exception))

    def test_a_boolean_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            cfgmod._load_idle_cutoff({"sessions": {"idle_cutoff_seconds": True}}, lambda key: None)

    def test_a_config_without_the_key_is_refused(self) -> None:
        with self.assertRaises(ValueError) as raised:
            cfgmod._load_idle_cutoff({"sessions": {"noise": {}}}, lambda key: None)
        self.assertIn("defaults.json", str(raised.exception))


class TestStoredActivity(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        from session_analytics._register import register_all

        register_all()
        _isolated(self)
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        self.addCleanup(self.db.close)

    def _sessions(self) -> int:
        return int(self.db.query_one("SELECT COUNT(*) FROM copilot_session")[0])

    def test_ingest_stores_one_row_per_session_at_the_configured_cutoff(self) -> None:
        rows = self.db.query(ROWS)
        self.assertEqual(len(rows), self._sessions())
        self.assertEqual({r[1] for r in rows}, {900})

    def test_the_stored_figure_matches_the_gaps_report(self) -> None:
        report = A.gap_report(self.db, [15])
        rows = self.db.query(ROWS)
        self.assertAlmostEqual(sum(r[2] for r in rows), report["cutoffs"][0]["active_seconds"], places=1)
        self.assertEqual(sum(r[3] for r in rows), report["gaps"])
        self.assertEqual(sum(r[4] for r in rows), report["skipped_unstamped"])

    def test_a_reingest_recomputes_the_row(self) -> None:
        before = self.db.query(ROWS)
        self.db.execute(f"UPDATE {C.TBL_SESSION_ACTIVITY} SET active_seconds = -1, gaps_measured = -1")
        self.db.commit()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.assertEqual(self.db.query(ROWS), before)

    def test_a_new_cutoff_is_filled_without_a_reingest(self) -> None:
        self.assertEqual(A.ensure_activity(self.db, 120), self._sessions())
        self.assertEqual({r[1] for r in self.db.query(ROWS)}, {120, 900})
        self.assertEqual(A.ensure_activity(self.db, 120), 0)

    def test_a_schema_12_store_gains_the_table_and_its_rows_in_place(self) -> None:
        self.db.execute(f"DROP TABLE {C.TBL_SESSION_ACTIVITY}")
        self.db.execute("DELETE FROM schema_version WHERE version = ?", (db_mod._SCHEMA_VERSION,))
        self.db.commit()
        apply_ddl(self.db)
        self.assertEqual(
            self.db.query_one("SELECT MAX(version) FROM schema_version")[0], db_mod._SCHEMA_VERSION
        )
        self.assertEqual(len(self.db.query(ROWS)), self._sessions())

    def test_a_session_with_no_turns_gets_a_zero_row(self) -> None:
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id) VALUES (?, ?)", (C.COPILOT_CLAUDE_CODE, "no-turns")
        )
        self.db.commit()
        self.assertEqual(A.ensure_activity(self.db), 1)
        (session_pk,) = self.db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", ("no-turns",))
        self.assertIn((session_pk, 900, 0.0, 0, 0, 0), self.db.query(ROWS))

    def test_an_unstamped_turn_is_counted_not_measured(self) -> None:
        (first_turn, turns) = self.db.query_one("SELECT MIN(id), COUNT(*) FROM copilot_turn")
        self.db.execute("UPDATE copilot_turn SET timestamp = NULL WHERE id = ?", (first_turn,))
        self.db.execute(f"DELETE FROM {C.TBL_SESSION_ACTIVITY}")
        self.db.commit()
        A.ensure_activity(self.db)
        (_, _, _, measured, unstamped, negative) = self.db.query(ROWS)[0]
        self.assertEqual((measured, unstamped, negative), (turns - 2, 1, 0))

    def test_a_store_that_refuses_writes_is_left_alone(self) -> None:
        readonly = Database.connect(self.dsn, sqlite_mode=SQLITE_MODE_RO)
        self.addCleanup(readonly.close)
        self.assertEqual(A.ensure_activity(readonly, 600), 0)
        self.assertNotIn(600, {r[1] for r in self.db.query(ROWS)})


if __name__ == "__main__":
    unittest.main()
