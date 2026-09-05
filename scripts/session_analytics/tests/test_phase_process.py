# Tests for descriptive phase-process metrics (#301).
#
# These are pure functions over a recorded timeline, so no DB is needed.
#
# THE ABSENCE OF A CONFORMANCE-SCORE TEST IS DELIBERATE. #301 exists
# because the recorded history CANNOT contain a violation — the Pi
# runtime's transition() returns before saveState when a gate fails — so
# a score over it would be 100% by construction. E3 (#65) stays open.

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics import phase_process as pp


class TestClassify(unittest.TestCase):
    def test_movements_are_described_not_graded(self) -> None:
        self.assertEqual(pp.classify("research", "plan"), pp.FORWARD)
        self.assertEqual(pp.classify("review", "build"), pp.BACKWARD)
        self.assertEqual(pp.classify("build", "build"), pp.SAME)
        self.assertEqual(pp.classify("build", "deploy"), pp.UNKNOWN)

    def test_no_verdict_vocabulary_is_exposed(self) -> None:
        # The module must not grow a grading vocabulary by accident: the
        # whole point of #301 is that the substrate cannot support one.
        exported = {n for n in dir(pp) if not n.startswith("_")}
        for banned in ("CONFORMING", "SequenceScore", "score_sequence", "VIOLATION"):
            self.assertNotIn(banned, exported)


class TestEntriesFromWorkflowState(unittest.TestCase):
    def test_current_phase_is_included_alongside_history(self) -> None:
        # history[] holds phases LEFT BEHIND; the active phase is at the
        # top level. Reading only history drops the phase the work is in
        # right now — the one most likely being asked about.
        state = {
            "phase": "build",
            "featureId": "F-1",
            "enteredAt": "2026-03-01T00:00:00Z",
            "history": [
                {"phase": "research", "featureId": "F-1", "at": "2026-01-01T00:00:00Z"},
                {"phase": "plan", "featureId": "F-1", "at": "2026-02-01T00:00:00Z"},
            ],
        }
        entries = pp.entries_from_workflow_state(state)
        self.assertEqual([e.phase for e in entries], ["research", "plan", "build"])
        self.assertEqual(entries[-1].at, "2026-03-01T00:00:00Z")

    def test_malformed_entries_are_skipped_not_guessed(self) -> None:
        state = {
            "phase": "plan",
            "history": [
                {"phase": "research", "at": "x"},
                {"at": "y"},              # no phase — not evidence of one
                "garbage",
                {"phase": "", "at": "z"},
            ],
        }
        self.assertEqual(
            [e.phase for e in pp.entries_from_workflow_state(state)],
            ["research", "plan"],
        )

    def test_empty_state_yields_nothing(self) -> None:
        self.assertEqual(pp.entries_from_workflow_state({}), [])


class TestTruncation(unittest.TestCase):
    def test_a_full_history_is_reported_as_possibly_truncated(self) -> None:
        # The runtime keeps the last 50. At the cap, earlier entries are
        # gone, so "not observed" describes the window, not the project.
        full = {"history": [{"phase": "build", "at": ""}] * C.PI_WORKFLOW_HISTORY_CAP}
        self.assertTrue(pp.history_may_be_truncated(full))

    def test_a_short_history_is_not(self) -> None:
        self.assertFalse(pp.history_may_be_truncated({"history": [{"phase": "build"}]}))
        self.assertFalse(pp.history_may_be_truncated({}))


class TestMetrics(unittest.TestCase):
    def _entries(self, *pairs) -> list[pp.Entry]:
        return [pp.Entry(phase=p, feature_id=f, at=str(i))
                for i, (p, f) in enumerate(pairs)]

    def test_a_clean_run_has_no_churn(self) -> None:
        m = pp.metrics_for(
            self._entries(("research", "F"), ("plan", "F"), ("build", "F"),
                          ("review", "F"))
        )
        self.assertEqual(m.oscillations, 0)
        self.assertEqual(m.rework_cycles, 0)
        self.assertTrue(m.review_observed)
        self.assertEqual([mv.kind for mv in m.moves], [pp.FORWARD] * 3)

    def test_oscillation_counts_a_return_not_a_single_move(self) -> None:
        # research -> plan -> research is churn. A lone backward move is
        # not: that is ordinary rework and is counted separately.
        churn = pp.metrics_for(
            self._entries(("research", "F"), ("plan", "F"), ("research", "F"))
        )
        self.assertEqual(churn.oscillations, 1)
        lone = pp.metrics_for(self._entries(("plan", "F"), ("research", "F")))
        self.assertEqual(lone.oscillations, 0)

    def test_rework_is_leaving_review_backwards(self) -> None:
        m = pp.metrics_for(
            self._entries(("build", "F"), ("review", "F"), ("build", "F"),
                          ("review", "F"))
        )
        self.assertEqual(m.rework_cycles, 1)
        self.assertTrue(m.review_observed)

    def test_review_observed_is_about_the_record_not_the_project(self) -> None:
        m = pp.metrics_for(self._entries(("research", "F"), ("plan", "F")))
        self.assertFalse(m.review_observed)
        # The field name must not claim "never reached review" — the
        # window may simply have evicted it. Callers pair this with
        # history_may_be_truncated to word the absence honestly.
        self.assertIn("review_observed", pp.ProcessMetrics.__dataclass_fields__)
        self.assertNotIn("never_reached_review", pp.ProcessMetrics.__dataclass_fields__)

    def test_phases_seen_preserves_first_appearance_order(self) -> None:
        m = pp.metrics_for(
            self._entries(("plan", "F"), ("research", "F"), ("plan", "F"))
        )
        self.assertEqual(m.phases_seen, ("plan", "research"))


class TestGrouping(unittest.TestCase):
    def test_parallel_features_do_not_fabricate_a_backward_move(self) -> None:
        # Two features interleaved in one project: alpha reaches build,
        # then beta starts at research. A single timeline reads that as
        # build -> research, a movement NOBODY MADE.
        entries = [
            pp.Entry("research", "alpha", "1"),
            pp.Entry("build", "alpha", "2"),
            pp.Entry("research", "beta", "3"),
            pp.Entry("plan", "beta", "4"),
        ]
        grouped = pp.group_by_feature(entries)
        self.assertEqual(set(grouped), {"alpha", "beta"})
        kinds = [
            mv.kind
            for entries_ in grouped.values()
            for mv in pp.metrics_for(entries_).moves
        ]
        self.assertNotIn(pp.BACKWARD, kinds)
        # And the ungrouped reading really would have shown one.
        self.assertIn(pp.BACKWARD, [mv.kind for mv in pp.metrics_for(entries).moves])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
