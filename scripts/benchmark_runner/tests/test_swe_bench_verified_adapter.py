# tests/test_swe_bench_verified_adapter.py — #33 SWE-bench Verified
# adapter scoring. Offline: isolation.run_in_worktree is faked so no
# docker/network is touched; verify() only reads task.metadata.

import subprocess
import unittest
from unittest import mock

from benchmark_runner.contracts import TaskSpec
from benchmarks.adapters.swe_bench_verified.adapter import SweBenchVerifiedAdapter


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["python", "-m", "pytest"], returncode=returncode,
        stdout=stdout, stderr=stderr,
    )


class TestSweBenchVerifyScoring(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = SweBenchVerifiedAdapter(cache_file=None)
        self.task = TaskSpec(
            task_id="astropy__astropy-12345",
            language="python",
            metadata={
                "FAIL_TO_PASS": ["tests/test_x.py::test_a"],
                "PASS_TO_PASS": ["tests/test_y.py::test_b"],
                "image": "swebench/sweb.eval.x86_64.astropy__astropy-12345",
                "base_commit": "deadbeef",
                "repo": "astropy/astropy",
            },
        )

    def test_all_pass_is_tests_passed(self) -> None:
        # full run exit 0, then the PASS_TO_PASS re-run also exit 0.
        with mock.patch(
            "benchmark_runner.isolation.run_in_worktree",
            side_effect=[_proc(0, "2 passed"), _proc(0, "1 passed")],
        ):
            r = self.adapter.verify(self.task, __import__("pathlib").Path("/wt"))
        self.assertTrue(r.tests_passed)
        self.assertEqual(r.failed_commands, 0)

    def test_fail_to_pass_still_failing(self) -> None:
        with mock.patch(
            "benchmark_runner.isolation.run_in_worktree",
            return_value=_proc(1, "1 failed, 1 passed"),
        ):
            r = self.adapter.verify(self.task, __import__("pathlib").Path("/wt"))
        self.assertFalse(r.tests_passed)
        self.assertEqual(r.failed_commands, 1)

    def test_pass_to_pass_regression_fails(self) -> None:
        # full run "passes" (exit 0) but the PASS_TO_PASS re-run regresses.
        with mock.patch(
            "benchmark_runner.isolation.run_in_worktree",
            side_effect=[_proc(0, "2 passed"), _proc(1, "1 failed")],
        ):
            r = self.adapter.verify(self.task, __import__("pathlib").Path("/wt"))
        self.assertFalse(r.tests_passed)
        self.assertIn("PASS_TO_PASS regression", r.tests_output)

    def test_no_test_cases(self) -> None:
        task = TaskSpec(task_id="x", language="python", metadata={})
        r = self.adapter.verify(task, __import__("pathlib").Path("/wt"))
        self.assertFalse(r.tests_passed)
        self.assertIn("no test cases", r.tests_output)

    def test_single_shot(self) -> None:
        self.assertEqual(self.adapter.max_attempts(), 1)


if __name__ == "__main__":
    unittest.main()
