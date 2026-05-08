# tests/test_run_orchestration.py — end-to-end stub × stub run.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_runner._register import register_all, unregister_all_for_tests
from benchmark_runner.run import run_benchmark


class TestRunOrchestration(unittest.TestCase):
    def setUp(self) -> None:
        unregister_all_for_tests()
        register_all()

    def test_stub_run_writes_complete_run_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "stub",
                "stub",
                runs=1,
                runs_root=Path(td),
            )
            # Run directory exists under the requested root.
            self.assertTrue(run_dir.exists())
            self.assertEqual(run_dir.parent, Path(td))

            # One attempt directory for the one task × one run × one attempt.
            attempt_dirs = [p for p in run_dir.rglob("attempt-*") if p.is_dir()]
            self.assertEqual(len(attempt_dirs), 1)
            attempt = attempt_dirs[0]

            for required_file in (
                "run-record.json",
                "score.json",
                "stats.json",
                "prompt.md",
                "diff.patch",
            ):
                self.assertTrue(
                    (attempt / required_file).is_file(),
                    f"missing {required_file} in {attempt}",
                )
            # Worktree contains the model-produced file (the stub backend's copy).
            self.assertTrue((attempt / "worktree" / "hello.txt").is_file())

    def test_stub_run_score_records_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "stub", "stub", runs=1, runs_root=Path(td)
            )
            score_files = list(run_dir.rglob("score.json"))
            self.assertEqual(len(score_files), 1)
            with score_files[0].open() as f:
                score = json.load(f)
            self.assertEqual(score["result"], "pass")
            self.assertEqual(score["scores"]["tests_passed"], True)
            # Lint/typecheck null because stub adapter doesn't run them.
            self.assertIsNone(score["scores"]["lint_passed"])
            self.assertIsNone(score["scores"]["typecheck_passed"])

    def test_run_record_carries_prompt_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "stub", "stub", runs=1, runs_root=Path(td)
            )
            rr_files = list(run_dir.rglob("run-record.json"))
            self.assertEqual(len(rr_files), 1)
            with rr_files[0].open() as f:
                rr = json.load(f)

        # Prompt block is required by schema and must be populated.
        self.assertIn("prompt", rr)
        self.assertEqual(rr["prompt"]["path"], "prompt.md")
        self.assertEqual(len(rr["prompt"]["sha256"]), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in rr["prompt"]["sha256"]))
        # Stub backend doesn't wrap → effective_prompt is null.
        self.assertIsNone(rr["effective_prompt"])

    def test_stats_no_dollar_cost(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "stub", "stub", runs=1, runs_root=Path(td)
            )
            stats = json.loads(
                next(run_dir.rglob("stats.json")).read_text(encoding="utf-8")
            )
        # Hard-locked invariant from spec.md § Constraints.
        self.assertEqual(stats["cost_reporting"]["enabled"], False)
        self.assertIn("billing-correlation", stats["cost_reporting"]["reason"])

    def test_runs_param_repeats(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "stub", "stub", runs=3, runs_root=Path(td)
            )
            scores = list(run_dir.rglob("score.json"))
            self.assertEqual(len(scores), 3)

    def test_invalid_runs_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                run_benchmark(
                    "stub", "stub", runs=0, runs_root=Path(td)
                )

    def test_empty_adapter_run_errors_with_fetch_hint(self) -> None:
        # Regression: an adapter that exposes zero tasks (typical
        # missing-cache case) used to silently produce an empty run-dir
        # and exit 0. Now: EmptyAdapterError surfaces, the CLI converts
        # to EXIT_USAGE, and the message tells the user to run fetch.
        from benchmark_runner._register import unregister_all_for_tests
        from benchmark_runner.contracts import (
            ISOLATION_WORKTREE,
            VerifyResult,
        )
        from benchmark_runner.registry import (
            register_adapter,
            register_backend,
        )
        from benchmark_runner.run import EmptyAdapterError

        unregister_all_for_tests()

        class _EmptyAdapter:
            benchmark_id = "empty"
            isolation_default = ISOLATION_WORKTREE
            def list_tasks(self): return []
            def prepare_task(self, task, worktree): return None
            def prompt_for(self, task, attempt, prior): return ""
            def verify(self, task, worktree):
                return VerifyResult(tests_passed=True, tests_output="")
            def golden_patch(self, task): return Path("/tmp")
            def max_attempts(self): return 1

        register_adapter("empty", _EmptyAdapter)

        from benchmark_runner.backends.stub import factory as stub_factory
        register_backend("stub", stub_factory)

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(EmptyAdapterError) as cm:
                run_benchmark("empty", "stub", runs=1, runs_root=Path(td))
            self.assertIn("fetch", str(cm.exception).lower())

    def test_two_shot_pass_first_attempt_skips_retry(self) -> None:
        # Regression: when a task passes on attempt 1, no second attempt
        # should be executed. The runner used to always loop to
        # max_attempts() regardless of pass/fail.
        from benchmark_runner._register import unregister_all_for_tests
        from benchmark_runner.contracts import (
            ISOLATION_WORKTREE,
            BackendResult,
            RunContext,
            TaskSpec,
            VerifyResult,
        )
        from benchmark_runner.registry import (
            register_adapter,
            register_backend,
        )

        unregister_all_for_tests()

        attempts_seen: list[int] = []

        class _AlwaysPass:
            benchmark_id = "always-pass"
            isolation_default = ISOLATION_WORKTREE
            def list_tasks(self):
                return [TaskSpec(task_id="t1", language="text")]
            def prepare_task(self, task, worktree): return None
            def prompt_for(self, task, attempt, prior):
                attempts_seen.append(attempt)
                return f"attempt-{attempt}"
            def verify(self, task, worktree):
                return VerifyResult(tests_passed=True, tests_output="ok")
            def golden_patch(self, task): return Path("/tmp")
            def max_attempts(self): return 2

        class _NoOpBackend:
            backend_id = "noop"
            def run(self, prompt: str, ctx: RunContext) -> BackendResult:
                return BackendResult(transcript_path=None, elapsed_seconds=0.0)

        register_adapter("always-pass", _AlwaysPass)
        register_backend("noop", lambda model: _NoOpBackend())

        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "always-pass", "noop", runs=1, runs_root=Path(td)
            )
            attempt_dirs = [p for p in run_dir.rglob("attempt-*") if p.is_dir()]
            self.assertEqual(len(attempt_dirs), 1, "should stop after first pass")
            self.assertEqual(attempts_seen, [1], "second attempt should not have been triggered")

    def test_two_shot_fail_carries_prior_into_attempt_2(self) -> None:
        # Regression: when attempt 1 fails, attempt 2's prompt must
        # include the prior verify output (Aider-style retry).
        from benchmark_runner._register import unregister_all_for_tests
        from benchmark_runner.contracts import (
            ISOLATION_WORKTREE,
            BackendResult,
            RunContext,
            TaskSpec,
            VerifyResult,
        )
        from benchmark_runner.registry import (
            register_adapter,
            register_backend,
        )

        unregister_all_for_tests()

        prompts_seen: list[str] = []
        verify_call_count = {"n": 0}

        class _FailThenPass:
            benchmark_id = "fail-then-pass"
            isolation_default = ISOLATION_WORKTREE
            def list_tasks(self):
                return [TaskSpec(task_id="t1", language="text")]
            def prepare_task(self, task, worktree): return None
            def prompt_for(self, task, attempt, prior):
                prompt = f"attempt-{attempt}"
                if prior is not None:
                    prompt += f"\nPRIOR_OUTPUT: {prior.tests_output}"
                prompts_seen.append(prompt)
                return prompt
            def verify(self, task, worktree):
                verify_call_count["n"] += 1
                if verify_call_count["n"] == 1:
                    return VerifyResult(
                        tests_passed=False,
                        tests_output="ERR: missing implementation",
                    )
                return VerifyResult(tests_passed=True, tests_output="ok")
            def golden_patch(self, task): return Path("/tmp")
            def max_attempts(self): return 2

        class _NoOpBackend:
            backend_id = "noop"
            def run(self, prompt: str, ctx: RunContext) -> BackendResult:
                return BackendResult(transcript_path=None, elapsed_seconds=0.0)

        register_adapter("fail-then-pass", _FailThenPass)
        register_backend("noop", lambda model: _NoOpBackend())

        with tempfile.TemporaryDirectory() as td:
            run_dir = run_benchmark(
                "fail-then-pass", "noop", runs=1, runs_root=Path(td)
            )

            self.assertEqual(len(prompts_seen), 2, "two prompts should be built")
            self.assertEqual(prompts_seen[0], "attempt-1")
            self.assertIn("PRIOR_OUTPUT: ERR: missing implementation", prompts_seen[1])

            # Two attempt directories on disk, one for each attempt.
            attempt_dirs = sorted(p for p in run_dir.rglob("attempt-*") if p.is_dir())
            self.assertEqual(len(attempt_dirs), 2)

    def test_back_to_back_runs_get_sibling_run_dirs(self) -> None:
        # Regression: two run_benchmark calls within the same UTC-second
        # must succeed, producing sibling run directories. Previously
        # the second collided on the second-precision timestamp and
        # raised FileExistsError.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir_a = run_benchmark("stub", "stub", runs=1, runs_root=root)
            run_dir_b = run_benchmark("stub", "stub", runs=1, runs_root=root)

            self.assertNotEqual(run_dir_a, run_dir_b)
            self.assertEqual(run_dir_a.parent, run_dir_b.parent)
            self.assertTrue(run_dir_a.exists())
            self.assertTrue(run_dir_b.exists())
            # Both runs should have produced complete records.
            self.assertEqual(len(list(run_dir_a.rglob("score.json"))), 1)
            self.assertEqual(len(list(run_dir_b.rglob("score.json"))), 1)


if __name__ == "__main__":
    unittest.main()
