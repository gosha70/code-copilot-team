# benchmark_runner.run — run-orchestration (Phase 0 stub).
#
# Phase 1 implements end-to-end orchestration:
#   resolve adapter -> resolve backend -> for each (task, attempt):
#     prepare worktree (per isolation tier) -> build prompt ->
#     invoke backend -> verify -> write score.json + stats.json
#     under runs/<ts>/<task>/<attempt>/.
#
# Phase 0 only exposes the public entrypoint signature so cli.py can
# wire it. Calling it raises NotImplementedError.

from __future__ import annotations

from pathlib import Path


def run_benchmark(
    benchmark_id: str,
    backend_spec: str,
    *,
    runs: int,
    runs_root: Path,
    task_filter: list[str] | None = None,
) -> Path:
    """Phase 1+: run ``benchmark_id`` against ``backend_spec``.

    Returns the path to the produced run directory under ``runs_root``.
    Phase 0 raises NotImplementedError; cli.py surfaces the message
    cleanly to the user.
    """
    raise NotImplementedError(
        "run orchestration lands in Phase 1 (see specs/benchmark-harness/plan.md)"
    )
