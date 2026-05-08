# benchmarks.adapters.stub.adapter — stub adapter for CI smoke tests.
#
# The stub adapter ships exactly one task ("hello-world") whose golden
# patch is a single text file. Used together with the stub backend it
# verifies the harness's plumbing (init -> run -> score -> report)
# without invoking any LLM. See specs/benchmark-harness/spec.md
# § "CI smoke test".

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from benchmark_runner.contracts import (
    ISOLATION_WORKTREE,
    BenchmarkAdapter,
    IsolationConfig,
    TaskSpec,
    VerifyResult,
)

BENCHMARK_ID = "stub"

_ADAPTER_DIR = Path(__file__).resolve().parent
_TASKS_DIR = _ADAPTER_DIR / "tasks"

_HELLO_WORLD = TaskSpec(
    task_id="hello-world",
    language="text",
    metadata={"description": "Write a fixed string to hello.txt."},
)


class StubAdapter:
    """Single-task adapter used by CI to exercise plumbing.

    Implements ``BenchmarkAdapter`` (see contracts.py). All paths are
    rooted under this module's directory so the adapter is relocatable
    with the dataset files.
    """

    benchmark_id = BENCHMARK_ID
    isolation_default = ISOLATION_WORKTREE

    def list_tasks(self) -> list[TaskSpec]:
        return [_HELLO_WORLD]

    def isolation_for(self, task: TaskSpec) -> IsolationConfig:
        # Stub adapter is single-tier; no per-task variance.
        return IsolationConfig(tier=ISOLATION_WORKTREE)

    def prepare_task(self, task: TaskSpec, worktree: Path) -> None:
        # Stub task starts from an empty worktree; nothing to copy.
        # Real adapters (Phase 2+) copy starter files here.
        if task.task_id != _HELLO_WORLD.task_id:
            raise KeyError(f"unknown stub task: {task.task_id!r}")

    def prompt_for(
        self,
        task: TaskSpec,
        attempt: int,
        prior: Optional[VerifyResult],
    ) -> str:
        prompt_path = _TASKS_DIR / task.task_id / "prompt.md"
        return prompt_path.read_text(encoding="utf-8")

    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult:
        verify_script = _TASKS_DIR / task.task_id / "verify.sh"
        proc = subprocess.run(
            ["bash", str(verify_script)],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=False,
        )
        passed = proc.returncode == 0
        return VerifyResult(
            tests_passed=passed,
            tests_output=(proc.stdout + proc.stderr).strip(),
            required_files_present=(worktree / "hello.txt").exists(),
        )

    def golden_patch(self, task: TaskSpec) -> Path:
        return _TASKS_DIR / task.task_id / "golden"

    def max_attempts(self) -> int:
        return 1


def register() -> None:
    """Idempotent-from-the-caller's-perspective registration entry.

    Registration is NOT a module-level side-effect because tests reset
    the registry between cases; Python imports each module once per
    process, so an import-time side-effect would not re-register on a
    second test invocation. ``benchmark_runner._register.register_all``
    is the single caller in production.
    """
    from benchmark_runner.registry import register_adapter
    register_adapter(BENCHMARK_ID, StubAdapter)


# Module-level type-check: confirms the class still satisfies the protocol
# even after refactors. Cheaper than a unittest at every import.
assert isinstance(StubAdapter(), BenchmarkAdapter)
