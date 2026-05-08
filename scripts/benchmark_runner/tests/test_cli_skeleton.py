# tests/test_cli_skeleton.py — CLI conformance.
#
# Phase 1 ships the stub adapter + stub backend by default. Tests that
# need an isolated registry call ``unregister_all_for_tests`` in setUp
# and then either drive the registry directly OR call main() and accept
# the auto-registered stub baseline.

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from benchmark_runner._register import (
    register_all,
    unregister_all_for_tests,
)
from benchmark_runner.cli import (
    EXIT_NOT_IMPLEMENTED,
    EXIT_OK,
    EXIT_RUNTIME,
    EXIT_USAGE,
    main,
)


class CLITestBase(unittest.TestCase):
    def setUp(self) -> None:
        unregister_all_for_tests()

    def _invoke(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()


class TestListCommand(CLITestBase):
    def test_list_default_includes_stub(self) -> None:
        rc, stdout, _ = self._invoke("list")
        self.assertEqual(rc, EXIT_OK)
        payload = json.loads(stdout)
        self.assertIn("stub", payload["adapters"])
        self.assertIn("stub", payload["backends"])

    def test_list_after_extra_adapter_registration(self) -> None:
        # Pre-register an additional adapter under a name that does NOT
        # collide with the shipped 'stub'. main() will auto-register
        # stub on top.
        from benchmark_runner.contracts import (
            ISOLATION_WORKTREE,
            TaskSpec,
            VerifyResult,
        )
        from benchmark_runner.registry import register_adapter

        class _Demo:
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

        register_adapter("demo", _Demo)

        rc, stdout, _ = self._invoke("list")
        self.assertEqual(rc, EXIT_OK)
        payload = json.loads(stdout)
        self.assertEqual(sorted(payload["adapters"]), ["demo", "stub"])
        self.assertIn("stub", payload["backends"])

    def test_list_with_known_benchmark_returns_tasks(self) -> None:
        rc, stdout, _ = self._invoke("list", "--benchmark", "stub")
        self.assertEqual(rc, EXIT_OK)
        payload = json.loads(stdout)
        self.assertEqual(payload["benchmark_id"], "stub")
        self.assertEqual(
            [t["task_id"] for t in payload["tasks"]],
            ["hello-world"],
        )

    def test_list_with_unknown_benchmark_returns_usage(self) -> None:
        rc, _, stderr = self._invoke("list", "--benchmark", "nope")
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("unknown adapter", stderr)


class TestRunCommand(CLITestBase):
    def test_run_unknown_adapter_returns_usage(self) -> None:
        rc, _, stderr = self._invoke(
            "run", "--benchmark", "nope", "--backend", "stub", "--runs", "1"
        )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("unknown adapter", stderr)

    def test_run_unknown_backend_returns_usage(self) -> None:
        rc, _, stderr = self._invoke(
            "run", "--benchmark", "stub", "--backend", "ghost:v1", "--runs", "1"
        )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("unknown backend", stderr)

    def test_run_unknown_task_filter_returns_usage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rc, _, stderr = self._invoke(
                "run",
                "--benchmark",
                "stub",
                "--backend",
                "stub",
                "--runs",
                "1",
                "--task",
                "missing-task",
                "--runs-root",
                td,
            )
            self.assertEqual(rc, EXIT_USAGE)
            self.assertIn("missing-task", stderr)

    def test_run_stub_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rc, stdout, _ = self._invoke(
                "run",
                "--benchmark",
                "stub",
                "--backend",
                "stub",
                "--runs",
                "1",
                "--runs-root",
                td,
            )
            self.assertEqual(rc, EXIT_OK)
            payload = json.loads(stdout)
            run_dir = Path(payload["run_dir"])
            self.assertTrue(run_dir.exists())
            scores = list(run_dir.rglob("score.json"))
            self.assertEqual(len(scores), 1)
            with scores[0].open() as f:
                score = json.load(f)
            self.assertEqual(score["result"], "pass")


class TestReportCommand(CLITestBase):
    def test_report_missing_dir_returns_usage(self) -> None:
        rc, _, stderr = self._invoke(
            "report", "--run-dir", "/nonexistent/path/runs"
        )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("run-dir not found", stderr)

    def test_report_empty_dir_returns_usage(self) -> None:
        # An existing dir with no score.json files cannot produce a
        # report; Phase 1 surfaces this as USAGE rather than crashing.
        with tempfile.TemporaryDirectory() as td:
            rc, _, stderr = self._invoke("report", "--run-dir", td)
            self.assertEqual(rc, EXIT_USAGE)
            self.assertIn("no score.json files", stderr)

    def test_report_after_run(self) -> None:
        # End-to-end: run, then report. Both subcommands hit real code.
        with tempfile.TemporaryDirectory() as td:
            rc, stdout, _ = self._invoke(
                "run",
                "--benchmark",
                "stub",
                "--backend",
                "stub",
                "--runs",
                "1",
                "--runs-root",
                td,
            )
            self.assertEqual(rc, EXIT_OK)
            run_dir = json.loads(stdout)["run_dir"]

            rc, stdout, _ = self._invoke("report", "--run-dir", run_dir)
            self.assertEqual(rc, EXIT_OK)
            report_md = Path(json.loads(stdout)["report_md"])
            self.assertTrue(report_md.exists())
            content = report_md.read_text(encoding="utf-8")
            self.assertIn("Backend `stub`", content)
            self.assertIn("100.0%", content)


class TestDogfoodCommand(CLITestBase):
    def test_dogfood_phase0_not_implemented(self) -> None:
        # Dogfood is Phase 4. Stays NOT_IMPLEMENTED for the whole MVP
        # build phases until issue #32's report+dogfood phase.
        rc, _, stderr = self._invoke(
            "dogfood", "--backend", "claude-code:sonnet"
        )
        self.assertEqual(rc, EXIT_NOT_IMPLEMENTED)
        self.assertIn("Phase 4", stderr)


if __name__ == "__main__":
    unittest.main()
