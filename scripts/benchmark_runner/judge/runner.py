# benchmark_runner.judge.runner — walk a run-dir, invoke a Judge per
# attempt, write judge.json adjacent to score.json.
#
# Additivity invariant (load-bearing): the runner READS the existing
# attempt artifacts (score.json, run-record.json, diff.patch, prompt.md,
# verify-output.txt) and writes only ``judge.json`` next to score.json.
# score.json is NEVER modified or replaced. The invariant is enforced
# in two ways:
#   1. The runner hashes score.json before and after each rate() call
#      and raises ScoreJsonMutatedError if the digests differ.
#   2. The runner uses Path.write_text only to write judge.json, never
#      score.json.
#
# Schema. judge.json is the on-disk serialization of a JudgeResult,
# plus a schema_version and a flat list of rubric_dimensions so
# downstream tooling can read it without consulting the rubric file.

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .contracts import (
    DimensionRating,
    Judge,
    JudgeInput,
    JudgeInvocation,
    JudgeResult,
    RubricSpec,
)


JUDGE_JSON_SCHEMA_VERSION = "1.0"

# Attempt directories under a run-dir match this pattern, produced by
# benchmark_runner.run._execute_attempt:
#   <run_dir>/<task-slug>/attempt-NN-run-MM/
_ATTEMPT_DIR_RE = re.compile(r"^attempt-\d+-run-[A-Za-z0-9._-]+$")


class ScoreJsonMutatedError(RuntimeError):
    """Raised when a Judge implementation mutated score.json.

    Hard failure: the additivity invariant is load-bearing for the
    whole feature; any Judge that breaks it must be fixed before
    its output is used.
    """


@dataclass(frozen=True)
class RunJudgeStats:
    """Per-call summary of what ``run_judge`` did.

    ``attempts_processed`` is the number of attempts the judge
    actually rated (a judge.json was written for each).
    ``attempts_skipped`` is the number of attempt directories the
    runner found but skipped (missing score.json, judge.json
    already present and overwrite=False, etc.) with the reason
    recorded in ``skip_reasons``.
    ``attempts_failed`` is the number where rate() raised; the
    exception is recorded in ``failure_reasons``. The runner
    continues past per-attempt failures so one bad attempt does
    not block a whole calibration pass.
    """

    attempts_processed: int = 0
    attempts_skipped: int = 0
    attempts_failed: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    failure_reasons: dict[str, str] = field(default_factory=dict)


def run_judge(
    run_dir: Path,
    judge: Judge,
    rubric: RubricSpec,
    *,
    judge_output_name: str = "judge.json",
    overwrite: bool = False,
) -> RunJudgeStats:
    """Run ``judge`` over every attempt under ``run_dir``.

    Walks ``<run_dir>/<task-slug>/attempt-NN-run-MM/`` (the layout
    benchmark_runner.run writes). For each attempt that has a
    score.json, constructs a JudgeInput and calls judge.rate(),
    then writes the serialized JudgeResult to ``<attempt_dir>/<judge_output_name>``.

    ``overwrite=False`` (default): if ``judge_output_name`` already
    exists, skip the attempt. Allows incremental re-runs that only
    fill in missing judge.json files. ``overwrite=True`` re-rates
    every attempt.
    """
    if not run_dir.exists():
        raise FileNotFoundError(f"run-dir not found: {run_dir}")

    attempt_dirs = _discover_attempt_dirs(run_dir)
    processed = 0
    skipped = 0
    failed = 0
    skip_reasons: dict[str, str] = {}
    failure_reasons: dict[str, str] = {}

    for attempt_dir in attempt_dirs:
        rel = str(attempt_dir.relative_to(run_dir))
        score_path = attempt_dir / "score.json"
        if not score_path.exists():
            skipped += 1
            skip_reasons[rel] = "score.json missing"
            continue
        output_path = attempt_dir / judge_output_name
        if output_path.exists() and not overwrite:
            skipped += 1
            skip_reasons[rel] = f"{judge_output_name} already exists (use overwrite=True)"
            continue

        try:
            score_data = json.loads(score_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            skipped += 1
            skip_reasons[rel] = f"score.json unparseable: {exc}"
            continue

        attempt = _build_input(attempt_dir, score_data, rubric)
        if attempt is None:
            skipped += 1
            skip_reasons[rel] = "required artifact missing (diff.patch / prompt.md)"
            continue

        before_sha = _sha256_file(score_path)
        result: Optional[JudgeResult] = None
        rate_error: Optional[BaseException] = None
        try:
            result = judge.rate(attempt)
        except Exception as exc:  # noqa: BLE001 — per-attempt isolation
            rate_error = exc

        # Additivity check runs whether rate() succeeded OR raised. A
        # judge that mutates score.json and then raises must still
        # trip the guard — otherwise per-attempt failure isolation
        # would silently swallow an invariant violation and the CLI
        # would return a normal summary. The guard takes precedence
        # over the per-attempt failure recording: any mutation is a
        # hard fail for the whole run, not a per-attempt skip.
        after_sha = _sha256_file(score_path)
        if before_sha != after_sha:
            raise ScoreJsonMutatedError(
                f"judge {judge.judge_id!r} mutated {score_path} during rate() "
                f"(sha256 {before_sha} → {after_sha}); the additivity "
                f"invariant forbids this. Fix the judge implementation."
            )

        if rate_error is not None:
            failed += 1
            failure_reasons[rel] = f"{type(rate_error).__name__}: {rate_error}"
            continue

        assert result is not None  # rate_error is None ⇒ result was assigned
        _write_judge_json(output_path, result)
        processed += 1

    return RunJudgeStats(
        attempts_processed=processed,
        attempts_skipped=skipped,
        attempts_failed=failed,
        skip_reasons=skip_reasons,
        failure_reasons=failure_reasons,
    )


# ── Helpers ────────────────────────────────────────────────────────────


def _discover_attempt_dirs(run_dir: Path) -> list[Path]:
    """Find every ``attempt-NN-run-MM/`` directory under ``run_dir``.

    Returns a sorted list so the runner's behavior is deterministic
    across machines (sorting by path string is enough — attempts
    sort first by task-slug then by attempt-run name).
    """
    found: list[Path] = []
    for child in sorted(run_dir.iterdir()):
        if not child.is_dir():
            continue
        # Layout: run_dir / <task-slug> / attempt-NN-run-MM
        for grand in sorted(child.iterdir()):
            if grand.is_dir() and _ATTEMPT_DIR_RE.match(grand.name):
                found.append(grand)
    return found


def _build_input(
    attempt_dir: Path,
    score_data: dict,
    rubric: RubricSpec,
) -> Optional[JudgeInput]:
    """Assemble a JudgeInput from attempt artifacts. None if missing required files."""
    diff_path = attempt_dir / "diff.patch"
    prompt_path = attempt_dir / "prompt.md"
    if not diff_path.exists() or not prompt_path.exists():
        return None
    verify_output_path = attempt_dir / "verify-output.txt"
    verify_output = (
        verify_output_path.read_text(encoding="utf-8")
        if verify_output_path.exists()
        else ""
    )
    return JudgeInput(
        attempt_dir=attempt_dir,
        task_id=str(score_data.get("task_id", "")),
        benchmark_id=str(score_data.get("benchmark_id", "")),
        diff_path=diff_path,
        prompt_path=prompt_path,
        verify_output=verify_output,
        rubric=rubric,
    )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _write_judge_json(path: Path, result: JudgeResult) -> None:
    payload = _serialize_result(result)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _serialize_result(result: JudgeResult) -> dict:
    """JudgeResult → JSON-serializable dict (judge.json schema 1.0)."""
    return {
        "schema_version": JUDGE_JSON_SCHEMA_VERSION,
        "judge_id": result.judge_id,
        "judge_model": result.judge_model,
        "judge_backend_id": result.judge_backend_id,
        "rubric_name": result.rubric_name,
        "rubric_dimensions": list(result.ratings.keys()),
        "ratings": {
            dim: _serialize_rating(r) for dim, r in result.ratings.items()
        },
        "judge_invocation": _serialize_invocation(result.invocation),
        "tokens_input": result.tokens_input,
        "tokens_output": result.tokens_output,
        "judge_metadata": dict(result.judge_metadata),
    }


def _serialize_rating(r: DimensionRating) -> dict:
    return {
        "rating": r.rating,
        "explanation": r.explanation,
        "prompt_sha256": r.prompt_sha256,
    }


def _serialize_invocation(inv: JudgeInvocation) -> dict:
    return {
        "model": inv.model,
        "temperature": inv.temperature,
        "seed": inv.seed,
        "temperature_control": inv.temperature_control,
        "seed_control": inv.seed_control,
        "provider_endpoint_present": inv.provider_endpoint_present,
    }
