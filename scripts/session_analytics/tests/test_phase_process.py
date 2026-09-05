# Tests for descriptive phase-process metrics (#301).
#
# These are pure functions over a recorded timeline, so no DB is needed.
#
# THE ABSENCE OF A CONFORMANCE-SCORE TEST IS DELIBERATE. #301 exists
# because the recorded history CANNOT contain a violation — the Pi
# runtime's transition() returns before saveState when a gate fails — so
# a score over it would be 100% by construction. E3 (#65) stays open.

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

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


class TestOccupancy(unittest.TestCase):
    def _e(self, phase, at):
        return pp.Entry(phase=phase, feature_id="F", at=at)

    def test_duration_is_until_the_next_entry(self) -> None:
        m = pp.metrics_for([
            self._e("research", "2026-01-01T00:00:00Z"),
            self._e("plan", "2026-01-01T01:00:00Z"),
            self._e("build", "2026-01-01T01:30:00Z"),
        ])
        self.assertEqual([o.seconds for o in m.occupancy], [3600.0, 1800.0, None])

    def test_the_active_phase_has_unknown_duration_not_zero(self) -> None:
        # The last entry is the phase still in progress. Reporting 0
        # would say it was entered and left instantly.
        m = pp.metrics_for([self._e("build", "2026-01-01T00:00:00Z")])
        self.assertIsNone(m.occupancy[0].seconds)

    def test_unparseable_or_backwards_stamps_yield_unknown(self) -> None:
        garbage = pp.metrics_for([
            self._e("research", "not-a-date"), self._e("plan", "2026-01-01T00:00:00Z"),
        ])
        self.assertIsNone(garbage.occupancy[0].seconds)
        # A clock change must not produce a negative elapsed time.
        backwards = pp.metrics_for([
            self._e("research", "2026-01-02T00:00:00Z"),
            self._e("plan", "2026-01-01T00:00:00Z"),
        ])
        self.assertIsNone(backwards.occupancy[0].seconds)


class TestProjectReader(unittest.TestCase):
    def _project(self, root, state) -> Path:
        cct = root / ".cct"
        cct.mkdir(parents=True, exist_ok=True)
        (root / Path(C.PI_WORKFLOW_REL)).write_text(json.dumps(state))
        return root

    def test_reads_a_project_and_finds_it_from_a_parent(self) -> None:
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        proj = self._project(base / "proj", {"phase": "build", "history": []})
        # base is a PARENT of projects
        self.assertEqual(pp.find_project_roots(base), [proj])
        # base IS the project
        self.assertEqual(pp.find_project_roots(proj), [proj])

    def test_missing_or_corrupt_file_is_none_not_a_crash(self) -> None:
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        self.assertIsNone(pp.read_project_workflow(base))
        (base / ".cct").mkdir()
        (base / Path(C.PI_WORKFLOW_REL)).write_text("{not json")
        self.assertIsNone(pp.read_project_workflow(base))


class TestReport(unittest.TestCase):
    def _root(self, state=None) -> Path:
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        if state is not None:
            (base / ".cct").mkdir(parents=True)
            (base / Path(C.PI_WORKFLOW_REL)).write_text(json.dumps(state))
        return base

    def test_a_clean_run(self) -> None:
        root = self._root({
            "phase": "review", "featureId": "F", "enteredAt": "4",
            "history": [{"phase": p, "featureId": "F", "at": str(i)}
                        for i, p in enumerate(["research", "plan", "build"], 1)],
        })
        feat = pp.report_for_roots([root])["projects"][0]["features"][0]
        self.assertEqual(feat["oscillations"], 0)
        self.assertEqual(feat["rework_cycles"], 0)
        self.assertTrue(feat["review_observed"])

    def test_an_oscillating_run(self) -> None:
        root = self._root({
            "phase": "plan", "featureId": "F", "enteredAt": "4",
            "history": [{"phase": p, "featureId": "F", "at": str(i)}
                        for i, p in enumerate(["research", "plan", "research"], 1)],
        })
        feat = pp.report_for_roots([root])["projects"][0]["features"][0]
        self.assertGreaterEqual(feat["oscillations"], 1)
        self.assertFalse(feat["review_observed"])

    def test_a_rework_cycle(self) -> None:
        root = self._root({
            "phase": "review", "featureId": "F", "enteredAt": "4",
            "history": [{"phase": p, "featureId": "F", "at": str(i)}
                        for i, p in enumerate(["build", "review", "build"], 1)],
        })
        feat = pp.report_for_roots([root])["projects"][0]["features"][0]
        self.assertEqual(feat["rework_cycles"], 1)

    def test_a_capped_history_is_flagged_and_worded_as_a_window(self) -> None:
        root = self._root({
            "phase": "build", "featureId": "F", "enteredAt": "x",
            "history": [{"phase": "build", "featureId": "F", "at": "x"}]
                       * C.PI_WORKFLOW_HISTORY_CAP,
        })
        report = pp.report_for_roots([root])
        self.assertTrue(report["projects"][0]["history_may_be_truncated"])
        self.assertTrue(report["any_history_may_be_truncated"])
        self.assertIn("retained window", report["absence_note"])
        self.assertNotIn("never", report["absence_note"].split("not evidence")[0])

    def test_no_history_is_reported_not_silently_empty(self) -> None:
        # A root with no workflow file must SAY so. An empty report that
        # looks healthy is the failure mode this guards.
        root = self._root(None)
        report = pp.report_for_roots([root])
        self.assertEqual(report["projects_with_history"], 0)
        self.assertFalse(report["projects"][0]["has_workflow_history"])
        self.assertEqual(report["projects"][0]["features"], [])

    def test_report_carries_no_score(self) -> None:
        root = self._root({"phase": "review", "featureId": "F", "history": []})
        import json as _json
        blob = _json.dumps(pp.report_for_roots([root]))
        for banned in ("score", "compliance", "violation", "conformance"):
            self.assertNotIn(banned, blob.lower())
