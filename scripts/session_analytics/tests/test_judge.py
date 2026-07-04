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
            stats = run_judge(db, _FakeJudge(), rubric)
            self.assertEqual(stats.labeled, 6)
            self.assertEqual(stats.parse_ok, 6)
            n = db.query("SELECT COUNT(*) FROM heuristic_label")[0][0]
            self.assertEqual(n, 6)

            # Re-running labels nothing new (all turns already labeled).
            again = run_judge(db, _FakeJudge(), rubric)
            self.assertEqual(again.labeled, 0)
            n2 = db.query("SELECT COUNT(*) FROM heuristic_label")[0][0]
            self.assertEqual(n2, 6)
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
                "phase_compliance_score, avg_interaction_quality FROM session_kpi"
            )[0]
            labeled, corr, autonomy, phase, avg_q = row
            self.assertEqual(labeled, 6)
            # Only the first user turn contains 'fix' → 1/6.
            self.assertAlmostEqual(corr, 1 / 6, places=4)
            # 3 user (commands) / (3 commands + 0 questions) = 1.0.
            self.assertAlmostEqual(autonomy, 1.0, places=4)
            self.assertAlmostEqual(phase, 1.0, places=4)
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
