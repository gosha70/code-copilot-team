# tests/test_cli_skeleton.py — CLI skeleton conformance.
#
# Phase 0 contract: ``list`` returns empty arrays when no adapter or
# backend is registered; ``run``/``report``/``dogfood`` validate args
# and exit with EXIT_NOT_IMPLEMENTED rather than crashing.

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from benchmark_runner.cli import (
    EXIT_NOT_IMPLEMENTED,
    EXIT_OK,
    EXIT_USAGE,
    main,
)
from benchmark_runner.registry import _reset_for_tests


class CLITestBase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_for_tests()

    def _invoke(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()


class TestListCommand(CLITestBase):
    def test_list_empty_returns_zero(self) -> None:
        rc, stdout, _ = self._invoke("list")
        self.assertEqual(rc, EXIT_OK)
        payload = json.loads(stdout)
        self.assertEqual(payload, {"adapters": [], "backends": []})

    def test_list_after_registration(self) -> None:
        from benchmark_runner.contracts import (
            ISOLATION_WORKTREE,
            BackendResult,
            RunContext,
            TaskSpec,
            VerifyResult,
        )
        from benchmark_runner.registry import register_adapter, register_backend

        class _A:
            benchmark_id = "demo"
            isolation_default = ISOLATION_WORKTREE

            def list_tasks(self) -> list[TaskSpec]:
                return []

            def prepare_task(self, task, worktree):  # type: ignore[no-untyped-def]
                return None

            def prompt_for(self, task, attempt, prior):  # type: ignore[no-untyped-def]
                return ""

            def verify(self, task, worktree):  # type: ignore[no-untyped-def]
                return VerifyResult(tests_passed=True, tests_output="")

            def golden_patch(self, task):  # type: ignore[no-untyped-def]
                return Path("/tmp")

            def max_attempts(self) -> int:
                return 1

        class _B:
            backend_id = "stub"

            def run(self, prompt: str, ctx: RunContext) -> BackendResult:
                return BackendResult(transcript_path=None, elapsed_seconds=0.0)

        register_adapter("demo", _A)
        register_backend("stub", lambda model: _B())

        rc, stdout, _ = self._invoke("list")
        self.assertEqual(rc, EXIT_OK)
        payload = json.loads(stdout)
        self.assertEqual(payload, {"adapters": ["demo"], "backends": ["stub"]})

    def test_list_with_benchmark_phase0_not_implemented(self) -> None:
        rc, _, stderr = self._invoke("list", "--benchmark", "demo")
        self.assertEqual(rc, EXIT_NOT_IMPLEMENTED)
        self.assertIn("Phase 1", stderr)


class TestRunCommand(CLITestBase):
    def test_run_unknown_adapter_returns_usage(self) -> None:
        rc, _, stderr = self._invoke(
            "run", "--benchmark", "nope", "--backend", "stub", "--runs", "1"
        )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("unknown adapter", stderr)

    def test_run_unknown_backend_returns_usage(self) -> None:
        # Register a real adapter so we get past the adapter check.
        from benchmark_runner.contracts import (
            ISOLATION_WORKTREE,
            TaskSpec,
            VerifyResult,
        )
        from benchmark_runner.registry import register_adapter

        class _A:
            benchmark_id = "demo"
            isolation_default = ISOLATION_WORKTREE

            def list_tasks(self) -> list[TaskSpec]:
                return []

            def prepare_task(self, task, worktree):  # type: ignore[no-untyped-def]
                return None

            def prompt_for(self, task, attempt, prior):  # type: ignore[no-untyped-def]
                return ""

            def verify(self, task, worktree):  # type: ignore[no-untyped-def]
                return VerifyResult(tests_passed=True, tests_output="")

            def golden_patch(self, task):  # type: ignore[no-untyped-def]
                return Path("/tmp")

            def max_attempts(self) -> int:
                return 1

        register_adapter("demo", _A)

        rc, _, stderr = self._invoke(
            "run", "--benchmark", "demo", "--backend", "ghost:v1", "--runs", "1"
        )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("unknown backend", stderr)


class TestReportCommand(CLITestBase):
    def test_report_missing_dir_returns_usage(self) -> None:
        rc, _, stderr = self._invoke(
            "report", "--run-dir", "/nonexistent/path/runs"
        )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("run-dir not found", stderr)

    def test_report_existing_dir_phase0_not_implemented(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            rc, _, stderr = self._invoke("report", "--run-dir", td)
            self.assertEqual(rc, EXIT_NOT_IMPLEMENTED)
            self.assertIn("Phase 1", stderr)


class TestDogfoodCommand(CLITestBase):
    def test_dogfood_phase0_not_implemented(self) -> None:
        rc, _, stderr = self._invoke(
            "dogfood", "--backend", "claude-code:sonnet"
        )
        self.assertEqual(rc, EXIT_NOT_IMPLEMENTED)
        self.assertIn("Phase 4", stderr)


if __name__ == "__main__":
    unittest.main()
