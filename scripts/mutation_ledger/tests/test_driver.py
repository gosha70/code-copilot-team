# Tests for the mutation-ledger driver.
#
# Every test here is a REGRESSION for a defect that actually occurred
# while producing specs/session-analytics-similarity-cluster/
# mutation-ledger.md — not speculative hardening. The runner is
# injected, so these are hermetic: no pytest subprocess, no real
# mutation of repo files.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mutation_ledger.driver import (
    AnchorError,
    BaselineError,
    Mutation,
    parse_failing_tests,
    run_ledger,
)

GREEN = "80 passed, 11 subtests passed in 4.54s"
RED = ("FAILED session_analytics/tests/test_x.py::TestA::test_alpha\n"
       "1 failed, 79 passed in 4.60s")


class _Runner:
    """Scripted runner: returns (rc, output) per call, recording calls."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.seen_sources = []

    def __call__(self, root, test_paths):
        self.calls += 1
        # capture what the file looked like AT RUN TIME, so a test can
        # prove the mutation was actually applied when the suite ran
        for p in sorted(Path(root).glob("*.py")):
            self.seen_sources.append(p.read_text(encoding="utf-8"))
        rc, out = self.outcomes.pop(0)
        return rc, out


def _tree(content="value = 1\n"):
    root = Path(tempfile.mkdtemp(prefix="cct-ledger-"))
    (root / "mod.py").write_text(content, encoding="utf-8")
    return root


class TestParserCountsSubtestFailures(unittest.TestCase):
    """REGRESSION: the parser matched FAILED/ERROR but not SUBFAILED.

    Subtest-driven discriminators reported "caught by 0 tests" — a
    caught mutation that looked like a hole, and which would equally
    have hidden a real one.
    """

    def test_subfailed_lines_are_counted(self) -> None:
        out = ("SUBFAILED(limit=1.5) a/b.py::TestC::test_limits\n"
               "SUBFAILED(limit=True) a/b.py::TestC::test_limits\n"
               "4 failed, 27 passed, 7 subtests passed in 2.34s")
        self.assertEqual(parse_failing_tests(out), ["test_limits"])

    def test_failed_and_error_still_counted(self) -> None:
        out = ("FAILED a/b.py::TestC::test_one\n"
               "ERROR a/b.py::TestC::test_two\n"
               "2 failed in 1s")
        self.assertEqual(parse_failing_tests(out), ["test_one", "test_two"])

    def test_names_are_deduplicated_and_sorted(self) -> None:
        out = ("SUBFAILED(x=1) a/b.py::T::test_b\n"
               "SUBFAILED(x=2) a/b.py::T::test_b\n"
               "FAILED a/b.py::T::test_a\n")
        self.assertEqual(parse_failing_tests(out), ["test_a", "test_b"])

    def test_passing_output_yields_nothing(self) -> None:
        self.assertEqual(parse_failing_tests(GREEN), [])


class TestUnmatchedAnchorIsFatal(unittest.TestCase):
    """REGRESSION: an anchor matching 0 or 2 places was SKIPPED.

    A mutation nobody ran still looked accounted for, so the ledger's
    total overstated what had been exercised.
    """

    def test_absent_anchor_raises_rather_than_skipping(self) -> None:
        root = _tree()
        runner = _Runner([(0, GREEN)])
        with self.assertRaises(AnchorError) as ctx:
            run_ledger([Mutation("M1", "mod.py", "not-present", "x")],
                       root=root, test_paths=["."], runner=runner)
        self.assertIn("matched 0 places", str(ctx.exception))
        self.assertIn("M1", str(ctx.exception))

    def test_ambiguous_anchor_raises(self) -> None:
        root = _tree("dup = 1\ndup = 1\n")
        runner = _Runner([(0, GREEN)])
        with self.assertRaises(AnchorError) as ctx:
            run_ledger([Mutation("M2", "mod.py", "dup = 1", "dup = 2")],
                       root=root, test_paths=["."], runner=runner)
        self.assertIn("matched 2 places", str(ctx.exception))

    def test_anchors_validated_before_anything_is_applied(self) -> None:
        # a good mutation followed by a bad one must not half-apply
        root = _tree("good = 1\n")
        runner = _Runner([(0, GREEN)])
        with self.assertRaises(AnchorError):
            run_ledger([Mutation("ok", "mod.py", "good = 1", "good = 2"),
                        Mutation("bad", "mod.py", "missing", "x")],
                       root=root, test_paths=["."], runner=runner)
        self.assertEqual((root / "mod.py").read_text(), "good = 1\n")
        self.assertEqual(runner.calls, 1, "only the baseline should have run")


class TestNoOpMutationIsReportedEscaped(unittest.TestCase):
    """REGRESSION: a mutation that changes nothing must not read as caught.

    `notes = {} or {...}` returns its second operand, so the "mutated"
    code was identical to the original. It reported a clean pass, which
    is indistinguishable from a genuine escape unless escapes are
    surfaced explicitly.
    """

    def test_suite_still_green_means_escaped(self) -> None:
        root = _tree()
        runner = _Runner([(0, GREEN), (0, GREEN), (0, GREEN)])
        report = run_ledger([Mutation("M", "mod.py", "value = 1", "value = 1 ")],
                            root=root, test_paths=["."], runner=runner)
        self.assertEqual(report.caught, 0)
        self.assertEqual(report.escaped, ("M",))
        self.assertEqual(report.results[0].failing_tests, ())

    def test_failing_suite_means_caught_with_names(self) -> None:
        root = _tree()
        runner = _Runner([(0, GREEN), (1, RED), (0, GREEN)])
        report = run_ledger([Mutation("M", "mod.py", "value = 1", "value = 2")],
                            root=root, test_paths=["."], runner=runner)
        self.assertEqual(report.caught, 1)
        self.assertEqual(report.escaped, ())
        self.assertEqual(report.results[0].failing_tests, ("test_alpha",))


class TestBaselineAndRestore(unittest.TestCase):
    """The measurement is only meaningful from a known starting state."""

    def test_red_baseline_refuses_to_run(self) -> None:
        root = _tree()
        with self.assertRaises(BaselineError) as ctx:
            run_ledger([Mutation("M", "mod.py", "value = 1", "value = 2")],
                       root=root, test_paths=["."], runner=_Runner([(1, RED)]))
        self.assertIn("not green", str(ctx.exception))

    def test_skipped_baseline_refuses_to_run(self) -> None:
        # a ledger run with skipped classes measures less than it claims
        root = _tree()
        skipped = "70 passed, 10 skipped in 4.0s"
        with self.assertRaises(BaselineError) as ctx:
            run_ledger([Mutation("M", "mod.py", "value = 1", "value = 2")],
                       root=root, test_paths=["."],
                       runner=_Runner([(0, skipped)]))
        self.assertIn("skips", str(ctx.exception))

    def test_mutation_is_actually_applied_when_the_suite_runs(self) -> None:
        root = _tree()
        runner = _Runner([(0, GREEN), (1, RED), (0, GREEN)])
        run_ledger([Mutation("M", "mod.py", "value = 1", "value = 999")],
                   root=root, test_paths=["."], runner=runner)
        # baseline, mutated, restored — the middle run must have seen it
        self.assertIn("value = 999", runner.seen_sources[1])
        self.assertNotIn("value = 999", runner.seen_sources[0])
        self.assertNotIn("value = 999", runner.seen_sources[2])

    def test_files_are_restored_even_when_the_runner_raises(self) -> None:
        root = _tree()

        class _Exploding(_Runner):
            def __call__(self, r, t):
                if self.calls >= 1:
                    self.calls += 1
                    raise RuntimeError("runner died mid-pass")
                return super().__call__(r, t)

        with self.assertRaises(RuntimeError):
            run_ledger([Mutation("M", "mod.py", "value = 1", "value = 2")],
                       root=root, test_paths=["."],
                       runner=_Exploding([(0, GREEN)]))
        self.assertEqual((root / "mod.py").read_text(), "value = 1\n",
                         "a driver that leaves the tree mutated corrupts "
                         "what it measures")

    def test_unrestored_suite_is_an_error(self) -> None:
        root = _tree()
        # green baseline, caught mutation, then RED on the restore check
        runner = _Runner([(0, GREEN), (1, RED), (1, RED)])
        with self.assertRaises(BaselineError) as ctx:
            run_ledger([Mutation("M", "mod.py", "value = 1", "value = 2")],
                       root=root, test_paths=["."], runner=runner)
        self.assertIn("NOT restored", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
