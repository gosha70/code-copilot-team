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
