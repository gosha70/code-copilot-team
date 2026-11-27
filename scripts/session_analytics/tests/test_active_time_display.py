from __future__ import annotations

import unittest

from session_analytics import activity as A
from session_analytics import config as cfgmod
from session_analytics import constants as C
from session_analytics.api import dashboard
from session_analytics.ingest.pipeline import ingest
from session_analytics.judge import session_analysis as sa
from session_analytics.mcp import tools as T
from session_analytics.relational.db import Database
from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase, packaged_config

ROW = (
    f"SELECT active_seconds, gaps_measured, gaps_unstamped FROM {C.TBL_SESSION_ACTIVITY} "
    "WHERE session_id = ? AND idle_cutoff_seconds = ?"
)


class _Store(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        from session_analytics._register import register_all

        register_all()
        context = packaged_config()
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        self.addCleanup(self.db.close)
        (self.pk,) = self.db.query_one("SELECT MIN(id) FROM copilot_session")

    def add_session(self, name: str, active: float | None, cutoff: int = 900) -> int:
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, started_at) VALUES (?, ?, ?)",
            (C.COPILOT_CLAUDE_CODE, name, "2026-01-01T00:00:00+00:00"),
        )
        (pk,) = self.db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", (name,))
        if active is not None:
            self.db.execute(
                f"INSERT INTO {C.TBL_SESSION_ACTIVITY} (session_id, idle_cutoff_seconds, active_seconds, "
                "gaps_measured, gaps_unstamped, gaps_negative) VALUES (?, ?, ?, ?, ?, ?)",
                (pk, cutoff, active, 3, 1, 0),
            )
        self.db.commit()
        return pk

    def listed(self, **kwargs) -> dict[int, dict]:
        return {s["id"]: s for s in T.search_sessions(self.db, **kwargs)}


class TestSessionActiveTime(_Store):
    def test_a_session_carries_the_figure_at_the_configured_cutoff(self) -> None:
        stored = self.db.query_one(ROW, (self.pk, 900))
        session = self.listed()[self.pk]
        self.assertEqual(session["active_seconds"], stored[0])
        self.assertEqual(session["active_cutoff_seconds"], 900)
        self.assertIsInstance(session["active_seconds"], float)

    def test_the_detail_says_what_the_figure_rests_on(self) -> None:
        stored = self.db.query_one(ROW, (self.pk, 900))
        detail = T.get_session_details(self.db, self.pk)
        self.assertEqual(detail["active_seconds"], stored[0])
        self.assertEqual(detail["active_cutoff_seconds"], 900)
        self.assertEqual((detail["active_gaps_measured"], detail["active_gaps_unstamped"]), (stored[1], stored[2]))

    def test_a_session_with_no_row_at_the_cutoff_reads_null_never_zero(self) -> None:
        self.db.execute(f"DELETE FROM {C.TBL_SESSION_ACTIVITY}")
        self.db.commit()
        for session in (self.listed()[self.pk], T.get_session_details(self.db, self.pk)):
            self.assertIsNone(session["active_seconds"])
            self.assertIsNone(session["active_cutoff_seconds"])
        detail = T.get_session_details(self.db, self.pk)
        self.assertIsNone(detail["active_gaps_measured"])
        self.assertIsNone(detail["active_gaps_unstamped"])

    def test_a_zero_figure_is_a_figure(self) -> None:
        pk = self.add_session("no-gaps", 0.0)
        self.assertEqual(self.listed()[pk]["active_seconds"], 0.0)

    def test_a_cutoff_changed_after_the_last_backfill_reads_null_until_it_is_stored(self) -> None:
        with packaged_config({cfgmod.ENV_IDLE_CUTOFF: "300"}):
            self.assertIsNone(self.listed()[self.pk]["active_seconds"])
            A.ensure_activity(self.db)
            session = self.listed()[self.pk]
            self.assertEqual(session["active_cutoff_seconds"], 300)
            self.assertEqual(session["active_seconds"], self.db.query_one(ROW, (self.pk, 300))[0])
        self.assertEqual(self.listed()[self.pk]["active_cutoff_seconds"], 900)

    def test_the_list_sorts_by_active_time_with_unknown_last_either_way(self) -> None:
        self.db.execute(f"DELETE FROM {C.TBL_SESSION_ACTIVITY}")
        self.db.commit()
        low, high = self.add_session("low", 10.0), self.add_session("high", 500.0)
        unknown = self.add_session("none", None)

        def order(descending: bool) -> list[int]:
            return [
                s["id"] for s in T.search_sessions(self.db, sort="active_seconds", descending=descending, limit=50)
            ]

        for descending, known in ((True, [high, low]), (False, [low, high])):
            ids = order(descending)
            self.assertEqual(ids[:2], known)
            self.assertEqual(set(ids[2:]), {unknown, self.pk})

    def test_active_seconds_is_a_sort_the_list_accepts(self) -> None:
        self.assertIn("active_seconds", T.SESSION_SORT_COLUMNS)
        with self.assertRaises(T.UnknownSortError):
            T.search_sessions(self.db, sort="active")


class TestOverviewActiveTime(_Store):
    def test_the_average_is_over_the_sessions_that_have_a_figure(self) -> None:
        self.db.execute(f"DELETE FROM {C.TBL_SESSION_ACTIVITY}")
        self.db.commit()
        self.add_session("a", 100.0)
        self.add_session("b", 300.0)
        self.add_session("unknown", None)
        totals = dashboard.kpis(self.db)["totals"]
        self.assertEqual(totals["avg_active_seconds"], 200.0)
        self.assertEqual(totals["active_cutoff_seconds"], 900)

    def test_it_is_null_when_no_session_has_a_figure(self) -> None:
        self.db.execute(f"DELETE FROM {C.TBL_SESSION_ACTIVITY}")
        self.db.commit()
        self.assertIsNone(dashboard.kpis(self.db)["totals"]["avg_active_seconds"])

    def test_a_figure_stored_at_another_cutoff_is_not_averaged_in(self) -> None:
        self.db.execute(f"DELETE FROM {C.TBL_SESSION_ACTIVITY}")
        self.db.commit()
        self.add_session("now", 120.0, cutoff=900)
        self.add_session("before", 9999.0, cutoff=300)
        self.assertEqual(dashboard.kpis(self.db)["totals"]["avg_active_seconds"], 120.0)

    def test_wall_clock_is_unchanged(self) -> None:
        wall = self.db.query_one("SELECT COALESCE(AVG(duration_seconds), 0) FROM copilot_session")[0]
        self.assertEqual(dashboard.kpis(self.db)["totals"]["avg_duration_seconds"], float(wall))


class TestJudgeFacts(_Store):
    def facts(self) -> str:
        transcript = sa.build_transcript(self.db, self.pk, max_chars=60000, per_turn_cap=1500)
        return sa.session_facts(self.db, self.pk, transcript)

    def test_the_facts_name_wall_clock_and_active_time(self) -> None:
        seconds = self.db.query_one(ROW, (self.pk, 900))[0]
        facts = self.facts()
        self.assertIn("duration (wall clock, first entry to last): ", facts)
        self.assertIn(f"active time (each gap capped at 15 min): {sa._fmt_duration(seconds)}; cost: ", facts)

    def test_a_session_without_a_figure_says_unknown(self) -> None:
        self.db.execute(f"DELETE FROM {C.TBL_SESSION_ACTIVITY}")
        self.db.commit()
        self.assertIn("active time (each gap capped at 15 min): unknown; cost: ", self.facts())

    def test_the_cutoff_in_the_facts_follows_the_config(self) -> None:
        with packaged_config({cfgmod.ENV_IDLE_CUTOFF: "300"}):
            A.ensure_activity(self.db)
            self.assertIn("each gap capped at 5 min", self.facts())
        with packaged_config({cfgmod.ENV_IDLE_CUTOFF: "90"}):
            self.assertIn("each gap capped at 90s", self.facts())


if __name__ == "__main__":
    unittest.main()
