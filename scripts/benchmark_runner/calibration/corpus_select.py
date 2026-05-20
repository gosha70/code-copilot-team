# benchmark_runner.calibration.corpus_select — corpus selection from runs/.
#
# Walks an existing run archive (a ``runs/`` tree at any depth — both
# single-run layouts ``<run>/<task>/<attempt>`` and compare-run
# layouts ``<compare>/<run>/<task>/<attempt>`` are handled by
# rglob-discovery on the ``attempt-NN-run-MM`` directory pattern),
# loads each attempt's ``run-record.json`` + ``score.json``, and
# selects a subset that satisfies the requested axes of variation.
#
# Determinism + reproducibility (user-mandated 2026-05-20):
#   - Discovery sorts attempt directories by relative path. Same input
#     tree → same candidate order on every machine.
#   - Selection is a deterministic stratified round-robin; no
#     randomness, no time-of-day, no host-specific tiebreakers.
#   - Skipped attempts (unparseable run-record.json / missing
#     score.json / etc.) are reported in meta.json — never silently
#     dropped.
#
# Output (additive to ``benchmarks/calibration/``, never to ``runs/``):
#   - ``<name>.corpus.jsonl`` — one JSON record per selected attempt.
#   - ``<name>.meta.json`` — selection command + axes + counts + skips,
#     the reproducibility record.
#
# Acceptance axes per issue #34 v3:
#   - ``model``         — distinct ``backend_invocation.model`` values.
#   - ``adapter``       — distinct ``benchmark_id`` values.
#   - ``backend``       — distinct ``backend_id`` values.
#   - ``repeated-runs`` — ≥1 (task_id, backend_id, model) tuple has
#                         ≥2 task-runs in the selection.
# An axis is "represented" iff (for non-``repeated-runs``) ≥2 distinct
# values appear in the selection, or (for ``repeated-runs``) the
# per-tuple count condition above holds.

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional


CORPUS_SCHEMA_VERSION = "1.0"

# Axis identifiers (use these constants everywhere instead of bare
# strings so a typo is a NameError, not a silent "axis ignored").
AXIS_MODEL = "model"
AXIS_ADAPTER = "adapter"
AXIS_BACKEND = "backend"
AXIS_REPEATED_RUNS = "repeated-runs"

VALID_AXES: frozenset[str] = frozenset({
    AXIS_MODEL, AXIS_ADAPTER, AXIS_BACKEND, AXIS_REPEATED_RUNS,
})

# Attempt directory name: ``attempt-NN-run-MM`` (matches the layout
# written by benchmark_runner.run._execute_attempt).
_ATTEMPT_DIR_RE = re.compile(r"^attempt-\d+-run-[A-Za-z0-9._-]+$")


# ── Errors ────────────────────────────────────────────────────────────


class InvalidAxisError(ValueError):
    """Caller asked for an axis name we don't know about."""


class EmptyCandidatePoolError(RuntimeError):
    """No parseable attempt directories under runs-root."""


class InsufficientAxisRepresentationError(RuntimeError):
    """The candidate pool can't satisfy a requested axis.

    E.g. requested ``--axes model`` but every attempt in ``runs/``
    has the same model. Raised early (before round-robin) so the
    user sees the constraint that actually fails, not a
    target_n-shortfall downstream.
    """


# ── Data shapes ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Candidate:
    """One attempt directory's selection-relevant metadata.

    ``rel_path`` is the path relative to ``runs_root``; used as the
    deterministic sort key. ``abs_path`` is the absolute filesystem
    path (for the caller's output records).
    """

    rel_path: str
    abs_path: Path
    benchmark_id: str
    backend_id: str
    model: str
    task_id: str
    result: str
    attempt: int
    run_id: str


@dataclass(frozen=True)
class SelectionResult:
    """Output of ``select_corpus``: selected candidates + diagnostics."""

    selected: tuple[Candidate, ...]
    candidate_pool_size: int
    skipped: dict[str, str] = field(default_factory=dict)
    axis_summary: dict[str, Any] = field(default_factory=dict)


# ── Discovery (read-only on runs/) ────────────────────────────────────


def discover_candidates(runs_root: Path) -> tuple[list[Candidate], dict[str, str]]:
    """Walk ``runs_root`` and return (candidates, skipped_reasons).

    Skipped reasons cover the documented failure modes: missing
    score.json, missing/unparseable run-record.json, JSON parse
    errors, etc. The corpus selector reports these in meta.json so
    a reviewer can see WHY an attempt didn't enter the candidate
    pool, never a silent disappearance.

    The walker uses ``rglob`` on the ``attempt-NN-run-MM`` pattern so
    BOTH single-run layouts (``<run>/<task>/<attempt>``) AND
    compare-run layouts (``<compare>/<run>/<task>/<attempt>``) are
    handled with one pass.
    """
    if not runs_root.exists():
        raise FileNotFoundError(f"runs-root not found: {runs_root}")

    candidates: list[Candidate] = []
    skipped: dict[str, str] = {}

    # Sort attempt directories by relative path for deterministic
    # discovery order. (Path.rglob returns filesystem-order on most
    # platforms — explicit sort is the load-bearing guarantee.)
    attempt_dirs = sorted(
        (p for p in runs_root.rglob("attempt-*") if p.is_dir() and _ATTEMPT_DIR_RE.match(p.name)),
        key=lambda p: str(p.relative_to(runs_root)),
    )

    for attempt_dir in attempt_dirs:
        rel = str(attempt_dir.relative_to(runs_root))
        run_record_path = attempt_dir / "run-record.json"
        score_path = attempt_dir / "score.json"
        if not run_record_path.exists():
            skipped[rel] = "run-record.json missing"
            continue
        if not score_path.exists():
            skipped[rel] = "score.json missing"
            continue
        try:
            rr = json.loads(run_record_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            skipped[rel] = f"run-record.json unparseable: {exc}"
            continue
        try:
            sc = json.loads(score_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            skipped[rel] = f"score.json unparseable: {exc}"
            continue
        invocation_raw = rr.get("backend_invocation")
        if invocation_raw is not None and not isinstance(invocation_raw, dict):
            # Malformed type → reported skip, not silent default and
            # not a fatal walk-aborting crash. The promised contract
            # is "missing/malformed → reported skip, never silent or
            # fatal."
            skipped[rel] = (
                f"run-record.json field 'backend_invocation' has "
                f"wrong type {type(invocation_raw).__name__} "
                f"(expected object)"
            )
            continue
        invocation = invocation_raw or {}
        # Required fields. Anything missing → skipped (don't silently
        # default to "" because that would silently group runs under
        # a phantom "empty model" axis).
        benchmark_id = rr.get("benchmark_id")
        backend_id = rr.get("backend_id")
        model = invocation.get("model")
        task_id = rr.get("task_id")
        result = sc.get("result")
        attempt_num = rr.get("attempt")
        run_id = rr.get("run_id")
        missing = [
            name for name, val in (
                ("benchmark_id", benchmark_id),
                ("backend_id", backend_id),
                ("backend_invocation.model", model),
                ("task_id", task_id),
                ("result", result),
                ("attempt", attempt_num),
                ("run_id", run_id),
            ) if val is None
        ]
        if missing:
            skipped[rel] = f"run-record.json missing fields: {missing}"
            continue
        # Type coercion guarded — a non-int ``attempt`` or otherwise
        # malformed typed field must become a skip, not a walk-
        # aborting crash. Same contract as for missing/unparseable.
        try:
            candidate = Candidate(
                rel_path=rel,
                abs_path=attempt_dir,
                benchmark_id=str(benchmark_id),
                backend_id=str(backend_id),
                model=str(model),
                task_id=str(task_id),
                result=str(result),
                attempt=int(attempt_num),
                run_id=str(run_id),
            )
        except (TypeError, ValueError) as exc:
            skipped[rel] = (
                f"run-record.json has malformed typed field: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        candidates.append(candidate)
    return candidates, skipped


# ── Selection ─────────────────────────────────────────────────────────


def _axis_value(candidate: Candidate, axis: str) -> str:
    if axis == AXIS_MODEL:
        return candidate.model
    if axis == AXIS_ADAPTER:
        return candidate.benchmark_id
    if axis == AXIS_BACKEND:
        return candidate.backend_id
    raise InvalidAxisError(axis)


def _validate_axes(axes: list[str]) -> None:
    if not axes:
        raise InvalidAxisError("at least one axis required")
    for a in axes:
        if a not in VALID_AXES:
            raise InvalidAxisError(
                f"unknown axis {a!r}; valid axes: {sorted(VALID_AXES)}"
            )


def _validate_pool(candidates: list[Candidate], axes: list[str]) -> None:
    """Fail-fast if the pool can't possibly satisfy a requested axis.

    Raised BEFORE round-robin so the user sees the real constraint
    (e.g. "only 1 model in the pool") rather than a downstream
    target_n shortfall.
    """
    for axis in axes:
        if axis == AXIS_REPEATED_RUNS:
            tuples_with_repeats = sum(
                1 for _, count in _tuple_counts(candidates).items() if count >= 2
            )
            if tuples_with_repeats < 1:
                raise InsufficientAxisRepresentationError(
                    "axis 'repeated-runs' requires at least one "
                    "(task_id, backend_id, model) tuple with ≥2 "
                    "attempts in the pool; none found"
                )
            continue
        distinct = {_axis_value(c, axis) for c in candidates}
        if len(distinct) < 2:
            raise InsufficientAxisRepresentationError(
                f"axis {axis!r} requires ≥2 distinct values in the "
                f"candidate pool; found {len(distinct)} ({sorted(distinct)})"
            )


def _tuple_counts(candidates: Iterable[Candidate]) -> dict[tuple[str, str, str], int]:
    """Count attempts per (task_id, backend_id, model) tuple."""
    counts: dict[tuple[str, str, str], int] = {}
    for c in candidates:
        key = (c.task_id, c.backend_id, c.model)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _round_robin_select(
    candidates: list[Candidate],
    non_rr_axes: list[str],
    target_n: int,
) -> list[Candidate]:
    """Stratified round-robin pick.

    Groups candidates by the cartesian product of ``non_rr_axes``
    values (e.g. for axes=[model, adapter], the key is
    (model, benchmark_id)). Iterates groups in sorted order; pulls
    one candidate from each group's path-sorted queue per pass;
    stops at ``target_n`` or when every queue is empty.

    With no non-rr axes (e.g. axes=[repeated-runs] alone — degenerate
    but valid), there's one group and we just slice the first target_n.
    """
    if not non_rr_axes:
        return list(candidates[:target_n])

    groups: dict[tuple, list[Candidate]] = {}
    for c in candidates:
        key = tuple(_axis_value(c, a) for a in non_rr_axes)
        groups.setdefault(key, []).append(c)
    # Within each group, sort by rel_path for deterministic order.
    for key in groups:
        groups[key].sort(key=lambda c: c.rel_path)

    group_keys = sorted(groups.keys())
    indices = {k: 0 for k in group_keys}
    selected: list[Candidate] = []
    progress = True
    while progress and len(selected) < target_n:
        progress = False
        for k in group_keys:
            if len(selected) >= target_n:
                break
            idx = indices[k]
            if idx < len(groups[k]):
                selected.append(groups[k][idx])
                indices[k] += 1
                progress = True
    return selected


def _repair_repeated_runs(
    selected: list[Candidate],
    candidates: list[Candidate],
) -> list[Candidate]:
    """If repeated-runs not satisfied, deterministically extend a tuple
    in the selection so at least one (task, backend, model) has ≥2 entries.

    Strategy A (preferred): find a (task, backend, model) tuple
    already in the selection that has ≥2 attempts in the pool. Add
    one of its unselected siblings to the selection, replacing the
    LAST entry (by rel_path) that does NOT belong to the same tuple
    we're extending. This preserves target_n and minimises damage to
    other axes.

    Strategy B (fallback): if no selected tuple has siblings in the
    pool, replace the LAST TWO selected entries (by rel_path) with
    the first two attempts of the smallest-by-rel_path repeating
    tuple in the pool. This degrades the other axes' representation
    at small target_n but always satisfies the requested axis.

    Pre-condition: ``_validate_pool`` already proved at least one
    repeating tuple exists in the pool. ``select_corpus`` also
    pre-validates ``target_n >= 2`` when repeated-runs is requested.
    """
    selected_paths = {c.rel_path for c in selected}
    pool_tuples = _tuple_counts(candidates)
    selected_keys = {(c.task_id, c.backend_id, c.model) for c in selected}

    # Strategy A — extend an existing tuple.
    for key in sorted(selected_keys):
        if pool_tuples.get(key, 0) < 2:
            continue
        members = sorted(
            (c for c in candidates
             if (c.task_id, c.backend_id, c.model) == key),
            key=lambda c: c.rel_path,
        )
        sibling: Optional[Candidate] = None
        for m in members:
            if m.rel_path not in selected_paths:
                sibling = m
                break
        if sibling is None:
            continue
        # Replace the LAST selected entry (by rel_path) that does
        # NOT belong to `key`, so we don't swap away the entry we're
        # extending. Fall back to last-of-everything if all selected
        # entries already belong to `key` (already a satisfied state,
        # but defensive).
        selected_sorted = sorted(selected, key=lambda c: c.rel_path)
        for i in range(len(selected_sorted) - 1, -1, -1):
            sc = selected_sorted[i]
            if (sc.task_id, sc.backend_id, sc.model) != key:
                selected_sorted[i] = sibling
                return selected_sorted
        return selected_sorted  # all entries already share `key`

    # Strategy B — overwrite the last two entries with a fresh repeating tuple.
    if len(selected) < 2:
        raise InsufficientAxisRepresentationError(
            "axis 'repeated-runs' requires target_n >= 2 to admit a repair"
        )
    for key, count in sorted(pool_tuples.items()):
        if count < 2:
            continue
        members = sorted(
            (c for c in candidates
             if (c.task_id, c.backend_id, c.model) == key),
            key=lambda c: c.rel_path,
        )
        if len(members) < 2:
            continue
        selected_sorted = sorted(selected, key=lambda c: c.rel_path)
        selected_sorted[-2:] = [members[0], members[1]]
        return selected_sorted

    # _validate_pool should have caught this; defensive.
    raise InsufficientAxisRepresentationError(
        "axis 'repeated-runs' requested but no repair possible"
    )


def select_corpus(
    candidates: list[Candidate],
    axes: list[str],
    target_n: int,
) -> SelectionResult:
    """Select ``target_n`` candidates satisfying ``axes``.

    Pure function — no I/O, no env, no time. Determined entirely by
    its inputs. Same (candidates, axes, target_n) → same selection
    (Candidate objects are frozen + hashable on identity).
    """
    if target_n < 1:
        raise ValueError(f"target_n must be >= 1; got {target_n}")
    _validate_axes(axes)
    if AXIS_REPEATED_RUNS in axes and target_n < 2:
        raise InsufficientAxisRepresentationError(
            f"axis 'repeated-runs' requires target_n >= 2; got {target_n}"
        )
    if not candidates:
        raise EmptyCandidatePoolError(
            "candidate pool is empty; nothing to select from"
        )
    pool_size = len(candidates)
    if target_n > pool_size:
        raise InsufficientAxisRepresentationError(
            f"target_n ({target_n}) exceeds candidate pool size ({pool_size})"
        )
    _validate_pool(candidates, axes)

    non_rr_axes = [a for a in axes if a != AXIS_REPEATED_RUNS]
    # Sort candidates once; round-robin re-sorts within each group.
    sorted_candidates = sorted(candidates, key=lambda c: c.rel_path)

    selected = _round_robin_select(sorted_candidates, non_rr_axes, target_n)

    # Verify all non-rr axes are represented post-selection. Round
    # robin guarantees this when target_n >= len(group_keys); the
    # check below catches the rare case where target_n is so small
    # that some axis values weren't reached.
    for axis in non_rr_axes:
        distinct = {_axis_value(c, axis) for c in selected}
        if len(distinct) < 2:
            raise InsufficientAxisRepresentationError(
                f"selection of target_n={target_n} produced only "
                f"{len(distinct)} distinct values for axis {axis!r} "
                f"({sorted(distinct)}); raise target_n"
            )

    # Repeated-runs check + repair.
    if AXIS_REPEATED_RUNS in axes:
        selected_tuple_counts = _tuple_counts(selected)
        if not any(v >= 2 for v in selected_tuple_counts.values()):
            selected = _repair_repeated_runs(selected, sorted_candidates)
            # Re-validate the OTHER requested axes after repair —
            # strategy B (replace last two entries with a fresh
            # repeating tuple's siblings) can collapse the model /
            # adapter / backend axes to a single distinct value if
            # those entries were the only representatives. The
            # contract is "all requested axes satisfied"; return
            # success only if the post-repair selection still
            # honours each one.
            for axis in non_rr_axes:
                distinct = {_axis_value(c, axis) for c in selected}
                if len(distinct) < 2:
                    raise InsufficientAxisRepresentationError(
                        f"repaired selection for 'repeated-runs' "
                        f"left axis {axis!r} with only {len(distinct)} "
                        f"distinct value(s) ({sorted(distinct)}); "
                        f"target_n={target_n} is too small to satisfy "
                        f"axes {axes!r} simultaneously — raise target_n"
                    )

    # Final sort for deterministic output order.
    selected = sorted(selected, key=lambda c: c.rel_path)

    return SelectionResult(
        selected=tuple(selected),
        candidate_pool_size=pool_size,
        axis_summary=_axis_summary(selected, axes),
    )


def _axis_summary(
    selected: list[Candidate],
    axes: list[str],
) -> dict[str, Any]:
    """Per-axis breakdown of the selection. Goes into meta.json."""
    summary: dict[str, Any] = {}
    for axis in axes:
        if axis == AXIS_REPEATED_RUNS:
            counts = _tuple_counts(selected)
            multi = {f"{k[0]} / {k[1]} / {k[2]}": v
                     for k, v in counts.items() if v >= 2}
            summary[axis] = {
                "tuples_with_>=2_runs": len(multi),
                "details": dict(sorted(multi.items())),
            }
            continue
        per_value: dict[str, int] = {}
        for c in selected:
            v = _axis_value(c, axis)
            per_value[v] = per_value.get(v, 0) + 1
        summary[axis] = dict(sorted(per_value.items()))
    return summary


# ── Output writers ────────────────────────────────────────────────────


def write_corpus(
    result: SelectionResult,
    *,
    name: str,
    axes: list[str],
    target_n: int,
    runs_root: Path,
    output_dir: Path,
    selection_command: str = "",
) -> tuple[Path, Path]:
    """Write ``<name>.corpus.jsonl`` + ``<name>.meta.json`` under output_dir.

    Returns the two written paths. Creates ``output_dir`` if missing.
    NEVER writes under ``runs_root`` — outputs are additive.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = output_dir / f"{name}.corpus.jsonl"
    meta_path = output_dir / f"{name}.meta.json"

    # corpus.jsonl — one record per selected attempt.
    with corpus_path.open("w", encoding="utf-8") as f:
        for c in result.selected:
            record = {
                "run_path": c.rel_path,
                "task_id": c.task_id,
                "benchmark_id": c.benchmark_id,
                "backend_id": c.backend_id,
                "model": c.model,
                "result": c.result,
                "attempt": c.attempt,
                "run_id": c.run_id,
            }
            f.write(json.dumps(record, sort_keys=False) + "\n")

    meta = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "name": name,
        "selected_at": datetime.datetime.now(datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "selection_command": selection_command,
        "runs_root": str(runs_root.resolve()),
        "axes": axes,
        "target_n": target_n,
        "actual_n": len(result.selected),
        "candidate_pool_size": result.candidate_pool_size,
        "axis_summary": result.axis_summary,
        "skipped": dict(sorted(result.skipped.items())),
    }
    meta_path.write_text(
        json.dumps(meta, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return corpus_path, meta_path


def select_and_write(
    *,
    runs_root: Path,
    axes: list[str],
    target_n: int,
    name: str,
    output_dir: Path,
    selection_command: str = "",
) -> tuple[Path, Path, SelectionResult]:
    """High-level entrypoint: discover, select, write.

    Combines ``discover_candidates`` + ``select_corpus`` + ``write_corpus``
    into one call for the CLI's use. The pure ``select_corpus`` stays
    available for unit tests that don't want I/O.
    """
    candidates, skipped = discover_candidates(runs_root)
    if not candidates:
        raise EmptyCandidatePoolError(
            f"no parseable attempt directories under {runs_root}; "
            f"skipped {len(skipped)} due to missing/malformed records"
        )
    result = select_corpus(candidates, axes, target_n)
    # Attach skips from discovery so meta.json carries them.
    result = SelectionResult(
        selected=result.selected,
        candidate_pool_size=result.candidate_pool_size,
        skipped=skipped,
        axis_summary=result.axis_summary,
    )
    corpus_path, meta_path = write_corpus(
        result,
        name=name,
        axes=axes,
        target_n=target_n,
        runs_root=runs_root,
        output_dir=output_dir,
        selection_command=selection_command,
    )
    return corpus_path, meta_path, result


def parse_axes_arg(value: str) -> list[str]:
    """Parse the CLI's ``--axes model,repeated-runs`` form.

    Trims whitespace, drops empty entries, preserves order, rejects
    duplicates. Raises ``InvalidAxisError`` on unknown axis names.
    """
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise InvalidAxisError("--axes must list at least one axis")
    seen: set[str] = set()
    for p in parts:
        if p not in VALID_AXES:
            raise InvalidAxisError(
                f"unknown axis {p!r}; valid axes: {sorted(VALID_AXES)}"
            )
        if p in seen:
            raise InvalidAxisError(f"duplicate axis in --axes: {p!r}")
        seen.add(p)
    return parts
