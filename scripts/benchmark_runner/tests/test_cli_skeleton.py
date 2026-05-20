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
        # TB1.5 — `judges` key now ships in the list output and
        # both shipped claude-code tokens (canonical + alias)
        # appear. Pin the contract so a future regression that
        # drops one is caught here.
        self.assertIn("judges", payload)
        self.assertIn("claude-code", payload["judges"])
        self.assertIn("claude-code-judge", payload["judges"])

    def test_list_after_extra_adapter_registration(self) -> None:
        # Pre-register an additional adapter under a name that does NOT
        # collide with the shipped 'stub'. main() will auto-register
        # stub on top.
        from benchmark_runner.contracts import (
            ISOLATION_WORKTREE,
            IsolationConfig,
            TaskSpec,
            VerifyResult,
        )
        from benchmark_runner.registry import register_adapter

        class _Demo:
            benchmark_id = "demo"
            isolation_default = ISOLATION_WORKTREE

            def list_tasks(self) -> list[TaskSpec]:
                return []

            def isolation_for(self, task):  # type: ignore[no-untyped-def]
                return IsolationConfig(tier=ISOLATION_WORKTREE)

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
        # 'demo' was pre-registered by the test; the rest come from
        # _register.register_all (the production set).
        self.assertIn("demo", payload["adapters"])
        self.assertIn("stub", payload["adapters"])
        self.assertIn("aider-polyglot", payload["adapters"])
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

    def test_run_combined_backend_form_hints_separate_flags(self) -> None:
        # Pre-push review F-finding #6: report uses "<backend>:<model>"
        # as a display label, but the CLI takes separate flags. A user
        # copying the report label into the CLI hits an "unknown
        # backend family" error unless the parser surfaces a specific
        # hint pointing at the separate-flags form.
        rc, _, stderr = self._invoke(
            "run",
            "--benchmark", "stub",
            "--backend", "claude-code:sonnet",
            "--runs", "1",
        )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("deprecated combined form", stderr)
        self.assertIn("--backend 'claude-code'", stderr)
        self.assertIn("--model 'sonnet'", stderr)

    def test_run_combined_form_hint_handles_hyphenated_model_name(self) -> None:
        # Pre-push review follow-up: real model names contain hyphens
        # (e.g. ``gpt-4o-mini``, ``claude-sonnet-4-6``,
        # ``meta-llama/Meta-Llama-3.1-70B-Instruct``). The hint must
        # render single-quoted strings cleanly without double-quoting
        # or shell-escape artifacts.
        rc, _, stderr = self._invoke(
            "run",
            "--benchmark", "stub",
            "--backend", "vllm:gpt-4o-mini",
            "--runs", "1",
        )
        self.assertEqual(rc, EXIT_USAGE)
        # Single quotes only, no double-quoting:
        self.assertIn("--backend 'vllm'", stderr)
        self.assertIn("--model 'gpt-4o-mini'", stderr)
        self.assertNotIn("\"vllm\"", stderr)
        self.assertNotIn("\"gpt-4o-mini\"", stderr)

    def test_run_unknown_backend_returns_usage(self) -> None:
        # Use a no-colon backend name so this test exercises the
        # registry's "unknown backend family" path rather than the
        # colon-form-rejection hint added in F6.
        rc, _, stderr = self._invoke(
            "run", "--benchmark", "stub", "--backend", "ghost", "--runs", "1"
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

    def test_run_empty_adapter_returns_usage_with_fetch_hint(self) -> None:
        # Regression: aider-polyglot with an empty cache returns USAGE
        # and prints a hint pointing at the fetch script. Was silently
        # exit 0 with an empty run-dir before the EmptyAdapterError fix.
        with tempfile.TemporaryDirectory() as td:
            rc, _, stderr = self._invoke(
                "run",
                "--benchmark",
                "aider-polyglot",
                "--backend",
                "stub",
                "--runs",
                "1",
                "--runs-root",
                td,
            )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("fetch", stderr.lower())
        self.assertIn("aider_polyglot", stderr)

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
            # New v3 group heading: `<backend>:<model>` or just
            # `<backend>` when model is empty (stub case).
            self.assertIn("`stub`", content)
            self.assertIn("backend=stub", content)
            self.assertIn("100.0%", content)


class TestDogfoodCommand(CLITestBase):
    def test_dogfood_unknown_backend_returns_usage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rc, _, stderr = self._invoke(
                "dogfood",
                "--backend", "nope",
                "--model", "sonnet",
                "--runs-root", td,
            )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("unknown backend", stderr)

    def test_dogfood_with_missing_polyglot_cache_returns_usage(self) -> None:
        # Most common real-world failure mode: user runs dogfood
        # before fetching the polyglot dataset. The harness's
        # EmptyAdapterError surfaces as USAGE with a fetch hint.
        # CI never has the cache; this test exercises that path.
        with tempfile.TemporaryDirectory() as td:
            rc, _, stderr = self._invoke(
                "dogfood",
                "--backend", "stub",
                "--runs-root", td,
            )
        self.assertEqual(rc, EXIT_USAGE)
        self.assertIn("fetch", stderr.lower())


if __name__ == "__main__":
    unittest.main()
