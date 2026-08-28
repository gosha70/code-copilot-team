"""Adapter-owned verification as a shell-invocable bridge.

Increment C's packet verification runs shell verifier commands inside
the packet worktree. For a delegated BENCHMARK task, the honest
verifier is the declared adapter's own ``verify`` — not a hand-written
grep — so this module exposes it as a command the generated
``verification.yaml`` can name:

    python3 -m benchmark_runner.routing_eval.adapter_verify <benchmark> <task>

Exit 0 iff the adapter's verification passed, with its output on
stdout. The working directory is the worktree under judgment, exactly
as the packet verifier contract runs commands.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: python3 -m benchmark_runner.routing_eval.adapter_verify "
            "<benchmark-id> <task-id>\n"
        )
        return 64
    benchmark_id, task_id = argv[1], argv[2]
    from benchmark_runner import _register
    from benchmark_runner.registry import get_adapter

    _register.register_all()
    # Out-of-tree adapters: CCT_EXTRA_ADAPTER_MODULE names a module
    # whose import registers additional adapters (the module calls
    # registry.register_adapter itself). This is the same extension
    # seam a third-party benchmark needs to reach the bridge, and the
    # test fixture adapter crosses the process boundary through it.
    extra = os.environ.get("CCT_EXTRA_ADAPTER_MODULE")
    if extra:
        importlib.import_module(extra)
    adapter = get_adapter(benchmark_id)
    spec = next((t for t in adapter.list_tasks() if t.task_id == task_id), None)
    if spec is None:
        sys.stderr.write(
            f"adapter_verify: task {task_id!r} is not exposed by "
            f"{benchmark_id!r}\n"
        )
        return 65
    result = adapter.verify(spec, Path.cwd())
    if result.tests_output:
        sys.stdout.write(result.tests_output)
    return 0 if result.tests_passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
