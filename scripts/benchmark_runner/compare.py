# benchmark_runner.compare — multi-LLM comparison driver.
#
# Reads a JSON config that lists N candidate (backend, model, env)
# tuples, runs each sequentially under one shared run-dir, and
# (by default) emits the aggregate Markdown + JSON report.
#
# Candidates are run sequentially, not in parallel, because:
#   - Polyglot (and other public benchmarks) hold a shared on-disk
#     cache; parallel adapters would contend on it.
#   - Most providers rate-limit per token, not per request fanout —
#     parallelism would burn the rate budget without buying wall time.
#   - The per-attempt worktree provisioning + venv install in the
#     ``worktree+venv`` tier is already I/O-heavy; stacking it doubles
#     up I/O without doubling CPU available to the agents.
#
# Each candidate's run-dir lands inside the parent, so the existing
# report aggregator (which already discovers attempts via
# ``rglob("score.json")``) groups them by ``(backend, model)`` without
# special-casing the compare layout.
#
# Provider routing (ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, etc.) is
# specified per-candidate via ``env``. Values are read into ``os.environ``
# for the duration of that candidate's runs and restored afterward.
# The compare manifest persists the env *key names* but NEVER the
# values — so a compare run-dir is safe to commit alongside the
# regular run records.

from __future__ import annotations

import datetime
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from .run import allocate_unique_dir, run_benchmark


COMPARE_SCHEMA_VERSION = "1"


# ── Config types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Candidate:
    """One (backend, model, env) tuple to evaluate."""

    name: str
    backend: str
    model: str
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CompareConfig:
    """A parsed compare-config file."""

    benchmark: str
    runs: int
    candidates: list[Candidate]
    task_filter: Optional[list[str]] = None


class CompareConfigError(ValueError):
    """Raised when the compare-config JSON is malformed."""


# ── Config loading + validation ────────────────────────────────────────


def load_config(path: Path) -> CompareConfig:
    """Load a compare-config from disk. Raises ``CompareConfigError`` on shape errors."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CompareConfigError(f"{path}: invalid JSON: {exc}") from exc
    return _validate(raw, source=str(path))


def _validate(raw: Any, *, source: str = "<config>") -> CompareConfig:
    if not isinstance(raw, dict):
        raise CompareConfigError(f"{source}: top-level value must be a JSON object")

    benchmark = raw.get("benchmark")
    if not isinstance(benchmark, str) or not benchmark:
        raise CompareConfigError(f"{source}: 'benchmark' must be a non-empty string")

    runs = raw.get("runs", 1)
    if not isinstance(runs, int) or isinstance(runs, bool) or runs < 1:
        raise CompareConfigError(f"{source}: 'runs' must be a positive integer (default 1)")

    task = raw.get("task")
    if task is not None:
        if not isinstance(task, list) or not all(isinstance(t, str) and t for t in task):
            raise CompareConfigError(
                f"{source}: 'task' must be a list of non-empty strings (or omitted)"
            )

    raw_candidates = raw.get("candidates")
    if not isinstance(raw_candidates, list):
        raise CompareConfigError(f"{source}: 'candidates' must be a list")
    if len(raw_candidates) < 2:
        raise CompareConfigError(
            f"{source}: 'candidates' must contain at least 2 entries — "
            f"comparing a single candidate against itself is what "
            f"`./scripts/benchmark run` already does"
        )

    candidates: list[Candidate] = []
    seen_names: set[str] = set()
    for i, c in enumerate(raw_candidates):
        prefix = f"{source}: candidates[{i}]"
        if not isinstance(c, dict):
            raise CompareConfigError(f"{prefix}: must be a JSON object")

        backend = c.get("backend")
        if not isinstance(backend, str) or not backend:
            raise CompareConfigError(f"{prefix}.backend: must be a non-empty string")
        if ":" in backend:
            raise CompareConfigError(
                f"{prefix}.backend: {backend!r} uses the deprecated combined form. "
                f"Split into separate 'backend' and 'model' fields."
            )

        model = c.get("model", "")
        if not isinstance(model, str):
            raise CompareConfigError(f"{prefix}.model: must be a string")

        # Default name derived from (backend, model) keeps simple
        # configs simple. Users override when they need to distinguish
        # candidates that share (backend, model) but differ in env
        # routing — e.g. same Claude Code + sonnet via Anthropic API
        # vs. via a vLLM gateway.
        default_name = f"{backend}:{model}" if model else backend
        name = c.get("name") or default_name
        if not isinstance(name, str) or not name:
            raise CompareConfigError(f"{prefix}.name: must be a non-empty string when set")
        if name in seen_names:
            raise CompareConfigError(
                f"{prefix}.name: {name!r} is reused; names must be unique. "
                f"Set explicit 'name' fields when (backend, model) pairs overlap."
            )
        seen_names.add(name)

        env_raw = c.get("env", {})
        if not isinstance(env_raw, dict):
            raise CompareConfigError(f"{prefix}.env: must be a flat string->string mapping")
        for k, v in env_raw.items():
            if not isinstance(k, str) or not k:
                raise CompareConfigError(f"{prefix}.env: keys must be non-empty strings")
            if not isinstance(v, str):
                raise CompareConfigError(
                    f"{prefix}.env[{k!r}]: must be a string (got {type(v).__name__}); "
                    f"env values are passed verbatim into os.environ"
                )

        candidates.append(
            Candidate(name=name, backend=backend, model=model, env=dict(env_raw))
        )

    return CompareConfig(
        benchmark=benchmark,
        runs=runs,
        candidates=candidates,
        task_filter=task,
    )


# ── Env patching ───────────────────────────────────────────────────────


@contextmanager
def _patched_env(overrides: dict[str, str]) -> Iterator[None]:
    """Apply env overrides for the duration of the block; restore on exit.

    Restoration covers both keys we set new and keys we replaced —
    pre-existing values are put back exactly. Exceptions during the
    block do not leak env state.
    """
    saved: dict[str, Optional[str]] = {}
    try:
        for k, v in overrides.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── Orchestrator ───────────────────────────────────────────────────────


def run_comparison(
    config: CompareConfig,
    *,
    runs_root: Path = Path("runs"),
    timestamp: Optional[str] = None,
    emit_report: bool = True,
) -> Path:
    """Run every candidate sequentially under one shared parent run-dir.

    Returns the parent run-dir path. The parent contains:
      - ``compare-manifest.json`` — config snapshot (env values
        redacted; only key names persisted).
      - ``candidate-runs.json`` — written after all candidates complete,
        mapping candidate name to its per-candidate run-dir.
      - One nested run-dir per candidate, exactly as a plain
        ``./scripts/benchmark run`` would have produced.
      - ``report.md`` + ``report.json`` (when ``emit_report=True``).

    A candidate failure aborts the comparison and leaves whatever was
    produced on disk for postmortem (matching the harness's existing
    "preserve on failure" convention).
    """
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Use the shared counter-suffix allocator so two ``compare`` calls
    # within the same UTC-second produce ``…-compare-<bench>-001`` and
    # ``…-002`` instead of colliding on FileExistsError. Same invariant
    # as ``run._make_run_dir`` — see ``allocate_unique_dir``'s docstring.
    parent = allocate_unique_dir(runs_root, f"{ts}-compare-{config.benchmark}")

    manifest: dict[str, Any] = {
        "schema_version": COMPARE_SCHEMA_VERSION,
        "created_at": ts,
        "benchmark": config.benchmark,
        "runs": config.runs,
        "task_filter": config.task_filter,
        "candidates": [
            {
                "name": c.name,
                "backend": c.backend,
                "model": c.model,
                # Persist env *key names* only. Values may contain
                # auth tokens; never write them to disk.
                "env_keys": sorted(c.env.keys()),
            }
            for c in config.candidates
        ],
    }
    (parent / "compare-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    candidate_runs: list[dict[str, str]] = []
    for c in config.candidates:
        with _patched_env(c.env):
            run_dir = run_benchmark(
                config.benchmark,
                c.backend,
                c.model,
                runs=config.runs,
                runs_root=parent,
                task_filter=config.task_filter,
            )
        candidate_runs.append(
            {"name": c.name, "run_dir": run_dir.relative_to(parent).as_posix()}
        )

    (parent / "candidate-runs.json").write_text(
        json.dumps({"candidates": candidate_runs}, indent=2) + "\n",
        encoding="utf-8",
    )

    if emit_report:
        # Imported lazily so the compare module loads cleanly even if
        # the report module gets refactored independently.
        from .report import render_report
        render_report(parent)

    return parent
