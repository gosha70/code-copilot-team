# benchmark_runner.run — Phase 1 orchestration.
#
# resolve adapter -> resolve backend -> for each task x attempt:
#   provision worktree (per isolation tier) ->
#   adapter.prepare_task ->
#   adapter.prompt_for(attempt=N, prior=...) ->
#   write prompt.md + sha256 ->
#   backend.run -> verify -> compute diff ->
#   write run-record.json + score.json + stats.json
#
# Layout under runs_root:
#   <UTC-ts>-<benchmark>-<backend>/<task-id-slug>/<attempt>/{worktree/, prepared/, ...}
#
# Cleanup: Phase 1 keeps worktrees on disk for postmortem inspection;
# Phase 4 may add a --clean-on-success flag.

from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Optional

from .contracts import (
    RESULT_ERROR,
    RESULT_FAIL,
    RESULT_PASS,
    BackendResult,
    BenchmarkAdapter,
    IsolationConfig,
    RunContext,
    TaskSpec,
    VerifyResult,
)
from .isolation import install_dependencies, provision_worktree
from .registry import get_adapter, get_backend


SCHEMA_VERSION = "1.0"
COST_REPORTING_REASON = "billing-correlation pending"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class EmptyAdapterError(RuntimeError):
    """Raised when an adapter exposes zero tasks at run time.

    Most commonly, this means the adapter's network-backed dataset
    cache is missing — e.g. the user invoked the Aider Polyglot
    adapter without first running its fetch script. Surfacing this as
    a USAGE-style error (caught and reported by the CLI) prevents a
    no-op run from being indistinguishable from a successful one.
    """


# ── Public entrypoint ──────────────────────────────────────────────────


def run_benchmark(
    benchmark_id: str,
    backend_family: str,
    backend_model: str = "",
    *,
    runs: int,
    runs_root: Path,
    task_filter: Optional[list[str]] = None,
) -> Path:
    """Execute the benchmark; return the produced run directory."""
    if runs < 1:
        raise ValueError(f"--runs must be >= 1; got {runs}")

    adapter = get_adapter(benchmark_id)
    backend = get_backend(backend_family, backend_model)

    all_tasks = adapter.list_tasks()
    if not all_tasks:
        raise EmptyAdapterError(
            f"benchmark {benchmark_id!r} exposed no tasks. "
            f"If this adapter requires a cached dataset, run its fetch "
            f"script first (e.g. for Aider Polyglot: "
            f"python3 -m benchmarks.adapters.aider_polyglot.fetch)."
        )
    tasks = _filter_tasks(all_tasks, task_filter)

    run_dir = _make_run_dir(runs_root, benchmark_id, backend.backend_id)

    for task in tasks:
        for run_index in range(1, runs + 1):
            run_id = f"run-{run_index:03d}"
            prior: Optional[VerifyResult] = None
            for attempt in range(1, adapter.max_attempts() + 1):
                attempt_verify = _execute_attempt(
                    adapter=adapter,
                    backend=backend,
                    backend_model=backend_model,
                    task=task,
                    attempt=attempt,
                    run_id=run_id,
                    run_dir=run_dir,
                    prior=prior,
                )
                # Stop early on success — there is no value in burning
                # a second attempt for a task that already passed.
                if attempt_verify.tests_passed:
                    break
                # Carry the failed verify result into the next attempt's
                # prompt so two-shot adapters (Aider-style) can show the
                # model what went wrong.
                prior = attempt_verify

    return run_dir


# ── Per-attempt execution ──────────────────────────────────────────────


def _execute_attempt(
    *,
    adapter: BenchmarkAdapter,
    backend,  # type: ignore[no-untyped-def]  (Backend protocol)
    backend_model: str,
    task: TaskSpec,
    attempt: int,
    run_id: str,
    run_dir: Path,
    prior: Optional[VerifyResult],
) -> VerifyResult:
    attempt_dir = run_dir / _slug(task.task_id) / f"attempt-{attempt:02d}-{run_id}"
    attempt_dir.mkdir(parents=True, exist_ok=False)

    started_at = _utc_now()
    started = time.monotonic()

    isolation_config = adapter.isolation_for(task)
    worktree = provision_worktree(isolation_config, attempt_dir)
    adapter.prepare_task(task, worktree)
    # install_command runs AFTER prepare_task so project-aware installs
    # (e.g. ``pip install -e .[dev]``) can see pyproject.toml/setup.py.
    install_dependencies(isolation_config, worktree)

    # Snapshot prepared state so we can compute the post-attempt diff.
    # ``.venv`` is excluded — installed packages aren't the model's
    # contribution and would explode the diff to thousands of lines.
    prepared = attempt_dir / "prepared"
    shutil.copytree(worktree, prepared, ignore=shutil.ignore_patterns(".venv"))

    # ``prior`` carries the previous attempt's verify result for two-shot
    # adapters (Aider-style retry); first attempt always sees None.
    prompt = adapter.prompt_for(task, attempt, prior)

    prompt_path = attempt_dir / "prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    prompt_sha = _sha256_file(prompt_path)

    ctx = RunContext(
        benchmark_id=adapter.benchmark_id,
        task_id=task.task_id,
        backend_id=backend.backend_id,
        run_id=run_id,
        attempt=attempt,
        worktree=worktree,
        model=backend_model,
        temperature=0.0,
        seed=None,
        timeout_seconds=None,
    )

    backend_error: Optional[str] = None
    try:
        backend_result: BackendResult = backend.run(prompt, ctx)
    except Exception as exc:  # noqa: BLE001 — capture, don't crash the run
        # The error string lives in run_record["backend"]["error"]; we
        # don't also stuff it into backend_metadata (which is the
        # backend's own free-form context — empty here because the
        # backend never produced a real result).
        backend_error = f"{type(exc).__name__}: {exc}"
        backend_result = BackendResult(
            transcript_path=None,
            elapsed_seconds=time.monotonic() - started,
        )

    # Verify regardless — even on backend error, the worktree may be
    # in a partially-populated state and the verify step's output is
    # diagnostic.
    verify_result = adapter.verify(task, worktree)

    # Compute diff (prepared -> worktree).
    diff_path = _write_diff(prepared, worktree, attempt_dir)
    files_changed, lines_added, lines_removed = _diff_stats(prepared, worktree)

    finished_at = _utc_now()
    elapsed = time.monotonic() - started

    # ── Compose record files ─────────────────────────────────────
    run_record = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": adapter.benchmark_id,
        "task_id": task.task_id,
        "backend_id": backend.backend_id,
        "run_id": run_id,
        "attempt": attempt,
        "started_at": started_at,
        "finished_at": finished_at,
        "isolation": _isolation_record(isolation_config),
        "backend_invocation": {
            "model": ctx.model,
            "temperature": ctx.temperature,
            "seed": ctx.seed,
        },
        "prompt": {
            "path": str(prompt_path.relative_to(attempt_dir)),
            "sha256": prompt_sha,
        },
        "effective_prompt": _effective_prompt_block(backend_result, attempt_dir),
        "model_output_path": _relpath_or_none(
            backend_result.model_output_path, attempt_dir
        ),
        "backend": {
            "error": backend_error,
            "metadata": dict(backend_result.backend_metadata),
        },
    }

    score = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": adapter.benchmark_id,
        "task_id": task.task_id,
        "backend_id": backend.backend_id,
        "run_id": run_id,
        "attempt": attempt,
        "scores": {
            "tests_passed": verify_result.tests_passed,
            "lint_passed": verify_result.lint_passed,
            "typecheck_passed": verify_result.typecheck_passed,
            "required_files_present": verify_result.required_files_present,
            "timeout": False,
            "human_interventions": 0,
        },
        "derived": {
            "elapsed_seconds": round(elapsed, 4),
            "files_changed": files_changed,
            "lines_added": lines_added,
            "lines_removed": lines_removed,
            "failed_commands": backend_result.failed_commands + verify_result.failed_commands,
        },
        "result": _classify_result(verify_result, backend_error),
    }

    stats = {
        "schema_version": SCHEMA_VERSION,
        "elapsed_seconds": round(elapsed, 4),
        "tokens_input": backend_result.tokens_input,
        "tokens_output": backend_result.tokens_output,
        "cache_read_tokens": backend_result.cache_read_tokens,
        "cache_write_tokens": backend_result.cache_write_tokens,
        "tool_calls": dict(backend_result.tool_calls),
        "temperature": ctx.temperature,
        "seed": ctx.seed,
        "cost_reporting": {"enabled": False, "reason": COST_REPORTING_REASON},
    }

    _write_json(attempt_dir / "run-record.json", run_record)
    _write_json(attempt_dir / "score.json", score)
    _write_json(attempt_dir / "stats.json", stats)

    if verify_result.tests_output:
        (attempt_dir / "verify-output.txt").write_text(
            verify_result.tests_output, encoding="utf-8"
        )

    return verify_result


# ── Helpers ────────────────────────────────────────────────────────────


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value).strip("-") or "task"


def _isolation_record(config: IsolationConfig) -> dict:
    """Serialize an IsolationConfig into the run-record's isolation block.

    Only emits the optional fields that are actually set, so
    ``worktree`` runs don't end up with null python/install_command
    keys cluttering the record.

    ``verify_imports`` is included whenever it's non-empty — that
    way a successful run-record carries proof of which modules were
    contractually required to be importable, so any post-hoc audit
    can tell whether the install_command was supposed to install
    pytest (or ruff, etc.) independently of whether it succeeded.
    """
    out: dict = {"tier": config.tier}
    if config.python is not None:
        out["python"] = config.python
    if config.install_command is not None:
        out["install_command"] = config.install_command
    if config.verify_imports:
        out["verify_imports"] = list(config.verify_imports)
    if config.dockerfile is not None:
        out["dockerfile"] = str(config.dockerfile)
    if config.build_args:
        out["build_args"] = dict(config.build_args)
    return out


def _utc_now() -> str:
    # ISO-8601 with Z suffix, matching the run-record schema's date-time format.
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_run_dir(runs_root: Path, benchmark_id: str, backend_id: str) -> Path:
    """Mint a fresh single-run directory under ``runs_root``."""
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_name = f"{ts}-{_slug(benchmark_id)}-{_slug(backend_id)}"
    return allocate_unique_dir(runs_root, base_name)


def allocate_unique_dir(parent: Path, base_name: str) -> Path:
    """Atomically allocate a fresh directory under ``parent``.

    Two invocations within the same UTC-second collide on a
    timestamp-based ``base_name`` alone (the schema's date-time format
    is second-precision). We disambiguate with a 3-digit counter
    suffix (-001, -002, ...) and create the directory atomically; the
    counter increments until ``mkdir`` succeeds. 999 collisions in
    one second would be a pathological loop, so we cap and surface a
    clear error.

    Used by ``_make_run_dir`` for per-(benchmark, backend) run-dirs
    and by ``compare.run_comparison`` for the compare parent run-dir.
    Centralising the loop keeps the collision-safety invariant in one
    place — the original bug fix has been re-introduced once already
    when ``compare`` shipped without this helper.
    """
    parent.mkdir(parents=True, exist_ok=True)
    for counter in range(1, 1000):
        candidate = parent / f"{base_name}-{counter:03d}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError(
        f"could not allocate a unique directory under {parent!r} "
        f"for {base_name!r} after 999 attempts"
    )


def _filter_tasks(
    tasks: list[TaskSpec], task_filter: Optional[list[str]]
) -> list[TaskSpec]:
    if not task_filter:
        return tasks
    wanted = set(task_filter)
    out = [t for t in tasks if t.task_id in wanted]
    missing = wanted - {t.task_id for t in out}
    if missing:
        raise KeyError(f"unknown task ids: {sorted(missing)}")
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _classify_result(verify: VerifyResult, backend_error: Optional[str]) -> str:
    if backend_error is not None:
        return RESULT_ERROR
    return RESULT_PASS if verify.tests_passed else RESULT_FAIL


def _effective_prompt_block(
    br: BackendResult, attempt_dir: Path
) -> Optional[dict]:
    if br.prompt_path is None:
        return None
    return {
        "path": str(br.prompt_path.relative_to(attempt_dir))
        if _is_under(br.prompt_path, attempt_dir)
        else str(br.prompt_path),
        "sha256": _sha256_file(br.prompt_path),
    }


def _relpath_or_none(p: Optional[Path], attempt_dir: Path) -> Optional[str]:
    if p is None:
        return None
    if _is_under(p, attempt_dir):
        return str(p.relative_to(attempt_dir))
    return str(p)


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")


def _json_default(obj):  # type: ignore[no-untyped-def]
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"unserializable: {type(obj).__name__}")


# ── Diff helpers ───────────────────────────────────────────────────────


def _write_diff(prepared: Path, worktree: Path, attempt_dir: Path) -> Path:
    """Write a unified diff comparing prepared/ to worktree/.

    Uses ``diff -urN`` so additions, deletions, and modifications are
    all captured. Empty file when prepared and worktree are identical.
    """
    diff_path = attempt_dir / "diff.patch"
    proc = subprocess.run(
        # Exclude .venv (mirrors the prepared/ snapshot's ignore pattern):
        # installed-package files swamp the model's actual edits.
        ["diff", "-urN", "-x", ".venv", str(prepared), str(worktree)],
        capture_output=True,
        text=True,
        check=False,
    )
    # diff exits 0 when identical, 1 when differing, >1 on error.
    if proc.returncode > 1:
        diff_path.write_text(
            f"# diff command failed (exit {proc.returncode}):\n{proc.stderr}",
            encoding="utf-8",
        )
    else:
        diff_path.write_text(proc.stdout, encoding="utf-8")
    return diff_path


def _diff_stats(prepared: Path, worktree: Path) -> tuple[int, int, int]:
    """Return ``(files_changed, lines_added, lines_removed)``.

    Lightweight implementation: walks both trees and counts line-level
    changes per file. Treats binary files as one line of change.
    """
    files_changed = 0
    lines_added = 0
    lines_removed = 0

    # Mirror the diff command's exclusion: ``.venv`` is a runner artifact,
    # not the model's contribution — counting its files would dominate.
    pre_files = {
        p.relative_to(prepared): p
        for p in prepared.rglob("*")
        if p.is_file() and ".venv" not in p.parts
    }
    post_files = {
        p.relative_to(worktree): p
        for p in worktree.rglob("*")
        if p.is_file() and ".venv" not in p.parts
    }

    for rel in set(pre_files) | set(post_files):
        pre = pre_files.get(rel)
        post = post_files.get(rel)
        added, removed = _line_delta(pre, post)
        if added or removed:
            files_changed += 1
            lines_added += added
            lines_removed += removed

    return files_changed, lines_added, lines_removed


def _line_delta(pre: Optional[Path], post: Optional[Path]) -> tuple[int, int]:
    pre_lines = _read_lines_or_empty(pre)
    post_lines = _read_lines_or_empty(post)
    # Phase 1: cheap line count delta. Real LCS-based line counts can come later.
    return (
        max(0, len(post_lines) - len(pre_lines))
        if pre_lines != post_lines and post is not None
        else 0,
        max(0, len(pre_lines) - len(post_lines))
        if pre_lines != post_lines and pre is not None
        else 0,
    )


def _read_lines_or_empty(p: Optional[Path]) -> list[str]:
    if p is None:
        return []
    try:
        return p.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        # Binary file: treat as one opaque "line" so we still flag it changed.
        return ["<binary>"]
