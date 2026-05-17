# tests/test_contracts.py — adapter/backend contract conformance tests.

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from benchmark_runner.contracts import (
    ISOLATION_DOCKER,
    ISOLATION_WORKTREE,
    ISOLATION_WORKTREE_VENV,
    RESULT_PASS,
    Backend,
    BackendResult,
    BenchmarkAdapter,
    RunContext,
    TaskSpec,
    VerifyResult,
)


class TestTaskSpec(unittest.TestCase):
    def test_frozen(self) -> None:
        task = TaskSpec(task_id="x/y", language="python")
        with self.assertRaises(FrozenInstanceError):
            task.task_id = "z"  # type: ignore[misc]

    def test_metadata_default_empty(self) -> None:
        task = TaskSpec(task_id="x", language="python")
        self.assertEqual(dict(task.metadata), {})

    def test_metadata_preserved(self) -> None:
        task = TaskSpec(
            task_id="x",
            language="python",
            metadata={"difficulty": "easy"},
        )
        self.assertEqual(task.metadata["difficulty"], "easy")


class TestVerifyResult(unittest.TestCase):
    def test_null_lint_distinct_from_false(self) -> None:
        # Adapters that don't run lint must report None, not False.
        nolint = VerifyResult(tests_passed=True, tests_output="ok")
        failed = VerifyResult(tests_passed=True, tests_output="ok", lint_passed=False)
        self.assertIsNone(nolint.lint_passed)
        self.assertEqual(failed.lint_passed, False)

    def test_required_files_present_default_true(self) -> None:
        # Default convention: assume present unless adapter says otherwise.
        v = VerifyResult(tests_passed=True, tests_output="")
        self.assertTrue(v.required_files_present)


class TestBackendResult(unittest.TestCase):
    def test_token_fields_default_none(self) -> None:
        br = BackendResult(transcript_path=None, elapsed_seconds=1.0)
        self.assertIsNone(br.tokens_input)
        self.assertIsNone(br.tokens_output)
        self.assertIsNone(br.cache_read_tokens)
        self.assertIsNone(br.cache_write_tokens)

    def test_zero_distinct_from_none(self) -> None:
        # Backends that report 0 must surface 0 (not be coerced to None).
        br = BackendResult(
            transcript_path=Path("/tmp/x"),
            elapsed_seconds=0.5,
            tokens_input=0,
            tokens_output=0,
        )
        self.assertEqual(br.tokens_input, 0)
        self.assertEqual(br.tokens_output, 0)

    def test_prompt_artifact_fields_default_none(self) -> None:
        # Backends that don't wrap the harness-provided prompt leave
        # prompt_path None — the runner records only its canonical
        # prompt under <attempt>/prompt.md. Same for model_output_path
        # when the backend only mutates the worktree.
        br = BackendResult(transcript_path=None, elapsed_seconds=1.0)
        self.assertIsNone(br.prompt_path)
        self.assertIsNone(br.model_output_path)

    def test_prompt_artifact_fields_carry_paths(self) -> None:
        br = BackendResult(
            transcript_path=Path("/tmp/x/transcript.jsonl"),
            elapsed_seconds=1.0,
            prompt_path=Path("/tmp/x/effective-prompt.md"),
            model_output_path=Path("/tmp/x/model-output.txt"),
        )
        self.assertEqual(br.prompt_path, Path("/tmp/x/effective-prompt.md"))
        self.assertEqual(br.model_output_path, Path("/tmp/x/model-output.txt"))


class TestRunContext(unittest.TestCase):
    def test_default_temperature_zero(self) -> None:
        ctx = RunContext(
            benchmark_id="stub",
            task_id="hello",
            backend_id="stub",
            run_id="run-001",
            attempt=1,
            worktree=Path("/tmp/wt"),
            model="",
        )
        self.assertEqual(ctx.temperature, 0.0)
        self.assertIsNone(ctx.seed)


class TestProtocols(unittest.TestCase):
    """Smoke-test that the protocols accept duck-typed implementations.

    We don't ship any real adapter/backend in Phase 0; this just
    confirms the protocol surface matches what the spec promises.
    """

    def test_adapter_protocol_shape(self) -> None:
        from benchmark_runner.contracts import IsolationConfig

        class _Stub:
            benchmark_id = "stub"
            isolation_default = ISOLATION_WORKTREE

            def list_tasks(self) -> list[TaskSpec]:
                return []

            def isolation_for(self, task: TaskSpec) -> IsolationConfig:
                return IsolationConfig(tier=ISOLATION_WORKTREE)

            def prepare_task(self, task: TaskSpec, worktree: Path) -> None:
                return None

            def prompt_for(self, task, attempt, prior):  # type: ignore[no-untyped-def]
                return ""

            def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult:
                return VerifyResult(tests_passed=True, tests_output="")

            def golden_patch(self, task: TaskSpec) -> Path:
                return Path("/tmp")

            def max_attempts(self) -> int:
                return 1

        adapter = _Stub()
        self.assertIsInstance(adapter, BenchmarkAdapter)

    def test_backend_protocol_shape(self) -> None:
        class _Stub:
            backend_id = "stub"

            def run(self, prompt: str, ctx: RunContext) -> BackendResult:
                return BackendResult(transcript_path=None, elapsed_seconds=0.0)

        backend = _Stub()
        self.assertIsInstance(backend, Backend)


class TestIsolationConstants(unittest.TestCase):
    def test_three_tiers_exposed(self) -> None:
        # All three tiers in the schema from day one (spec.md § Constraints).
        self.assertEqual(ISOLATION_WORKTREE, "worktree")
        self.assertEqual(ISOLATION_WORKTREE_VENV, "worktree+venv")
        self.assertEqual(ISOLATION_DOCKER, "docker")


class TestResultConstants(unittest.TestCase):
    def test_pass_constant(self) -> None:
        self.assertEqual(RESULT_PASS, "pass")


if __name__ == "__main__":
    unittest.main()
