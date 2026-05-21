# benchmarks.adapters.livecodebench.adapter — DEFERRED scaffolding.
#
# See README.md in this directory for the empirical blocker that
# prevents shipping a working LiveCodeBench adapter under this
# project's stdlib-only / no-new-deps constraint. Summary: the
# HuggingFace datasets-server rows API refuses the loader-script
# dataset; the raw test.jsonl mirror is ~497 MB.
#
# This module exists so the adapter directory follows the project's
# layout convention (every adapter subdir has an adapter.py) and
# so the registration path can fail loudly with an actionable error
# message if someone accidentally wires it up.

from __future__ import annotations

from benchmark_runner.registry import register_adapter

BENCHMARK_ID = "livecodebench"


class LiveCodeBenchAdapter:
    """Placeholder. Calling any protocol method raises with a pointer
    to README.md in this directory."""

    benchmark_id = BENCHMARK_ID

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError(
            "livecodebench adapter is intentionally deferred. See "
            "benchmarks/adapters/livecodebench/README.md for the "
            "empirical blocker (HF datasets-server rows API + raw "
            "JSONL mirror size) and the maintainer-side enable "
            "procedure. Issue: gosha70/code-copilot-team#43."
        )


def register() -> None:
    # Intentionally NOT registered in _register.py — calling the
    # constructor would fail at runtime. Kept here so a future
    # maintainer who removes the deferral has one less file to write.
    register_adapter(BENCHMARK_ID, LiveCodeBenchAdapter)
