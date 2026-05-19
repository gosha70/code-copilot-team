# tests/test_timeout_classification.py — D5 timeout classification + skip + aggregator flag.
#
# Test groups:
#   A. Timeout detection: BackendResult.timed_out=True → result="timeout",
#      scores.timeout=True, verify-output.txt contains harness note.
#   B. Skip-to-next: timed-out attempt does NOT halt the campaign;
#      the next attempt/run continues normally.
#   C. Progress: end line contains "timeout after Ns — skipping".
#   D. Aggregator: timed_out count in group summary; verify-output.txt
#      contains harness note; verdict calculus unchanged (constraint #8).
#   E. compare._validate / CompareConfig parse attempt_timeout_seconds.
#   F. Timeout threading: RunContext.timeout_seconds carries the resolved value.
#   G. Precedence: --attempt-timeout > preset > heuristic.
#   H. load_config on local-vs-cloud.json retains attempt_timeout_seconds == 600.
#
# No real `claude` is spawned — all backends are in-process stubs.

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from benchmark_runner._register import register_all, unregister_all_for_tests
from benchmark_runner.compare import (
    CompareConfig,
    CompareConfigError,
    _validate,
    load_config,
)
from benchmark_runner.contracts import (
    ISOLATION_WORKTREE,
    BackendResult,
    IsolationConfig,
    RunContext,
    TaskSpec,
    VerifyResult,
)
from benchmark_runner.progress import ProgressLogger
from benchmark_runner.registry import register_adapter, register_backend
from benchmark_runner.report import render_report
from benchmark_runner.run import run_benchmark


# ── Minimal test adapter ────────────────────────────────────────────────


class _MinimalAdapter:
    """Minimal benchmark adapter shared across all timeout test groups."""

    benchmark_id = "timeout-test"

    def __init__(self, verify_pass: bool = False) -> None:
        self._verify_pass = verify_pass

    def list_tasks(self) -> list[TaskSpec]:
        return [TaskSpec(task_id="timeout/task", language="text")]

    def isolation_for(self, task: TaskSpec) -> IsolationConfig:
        return IsolationConfig(tier=ISOLATION_WORKTREE)

    def prepare_task(self, task: TaskSpec, worktree: Path) -> None:
        pass

    def prompt_for(self, task: TaskSpec, attempt: int, prior: object) -> str:
        return f"attempt {attempt}"

    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult:
        return VerifyResult(
            tests_passed=self._verify_pass, tests_output=""
        )

    def golden_patch(self, task: TaskSpec) -> Path:
        return Path("/tmp")

    def max_attempts(self) -> int:
        return 1


# ── Timed-out backend stub ──────────────────────────────────────────────


class _TimedOutBackend:
    """Backend that signals it timed out (timed_out=True, exit_code=None).

    Simulates exactly what ClaudeCodeBackend returns on TimeoutExpired —
    without actually sleeping or spawning processes. Sets timed_out=True
    so _classify_result picks up RESULT_TIMEOUT.
    """

    backend_id = "timed-out-stub"

    def __init__(self, elapsed: float = 5.0) -> None:
        self._elapsed = elapsed

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        return BackendResult(
            transcript_path=None,
            elapsed_seconds=self._elapsed,
            failed_commands=1,
            timed_out=True,
            backend_metadata={
                "family": "timed-out-stub",
                "model": "",
                "exit_code": None,
                "note": f"claude -p timed out after {self._elapsed}s (process group killed)",
            },
        )


class _NormalBackend:
    """Backend that returns normally (no timeout)."""

    backend_id = "normal-stub"

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        return BackendResult(transcript_path=None, elapsed_seconds=0.1)


# ── Helper ──────────────────────────────────────────────────────────────


def _capture_stderr(fn) -> list[str]:
    buf = io.StringIO()
    old = sys.stderr
    sys.stderr = buf
    try:
        fn()
    finally:
        sys.stderr = old
    return buf.getvalue().splitlines()


# ── A. Timeout detection ────────────────────────────────────────────────


class TestTimeoutDetection(unittest.TestCase):
    """score.json reflects result=timeout, scores.timeout=True, verify-output.txt note."""

    def setUp(self) -> None:
        unregister_all_for_tests()
        register_adapter("timeout-test", _MinimalAdapter)
        register_backend("timed-out-stub", lambda model: _TimedOutBackend(elapsed=5.0))

    def test_result_is_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "timeout-test", "timed-out-stub", runs=1, runs_root=Path(td)
            )
            score = json.loads(next(run_dir.rglob("score.json")).read_text())
        self.assertEqual(score["result"], "timeout")

    def test_scores_timeout_true(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "timeout-test", "timed-out-stub", runs=1, runs_root=Path(td)
            )
            score = json.loads(next(run_dir.rglob("score.json")).read_text())
        self.assertTrue(score["scores"]["timeout"])

    def test_verify_output_contains_harness_note(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "timeout-test", "timed-out-stub", runs=1, runs_root=Path(td)
            )
            attempt_dirs = [p for p in run_dir.rglob("attempt-*") if p.is_dir()]
            self.assertEqual(len(attempt_dirs), 1)
            vo_path = attempt_dirs[0] / "verify-output.txt"
            self.assertTrue(vo_path.exists(), "verify-output.txt must be written on timeout")
            vo = vo_path.read_text()
        self.assertIn("<harness-imposed timeout after", vo)

    def test_non_timeout_backend_does_not_set_timeout_flag(self) -> None:
        """Regression: normal returns must keep scores.timeout == False."""
        unregister_all_for_tests()
        register_adapter("timeout-test", lambda: _MinimalAdapter(verify_pass=True))
        register_backend("normal-stub", lambda model: _NormalBackend())

        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "timeout-test", "normal-stub", runs=1, runs_root=Path(td)
            )
            score = json.loads(next(run_dir.rglob("score.json")).read_text())
        self.assertFalse(score["scores"]["timeout"])
        self.assertEqual(score["result"], "pass")


# ── B. Skip-to-next ─────────────────────────────────────────────────────


class TestSkipToNext(unittest.TestCase):
    """A timed-out attempt does not halt the campaign; subsequent runs execute."""

    def setUp(self) -> None:
        unregister_all_for_tests()

    def test_multiple_runs_all_continue_after_timeout(self) -> None:
        """With runs=3, all 3 runs execute even though each times out."""
        register_adapter("timeout-test", _MinimalAdapter)
        register_backend("timed-out-stub", lambda model: _TimedOutBackend())

        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "timeout-test", "timed-out-stub", runs=3, runs_root=Path(td)
            )
            scores = list(run_dir.rglob("score.json"))

            self.assertEqual(len(scores), 3, "all 3 runs must execute even on timeout")
            for s_path in scores:
                s = json.loads(s_path.read_text())
                self.assertEqual(s["result"], "timeout")

    def test_mixed_timeout_and_normal_both_recorded(self) -> None:
        """One timed-out backend + one normal backend in a two-candidate compare
        both produce score files — the campaign does not abort on timeout."""
        from benchmark_runner import _register
        from benchmark_runner.compare import Candidate as Can, run_comparison

        _register.unregister_all_for_tests()
        from benchmarks.adapters.stub.adapter import register as register_stub_adapter
        register_stub_adapter()
        from benchmark_runner.backends.stub import factory as stub_factory
        register_backend("stub", stub_factory)
        register_backend("timed-out-stub", lambda model: _TimedOutBackend())

        cfg2 = CompareConfig(
            benchmark="stub",
            runs=1,
            candidates=[
                Can(name="normal", backend="stub", model="", env={}),
                Can(name="hung", backend="timed-out-stub", model="", env={}),
            ],
        )

        with tempfile.TemporaryDirectory() as td:
            run_dir = run_comparison(cfg2, runs_root=Path(td), emit_report=False)
            scores = list(run_dir.rglob("score.json"))

            self.assertEqual(len(scores), 2, "both candidates must produce a score.json")
            results = {json.loads(p.read_text())["result"] for p in scores}
        self.assertIn("pass", results, "normal candidate must pass")
        self.assertIn("timeout", results, "timed-out candidate must record timeout")


# ── C. Progress line ─────────────────────────────────────────────────────


class TestTimeoutProgressLine(unittest.TestCase):
    """The heartbeat end line reads 'timeout after Ns — skipping'."""

    def setUp(self) -> None:
        unregister_all_for_tests()
        register_adapter("timeout-test", _MinimalAdapter)
        register_backend("timed-out-stub", lambda model: _TimedOutBackend(elapsed=5.2))

    def test_end_line_says_timeout_after_skipping(self) -> None:
        def _run():
            with tempfile.TemporaryDirectory() as td:
                with mock.patch(
                    "benchmark_runner.run.ProgressLogger",
                    return_value=ProgressLogger(heartbeat_interval=0.05),
                ):
                    run_benchmark(
                        "timeout-test", "timed-out-stub", runs=1, runs_root=Path(td)
                    )

        lines = _capture_stderr(_run)
        end_lines = [l for l in lines if "timeout after" in l and "skipping" in l]
        self.assertGreater(
            len(end_lines),
            0,
            f"Expected a 'timeout after ... — skipping' line. All lines: {lines}",
        )


# ── D. Aggregator tally ──────────────────────────────────────────────────


class TestAggregatorTimeoutTally(unittest.TestCase):
    """report.py group summary carries timed_out count; verdict calculus unchanged.

    Constraint #8 proof: given two otherwise-identical run-dirs where one
    has a timeout attempt and the other has that attempt relabeled fail, the
    verdict (pass_rate_verdict, elapsed_seconds_verdict, etc.) is identical.
    """

    def setUp(self) -> None:
        unregister_all_for_tests()
        register_all()

    def _make_score(
        self,
        td: str,
        result: str,
        timeout_flag: bool,
    ) -> Path:
        """Write a minimal score.json + run-record.json for one attempt."""
        attempt_dir = Path(td) / "attempt-01-run-001"
        attempt_dir.mkdir(parents=True)
        score = {
            "schema_version": "1.0",
            "benchmark_id": "stub",
            "task_id": "stub/hello-world",
            "backend_id": "stub",
            "run_id": "run-001",
            "attempt": 1,
            "scores": {
                "tests_passed": False,
                "lint_passed": None,
                "typecheck_passed": None,
                "required_files_present": True,
                "timeout": timeout_flag,
                "human_interventions": 0,
            },
            "derived": {
                "elapsed_seconds": 5.0,
                "files_changed": 0,
                "lines_added": 0,
                "lines_removed": 0,
                "failed_commands": 1,
            },
            "result": result,
        }
        rr = {
            "backend_id": "stub",
            "backend_invocation": {"model": ""},
            "backend": {"metadata": {}},
        }
        (attempt_dir / "score.json").write_text(json.dumps(score))
        (attempt_dir / "run-record.json").write_text(json.dumps(rr))
        return Path(td)

    def test_timed_out_count_in_group_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = self._make_score(td, result="timeout", timeout_flag=True)
            render_report(run_dir)
            summary = json.loads((run_dir / "report.json").read_text())

        # The group summary must carry a timed_out count.
        groups = summary["groups"]
        self.assertEqual(len(groups), 1)
        group = next(iter(groups.values()))
        self.assertIn("timed_out", group, "group summary must carry timed_out")
        self.assertEqual(group["timed_out"], 1)

    def test_no_timeouts_timed_out_is_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = self._make_score(td, result="fail", timeout_flag=False)
            render_report(run_dir)
            summary = json.loads((run_dir / "report.json").read_text())
        group = next(iter(summary["groups"].values()))
        self.assertEqual(group["timed_out"], 0)

    def test_markdown_shows_timed_out_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = self._make_score(td, result="timeout", timeout_flag=True)
            render_report(run_dir)
            md = (run_dir / "report.md").read_text()
        self.assertIn("Timed out:", md)

    def test_constraint_8_verdict_calculus_unchanged(self) -> None:
        """The same attempt recorded as 'timeout' vs 'fail' must produce
        byte-identical verdicts — only the visible tally differs.

        This is the constraint #8 proof. We use two groups in each run-dir
        (one with timeout+timeout, one with fail+fail for the same candidates)
        to get pairwise verdicts, and assert the verdict tuples match.
        """
        # Build a compare-style run-dir with two groups, both having the
        # same (backend, model) but different candidate names so they group
        # distinctly. One run-dir uses result="timeout"; the other uses
        # result="fail" for the same attempts. Both must produce the same
        # pairwise verdict tuple.
        def _make_compare_run_dir(td: str, result: str, timeout_flag: bool) -> Path:
            """Two candidates ('A', 'B'), each with 2 attempts, all with result."""
            parent = Path(td)
            # candidate-runs.json
            for cand_name, backend_id in [("A", "stub"), ("B", "stub2")]:
                cand_dir = parent / f"run-{cand_name}"
                for attempt_n in range(1, 3):
                    attempt_dir = cand_dir / f"task-stub--hello-world" / f"attempt-0{attempt_n}-run-001"
                    attempt_dir.mkdir(parents=True)
                    score = {
                        "schema_version": "1.0",
                        "benchmark_id": "stub",
                        "task_id": "stub/hello-world",
                        "backend_id": backend_id,
                        "run_id": "run-001",
                        "attempt": attempt_n,
                        "scores": {
                            "tests_passed": False,
                            "lint_passed": None,
                            "typecheck_passed": None,
                            "required_files_present": True,
                            "timeout": timeout_flag,
                            "human_interventions": 0,
                        },
                        "derived": {
                            "elapsed_seconds": 5.0,
                            "files_changed": 0,
                            "lines_added": 0,
                            "lines_removed": 0,
                            "failed_commands": 1,
                        },
                        "result": result,
                    }
                    rr = {
                        "backend_id": backend_id,
                        "backend_invocation": {"model": ""},
                        "backend": {"metadata": {}},
                    }
                    (attempt_dir / "score.json").write_text(json.dumps(score))
                    (attempt_dir / "run-record.json").write_text(json.dumps(rr))
            candidate_runs = {
                "candidates": [
                    {"name": "A", "run_dir": "run-A"},
                    {"name": "B", "run_dir": "run-B"},
                ]
            }
            (parent / "candidate-runs.json").write_text(json.dumps(candidate_runs))
            return parent

        with tempfile.TemporaryDirectory() as td1:
            run_dir_timeout = _make_compare_run_dir(td1, "timeout", True)
            render_report(run_dir_timeout)
            summary_timeout = json.loads((run_dir_timeout / "report.json").read_text())

        with tempfile.TemporaryDirectory() as td2:
            run_dir_fail = _make_compare_run_dir(td2, "fail", False)
            render_report(run_dir_fail)
            summary_fail = json.loads((run_dir_fail / "report.json").read_text())

        # Extract the pairwise verdicts — must be identical across both reports.
        pairs_t = summary_timeout["verdicts"]["pairwise"]
        pairs_f = summary_fail["verdicts"]["pairwise"]
        self.assertEqual(len(pairs_t), len(pairs_f))
        for pt, pf in zip(pairs_t, pairs_f):
            self.assertEqual(
                pt["pass_rate_verdict"],
                pf["pass_rate_verdict"],
                "pass_rate_verdict must be identical for timeout vs fail",
            )
            self.assertEqual(
                pt["elapsed_seconds_verdict"],
                pf["elapsed_seconds_verdict"],
                "elapsed_seconds_verdict must be identical",
            )
            self.assertEqual(
                pt["failed_commands_verdict"],
                pf["failed_commands_verdict"],
                "failed_commands_verdict must be identical",
            )
            self.assertEqual(
                pt["human_interventions_verdict"],
                pf["human_interventions_verdict"],
                "human_interventions_verdict must be identical",
            )

        # But the timeout tally DOES differ.
        group_t = next(iter(summary_timeout["groups"].values()))
        group_f = next(iter(summary_fail["groups"].values()))
        self.assertGreater(group_t["timed_out"], 0, "timeout run-dir must show timed_out > 0")
        self.assertEqual(group_f["timed_out"], 0, "fail run-dir must show timed_out == 0")


# ── E. compare._validate attempt_timeout_seconds ────────────────────────


class TestCompareValidateTimeout(unittest.TestCase):
    """compare._validate parses and validates attempt_timeout_seconds."""

    def _base(self) -> dict:
        return {
            "benchmark": "stub",
            "candidates": [
                {"backend": "stub"},
                {"backend": "stub2"},
            ],
        }

    def test_valid_positive_integer_accepted(self) -> None:
        raw = self._base()
        raw["attempt_timeout_seconds"] = 300
        cfg = _validate(raw)
        self.assertEqual(cfg.attempt_timeout_seconds, 300)

    def test_absent_is_none(self) -> None:
        cfg = _validate(self._base())
        self.assertIsNone(cfg.attempt_timeout_seconds)

    def test_rejects_zero(self) -> None:
        raw = self._base()
        raw["attempt_timeout_seconds"] = 0
        with self.assertRaisesRegex(CompareConfigError, "positive integer"):
            _validate(raw)

    def test_rejects_negative(self) -> None:
        raw = self._base()
        raw["attempt_timeout_seconds"] = -60
        with self.assertRaisesRegex(CompareConfigError, "positive integer"):
            _validate(raw)

    def test_rejects_bool(self) -> None:
        raw = self._base()
        raw["attempt_timeout_seconds"] = True
        with self.assertRaisesRegex(CompareConfigError, "positive integer"):
            _validate(raw)

    def test_rejects_float(self) -> None:
        raw = self._base()
        raw["attempt_timeout_seconds"] = 300.5
        with self.assertRaisesRegex(CompareConfigError, "positive integer"):
            _validate(raw)

    def test_rejects_string(self) -> None:
        raw = self._base()
        raw["attempt_timeout_seconds"] = "300"
        with self.assertRaisesRegex(CompareConfigError, "positive integer"):
            _validate(raw)

    def test_load_config_local_vs_cloud_retains_600(self) -> None:
        """load_config on the committed local-vs-cloud.json retains attempt_timeout_seconds==600."""
        presets_dir = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "benchmarks" / "presets"
        )
        preset_path = presets_dir / "local-vs-cloud.json"
        self.assertTrue(preset_path.exists(), f"preset not found: {preset_path}")
        cfg = load_config(preset_path)
        self.assertEqual(
            cfg.attempt_timeout_seconds,
            600,
            "local-vs-cloud.json must retain attempt_timeout_seconds == 600",
        )


# ── F. Timeout threading into RunContext ─────────────────────────────────


class TestTimeoutThreading(unittest.TestCase):
    """attempt_timeout_seconds flows from run_benchmark → RunContext.timeout_seconds."""

    def setUp(self) -> None:
        unregister_all_for_tests()

    def test_run_context_carries_timeout(self) -> None:
        """Backend receives RunContext.timeout_seconds == the value passed to run_benchmark."""
        seen_timeouts: list[Optional[int]] = []

        class _SpyBackend:
            backend_id = "spy"

            def run(self, prompt: str, ctx: RunContext) -> BackendResult:
                seen_timeouts.append(ctx.timeout_seconds)
                return BackendResult(transcript_path=None, elapsed_seconds=0.1)

        register_adapter("timeout-test", lambda: _MinimalAdapter(verify_pass=True))
        register_backend("spy", lambda model: _SpyBackend())

        with tempfile.TemporaryDirectory() as td:
            run_benchmark(
                "timeout-test", "spy", runs=1, runs_root=Path(td),
                attempt_timeout_seconds=42,
            )

        self.assertEqual(seen_timeouts, [42], f"Expected [42], got {seen_timeouts}")

    def test_none_timeout_passes_none_to_run_context(self) -> None:
        seen_timeouts: list[Optional[int]] = []

        class _SpyBackend:
            backend_id = "spy2"

            def run(self, prompt: str, ctx: RunContext) -> BackendResult:
                seen_timeouts.append(ctx.timeout_seconds)
                return BackendResult(transcript_path=None, elapsed_seconds=0.1)

        register_adapter("timeout-test", lambda: _MinimalAdapter(verify_pass=True))
        register_backend("spy2", lambda model: _SpyBackend())

        with tempfile.TemporaryDirectory() as td:
            run_benchmark(
                "timeout-test", "spy2", runs=1, runs_root=Path(td),
                # No attempt_timeout_seconds → None
            )

        self.assertEqual(seen_timeouts, [None])


# ── G. Precedence unit tests ─────────────────────────────────────────────


class TestTimeoutPrecedence(unittest.TestCase):
    """_resolve_timeout precedence: explicit > preset > heuristic."""

    def setUp(self) -> None:
        # Import the private function directly for unit testing.
        from benchmark_runner.bench import _resolve_timeout, ResolvedCandidate
        self._resolve = _resolve_timeout
        self._RC = ResolvedCandidate

    def _cloud_candidate(self) -> object:
        return self._RC(name="x", backend="claude-code", model="sonnet", env={}, is_anthropic=True)

    def _local_candidate(self) -> object:
        return self._RC(
            name="y", backend="claude-code", model="qwen",
            env={"ANTHROPIC_BASE_URL": "http://localhost:11434"}, is_anthropic=False,
        )

    def test_explicit_overrides_preset(self) -> None:
        result = self._resolve(explicit=999, preset_timeout=600, candidates=[self._cloud_candidate()])
        self.assertEqual(result, 999)

    def test_explicit_overrides_heuristic(self) -> None:
        result = self._resolve(explicit=42, candidates=[self._local_candidate()])
        self.assertEqual(result, 42)

    def test_preset_overrides_heuristic(self) -> None:
        result = self._resolve(preset_timeout=777, candidates=[self._cloud_candidate()])
        self.assertEqual(result, 777)

    def test_heuristic_cloud_is_300(self) -> None:
        result = self._resolve(candidates=[self._cloud_candidate()])
        self.assertEqual(result, 300)

    def test_heuristic_local_is_600(self) -> None:
        result = self._resolve(candidates=[self._local_candidate()])
        self.assertEqual(result, 600)

    def test_heuristic_any_local_candidate_triggers_600(self) -> None:
        """If ANY candidate is local, use the local (600s) heuristic."""
        result = self._resolve(candidates=[self._cloud_candidate(), self._local_candidate()])
        self.assertEqual(result, 600)

    def test_no_candidates_returns_none(self) -> None:
        result = self._resolve(candidates=[])
        self.assertIsNone(result)


# ── H. load_config retains attempt_timeout_seconds ──────────────────────
# (Covered by TestCompareValidateTimeout.test_load_config_local_vs_cloud_retains_600 above.)


# ── I. run_benchmark validates attempt_timeout_seconds ──────────────────


class TestRunBenchmarkTimeoutValidation(unittest.TestCase):
    """run_benchmark rejects non-positive or bool attempt_timeout_seconds."""

    def setUp(self) -> None:
        unregister_all_for_tests()
        register_adapter("timeout-test", _MinimalAdapter)
        register_backend("normal-stub", lambda model: _NormalBackend())

    def _run(self, timeout_val) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_benchmark(
                "timeout-test", "normal-stub", runs=1,
                runs_root=Path(td), attempt_timeout_seconds=timeout_val,
            )

    def test_zero_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integer"):
            self._run(0)

    def test_negative_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integer"):
            self._run(-5)

    def test_bool_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integer"):
            self._run(True)

    def test_none_does_not_raise(self) -> None:
        # attempt_timeout_seconds=None is the default — must proceed normally.
        self._run(None)  # no exception

    def test_positive_int_does_not_raise(self) -> None:
        # attempt_timeout_seconds=300 is valid.
        self._run(300)  # no exception


if __name__ == "__main__":
    unittest.main()
