# benchmark_runner.backends.stub — CI-only stub backend.
#
# The stub backend bypasses any LLM. It asks the adapter for the task's
# golden patch and copies it into the worktree, then returns a
# BackendResult populated with deterministic placeholder values.
#
# Used by the CI smoke test to verify the harness's plumbing
# (init -> run -> score -> report) without exercising any model. Not a
# real backend — never registered by default outside of test harnesses
# and the CI workflow.

from __future__ import annotations

import shutil
import time
from pathlib import Path

from ..contracts import BackendResult, RunContext
from ..registry import get_adapter

BACKEND_FAMILY = "stub"


class StubBackend:
    """Copies the golden patch into the worktree.

    The constructor accepts a model spec (the part after ``stub:``)
    purely for protocol uniformity; it is recorded in the
    ``backend_metadata`` so reports can distinguish e.g. ``stub`` from
    ``stub:variant-a`` if a fixture ever needs to.
    """

    backend_id = BACKEND_FAMILY

    def __init__(self, model: str = "") -> None:
        self._model = model

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        adapter = get_adapter(ctx.benchmark_id)
        # Resolve the task by id so we can ask for its golden_patch.
        for task in adapter.list_tasks():
            if task.task_id == ctx.task_id:
                break
        else:
            raise KeyError(
                f"stub: task {ctx.task_id!r} not found in adapter "
                f"{ctx.benchmark_id!r}"
            )

        golden = adapter.golden_patch(task)
        if not golden.exists():
            raise FileNotFoundError(
                f"stub: golden patch missing for {ctx.task_id!r}: {golden}"
            )

        started = time.monotonic()
        # Copy every file under golden/ into worktree/, preserving structure.
        for src in golden.rglob("*"):
            if src.is_dir():
                continue
            relative = src.relative_to(golden)
            dst = ctx.worktree / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elapsed = time.monotonic() - started

        return BackendResult(
            transcript_path=None,
            elapsed_seconds=elapsed,
            prompt_path=None,
            model_output_path=None,
            tokens_input=0,
            tokens_output=0,
            cache_read_tokens=None,
            cache_write_tokens=None,
            tool_calls={},
            failed_commands=0,
            backend_metadata={
                "family": BACKEND_FAMILY,
                "model": self._model,
                "note": "stub backend; copied golden_patch verbatim",
            },
        )


def factory(model: str) -> StubBackend:
    return StubBackend(model)
