# Tests for E4 predictive analytics and E10 label correlation (#65).
#
# Both features make claims about small samples, so most of what is
# pinned here is the REFUSAL to claim: figures withheld below a floor,
# rates that stay None rather than becoming 0.0, and coverage reported
# alongside every correlation.

from __future__ import annotations

from session_analytics import constants as C
from session_analytics import correlate_labels as cl
from session_analytics import predict
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import RegistryResetTestCase


class _Base(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.dsn = self.sqlite_dsn()
        self.db = Database.connect(self.dsn)
        apply_ddl(self.db)

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def _session(self, sid, project="/repo/a", turns=0, tools=0, errors=0,
                 duration=None) -> int:
        return self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, project_path,"
            " turn_count, tool_call_count, error_count, duration_seconds)"
            " VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (C.COPILOT_CLAUDE_CODE, sid, project, turns, tools, errors, duration),
        )

    def _turn(self, session_ref, seq, cost=None, model="claude-x") -> int:
        # `model` is what makes a turn price-ELIGIBLE (cost.py returns
        # NULL without one), so a priced turn must carry one — a priced
        # model-less turn is a state the pricing path cannot produce.
        return self.db.insert_returning_id(
            "INSERT INTO copilot_turn (session_id, sequence_num, role, model,"
            " cost_usd) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (session_ref, seq, "assistant", model, cost),
        )


class TestEffortEstimate(_Base):
    def test_withheld_below_the_floor(self) -> None:
        # Two sessions is not a distribution. The count is reported so
        # the caller can see WHY the estimate is absent.
        for i in range(2):
            self._session(f"s{i}", turns=10)
        est = predict.effort_estimate(self.db)
        self.assertEqual(est["turns"]["observations"], 2)
        self.assertFalse(est["turns"]["sufficient"])
        self.assertIsNone(est["turns"]["median"])

    def test_reported_at_and_above_the_floor(self) -> None:
        for i in range(predict.MIN_OBSERVATIONS):
            self._session(f"s{i}", turns=10 + i)
        est = predict.effort_estimate(self.db)
        self.assertTrue(est["turns"]["sufficient"])
        self.assertIsNotNone(est["turns"]["median"])
        self.assertGreaterEqual(est["turns"]["p90"], est["turns"]["median"])

    def test_scoped_to_one_project(self) -> None:
        for i in range(predict.MIN_OBSERVATIONS):
            self._session(f"a{i}", project="/repo/a", turns=10)
        for i in range(predict.MIN_OBSERVATIONS):
            self._session(f"b{i}", project="/repo/b", turns=100)
        a = predict.effort_estimate(self.db, "/repo/a")
        self.assertEqual(a["scope"], "/repo/a")
        self.assertEqual(a["turns"]["median"], 10.0)
        self.assertEqual(a["sessions"], predict.MIN_OBSERVATIONS)

    def test_unpriced_turns_are_excluded_not_zeroed(self) -> None:
        # A session whose turns carry no price contributes NO cost
        # observation. Counting it as 0.0 would drag a median toward a
        # spend that never happened.
        for i in range(predict.MIN_OBSERVATIONS):
            ref = self._session(f"p{i}", turns=1)
            self._turn(ref, 0, cost=2.0)
        unpriced = self._session("u", turns=1)
        self._turn(unpriced, 0, cost=None)
        est = predict.effort_estimate(self.db)
        # The unpriced session contributes NO observation — it is not a
        # $0 session, it is a session whose cost is unknown.
        self.assertEqual(est["cost_usd"]["observations"], predict.MIN_OBSERVATIONS)
        self.assertEqual(est["cost_usd"]["median"], 2.0)
        self.assertEqual(
            est["cost_usd_coverage"]["sessions_fully_priced"],
            predict.MIN_OBSERVATIONS,
        )

    def test_it_does_not_claim_to_be_a_model(self) -> None:
        # The wording is part of the contract: this is a base rate, and
        # calling it a prediction from a model would oversell it.
        est = predict.effort_estimate(self.db)
        self.assertIn("base rate", est["basis"])
        self.assertIn("not a fitted model", est["basis"])


class TestOutcomePrediction(_Base):
    _attempts = 0

    def _attempt(self, session_ref, result) -> None:
        # run_dir is NOT NULL UNIQUE — one row per attempt directory.
        type(self)._attempts += 1
        self.db.execute(
            f"INSERT INTO {C.TBL_BENCHMARK_RESULT}"
            " (run_dir, benchmark_id, task_id, run_id, attempt, result,"
            "  session_ref) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"/runs/{id(self)}-{type(self)._attempts}", "bench", "task",
             "run", 1, result, session_ref),
        )

    def test_pass_rate_withheld_below_the_floor(self) -> None:
        ref = self._session("s0")
        self._attempt(ref, "pass")
        rep = predict.outcome_prediction(self.db)
        self.assertEqual(rep["projects"][0]["attempts"], 1)
        self.assertFalse(rep["projects"][0]["sufficient"])
        self.assertIsNone(rep["projects"][0]["predicted_pass_rate"])

    def test_pass_rate_at_the_floor(self) -> None:
        for i in range(predict.MIN_OBSERVATIONS):
            ref = self._session(f"s{i}")
            self._attempt(ref, "pass" if i < 3 else "fail")
        proj = predict.outcome_prediction(self.db)["projects"][0]
        self.assertTrue(proj["sufficient"])
        self.assertAlmostEqual(proj["predicted_pass_rate"], 3 / 5)

    def test_unbenchmarked_sessions_are_counted_not_hidden(self) -> None:
        # A pass rate over benchmarked work must not be read as a rate
        # over everything; the denominator gap has to be visible.
        ref = self._session("benched")
        self._attempt(ref, "pass")
        for i in range(4):
            self._session(f"organic{i}")
        rep = predict.outcome_prediction(self.db)
        self.assertEqual(rep["sessions_total"], 5)
        self.assertEqual(rep["sessions_with_outcome"], 1)


class TestLabelCorrelation(_Base):
    def _label(self, turn_id, **flags) -> None:
        cols = ["turn_id", "rubric_name"] + list(flags)
        vals = [turn_id, "heuristic-v1"] + list(flags.values())
        self.db.execute(
            f"INSERT INTO {C.TBL_HEURISTIC_LABEL} ({', '.join(cols)})"
            f" VALUES ({', '.join('?' for _ in cols)})",
            tuple(vals),
        )

    def _trace(self, session_ref, seq, content) -> None:
        self.db.execute(
            f"INSERT INTO {C.TBL_TRACE_DOCUMENT}"
            " (session_ref, sequence_num, source_kind, content, redaction_mode)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_ref, seq, C.SOURCE_KIND_COPILOT_TRANSCRIPT, content,
             C.REDACT_CODE),
        )

    def test_coverage_is_reported_even_when_nothing_correlates(self) -> None:
        # Labels without traces is the common real state (the archive is
        # opt-in). An empty correlation must be explained, not implied.
        ref = self._session("s")
        tid = self._turn(ref, 0)
        self._label(tid, rework_detected=True)
        rep = cl.correlations(self.db)
        self.assertEqual(rep["coverage"]["labelled_turns"], 1)
        self.assertEqual(rep["coverage"]["archived_turns"], 0)
        self.assertEqual(rep["coverage"]["labelled_turns_with_trace"], 0)
        self.assertEqual(rep["sufficient_labels"], 0)

    def test_rate_is_none_not_zero_without_data(self) -> None:
        rep = cl.correlations(self.db)
        for row in rep["labels"]:
            self.assertIsNone(row["true_rate"], row["label"])

    def test_correlates_on_session_and_sequence_not_turn_id(self) -> None:
        # Re-ingest reassigns turn ids, so the stable key is
        # (session, sequence_num). This passes only if that join is used.
        ref = self._session("s")
        for seq in range(cl_min := 6):
            tid = self._turn(ref, seq)
            self._trace(ref, seq, "some archived text " * 3)
            self._label(tid, rework_detected=(seq < 2), interaction_quality=4)
        rep = cl.correlations(self.db)
        by_label = {r["label"]: r for r in rep["labels"]}
        row = by_label["rework_detected"]
        self.assertEqual(row["correlated_turns"], cl_min)
        self.assertEqual(row["true_count"], 2)
        self.assertAlmostEqual(row["true_rate"], 2 / 6)
        self.assertTrue(row["sufficient"])
        self.assertIsNotNone(row["avg_trace_chars"])

    def test_traces_for_label_returns_the_text(self) -> None:
        ref = self._session("s")
        tid = self._turn(ref, 0)
        self._trace(ref, 0, "the agent redid the migration")
        self._label(tid, rework_detected=True)
        hits = cl.traces_for_label(self.db, "rework_detected")
        self.assertEqual(len(hits), 1)
        self.assertIn("redid the migration", hits[0]["snippet"])

    def test_unknown_label_is_refused_not_interpolated(self) -> None:
        # The label reaches SQL as an identifier, so an unchecked value
        # would be an injection point.
        with self.assertRaises(ValueError):
            cl.traces_for_label(self.db, "1=1; DROP TABLE copilot_session--")
        with self.assertRaises(ValueError):
            cl.traces_for_label(self.db, "phase_violation")  # removed in #300


class TestReviewFindings(_Base):
    """The three #304 defects, each reproduced then pinned."""

    def _label(self, turn_id, rubric, **flags) -> None:
        cols = ["turn_id", "rubric_name"] + list(flags)
        vals = [turn_id, rubric] + list(flags.values())
        self.db.execute(
            f"INSERT INTO {C.TBL_HEURISTIC_LABEL} ({', '.join(cols)})"
            f" VALUES ({', '.join('?' for _ in cols)})",
            tuple(vals),
        )

    def _trace(self, session_ref, seq, content="archived text here") -> None:
        self.db.execute(
            f"INSERT INTO {C.TBL_TRACE_DOCUMENT}"
            " (session_ref, sequence_num, source_kind, content, redaction_mode)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_ref, seq, C.SOURCE_KIND_COPILOT_TRANSCRIPT, content,
             C.REDACT_CODE),
        )

    def _priced_turn(self, ref, seq, cost, model="claude-x") -> None:
        self.db.execute(
            "INSERT INTO copilot_turn (session_id, sequence_num, role, model,"
            " cost_usd) VALUES (?, ?, ?, ?, ?)",
            (ref, seq, "assistant", model, cost),
        )

    # ── one turn, two rubrics, must count once ─────────────────────────

    def test_two_rubrics_on_one_turn_count_as_one_turn(self) -> None:
        ref = self._session("s")
        tid = self._turn(ref, 0)
        self._trace(ref, 0)
        self._label(tid, "heuristic-v1", rework_detected=True)
        self._label(tid, "heuristic-v2", rework_detected=True)
        rep = cl.correlations(self.db)
        self.assertEqual(rep["coverage"]["labelled_turns"], 1)
        self.assertEqual(rep["coverage"]["labelled_turns_with_trace"], 1)
        row = {r["label"]: r for r in rep["labels"]}["rework_detected"]
        self.assertEqual(row["correlated_turns"], 1)
        self.assertEqual(row["true_count"], 1)

    def test_double_judging_cannot_cross_the_support_floor(self) -> None:
        # THE consequence: three turns judged twice would report support
        # 6 and be marked sufficient on three turns of evidence.
        ref = self._session("s")
        for seq in range(3):
            tid = self._turn(ref, seq)
            self._trace(ref, seq)
            self._label(tid, "heuristic-v1", rework_detected=True)
            self._label(tid, "heuristic-v2", rework_detected=True)
        row = {r["label"]: r for r in cl.correlations(self.db)["labels"]}
        self.assertEqual(row["rework_detected"]["correlated_turns"], 3)
        self.assertFalse(row["rework_detected"]["sufficient"])

    def test_traces_for_label_returns_a_turn_once(self) -> None:
        ref = self._session("s")
        tid = self._turn(ref, 0)
        self._trace(ref, 0)
        self._label(tid, "heuristic-v1", rework_detected=True)
        self._label(tid, "heuristic-v2", rework_detected=True)
        self.assertEqual(len(cl.traces_for_label(self.db, "rework_detected")), 1)

    def test_rubric_can_be_narrowed(self) -> None:
        ref = self._session("s")
        tid = self._turn(ref, 0)
        self._trace(ref, 0)
        self._label(tid, "heuristic-v1", rework_detected=True)
        self._label(tid, "heuristic-v2", rework_detected=False)
        v1 = {r["label"]: r for r in
              cl.correlations(self.db, rubric_name="heuristic-v1")["labels"]}
        v2 = {r["label"]: r for r in
              cl.correlations(self.db, rubric_name="heuristic-v2")["labels"]}
        self.assertEqual(v1["rework_detected"]["true_count"], 1)
        self.assertEqual(v2["rework_detected"]["true_count"], 0)

    # ── partial session costs must not be presented as totals ──────────

    def test_partially_priced_sessions_are_excluded_from_cost(self) -> None:
        # Five sessions, each with one priced and one unpriced eligible
        # turn. Every total is INCOMPLETE, so there is no cost estimate
        # — reporting median $2 from partial sums understates real spend
        # while looking like a real figure.
        for i in range(5):
            ref = self._session(f"partial{i}", turns=2)
            self._priced_turn(ref, 0, 2.0)
            self._priced_turn(ref, 1, None)
        est = predict.effort_estimate(self.db)
        self.assertEqual(est["cost_usd"]["observations"], 0)
        self.assertFalse(est["cost_usd"]["sufficient"])
        self.assertIsNone(est["cost_usd"]["median"])
        cov = est["cost_usd_coverage"]
        self.assertEqual(cov["sessions_with_any_priced_turn"], 5)
        self.assertEqual(cov["sessions_fully_priced"], 0)

    def test_fully_priced_sessions_are_estimated(self) -> None:
        for i in range(5):
            ref = self._session(f"full{i}", turns=2)
            self._priced_turn(ref, 0, 1.0)
            self._priced_turn(ref, 1, 1.0)
        est = predict.effort_estimate(self.db)
        self.assertEqual(est["cost_usd"]["observations"], 5)
        self.assertEqual(est["cost_usd"]["median"], 2.0)

    def test_turns_with_no_model_do_not_block_a_complete_session(self) -> None:
        # A user turn has no model and is never priceable, so it must
        # not make an otherwise fully-priced session look partial.
        for i in range(5):
            ref = self._session(f"mixed{i}", turns=2)
            self._priced_turn(ref, 0, 3.0)
            self._priced_turn(ref, 1, None, model=None)
        est = predict.effort_estimate(self.db)
        self.assertEqual(est["cost_usd"]["observations"], 5)
        self.assertEqual(est["cost_usd"]["median"], 3.0)

    # ── nearest-rank percentile ────────────────────────────────────────

    def test_percentile_is_actually_nearest_rank(self) -> None:
        # p90 of [1..6] is 6 (ceil(0.9*6)=6th). The previous
        # round(f*(n-1)) gave 5 — understating the tail a p90 exists
        # to show.
        self.assertEqual(predict._percentile([1, 2, 3, 4, 5, 6], 0.9), 6.0)
        self.assertEqual(predict._percentile([1, 2, 3, 4, 5, 6], 0.5), 3.0)
        self.assertEqual(predict._percentile([1], 0.9), 1.0)
        self.assertIsNone(predict._percentile([], 0.5))

    def test_p90_never_understates_the_median(self) -> None:
        for n in range(1, 12):
            values = list(range(1, n + 1))
            self.assertGreaterEqual(
                predict._percentile(values, 0.9),
                predict._percentile(values, 0.5),
                f"n={n}",
            )
