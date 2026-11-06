# Tests for the LLM-as-Judge layer (parser, runner, KPIs) — no real LLM.

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.ingest.pipeline import ingest
from session_analytics.judge import parse
from session_analytics.judge.contracts import (
    PARSE_INNER_UNPARSEABLE,
    PARSE_OK,
    Rubric,
    TurnContext,
    TurnLabels,
)
from session_analytics.judge.kpis import compute_kpis
from session_analytics.judge.rubric import load_rubric
from session_analytics.judge.runner import run_judge
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class _FakeJudge:
    """Deterministic judge — labels from the turn text, no network."""

    judge_id = "fake"

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels:
        bools = {label: False for label in rubric.bool_labels}
        bools["user_corrects_agent"] = "fix" in (ctx.text or "").lower()
        bools["user_gives_command"] = ctx.role == C.ROLE_USER
        bools["response_helpful"] = True
        return TurnLabels(
            bool_labels=bools,
            sentiment="NEUTRAL",
            interaction_quality=4,
            parse_status=PARSE_OK,
            judge_id=self.judge_id,
            judge_model="fake-1",
        )


class TestParser(unittest.TestCase):
    def setUp(self) -> None:
        self.rubric = load_rubric()

    def test_clean_json(self) -> None:
        txt = '{"user_corrects_agent": true, "sentiment": "FRUSTRATED", "interaction_quality": 5}'
        labels = parse.parse_labels(txt, self.rubric, judge_id="j", judge_model="m")
        self.assertEqual(labels.parse_status, PARSE_OK)
        self.assertIs(labels.bool_labels["user_corrects_agent"], True)
        self.assertEqual(labels.sentiment, "FRUSTRATED")
        self.assertEqual(labels.interaction_quality, 5)

    def test_fenced_and_prose(self) -> None:
        txt = 'Here is the result:\n```json\n{"response_helpful": true, "interaction_quality": 3}\n```'
        labels = parse.parse_labels(txt, self.rubric, judge_id="j", judge_model="m")
        self.assertIs(labels.bool_labels["response_helpful"], True)
        self.assertEqual(labels.interaction_quality, 3)

    def test_bad_values_coerced_to_none(self) -> None:
        txt = '{"sentiment": "happy", "interaction_quality": 9, "response_helpful": "maybe"}'
        labels = parse.parse_labels(txt, self.rubric, judge_id="j", judge_model="m")
        self.assertIsNone(labels.sentiment)            # not in enum
        self.assertIsNone(labels.interaction_quality)  # out of band
        self.assertIsNone(labels.bool_labels["response_helpful"])

    def test_empty(self) -> None:
        labels = parse.parse_labels("", self.rubric, judge_id="j", judge_model="m")
        self.assertEqual(labels.parse_status, PARSE_INNER_UNPARSEABLE)


class TestRunnerAndKpis(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()

    def _seed(self) -> tuple[str, Rubric]:
        dsn = self.sqlite_dsn()
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        return dsn, load_rubric()

    def test_runner_labels_all_turns_once(self) -> None:
        dsn, rubric = self._seed()
        db = Database.connect(dsn)
        try:
            apply_ddl(db)
            # 6 turns, 4 with text — the judge is asked about those 4 only
            # (#313: an empty tool-result turn has nothing to judge).
            stats = run_judge(db, _FakeJudge(), rubric)
            self.assertEqual(stats.labeled, 4)
            self.assertEqual(stats.parse_ok, 4)
            n = db.query("SELECT COUNT(*) FROM heuristic_label")[0][0]
            self.assertEqual(n, 4)

            # Re-running labels nothing new (all turns already labeled).
            again = run_judge(db, _FakeJudge(), rubric)
            self.assertEqual(again.labeled, 0)
            n2 = db.query("SELECT COUNT(*) FROM heuristic_label")[0][0]
            self.assertEqual(n2, 4)
        finally:
            db.close()

    def test_a_failed_attempt_is_retried(self) -> None:
        # The funnel's "N judge attempts failed" must be able to clear: a
        # turn whose only row is a failed attempt is selected again on the
        # next run, and once labelled successfully it is not judged again.
        from session_analytics.judge.contracts import PARSE_BACKEND_ERROR

        class _DeadJudge:
            judge_id = "dead"

            def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels:
                return TurnLabels(
                    bool_labels={label: None for label in rubric.bool_labels},
                    sentiment=None,
                    interaction_quality=None,
                    parse_status=PARSE_BACKEND_ERROR,
                    judge_id=self.judge_id,
                    judge_model="dead-1",
                    metadata={"error": "HTTP 404: model 'm' not found"},
                )

        dsn, rubric = self._seed()
        db = Database.connect(dsn)
        try:
            apply_ddl(db)
            first = run_judge(db, _DeadJudge(), rubric)
            self.assertEqual(first.parse_ok, 0)
            self.assertEqual(first.parse_failed, 4)
            failed = db.query(
                "SELECT COUNT(*) FROM heuristic_label WHERE parse_status <> ?", (PARSE_OK,)
            )[0][0]
            self.assertEqual(failed, 4)

            # A retry picks the same four turns up again and succeeds.
            second = run_judge(db, _FakeJudge(), rubric)
            self.assertEqual(second.labeled, 4)
            self.assertEqual(second.parse_ok, 4)
            ok = db.query(
                "SELECT COUNT(*) FROM heuristic_label WHERE parse_status = ?", (PARSE_OK,)
            )[0][0]
            self.assertEqual(ok, 4)

            # Successfully labelled: nothing left to judge.
            third = run_judge(db, _FakeJudge(), rubric)
            self.assertEqual(third.labeled, 0)
        finally:
            db.close()

    def test_kpis_math(self) -> None:
        dsn, rubric = self._seed()
        db = Database.connect(dsn)
        try:
            apply_ddl(db)
            run_judge(db, _FakeJudge(), rubric)
            compute_kpis(db, rubric.name)
            row = db.query(
                "SELECT labeled_turn_count, correction_rate, autonomy_score, "
                "avg_interaction_quality FROM session_kpi"
            )[0]
            labeled, corr, autonomy, avg_q = row
            self.assertEqual(labeled, 4)
            # Only the first user turn contains 'fix' → 1/4 of the judged turns.
            self.assertAlmostEqual(corr, 1 / 4, places=4)
            # 1 user turn with text (a command) / (1 command + 0 questions) = 1.0.
            self.assertAlmostEqual(autonomy, 1.0, places=4)
            self.assertAlmostEqual(avg_q, 4.0, places=4)
        finally:
            db.close()


class TestJudgeRegistration(RegistryResetTestCase):
    def test_judges_registered(self) -> None:
        from session_analytics._register import register_all
        from session_analytics.judge.registry import list_judge_ids

        register_all()
        ids = list_judge_ids()
        self.assertIn("ollama", ids)
        self.assertIn("claude-code", ids)


if __name__ == "__main__":
    unittest.main()
