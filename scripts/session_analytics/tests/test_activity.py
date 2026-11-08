from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from session_analytics import activity as A
from session_analytics import constants as C
from session_analytics.cli import main
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import SQLITE_MODE_RO, Database
from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase, packaged_config

T0 = datetime(2026, 11, 1, 9, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def user(seconds, text="hi", **kw) -> A.Turn:
    return A.Turn(C.ROLE_USER, at(seconds) if seconds is not None else None, len(text), text, **kw)


def assistant(seconds) -> A.Turn:
    return A.Turn(C.ROLE_ASSISTANT, at(seconds), 10, "ok")


class TestGapKind(unittest.TestCase):
    def test_assistant_turn(self) -> None:
        self.assertEqual(A.gap_kind(assistant(0)), A.GAP_ASSISTANT)

    def test_tool_result_turn(self) -> None:
        self.assertEqual(A.gap_kind(user(0, "", is_tool_result=True)), A.GAP_TOOL_RESULT)

    def test_an_empty_user_turn_that_is_no_tool_result_is_the_person(self) -> None:
        self.assertEqual(A.gap_kind(user(0, "")), A.GAP_HUMAN)

    def test_typed_message_is_human(self) -> None:
        self.assertEqual(A.gap_kind(user(0, "fix the failing test")), A.GAP_HUMAN)

    def test_harness_written_user_turns_are_injected(self) -> None:
        for text in (
            "<task-notification>\n<task-id>b1</task-id>",
            "<system-reminder>The working directory changed",
            "<local-command-stdout>done</local-command-stdout>",
            "<bash-stdout>ok</bash-stdout>",
            "This session is being continued from a previous conversation",
        ):
            with self.subTest(text=text):
                self.assertEqual(A.gap_kind(user(0, text)), A.GAP_INJECTED)

    def test_a_command_the_person_typed_is_human(self) -> None:
        for text in ("<command-name>/compact</command-name>", "<bash-input>git status</bash-input>"):
            with self.subTest(text=text):
                self.assertEqual(A.gap_kind(user(0, text)), A.GAP_HUMAN)


class TestSessionGaps(unittest.TestCase):
    def test_each_gap_is_classified_by_the_turn_that_ends_it(self) -> None:
        turns = [user(0), assistant(4), user(10, "", is_tool_result=True), assistant(13), user(613)]
        result = A.session_gaps(turns)
        self.assertEqual(result.gaps, [
            (A.GAP_ASSISTANT, 4.0), (A.GAP_TOOL_RESULT, 6.0), (A.GAP_ASSISTANT, 3.0), (A.GAP_HUMAN, 600.0),
        ])
        self.assertEqual((result.skipped_unstamped, result.skipped_negative), (0, 0))

    def test_a_gap_touching_an_unstamped_or_unreadable_turn_is_skipped_and_counted(self) -> None:
        bad = A.Turn(C.ROLE_ASSISTANT, "not a time", 5, "x")
        result = A.session_gaps([user(0), user(None), assistant(20), bad, user(40)])
        self.assertEqual(result.gaps, [])
        self.assertEqual(result.skipped_unstamped, 4)

    def test_a_negative_gap_is_skipped_and_counted(self) -> None:
        result = A.session_gaps([user(100), assistant(40), user(50)])
        self.assertEqual(result.gaps, [(A.GAP_HUMAN, 10.0)])
        self.assertEqual(result.skipped_negative, 1)

    def test_a_one_turn_session_has_no_gaps(self) -> None:
        self.assertEqual(A.session_gaps([user(0)]).gaps, [])


class TestActiveSeconds(unittest.TestCase):
    def test_every_gap_is_capped_at_the_cutoff(self) -> None:
        self.assertEqual(A.active_seconds([30, 900, 901, 86400], 900), 30 + 900 + 900 + 900)

    def test_no_gaps_is_zero(self) -> None:
        self.assertEqual(A.active_seconds([], 900), 0)

    def test_percentile_is_nearest_rank(self) -> None:
        values = [float(v) for v in range(1, 101)]
        self.assertEqual(
            (A.percentile(values, 50), A.percentile(values, 90), A.percentile(values, 99)), (50.0, 90.0, 99.0)
        )

    def test_percentile_follows_the_repository_rule(self) -> None:
        self.assertEqual(A.percentile([6.0, 1.0, 5.0, 2.0, 4.0, 3.0], 90), 6.0)


class _FixtureStore(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        from session_analytics._register import register_all

        register_all()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)

    def _report(self, cutoffs=A.DEFAULT_CUTOFFS_MINUTES) -> dict:
        db = Database.connect(self.dsn, sqlite_mode=SQLITE_MODE_RO)
        try:
            return A.gap_report(db, cutoffs)
        finally:
            db.close()


class TestGapReportOnAStore(_FixtureStore):
    def test_tool_result_turns_are_matched_through_completed_at(self) -> None:
        db = Database.connect(self.dsn, sqlite_mode=SQLITE_MODE_RO)
        try:
            (results,) = db.query_one("SELECT COUNT(*) FROM copilot_tool_result WHERE completed_at IS NOT NULL")
        finally:
            db.close()
        report = self._report()
        self.assertGreater(results, 0)
        self.assertEqual(report["kinds"][A.GAP_TOOL_RESULT]["gaps"], results)

    def test_every_gap_between_stamped_turns_is_measured(self) -> None:
        report = self._report()
        skipped = report["skipped_unstamped"] + report["skipped_negative"]
        self.assertEqual(report["gaps"], report["turns"] - report["sessions"] - skipped)
        self.assertEqual(sum(k["gaps"] for k in report["kinds"].values()), report["gaps"])

    def test_active_time_grows_with_the_cutoff_and_never_exceeds_wall_clock(self) -> None:
        report = self._report([1, 10 ** 6])
        loose = report["cutoffs"][1]["active_seconds"]
        self.assertLessEqual(report["cutoffs"][0]["active_seconds"], loose)
        self.assertLessEqual(loose, report["wall_clock_seconds"])

    def test_a_session_with_no_turns_counts_in_the_sample_and_the_wall_clock_alike(self) -> None:
        before = self._report()
        db = Database.connect(self.dsn)
        try:
            db.execute(
                "INSERT INTO copilot_session (copilot, session_id, duration_seconds) VALUES (?, ?, ?)",
                (C.COPILOT_CLAUDE_CODE, "no-turns", 100),
            )
            db.commit()
        finally:
            db.close()
        after = self._report()
        self.assertEqual(after["sessions"], before["sessions"] + 1)
        self.assertEqual(after["wall_clock_seconds"], before["wall_clock_seconds"] + 100)
        self.assertEqual(after["gaps"], before["gaps"])

    def test_the_report_renders_both_tables(self) -> None:
        text = A.render_markdown(self._report([15]))
        self.assertIn("| gap ends at | gaps | p50 | p90 | p99 | max |", text)
        self.assertIn("| 15 min |", text)


class TestGapsCli(_FixtureStore):
    def _run(self, argv) -> tuple[int, str]:
        out = io.StringIO()
        with packaged_config(), redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(argv)
        return code, out.getvalue()

    def test_prints_the_tables(self) -> None:
        code, out = self._run(["gaps", "--db", self.dsn, "--cutoff", "5", "--cutoff", "15"])
        self.assertEqual(code, C.EXIT_OK)
        self.assertIn("| 5 min |", out)
        self.assertIn("| 15 min |", out)

    def test_json(self) -> None:
        code, out = self._run(["gaps", "--db", self.dsn, "--json"])
        self.assertEqual(code, C.EXIT_OK)
        report = json.loads(out)
        self.assertEqual([c["minutes"] for c in report["cutoffs"]], [2, 5, 10, 15, 30])
        self.assertEqual((report["sessions"], report["excluded_noise"]), (1, 0))

    def test_whole_minute_cutoffs_print_as_integers(self) -> None:
        code, out = self._run(["gaps", "--db", self.dsn, "--json", "--cutoff", "5", "--cutoff", "7.5"])
        self.assertEqual(code, C.EXIT_OK)
        minutes = [c["minutes"] for c in json.loads(out)["cutoffs"]]
        self.assertEqual([(m, type(m)) for m in minutes], [(5, int), (7.5, float)])

    def test_exclude_noise_leaves_noise_out_and_says_so(self) -> None:
        code, out = self._run(["gaps", "--db", self.dsn, "--json", "--exclude-noise"])
        self.assertEqual(code, C.EXIT_OK)
        report = json.loads(out)
        self.assertEqual((report["sessions"], report["gaps"], report["excluded_noise"]), (0, 0, 1))
        code, out = self._run(["gaps", "--db", self.dsn, "--exclude-noise"])
        self.assertIn("Noise sessions left out: 1 (drop --exclude-noise to count them).", out)

    def test_a_cutoff_that_is_not_positive_is_a_usage_error(self) -> None:
        for value in ("0", "-5"):
            with self.subTest(value=value):
                self.assertEqual(self._run(["gaps", "--db", self.dsn, f"--cutoff={value}"])[0], C.EXIT_USAGE)

    def test_a_cutoff_that_is_not_a_number_is_refused_by_the_parser(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self._run(["gaps", "--db", self.dsn, "--cutoff", "x"])
        self.assertEqual(raised.exception.code, C.EXIT_USAGE)

    def test_no_store_configured_is_a_usage_error(self) -> None:
        self.assertEqual(self._run(["gaps"])[0], C.EXIT_USAGE)

    def test_a_missing_store_is_not_created(self) -> None:
        target = Path(self.dsn.removeprefix("sqlite:///")).with_name("absent.db")
        code, _ = self._run(["gaps", "--db", f"sqlite:///{target}"])
        self.assertEqual(code, C.EXIT_RUNTIME)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
