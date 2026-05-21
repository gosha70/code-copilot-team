# benchmark_runner.calibration.validate — calibration orchestration.
#
# Given a human-labeled JSONL corpus + judge.json files on disk, this
# module:
#
#   1. Loads labels (label = {run_path, dimension, rating, notes}).
#   2. Loads the corresponding judge.json files (one per run_path).
#   3. Joins per (run_path, dimension) on integer ratings, dropping
#      pairs where either side is null (structurally inapplicable per
#      the rubric) or where the join failed (missing judge.json,
#      missing dimension, judge_id mismatch).
#   4. For each dimension: computes Spearman ρ + exact-match rate,
#      classifies as "calibrated" / "uncalibrated" / "no_signal".
#   5. Writes <name>.calibration-report.md (human-readable) and
#      <name>.calibrated-dimensions.json (machine-readable; consumed
#      by report.py + report_winner.py in sub-issue C/D).
#
# Threshold: per-dimension Spearman >= threshold (default 0.6 per
# issue #34 v3) → calibrated; otherwise uncalibrated. The threshold
# is stored in the JSON output so reports are self-describing
# without re-running calibration.
#
# Determinism: deterministic ordering throughout. Labels are sorted
# by (run_path, dimension); dimensions in outputs sorted; per-pair
# sample arrays sorted by run_path. Same inputs → byte-identical
# outputs (modulo the generated_at timestamp).

from __future__ import annotations

import datetime
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .spearman import exact_match_rate, spearman


# Spearman ρ is bounded in [-1, 1]; the threshold gates "calibrated"
# dimensions, so the practical domain is [0, 1] — a negative
# threshold would mean "calibrated if anti-correlated," which is
# nonsensical for the calibration step. NaN/inf are rejected
# because (a) they'd produce non-standard JSON in the output,
# and (b) NaN comparisons silently fail-open (any rho < NaN is
# False, so a NaN threshold would mark every dimension as
# uncalibrated without surfacing the misconfiguration).
THRESHOLD_MIN = 0.0
THRESHOLD_MAX = 1.0


CALIBRATED_DIMENSIONS_SCHEMA_VERSION = "1.0"
DEFAULT_THRESHOLD = 0.6
DEFAULT_JUDGE_OUTPUT_NAME = "judge.json"

# Dimension status sentinels (use these everywhere instead of bare
# strings so a rename is a NameError not a silent miss).
STATUS_CALIBRATED = "calibrated"
STATUS_UNCALIBRATED = "uncalibrated"
STATUS_NO_SIGNAL = "no_signal"


# ── Errors ────────────────────────────────────────────────────────────


class LabelsParseError(ValueError):
    """Labels JSONL malformed beyond what per-line skips can absorb."""


class NoLabelsError(RuntimeError):
    """Labels file present but contained zero parseable records."""


# ── Data shapes ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Label:
    """One human label record: (run_path, dimension, rating, notes)."""

    run_path: str
    dimension: str
    rating: Optional[int]  # None = structurally inapplicable per the rubric
    notes: str = ""


@dataclass(frozen=True)
class DimensionResult:
    """Per-dimension calibration outcome."""

    dimension: str
    n_paired: int
    spearman: Optional[float]
    exact_match_rate: Optional[float]
    status: str  # one of STATUS_*
    reason: str = ""  # diagnostic for no_signal/uncalibrated


@dataclass(frozen=True)
class DataQuality:
    """Counts of labels + judge-output records that didn't enter samples."""

    labels_total: int = 0
    labels_with_null_rating: int = 0
    labels_for_missing_judge_output: int = 0
    labels_for_unparseable_judge_output: int = 0
    labels_for_judge_id_mismatch: int = 0
    labels_for_missing_dimension: int = 0
    labels_for_null_judge_rating: int = 0
    labels_for_malformed_judge_rating: int = 0
    labels_for_out_of_range_judge_rating: int = 0
    judge_output_skip_reasons: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    """End-to-end output of validate_corpus."""

    results: tuple[DimensionResult, ...]
    threshold: float
    data_quality: DataQuality


# ── Loading ────────────────────────────────────────────────────────────


def load_labels(path: Path) -> list[Label]:
    """Parse a labels JSONL file.

    Each line is a JSON object with required fields ``run_path``,
    ``dimension``, ``rating`` (int 1..5 or null), optional ``notes``.
    Lines that are blank or comment-shaped (start with ``//`` or
    ``#``) are skipped silently. Malformed lines raise
    ``LabelsParseError`` with the offending line number — strict
    parsing because a typo in labels would otherwise silently drop
    a sample.
    """
    if not path.exists():
        raise FileNotFoundError(f"labels file not found: {path}")
    out: list[Label] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("//") or stripped.startswith("#"):
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise LabelsParseError(
                    f"{path}:{lineno}: JSON parse error: {exc}"
                ) from exc
            if not isinstance(rec, dict):
                raise LabelsParseError(
                    f"{path}:{lineno}: expected JSON object; got "
                    f"{type(rec).__name__}"
                )
            for field_name in ("run_path", "dimension"):
                if field_name not in rec:
                    raise LabelsParseError(
                        f"{path}:{lineno}: missing required field "
                        f"{field_name!r}"
                    )
            if "rating" not in rec:
                raise LabelsParseError(
                    f"{path}:{lineno}: missing required field 'rating' "
                    f"(use null for structurally inapplicable)"
                )
            rating = rec["rating"]
            if rating is not None:
                if isinstance(rating, bool) or not isinstance(rating, int):
                    raise LabelsParseError(
                        f"{path}:{lineno}: rating must be int 1..5 or null; "
                        f"got {type(rating).__name__} {rating!r}"
                    )
                if not (1 <= rating <= 5):
                    raise LabelsParseError(
                        f"{path}:{lineno}: rating out of range; "
                        f"got {rating} (expected 1..5 or null)"
                    )
            out.append(Label(
                run_path=str(rec["run_path"]),
                dimension=str(rec["dimension"]),
                rating=rating,
                notes=str(rec.get("notes", "") or ""),
            ))
    return out


def load_judge_output(path: Path) -> Optional[dict]:
    """Parse a single judge.json file. Returns the parsed dict, or
    ``None`` if the file is missing/unparseable. Callers record a
    skip reason; this function does not raise."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# ── Per-dimension evaluation ──────────────────────────────────────────


def evaluate_dimension(
    dimension: str,
    paired: list[tuple[int, int]],
    *,
    threshold: float,
) -> DimensionResult:
    """Compute Spearman ρ + exact-match rate for a dimension's paired
    samples; classify as calibrated/uncalibrated/no_signal.

    ``paired`` is a list of ``(human_rating, judge_rating)`` tuples,
    both integers (caller has already filtered out nulls). Spearman
    needs n >= 2 + variation on both sides; either condition not
    met → no_signal with a reason.
    """
    n = len(paired)
    if n < 2:
        return DimensionResult(
            dimension=dimension,
            n_paired=n,
            spearman=None,
            exact_match_rate=None if n == 0 else exact_match_rate(
                [p[0] for p in paired], [p[1] for p in paired],
            ),
            status=STATUS_NO_SIGNAL,
            reason=f"n_paired={n} (need >= 2)",
        )
    xs = [p[0] for p in paired]
    ys = [p[1] for p in paired]
    em = exact_match_rate(xs, ys)
    try:
        rho = spearman(xs, ys)
    except ValueError as exc:
        # "no variation" path from spearman — surface verbatim.
        return DimensionResult(
            dimension=dimension,
            n_paired=n,
            spearman=None,
            exact_match_rate=em,
            status=STATUS_NO_SIGNAL,
            reason=str(exc),
        )
    status = STATUS_CALIBRATED if rho >= threshold else STATUS_UNCALIBRATED
    reason = "" if status == STATUS_CALIBRATED else (
        f"Spearman {rho:.4f} < threshold {threshold}"
    )
    return DimensionResult(
        dimension=dimension,
        n_paired=n,
        spearman=rho,
        exact_match_rate=em,
        status=status,
        reason=reason,
    )


# ── Orchestrator ──────────────────────────────────────────────────────


def validate_threshold(threshold: float) -> None:
    """Raise ``ValueError`` if ``threshold`` is not a finite number in
    ``[THRESHOLD_MIN, THRESHOLD_MAX]``.

    Defense-in-depth: the CLI does the same check before calling
    into this module, but a direct caller that bypasses the CLI
    still gets the safety net. The error message names the
    constraint that failed.
    """
    if math.isnan(threshold) or math.isinf(threshold):
        raise ValueError(
            f"threshold must be a finite number; got {threshold!r}"
        )
    if not (THRESHOLD_MIN <= threshold <= THRESHOLD_MAX):
        raise ValueError(
            f"threshold must be in [{THRESHOLD_MIN}, {THRESHOLD_MAX}] "
            f"(Spearman ρ domain for calibration); got {threshold}"
        )


def validate_corpus(
    labels: Iterable[Label],
    *,
    runs_root: Path,
    judge_family_model: str,
    threshold: float = DEFAULT_THRESHOLD,
    judge_output_name: str = DEFAULT_JUDGE_OUTPUT_NAME,
) -> ValidationResult:
    """Join labels with judge outputs, compute per-dimension calibration.

    Pure-ish: reads judge.json files from disk but does not write.
    The writer (``write_calibration_artifacts``) takes the
    ValidationResult and produces the on-disk artifacts.
    """
    validate_threshold(threshold)
    labels_list = list(labels)

    # Counts for the data-quality block.
    dq_labels_with_null_rating = 0
    dq_labels_for_missing_judge_output = 0
    dq_labels_for_unparseable_judge_output = 0
    dq_labels_for_judge_id_mismatch = 0
    dq_labels_for_missing_dimension = 0
    dq_labels_for_null_judge_rating = 0
    dq_labels_for_malformed_judge_rating = 0
    dq_labels_for_out_of_range_judge_rating = 0
    judge_output_skip_reasons: dict[str, str] = {}

    # Cache judge outputs per run_path (one judge.json file may carry
    # ratings for multiple dimensions of the same attempt).
    judge_cache: dict[str, Optional[dict]] = {}

    # Per-dimension paired samples (deterministically ordered by
    # iterating labels in sorted (run_path, dimension) order).
    per_dim_samples: dict[str, list[tuple[int, int]]] = {}
    dimensions_seen: set[str] = set()
    for label in sorted(labels_list, key=lambda l: (l.run_path, l.dimension)):
        dimensions_seen.add(label.dimension)
        if label.rating is None:
            dq_labels_with_null_rating += 1
            continue
        if label.run_path not in judge_cache:
            judge_path = runs_root / label.run_path / judge_output_name
            loaded = load_judge_output(judge_path)
            judge_cache[label.run_path] = loaded
            if loaded is None:
                if judge_path.exists():
                    judge_output_skip_reasons[label.run_path] = (
                        f"{judge_output_name} unparseable"
                    )
                else:
                    judge_output_skip_reasons[label.run_path] = (
                        f"{judge_output_name} missing"
                    )
        judge_doc = judge_cache[label.run_path]
        if judge_doc is None:
            reason = judge_output_skip_reasons.get(label.run_path, "missing")
            if "unparseable" in reason:
                dq_labels_for_unparseable_judge_output += 1
            else:
                dq_labels_for_missing_judge_output += 1
            continue
        # judge_id + judge_model assertion — calibration is meaningful
        # only against the specified judge.
        actual = (
            f"{judge_doc.get('judge_backend_id', judge_doc.get('judge_id', '?'))}"
            f":{judge_doc.get('judge_model', '?')}"
        )
        # The judge_id-style "<backend>:<model>" identification has
        # two acceptable shapes depending on how the producer chose
        # to identify itself; tolerate both vs the user-supplied
        # form.
        if not _judge_matches(judge_doc, judge_family_model):
            dq_labels_for_judge_id_mismatch += 1
            continue
        ratings_block = judge_doc.get("ratings") or {}
        if label.dimension not in ratings_block:
            dq_labels_for_missing_dimension += 1
            continue
        judge_rating = ratings_block[label.dimension].get("rating") \
            if isinstance(ratings_block[label.dimension], dict) else None
        if judge_rating is None:
            dq_labels_for_null_judge_rating += 1
            continue
        if isinstance(judge_rating, bool) or not isinstance(judge_rating, int):
            # Malformed type (bool, float, str, …). The judge runner's
            # DimensionRating.__post_init__ should have rejected this
            # at write-time; the validator can't trust that — a
            # hand-edited judge.json could re-introduce it.
            dq_labels_for_malformed_judge_rating += 1
            continue
        if not (1 <= judge_rating <= 5):
            # Out-of-band integer rating (0, 6, 99, -1, …). Same
            # defense as above: DimensionRating.__post_init__ enforces
            # the band at write-time, but a malformed or hand-edited
            # judge.json could carry an out-of-range value. Treat it
            # as a skip in its own data-quality bucket so the report
            # surfaces the misconfiguration rather than letting a
            # bogus pair enter the Spearman sample.
            dq_labels_for_out_of_range_judge_rating += 1
            continue
        per_dim_samples.setdefault(label.dimension, []).append(
            (label.rating, judge_rating)
        )

    # Evaluate each dimension that appeared in the labels.
    results: list[DimensionResult] = []
    for dim in sorted(dimensions_seen):
        results.append(evaluate_dimension(
            dim,
            per_dim_samples.get(dim, []),
            threshold=threshold,
        ))

    data_quality = DataQuality(
        labels_total=len(labels_list),
        labels_with_null_rating=dq_labels_with_null_rating,
        labels_for_missing_judge_output=dq_labels_for_missing_judge_output,
        labels_for_unparseable_judge_output=dq_labels_for_unparseable_judge_output,
        labels_for_judge_id_mismatch=dq_labels_for_judge_id_mismatch,
        labels_for_missing_dimension=dq_labels_for_missing_dimension,
        labels_for_null_judge_rating=dq_labels_for_null_judge_rating,
        labels_for_malformed_judge_rating=dq_labels_for_malformed_judge_rating,
        labels_for_out_of_range_judge_rating=dq_labels_for_out_of_range_judge_rating,
        judge_output_skip_reasons=judge_output_skip_reasons,
    )
    return ValidationResult(
        results=tuple(results),
        threshold=threshold,
        data_quality=data_quality,
    )


def _judge_matches(judge_doc: dict, expected: str) -> bool:
    """Does ``judge_doc``'s identity match the user-supplied ``--judge``?

    Accepts both ``<judge_backend_id>:<judge_model>`` and
    ``<judge_id>:<judge_model>`` forms, since the spec's CLI surface
    uses the SDD-canonical ``claude-code`` (the backend id) while
    judge.json records ``judge_id: "claude-code-judge"`` (the
    internal id) plus ``judge_backend_id: "claude-code"``.
    """
    if ":" not in expected:
        return False
    fam, _, model = expected.partition(":")
    actual_model = judge_doc.get("judge_model", "")
    if actual_model != model:
        return False
    judge_backend_id = judge_doc.get("judge_backend_id", "")
    judge_id = judge_doc.get("judge_id", "")
    return fam in (judge_backend_id, judge_id)


# ── Writers ───────────────────────────────────────────────────────────


def write_calibration_artifacts(
    result: ValidationResult,
    *,
    name: str,
    judge_family_model: str,
    labels_path: Path,
    runs_root: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write <name>.calibration-report.md + <name>.calibrated-dimensions.json.

    Returns ``(report_path, json_path)``. Creates ``output_dir`` if
    missing. Never writes under ``runs_root``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{name}.calibration-report.md"
    json_path = output_dir / f"{name}.calibrated-dimensions.json"

    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    # ── JSON ──
    payload: dict[str, Any] = {
        "schema_version": CALIBRATED_DIMENSIONS_SCHEMA_VERSION,
        "name": name,
        "judge": judge_family_model,
        "threshold": result.threshold,
        "labels_path": str(labels_path.resolve()),
        "runs_root": str(runs_root.resolve()),
        "generated_at": generated_at,
        "calibrated": [],
        "uncalibrated": [],
        "no_signal": [],
        "data_quality": _serialize_data_quality(result.data_quality),
    }
    for r in result.results:
        entry = {
            "dimension": r.dimension,
            "n_paired": r.n_paired,
            "spearman": r.spearman,
            "exact_match_rate": r.exact_match_rate,
        }
        if r.status == STATUS_CALIBRATED:
            payload["calibrated"].append(entry)
        elif r.status == STATUS_UNCALIBRATED:
            entry["reason"] = r.reason
            payload["uncalibrated"].append(entry)
        else:
            entry["reason"] = r.reason
            payload["no_signal"].append(entry)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    # ── Markdown ──
    report_path.write_text(
        _render_report_md(
            name=name,
            judge_family_model=judge_family_model,
            labels_path=labels_path,
            runs_root=runs_root,
            generated_at=generated_at,
            result=result,
        ),
        encoding="utf-8",
    )
    return report_path, json_path


def _serialize_data_quality(dq: DataQuality) -> dict:
    return {
        "labels_total": dq.labels_total,
        "labels_with_null_rating": dq.labels_with_null_rating,
        "labels_for_missing_judge_output": dq.labels_for_missing_judge_output,
        "labels_for_unparseable_judge_output": dq.labels_for_unparseable_judge_output,
        "labels_for_judge_id_mismatch": dq.labels_for_judge_id_mismatch,
        "labels_for_missing_dimension": dq.labels_for_missing_dimension,
        "labels_for_null_judge_rating": dq.labels_for_null_judge_rating,
        "labels_for_malformed_judge_rating": dq.labels_for_malformed_judge_rating,
        "labels_for_out_of_range_judge_rating": dq.labels_for_out_of_range_judge_rating,
        "judge_output_skip_reasons": dict(sorted(dq.judge_output_skip_reasons.items())),
    }


def _render_report_md(
    *,
    name: str,
    judge_family_model: str,
    labels_path: Path,
    runs_root: Path,
    generated_at: str,
    result: ValidationResult,
) -> str:
    lines: list[str] = []
    lines.append(f"# Calibration Report — `{name}`")
    lines.append("")
    lines.append(f"- Generated: `{generated_at}`")
    lines.append(f"- Judge: `{judge_family_model}`")
    lines.append(f"- Threshold (Spearman ≥): `{result.threshold}`")
    lines.append(f"- Labels: `{labels_path}`")
    lines.append(f"- Runs root: `{runs_root}`")
    lines.append("")
    lines.append("## Per-dimension results")
    lines.append("")
    lines.append("| Dimension | n (paired) | Spearman ρ | Exact-match | Status | Notes |")
    lines.append("|---|---:|---:|---:|---|---|")
    for r in result.results:
        rho_cell = "—" if r.spearman is None else f"{r.spearman:.4f}"
        em_cell = "—" if r.exact_match_rate is None else f"{r.exact_match_rate:.4f}"
        lines.append(
            f"| `{r.dimension}` | {r.n_paired} | {rho_cell} | {em_cell} | "
            f"{r.status} | {r.reason or ''} |"
        )
    lines.append("")
    n_cal = sum(1 for r in result.results if r.status == STATUS_CALIBRATED)
    n_unc = sum(1 for r in result.results if r.status == STATUS_UNCALIBRATED)
    n_nosig = sum(1 for r in result.results if r.status == STATUS_NO_SIGNAL)
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Calibrated: **{n_cal}**")
    lines.append(f"- Uncalibrated: **{n_unc}**")
    lines.append(f"- No-signal: **{n_nosig}**")
    if n_cal == 0:
        lines.append("")
        lines.append(
            "> Zero dimensions cleared the threshold. Per spec.md D6 "
            "(zero-dimensions-calibrated terminal state), this is a "
            "valid empirical outcome — reports continue to render raw "
            "ratings advisory-only, and no calibrated-judge verdict "
            "is declared. Maintainer recovery options: revise the "
            "rubric (new `rubric-default-vN.md`), try a different "
            "judge model, or accept the negative result."
        )
    lines.append("")
    lines.append("## Data quality")
    lines.append("")
    dq = result.data_quality
    lines.append(f"- Labels total: {dq.labels_total}")
    lines.append(f"- Labels with null human rating (structurally inapplicable): {dq.labels_with_null_rating}")
    lines.append(f"- Labels with missing judge.json: {dq.labels_for_missing_judge_output}")
    lines.append(f"- Labels with unparseable judge.json: {dq.labels_for_unparseable_judge_output}")
    lines.append(f"- Labels with judge-id mismatch: {dq.labels_for_judge_id_mismatch}")
    lines.append(f"- Labels whose dimension was missing from the judge output: {dq.labels_for_missing_dimension}")
    lines.append(f"- Labels with null judge rating (judge declared inapplicable): {dq.labels_for_null_judge_rating}")
    lines.append(f"- Labels with malformed judge rating (non-int / bool / float): {dq.labels_for_malformed_judge_rating}")
    lines.append(f"- Labels with out-of-range judge rating (not in 1..5): {dq.labels_for_out_of_range_judge_rating}")
    if dq.judge_output_skip_reasons:
        lines.append("")
        lines.append("### Judge-output skip reasons")
        lines.append("")
        for run_path, reason in sorted(dq.judge_output_skip_reasons.items()):
            lines.append(f"- `{run_path}`: {reason}")
    return "\n".join(lines) + "\n"


# ── High-level entrypoint for the CLI ────────────────────────────────


def validate_and_write(
    *,
    labels_path: Path,
    runs_root: Path,
    judge_family_model: str,
    name: str,
    output_dir: Path,
    threshold: float = DEFAULT_THRESHOLD,
    judge_output_name: str = DEFAULT_JUDGE_OUTPUT_NAME,
) -> tuple[Path, Path, ValidationResult]:
    """Convenience wrapper for the CLI: load → validate → write."""
    labels = load_labels(labels_path)
    if not labels:
        raise NoLabelsError(f"labels file empty or contains zero records: {labels_path}")
    result = validate_corpus(
        labels,
        runs_root=runs_root,
        judge_family_model=judge_family_model,
        threshold=threshold,
        judge_output_name=judge_output_name,
    )
    report_path, json_path = write_calibration_artifacts(
        result,
        name=name,
        judge_family_model=judge_family_model,
        labels_path=labels_path,
        runs_root=runs_root,
        output_dir=output_dir,
    )
    return report_path, json_path, result
