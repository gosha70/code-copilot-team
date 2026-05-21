# benchmark_runner.report — report aggregator with calibrated verdicts.
#
# Aggregates a run directory into report.md + report.json. Per-task
# pass/fail and per-(backend, model) totals; mean/stdev across runs.
# When 2+ (backend, model) groups are present, the calibrated
# winner-declaration rule (report_winner.py) emits per-metric verdicts.
#
# Per the v3 architectural correction, the comparison axis is
# (backend, model) — same backend with different models is a meaningful
# comparison; same model on different backends is a meaningful
# comparison. Provider endpoint is surfaced per group so reports
# distinguish gateway-routed runs from default-Anthropic runs.

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from .report_winner import MetricSpec, declare_winner


# ── Metric specs used for verdict declaration ─────────────────────────

PASS_RATE_METRIC = MetricSpec(
    name="pass_rate",
    # ``continuous`` because pass rate is a fraction in [0, 1], not a
    # count. ``deterministic_threshold=1.0`` would mean "must differ
    # by 100 percentage points," which only an all-pass-vs-all-fail
    # comparison ever clears — too strict to be useful. The continuous
    # threshold (10% of the smaller mean) instead requires e.g. ~8 pp
    # at mean(0.85, 0.75)=0.80, ~5 pp at mean(0.55, 0.45)=0.50 — both
    # roughly aligned with reviewer intuition for "noticeable
    # difference vs noise."
    kind="continuous",
    higher_is_better=True,
    continuous_threshold_relative=0.10,
)

ELAPSED_SECONDS_METRIC = MetricSpec(
    name="elapsed_seconds",
    kind="continuous",
    higher_is_better=False,  # faster is better
    continuous_threshold_relative=0.10,
)

FAILED_COMMANDS_METRIC = MetricSpec(
    name="failed_commands",
    # Backend-stability signal: how many commands the backend retried
    # or had to abort. Per-attempt integer count; a difference of 1
    # is meaningful ("backend X retried once, backend Y didn't"), so
    # deterministic with a 1-point threshold is the right shape.
    kind="deterministic",
    higher_is_better=False,  # fewer failed commands is better
    deterministic_threshold=1.0,
)

HUMAN_INTERVENTIONS_METRIC = MetricSpec(
    name="human_interventions",
    # Always 0 in the MVP (no human-in-the-loop), but reserved so
    # future backends that allow human edits surface here when the
    # field departs from 0. Same shape as failed_commands.
    kind="deterministic",
    higher_is_better=False,
    deterministic_threshold=1.0,
)


def render_report(
    run_dir: Path,
    *,
    html: bool = False,
    csv: bool = False,
    calibrated_dimensions_path: Path | None = None,
    judge_output_name: str = "judge.json",
) -> Path:
    """Aggregate ``run_dir`` into report.md + report.json (always) plus
    optional report.html, report.csv / report-by-model.csv, and
    static SVG charts when ``html`` / ``csv`` are set.

    Calibrated-judge verdicts (sub-issue #51) activate when both:
      - per-attempt ``judge.json`` files exist under ``run_dir``, AND
      - ``calibrated_dimensions_path`` points at a valid JSON
        produced by ``./scripts/benchmark calibrate`` (sub-issue B).

    Without those two, the report ignores any judge data — preserving
    byte-identity with the pre-#50 baseline (additivity invariant).

    Returns the path to ``report.md``. Raises ``FileNotFoundError`` if
    the run-dir doesn't exist or contains no score files.
    """
    if not run_dir.exists():
        raise FileNotFoundError(f"run-dir not found: {run_dir}")

    attempts = _load_attempts(run_dir)
    if not attempts:
        raise FileNotFoundError(
            f"no score.json files found under {run_dir}; nothing to report"
        )

    candidate_map = _load_candidate_map(run_dir)
    summary = _summarize(attempts, candidate_map)

    # Judge enrichment (additive). Only adds keys to summary when
    # judge.json files exist — preserves byte-identity for runs
    # without judge data.
    judge_outputs = _load_judge_outputs(run_dir, judge_output_name)
    calibrated_dims = _load_calibrated_dimensions(calibrated_dimensions_path)
    if judge_outputs:
        _enrich_summary_with_judge(summary, attempts, judge_outputs, calibrated_dims)

    report_md_path = run_dir / "report.md"
    report_json_path = run_dir / "report.json"

    report_md_path.write_text(_render_markdown(summary), encoding="utf-8")
    report_json_path.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    if html:
        (run_dir / "report.html").write_text(
            _render_html(summary), encoding="utf-8"
        )
        # SVG charts are emitted alongside the HTML (and also embedded
        # by reference into the HTML). Always pass-rate bar chart;
        # judge histograms + forest plot only when judge data exists.
        (run_dir / "chart-pass-rate.svg").write_text(
            _render_svg_bar(summary), encoding="utf-8"
        )
        if summary.get("judge"):
            (run_dir / "chart-judge-histogram.svg").write_text(
                _render_svg_histogram(summary), encoding="utf-8"
            )
            (run_dir / "chart-verdict-forest.svg").write_text(
                _render_svg_forest(summary), encoding="utf-8"
            )

    if csv:
        (run_dir / "report-by-model.csv").write_text(
            _render_csv_by_model(summary), encoding="utf-8"
        )
        (run_dir / "report-per-task.csv").write_text(
            _render_csv_per_task(summary), encoding="utf-8"
        )

    return report_md_path


# ── Loading + aggregation ──────────────────────────────────────────────


def _load_attempts(run_dir: Path) -> list[dict]:
    """Load score.json + sibling run-record.json into one row per attempt.

    The score.json carries the metrics; run-record.json carries
    backend_invocation.model (the comparison axis) and backend.metadata
    (provider routing). Older run-dirs may have score.json but no
    run-record.json; we tolerate the absence by leaving model="" and
    provider_endpoint=None.

    ``score_path`` is included on every row so downstream grouping can
    derive candidate identity for compare-style run-dirs (where two
    candidates may share (backend_id, model) but live in different
    nested directories — e.g. the same Claude Code model routed through
    two providers).
    """
    out: list[dict] = []
    for score_path in sorted(run_dir.rglob("score.json")):
        with score_path.open(encoding="utf-8") as f:
            score = json.load(f)
        # run-record.json is in the same attempt directory.
        rr_path = score_path.parent / "run-record.json"
        run_record: dict[str, Any] = {}
        if rr_path.is_file():
            with rr_path.open(encoding="utf-8") as f:
                run_record = json.load(f)
        out.append({
            "score": score,
            "run_record": run_record,
            "score_path": score_path,
        })
    return out


def _load_candidate_map(run_dir: Path) -> dict[Path, str]:
    """For a compare run-dir, return absolute candidate-dir → name.

    ``./scripts/benchmark compare`` writes ``candidate-runs.json``
    alongside ``compare-manifest.json``; this helper reads it and
    resolves the per-candidate relative paths to absolute paths so the
    grouper can match attempts to their owning candidate by path.

    Returns ``{}`` for non-compare run-dirs (no
    ``candidate-runs.json``) — the grouper then falls back to the
    plain ``(backend_id, model)`` shape with empty candidate name,
    matching the pre-compare behaviour.
    """
    candidate_runs_path = run_dir / "candidate-runs.json"
    if not candidate_runs_path.is_file():
        return {}
    try:
        with candidate_runs_path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        # If the file is malformed, fall back to plain grouping rather
        # than crashing — a compare run-dir whose manifest got truncated
        # mid-write should still render *some* report.
        return {}
    out: dict[Path, str] = {}
    for c in payload.get("candidates", []):
        name = c.get("name")
        rel = c.get("run_dir")
        if isinstance(name, str) and isinstance(rel, str):
            out[(run_dir / rel).resolve()] = name
    return out


def _candidate_name_for(attempt: dict, candidate_map: Mapping[Path, str]) -> str:
    """Walk up the attempt's score_path until a candidate dir matches.

    Returns ``""`` when no candidate dir contains the attempt — which
    is always the case for non-compare run-dirs (the map is empty)
    and is also the right fallback if a compare run-dir somehow
    contains attempts outside any registered candidate directory.
    """
    if not candidate_map:
        return ""
    path = attempt["score_path"].resolve().parent
    while True:
        if path in candidate_map:
            return candidate_map[path]
        if path.parent == path:  # filesystem root
            return ""
        path = path.parent


def _group_key(attempt: dict) -> tuple[str, str, str]:
    """3-tuple group key: ``(backend_id, model, candidate_name)``.

    ``candidate_name`` is empty for non-compare run-dirs (preserved
    behaviour from the v1 report schema). For compare run-dirs it
    discriminates candidates that share ``(backend_id, model)`` but
    differ in env routing — without it, the report collapsed them
    into one group and produced misleading pairwise verdicts.
    """
    backend_id = attempt["score"]["backend_id"]
    model = (
        attempt["run_record"].get("backend_invocation", {}).get("model", "")
        or attempt["score"].get("model", "")
        or ""
    )
    candidate_name = attempt.get("_candidate_name", "")
    return backend_id, model, candidate_name


def _provider_endpoint_for(attempt: dict) -> str | None:
    return (
        attempt["run_record"]
        .get("backend", {})
        .get("metadata", {})
        .get("provider_endpoint")
    )


REPORT_SCHEMA_VERSION = "2"
"""Bumped on any breaking change to the report JSON shape.

Consumers of report.json (the dogfood subcommand internally; future
external tools) should branch on this value rather than the absence
or presence of fields.

- v1 (Phase 4a): top-level ``groups`` keyed by ``backend:model``,
  group summaries carrying ``backend_id`` + ``model``.
- v2 (compare driver shipped 2026-05-13): group key is the tuple
  ``(backend_id, model, candidate_name)``. For compare-style run-dirs
  the group label is the candidate name; for plain ``run`` run-dirs
  ``candidate_name`` is the empty string and the label is unchanged
  from v1 (``backend:model``). Each group summary additionally carries
  a ``candidate_name`` field.
"""


def _summarize(attempts: list[dict], candidate_map: Mapping[Path, str]) -> dict[str, Any]:
    # Stamp each attempt with its owning candidate name (empty string
    # for non-compare layouts) before grouping. Mutating the row in
    # place keeps the rest of the pipeline shape-stable.
    for a in attempts:
        a["_candidate_name"] = _candidate_name_for(a, candidate_map)

    by_group: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for a in attempts:
        by_group[_group_key(a)].append(a)

    groups: dict[str, dict[str, Any]] = {}
    for (backend_id, model, candidate_name), rows in by_group.items():
        label = _label(backend_id, model, candidate_name)
        groups[label] = _group_summary(backend_id, model, candidate_name, rows)

    verdicts = _verdicts_across_groups(by_group) if len(by_group) >= 2 else None

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_count": len(attempts),
        "groups": groups,
        "verdicts": verdicts,
    }


def _label(backend_id: str, model: str, candidate_name: str = "") -> str:
    # When the run-dir is a compare layout, candidates are guaranteed
    # to have unique names by ``compare._validate``; use the name as
    # the label so two same-(backend, model) candidates that differ
    # only in env routing get distinct rows + distinct verdict pairs.
    if candidate_name:
        return candidate_name
    return f"{backend_id}:{model}" if model else backend_id


def _group_summary(
    backend_id: str, model: str, candidate_name: str, rows: list[dict]
) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for r in rows if r["score"]["result"] == "pass")
    # D5: count timeout attempts separately so reviewers can distinguish
    # "LLM failed" from "LLM hung". The timeout count is additive — it does
    # NOT change pass_rate (timeouts already lower it via result != "pass").
    # Constraint #8: verdict calculus is untouched; we only ADD a tally.
    timed_out = sum(1 for r in rows if r["score"]["result"] == "timeout")
    elapsed_values = [r["score"]["derived"]["elapsed_seconds"] for r in rows]

    # Provider endpoints seen in this group — usually one, but multiple
    # if a maintainer ran the same (backend, model) against different
    # gateways within the same run-dir.
    endpoints: set[str | None] = {_provider_endpoint_for(r) for r in rows}
    # ``None`` means "default Anthropic API" for claude-code; we keep
    # the None bucket distinct from a string-URL bucket.
    endpoints_sorted = sorted(
        endpoints, key=lambda e: ("" if e is None else e)
    )

    return {
        "backend_id": backend_id,
        "model": model,
        "candidate_name": candidate_name,
        "total_attempts": total,
        "passed": passed,
        "timed_out": timed_out,
        "pass_rate": _safe_div(passed, total),
        "elapsed_seconds_mean": _mean(elapsed_values),
        "elapsed_seconds_stdev": _stdev(elapsed_values),
        "provider_endpoints": list(endpoints_sorted),
        "per_task": _per_task(rows),
    }


def _per_task(rows: list[dict]) -> dict[str, Any]:
    by_task: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_task[r["score"]["task_id"]].append(r)

    out: dict[str, Any] = {}
    for task_id, attempts in by_task.items():
        total = len(attempts)
        passed = sum(1 for a in attempts if a["score"]["result"] == "pass")
        elapsed_values = [a["score"]["derived"]["elapsed_seconds"] for a in attempts]
        out[task_id] = {
            "attempts": total,
            "passed": passed,
            "pass_rate": _safe_div(passed, total),
            "elapsed_seconds_mean": _mean(elapsed_values),
            "elapsed_seconds_stdev": _stdev(elapsed_values),
        }
    return out


def _verdicts_across_groups(
    by_group: Mapping[tuple[str, str, str], list[dict]],
) -> dict[str, Any]:
    """Pairwise verdicts for the registered metrics.

    For every pair of (backend, model) groups, emit verdicts on:
      - pass_rate (continuous, higher is better)
      - elapsed_seconds (continuous, lower is better)
      - failed_commands (deterministic, lower is better — backend
        stability signal: distinguishes "passed but needed retries"
        from "passed cleanly")
      - human_interventions (deterministic, lower is better — always
        0 in the MVP but reserved for future human-in-the-loop runs)

    Label pair is sorted so the output is deterministic.
    """
    keys = sorted(by_group.keys())
    pairs: list[dict[str, Any]] = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a_key = keys[i]
            b_key = keys[j]
            a_rows = by_group[a_key]
            b_rows = by_group[b_key]
            pairs.append(
                {
                    "a": _label(*a_key),
                    "b": _label(*b_key),
                    "pass_rate_verdict": declare_winner(
                        PASS_RATE_METRIC,
                        [_pass_rate_for_attempt(r) for r in a_rows],
                        [_pass_rate_for_attempt(r) for r in b_rows],
                    ),
                    "elapsed_seconds_verdict": declare_winner(
                        ELAPSED_SECONDS_METRIC,
                        [r["score"]["derived"]["elapsed_seconds"] for r in a_rows],
                        [r["score"]["derived"]["elapsed_seconds"] for r in b_rows],
                    ),
                    "failed_commands_verdict": declare_winner(
                        FAILED_COMMANDS_METRIC,
                        [r["score"]["derived"].get("failed_commands", 0) for r in a_rows],
                        [r["score"]["derived"].get("failed_commands", 0) for r in b_rows],
                    ),
                    "human_interventions_verdict": declare_winner(
                        HUMAN_INTERVENTIONS_METRIC,
                        [r["score"]["scores"].get("human_interventions", 0) for r in a_rows],
                        [r["score"]["scores"].get("human_interventions", 0) for r in b_rows],
                    ),
                }
            )
    return {"pairwise": pairs}


def _pass_rate_for_attempt(row: dict) -> float:
    # Per-attempt "pass rate" is just 0/1; declare_winner aggregates
    # across attempts via mean. Keeps the threshold-rule semantics
    # consistent (1pt = 1 percentage point on the count, mean across
    # attempts is the empirical pass rate).
    return 1.0 if row["score"]["result"] == "pass" else 0.0


def _safe_div(num: int, denom: int) -> float | None:
    return (num / denom) if denom else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return statistics.stdev(values)


# ── Markdown rendering ─────────────────────────────────────────────────


def _render_markdown(summary: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Benchmark report")
    lines.append("")
    lines.append(f"Total attempts recorded: **{summary['run_count']}**")
    lines.append("")

    for label, g in summary["groups"].items():
        lines.append(f"## `{label}` (backend={g['backend_id']}, model={g['model'] or '<none>'})")
        lines.append("")
        timeout_note = f" ({g['timed_out']} timed out)" if g.get("timed_out", 0) > 0 else ""
        lines.append(
            f"- Total attempts: {g['total_attempts']}  "
            f"\n- Passed: {g['passed']}  "
            f"\n- Timed out: {g.get('timed_out', 0)}{timeout_note}  "
            f"\n- Pass rate: {_fmt_pct(g['pass_rate'])}  "
            f"\n- Elapsed (s): mean {_fmt_num(g['elapsed_seconds_mean'])}, "
            f"stdev {_fmt_num(g['elapsed_seconds_stdev'])}"
        )
        lines.append(f"\n- Provider endpoint(s): {_fmt_endpoints(g['provider_endpoints'])}")
        lines.append("")

        if g["per_task"]:
            lines.append("### Per-task")
            lines.append("")
            lines.append("| task | attempts | passed | pass-rate | elapsed (mean ± stdev) |")
            lines.append("| --- | --- | --- | --- | --- |")
            for task_id, t in sorted(g["per_task"].items()):
                lines.append(
                    f"| `{task_id}` | {t['attempts']} | {t['passed']} | "
                    f"{_fmt_pct(t['pass_rate'])} | "
                    f"{_fmt_num(t['elapsed_seconds_mean'])} ± "
                    f"{_fmt_num(t['elapsed_seconds_stdev'])} |"
                )
            lines.append("")

    if summary["verdicts"]:
        lines.append("## Winner verdicts")
        lines.append("")
        lines.append("Calibrated rule: `Δ > 2σ AND |Δ| ≥ threshold` (deterministic threshold = 1 point; continuous threshold = 10% relative). See `scripts/benchmark_runner/report_winner.py`.")
        lines.append("")
        lines.append("| A | B | pass_rate | elapsed_seconds | failed_commands | human_interventions |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for pair in summary["verdicts"]["pairwise"]:
            pr = _fmt_verdict_label(pair["pass_rate_verdict"], pair["a"], pair["b"])
            es = _fmt_verdict_label(pair["elapsed_seconds_verdict"], pair["a"], pair["b"])
            fc = _fmt_verdict_label(pair["failed_commands_verdict"], pair["a"], pair["b"])
            hi = _fmt_verdict_label(pair["human_interventions_verdict"], pair["a"], pair["b"])
            lines.append(f"| `{pair['a']}` | `{pair['b']}` | {pr} | {es} | {fc} | {hi} |")
        lines.append("")

    # Judge section (additive — emitted only when judge data exists).
    lines.extend(_render_markdown_judge_section(summary))

    return "\n".join(lines).rstrip() + "\n"


def _fmt_endpoints(endpoints: list[str | None]) -> str:
    # ``None`` means the backend did not record a provider_endpoint.
    # For claude-code, that means default Anthropic API; for stub or
    # other backends it just means the metadata field wasn't populated.
    # Use generic language; let context speak.
    if not endpoints:
        return "_(unknown)_"
    return ", ".join(
        "_(none recorded)_" if e is None else f"`{e}`"
        for e in endpoints
    )


def _fmt_verdict_label(verdict: str, a: str, b: str) -> str:
    if verdict == "A":
        return f"**{a}** wins"
    if verdict == "B":
        return f"**{b}** wins"
    return "directional, no winner declared"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "_n/a_"
    return f"{value * 100:.1f}%"


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "_n/a_"
    if math.isnan(value):
        return "_n/a_"
    return f"{value:.3f}"


# ══════════════════════════════════════════════════════════════════════
# Judge enrichment + rich-report renderers (#50, #51)
# ══════════════════════════════════════════════════════════════════════
# All code below is additive. When judge.json files are absent AND no
# calibrated-dimensions path is provided, the original summary dict +
# report.md/json output above are byte-identical to the pre-#50
# baseline. Verified by the additivity snapshot test in
# test_report_judge_additivity.py.


def _load_judge_outputs(run_dir: Path, judge_output_name: str) -> dict[Path, dict]:
    """Walk run_dir for judge.json files (one per attempt).

    Returns a map from attempt-dir absolute Path → parsed judge.json
    dict. Malformed judge.json files are skipped silently (the report
    can't fix them; the calibration step (#49) is where parse errors
    surface with reasons).
    """
    out: dict[Path, dict] = {}
    for jp in sorted(run_dir.rglob(judge_output_name)):
        try:
            out[jp.parent.resolve()] = json.loads(jp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _load_calibrated_dimensions(path: Path | None) -> dict | None:
    """Load calibrated-dimensions.json from sub-issue B.

    Returns None when the path is None or the file is missing /
    unparseable. The caller treats None as "no calibrated dimensions"
    — every judge dimension renders as ``uncalibrated`` in the report.
    """
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _enrich_summary_with_judge(
    summary: dict[str, Any],
    attempts: list[dict],
    judge_outputs: Mapping[Path, dict],
    calibrated_dims: dict | None,
) -> None:
    """Add a ``summary['judge']`` block + per-group judge ratings.

    Mutates ``summary`` in place (mirrors the rest of the pipeline's
    style — this module is a single-pass aggregator that mutates the
    growing dict).

    Per-attempt judge data → per-(backend, model) group aggregation +
    pairwise calibrated-judge verdicts via report_winner.declare_winner.
    Deterministic-first ordering enforced at the verdict level:
    calibrated-judge samples only count for pairs where BOTH sides
    passed deterministically on the same task.
    """
    # Index judge ratings per attempt-dir, joined onto the existing
    # attempts list by score_path's parent directory.
    for a in attempts:
        attempt_dir = a["score_path"].parent.resolve()
        a["_judge"] = judge_outputs.get(attempt_dir)

    # Per-group judge data: per-dimension rating distributions.
    by_group: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for a in attempts:
        by_group[_group_key(a)].append(a)

    # Collect every dimension name seen across all judge outputs;
    # sorted for determinism.
    dimensions: set[str] = set()
    for jo in judge_outputs.values():
        for dim in (jo.get("rubric_dimensions") or list((jo.get("ratings") or {}).keys())):
            dimensions.add(dim)
    dimensions_sorted = sorted(dimensions)

    # Calibrated dimensions: a set of dimension names that passed the
    # Spearman threshold per sub-issue B's calibrate command.
    calibrated_set: set[str] = set()
    threshold: float | None = None
    if calibrated_dims is not None:
        threshold = calibrated_dims.get("threshold")
        for e in calibrated_dims.get("calibrated", []) or []:
            d = e.get("dimension")
            if isinstance(d, str):
                calibrated_set.add(d)

    # Per-group dimension means + per-task ratings.
    judge_groups: dict[str, dict[str, Any]] = {}
    for group_key, rows in by_group.items():
        label = _label(*group_key)
        # Per-dimension: list of integer ratings from rows whose
        # judge.json carried that dimension.
        per_dim: dict[str, Any] = {}
        for dim in dimensions_sorted:
            ratings = []
            for r in rows:
                jo = r.get("_judge")
                if not jo:
                    continue
                entry = (jo.get("ratings") or {}).get(dim)
                if not isinstance(entry, dict):
                    continue
                val = entry.get("rating")
                # Defense-in-depth: report must reject the same
                # out-of-band ratings the validator rejects. A stale or
                # hand-edited judge.json with rating 6 must NOT enter
                # group means or feed declare_winner. Mirror the
                # rubric-enforced 1..5 band from
                # judge.contracts.DimensionRating.__post_init__.
                if (
                    isinstance(val, int)
                    and not isinstance(val, bool)
                    and 1 <= val <= 5
                ):
                    ratings.append(val)
            per_dim[dim] = {
                "n": len(ratings),
                "mean": _mean([float(x) for x in ratings]),
                "stdev": _stdev([float(x) for x in ratings]),
                "calibrated": dim in calibrated_set,
            }
        judge_groups[label] = {"per_dimension": per_dim}

    # Pairwise calibrated-judge verdicts. Only computed for dimensions
    # in calibrated_set; deterministic-first ordering enforced.
    judge_pairwise: list[dict[str, Any]] = []
    if calibrated_set:
        keys = sorted(by_group.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a_key, b_key = keys[i], keys[j]
                pair_entry: dict[str, Any] = {
                    "a": _label(*a_key),
                    "b": _label(*b_key),
                    "calibrated_judge_verdicts": {},
                }
                for dim in sorted(calibrated_set):
                    a_samples, b_samples = _calibrated_judge_samples(
                        by_group[a_key], by_group[b_key], dim,
                    )
                    if not a_samples or not b_samples:
                        pair_entry["calibrated_judge_verdicts"][dim] = (
                            "directional"
                        )
                        continue
                    pair_entry["calibrated_judge_verdicts"][dim] = declare_winner(
                        MetricSpec(
                            name=f"judge:{dim}",
                            kind="continuous",
                            higher_is_better=True,
                            continuous_threshold_relative=0.10,
                        ),
                        a_samples,
                        b_samples,
                    )
                judge_pairwise.append(pair_entry)

    summary["judge"] = {
        "dimensions": dimensions_sorted,
        "calibrated_dimensions": sorted(calibrated_set),
        "threshold": threshold,
        "groups": judge_groups,
        "pairwise": judge_pairwise,
        "note": (
            "Calibrated-judge verdicts only consider attempts that "
            "passed deterministically on BOTH sides of each pair "
            "(deterministic-first ordering — spec.md AC8). "
            "Uncalibrated dimensions never declare a winner."
        ),
    }


def _calibrated_judge_samples(
    a_rows: list[dict],
    b_rows: list[dict],
    dimension: str,
) -> tuple[list[float], list[float]]:
    """Build per-attempt judge-rating samples for the deterministic-first
    calibrated verdict.

    Only attempts that passed deterministically AND whose task was
    also passed by the OTHER side enter the sample. This is the AC8
    enforcement (deterministic-first ordering).
    """
    # Tasks passed on each side.
    a_passed_tasks = {
        r["score"]["task_id"]
        for r in a_rows if r["score"]["result"] == "pass"
    }
    b_passed_tasks = {
        r["score"]["task_id"]
        for r in b_rows if r["score"]["result"] == "pass"
    }
    common = a_passed_tasks & b_passed_tasks
    a_samples = _pull_judge_ratings(a_rows, dimension, common)
    b_samples = _pull_judge_ratings(b_rows, dimension, common)
    return a_samples, b_samples


def _pull_judge_ratings(
    rows: list[dict],
    dimension: str,
    task_filter: set[str],
) -> list[float]:
    out: list[float] = []
    for r in rows:
        if r["score"]["task_id"] not in task_filter:
            continue
        if r["score"]["result"] != "pass":
            continue
        jo = r.get("_judge")
        if not jo:
            continue
        entry = (jo.get("ratings") or {}).get(dimension)
        if not isinstance(entry, dict):
            continue
        val = entry.get("rating")
        # Same 1..5-band guard as _enrich_summary_with_judge:
        # out-of-band ratings (0, 6, 99) from a stale/hand-edited
        # judge.json must not contribute to calibrated-judge
        # winner-extension samples.
        if (
            isinstance(val, int)
            and not isinstance(val, bool)
            and 1 <= val <= 5
        ):
            out.append(float(val))
    return out


# ── HTML renderer (stdlib only, no JS) ────────────────────────────────


def _render_html(summary: Mapping[str, Any]) -> str:
    """Render an HTML report — deterministic block first, judge block
    second, verdicts third, with an explicit visual separator between
    deterministic and judge sections (AC5).

    Stdlib-only string assembly; no templating engine. Embeds the
    pass-rate SVG via ``<object>`` so the chart renders without JS.
    """
    out: list[str] = []
    out.append("<!doctype html>")
    out.append('<html><head><meta charset="utf-8">')
    out.append("<title>Benchmark report</title>")
    out.append("<style>")
    out.append("body{font:14px/1.5 -apple-system,system-ui,sans-serif;max-width:1100px;margin:2em auto;padding:0 1em;color:#222}")
    out.append("h1,h2,h3{font-weight:600}")
    out.append("table{border-collapse:collapse;margin:1em 0}")
    out.append("th,td{border:1px solid #ccc;padding:4px 8px;text-align:left}")
    out.append("th{background:#f5f5f5}")
    out.append("td.num{text-align:right;font-variant-numeric:tabular-nums}")
    out.append("hr.section{border:0;border-top:3px double #aaa;margin:2em 0}")
    out.append(".judge{background:#fafafa;padding:.5em 1em;border-left:4px solid #888}")
    out.append(".cal{color:#0a7;font-weight:600}")
    out.append(".uncal{color:#888;font-style:italic}")
    out.append("code{background:#f0f0f0;padding:1px 4px;border-radius:3px}")
    out.append("</style></head><body>")
    out.append("<h1>Benchmark report</h1>")
    out.append(f"<p>Total attempts recorded: <strong>{summary['run_count']}</strong></p>")

    # ── Deterministic block (AC5: first) ──
    out.append("<h2>Deterministic results</h2>")
    out.append('<object data="chart-pass-rate.svg" type="image/svg+xml" aria-label="Pass-rate bar chart per (backend, model)"></object>')
    out.append("<table>")
    out.append("<tr><th>Candidate</th><th>Backend</th><th>Model</th><th>Attempts</th><th>Passed</th><th>Pass-rate</th><th>Elapsed (mean &plusmn; stdev)</th></tr>")
    for label, g in summary["groups"].items():
        out.append(
            f"<tr><td><code>{_html_escape(label)}</code></td>"
            f"<td>{_html_escape(g['backend_id'])}</td>"
            f"<td>{_html_escape(g['model'] or '—')}</td>"
            f"<td class='num'>{g['total_attempts']}</td>"
            f"<td class='num'>{g['passed']}</td>"
            f"<td class='num'>{_fmt_pct(g['pass_rate'])}</td>"
            f"<td class='num'>{_fmt_num(g['elapsed_seconds_mean'])} &plusmn; {_fmt_num(g['elapsed_seconds_stdev'])}</td></tr>"
        )
    out.append("</table>")

    # ── Visual separator + judge block (AC5: second) ──
    if summary.get("judge"):
        out.append('<hr class="section">')
        out.append('<div class="judge">')
        out.append("<h2>Judge ratings (secondary signal)</h2>")
        out.append(
            "<p><em>Judge is secondary. Uncalibrated dimensions are "
            "shown for reviewer awareness but never declare a winner. "
            "Deterministic-first ordering enforced — see "
            "<code>summary.judge.note</code> in <code>report.json</code>.</em></p>"
        )
        threshold = summary["judge"].get("threshold")
        if threshold is not None:
            out.append(f"<p>Spearman threshold: <code>{threshold}</code></p>")
        cal_dims = set(summary["judge"]["calibrated_dimensions"])
        out.append("<table>")
        out.append("<tr><th>Candidate</th>")
        for dim in summary["judge"]["dimensions"]:
            badge = (
                f'<span class="cal">[calibrated]</span>'
                if dim in cal_dims
                else f'<span class="uncal">[uncalibrated]</span>'
            )
            out.append(f"<th>{_html_escape(dim)}<br>{badge}</th>")
        out.append("</tr>")
        for label, g in summary["judge"]["groups"].items():
            out.append(f"<tr><td><code>{_html_escape(label)}</code></td>")
            for dim in summary["judge"]["dimensions"]:
                pd = g["per_dimension"].get(dim) or {}
                mean = pd.get("mean")
                stdev = pd.get("stdev")
                n = pd.get("n", 0)
                if mean is None or n == 0:
                    out.append("<td class='num'>—</td>")
                else:
                    out.append(
                        f"<td class='num'>{_fmt_num(mean)} &plusmn; "
                        f"{_fmt_num(stdev)} <small>(n={n})</small></td>"
                    )
            out.append("</tr>")
        out.append("</table>")
        out.append('<object data="chart-judge-histogram.svg" type="image/svg+xml" aria-label="Judge rating distribution per dimension"></object>')
        out.append("</div>")

    # ── Verdicts (AC5: third) ──
    if summary["verdicts"]:
        out.append("<h2>Winner verdicts</h2>")
        out.append(
            "<p>Calibrated rule: "
            "<code>&Delta; &gt; 2&sigma; AND |&Delta;| &ge; threshold</code>."
            "</p>"
        )
        out.append("<h3>Deterministic verdicts</h3>")
        out.append("<table>")
        out.append("<tr><th>A</th><th>B</th><th>pass_rate</th><th>elapsed_seconds</th><th>failed_commands</th><th>human_interventions</th></tr>")
        for pair in summary["verdicts"]["pairwise"]:
            out.append(
                f"<tr><td><code>{_html_escape(pair['a'])}</code></td>"
                f"<td><code>{_html_escape(pair['b'])}</code></td>"
                f"<td>{_html_verdict_label(pair['pass_rate_verdict'], pair['a'], pair['b'])}</td>"
                f"<td>{_html_verdict_label(pair['elapsed_seconds_verdict'], pair['a'], pair['b'])}</td>"
                f"<td>{_html_verdict_label(pair['failed_commands_verdict'], pair['a'], pair['b'])}</td>"
                f"<td>{_html_verdict_label(pair['human_interventions_verdict'], pair['a'], pair['b'])}</td></tr>"
            )
        out.append("</table>")
        # Calibrated-judge verdicts (or D6 terminal-state paragraph)
        # surface when judge data is present — independently of
        # whether ``pairwise`` is populated, since pairwise is only
        # built when at least one dimension calibrated.
        if summary.get("judge"):
            cal_dims = summary["judge"]["calibrated_dimensions"]
            if not cal_dims:
                out.append("<h3>Calibrated-judge verdicts</h3>")
                out.append(
                    "<p><em>Zero calibrated dimensions — no "
                    "calibrated-judge verdicts to declare. Raw "
                    "ratings above remain advisory-only. This is "
                    "spec.md D6's zero-dimensions-calibrated "
                    "terminal state: a valid completed outcome of "
                    "the empirical research question, not a build "
                    "failure. Maintainer recovery options: revise "
                    "the rubric (new <code>rubric-default-vN.md</code>), "
                    "try a different judge model, or accept the "
                    "negative result as advisory-only.</em></p>"
                )
            elif summary["judge"].get("pairwise"):
                out.append("<h3>Calibrated-judge verdicts</h3>")
                out.append('<object data="chart-verdict-forest.svg" type="image/svg+xml" aria-label="A/B forest plot for all verdicts"></object>')
                out.append("<table>")
                out.append("<tr><th>A</th><th>B</th>")
                for dim in cal_dims:
                    out.append(f"<th>judge:{_html_escape(dim)}</th>")
                out.append("</tr>")
                for pair in summary["judge"]["pairwise"]:
                    out.append(
                        f"<tr><td><code>{_html_escape(pair['a'])}</code></td>"
                        f"<td><code>{_html_escape(pair['b'])}</code></td>"
                    )
                    for dim in cal_dims:
                        v = pair["calibrated_judge_verdicts"].get(dim, "directional")
                        out.append(f"<td>{_html_verdict_label(v, pair['a'], pair['b'])}</td>")
                    out.append("</tr>")
                out.append("</table>")

    out.append("</body></html>")
    return "\n".join(out) + "\n"


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _html_verdict_label(verdict: str, a: str, b: str) -> str:
    if verdict == "A":
        return f"<strong>{_html_escape(a)}</strong> wins"
    if verdict == "B":
        return f"<strong>{_html_escape(b)}</strong> wins"
    return "<em>directional</em>"


# ── CSV renderers ─────────────────────────────────────────────────────


def _render_csv_by_model(summary: Mapping[str, Any]) -> str:
    """Per-(backend, model) summary CSV — one row per group."""
    rows = ["label,backend_id,model,total_attempts,passed,pass_rate,elapsed_seconds_mean,elapsed_seconds_stdev"]
    for label, g in summary["groups"].items():
        rows.append(",".join([
            _csv_escape(label),
            _csv_escape(g["backend_id"]),
            _csv_escape(g["model"] or ""),
            str(g["total_attempts"]),
            str(g["passed"]),
            f"{g['pass_rate']:.6f}" if g.get("pass_rate") is not None else "",
            f"{g['elapsed_seconds_mean']:.6f}" if g.get("elapsed_seconds_mean") is not None else "",
            f"{g['elapsed_seconds_stdev']:.6f}" if g.get("elapsed_seconds_stdev") is not None else "",
        ]))
    return "\n".join(rows) + "\n"


def _render_csv_per_task(summary: Mapping[str, Any]) -> str:
    """Per-task × per-group CSV — one row per (task, group)."""
    rows = ["label,task_id,attempts,passed,pass_rate,elapsed_seconds_mean,elapsed_seconds_stdev"]
    for label, g in summary["groups"].items():
        for task_id, t in sorted(g.get("per_task", {}).items()):
            rows.append(",".join([
                _csv_escape(label),
                _csv_escape(task_id),
                str(t["attempts"]),
                str(t["passed"]),
                f"{t['pass_rate']:.6f}" if t.get("pass_rate") is not None else "",
                f"{t['elapsed_seconds_mean']:.6f}" if t.get("elapsed_seconds_mean") is not None else "",
                f"{t['elapsed_seconds_stdev']:.6f}" if t.get("elapsed_seconds_stdev") is not None else "",
            ]))
    return "\n".join(rows) + "\n"


def _csv_escape(s: str) -> str:
    """Minimal CSV escaping — wrap in quotes if commas/quotes/newlines."""
    if any(c in s for c in (",", '"', "\n", "\r")):
        return '"' + s.replace('"', '""') + '"'
    return s


# ── SVG renderers (pure-string, no matplotlib) ────────────────────────


def _render_svg_bar(summary: Mapping[str, Any]) -> str:
    """Pass-rate bar chart per (backend, model)."""
    groups = summary["groups"]
    if not groups:
        return _svg_empty("no groups to chart")
    labels = list(groups.keys())
    rates = [groups[k].get("pass_rate") or 0.0 for k in labels]
    bar_w = 60
    bar_gap = 20
    margin_l = 80
    margin_t = 40
    margin_b = 80
    chart_h = 200
    width = margin_l + len(labels) * (bar_w + bar_gap) + 20
    height = margin_t + chart_h + margin_b

    out: list[str] = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    out.append(f'<text x="{margin_l}" y="20" font-family="sans-serif" font-size="14" font-weight="600">Pass rate per (backend, model)</text>')
    # Y-axis ticks at 0%, 50%, 100%.
    for pct, tick in [(0.0, "0%"), (0.5, "50%"), (1.0, "100%")]:
        y = margin_t + chart_h - pct * chart_h
        out.append(f'<line x1="{margin_l}" y1="{y}" x2="{width - 10}" y2="{y}" stroke="#ddd"/>')
        out.append(f'<text x="{margin_l - 5}" y="{y + 4}" text-anchor="end" font-family="sans-serif" font-size="11">{tick}</text>')
    for i, (label, rate) in enumerate(zip(labels, rates)):
        x = margin_l + i * (bar_w + bar_gap)
        bar_h = rate * chart_h
        y = margin_t + chart_h - bar_h
        out.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="#4a7" stroke="#272"/>')
        # Label below bar (rotated for readability if many groups).
        text_x = x + bar_w / 2
        text_y = margin_t + chart_h + 15
        out.append(
            f'<text x="{text_x}" y="{text_y}" text-anchor="end" '
            f'transform="rotate(-30 {text_x} {text_y})" '
            f'font-family="sans-serif" font-size="11">{_html_escape(label)}</text>'
        )
        # Percentage label above bar.
        out.append(
            f'<text x="{text_x}" y="{y - 4}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="11">{rate*100:.0f}%</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _render_svg_histogram(summary: Mapping[str, Any]) -> str:
    """Per-dimension judge-rating histogram (across all groups)."""
    judge = summary.get("judge") or {}
    dims = judge.get("dimensions") or []
    if not dims:
        return _svg_empty("no judge dimensions")

    # Collect per-dimension rating counts (1..5).
    counts: dict[str, list[int]] = {d: [0, 0, 0, 0, 0] for d in dims}
    for label, g in judge.get("groups", {}).items():
        for d in dims:
            pd = g["per_dimension"].get(d) or {}
            n = pd.get("n", 0)
            mean = pd.get("mean")
            if mean is None or n == 0:
                continue
            # Without raw values we approximate by spreading n attempts
            # around the mean. Good enough for display; exact counts
            # would require re-iterating attempts. Simplest: place all
            # n at round(mean).
            bucket = max(1, min(5, round(mean)))
            counts[d][bucket - 1] += n

    cell_w = 30
    cell_h = 20
    margin_l = 140
    margin_t = 40
    width = margin_l + 5 * cell_w + 20
    height = margin_t + len(dims) * (cell_h + 10) + 40

    out: list[str] = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    out.append(f'<text x="20" y="20" font-family="sans-serif" font-size="14" font-weight="600">Judge rating distribution per dimension</text>')

    max_count = max(
        (max(counts[d]) for d in dims if max(counts[d]) > 0),
        default=1,
    )

    for di, d in enumerate(dims):
        y = margin_t + di * (cell_h + 10)
        out.append(f'<text x="{margin_l - 5}" y="{y + cell_h / 2 + 4}" text-anchor="end" font-family="sans-serif" font-size="11">{_html_escape(d)}</text>')
        for ri in range(5):
            x = margin_l + ri * cell_w
            c = counts[d][ri]
            intensity = c / max_count if max_count else 0
            shade = int(220 - intensity * 180)
            out.append(f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" fill="rgb({shade},{shade},{shade + 20 if shade + 20 < 255 else 255})" stroke="#888"/>')
            if c > 0:
                fg = "#fff" if intensity > 0.5 else "#222"
                out.append(f'<text x="{x + cell_w/2}" y="{y + cell_h/2 + 4}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="{fg}">{c}</text>')
    # X-axis legend (1..5).
    legend_y = margin_t + len(dims) * (cell_h + 10) + 14
    for ri in range(5):
        x = margin_l + ri * cell_w + cell_w / 2
        out.append(f'<text x="{x}" y="{legend_y}" text-anchor="middle" font-family="sans-serif" font-size="11">{ri+1}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _render_svg_forest(summary: Mapping[str, Any]) -> str:
    """A/B forest plot for verdict pairs."""
    out: list[str] = []
    deterministic_pairs = (summary.get("verdicts") or {}).get("pairwise", [])
    judge_pairs = ((summary.get("judge") or {}).get("pairwise")) or []
    rows: list[tuple[str, str, str, str]] = []  # (metric, a, b, verdict)
    for p in deterministic_pairs:
        for metric in ("pass_rate_verdict", "elapsed_seconds_verdict",
                       "failed_commands_verdict", "human_interventions_verdict"):
            rows.append((metric.replace("_verdict", ""), p["a"], p["b"], p[metric]))
    for p in judge_pairs:
        for dim, v in (p.get("calibrated_judge_verdicts") or {}).items():
            rows.append((f"judge:{dim}", p["a"], p["b"], v))

    if not rows:
        return _svg_empty("no verdicts to chart")

    row_h = 22
    margin_l = 220
    margin_t = 40
    chart_w = 300
    width = margin_l + chart_w + 200
    height = margin_t + len(rows) * row_h + 30

    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    out.append(f'<text x="20" y="20" font-family="sans-serif" font-size="14" font-weight="600">Verdict forest plot</text>')
    center = margin_l + chart_w / 2
    # Center vertical line (the "no winner" axis).
    out.append(f'<line x1="{center}" y1="{margin_t}" x2="{center}" y2="{margin_t + len(rows) * row_h}" stroke="#888" stroke-dasharray="3,3"/>')
    out.append(f'<text x="{margin_l}" y="{margin_t - 5}" font-family="sans-serif" font-size="11">A wins ←</text>')
    out.append(f'<text x="{margin_l + chart_w}" y="{margin_t - 5}" text-anchor="end" font-family="sans-serif" font-size="11">→ B wins</text>')

    for ri, (metric, a, b, verdict) in enumerate(rows):
        y = margin_t + ri * row_h + row_h / 2
        out.append(f'<text x="{margin_l - 5}" y="{y + 4}" text-anchor="end" font-family="sans-serif" font-size="11">{_html_escape(metric)}</text>')
        if verdict == "A":
            x = margin_l + chart_w / 4
            out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="#27a"/>')
            out.append(f'<text x="{margin_l + chart_w + 5}" y="{y + 4}" font-family="sans-serif" font-size="11">{_html_escape(a)}</text>')
        elif verdict == "B":
            x = margin_l + 3 * chart_w / 4
            out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="#27a"/>')
            out.append(f'<text x="{margin_l + chart_w + 5}" y="{y + 4}" font-family="sans-serif" font-size="11">{_html_escape(b)}</text>')
        else:
            out.append(f'<circle cx="{center}" cy="{y}" r="4" fill="#aaa"/>')
            out.append(f'<text x="{margin_l + chart_w + 5}" y="{y + 4}" font-family="sans-serif" font-size="11" fill="#888">directional</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _svg_empty(msg: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="60" viewBox="0 0 400 60">'
        f'<text x="20" y="35" font-family="sans-serif" font-size="12" fill="#888">{_html_escape(msg)}</text>'
        f'</svg>\n'
    )


# ── Markdown enhancement (judge section) ──────────────────────────────


def _render_markdown_judge_section(summary: Mapping[str, Any]) -> list[str]:
    """Append a judge section to the existing markdown, if judge data exists."""
    judge = summary.get("judge")
    if not judge:
        return []
    lines: list[str] = []
    lines.append("---")
    lines.append("")
    lines.append("## Judge ratings (secondary signal)")
    lines.append("")
    lines.append(
        "> Judge is secondary. Uncalibrated dimensions are shown for "
        "reviewer awareness but never declare a winner. "
        "Deterministic-first ordering enforced — see `summary.judge.note`."
    )
    lines.append("")
    threshold = judge.get("threshold")
    if threshold is not None:
        lines.append(f"Spearman threshold: `{threshold}`")
        lines.append("")
    cal_dims = set(judge["calibrated_dimensions"])
    header = ["Candidate"] + [
        f"{d} {'[calibrated]' if d in cal_dims else '[uncalibrated]'}"
        for d in judge["dimensions"]
    ]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for label, g in judge["groups"].items():
        row = [f"`{label}`"]
        for d in judge["dimensions"]:
            pd = g["per_dimension"].get(d) or {}
            n = pd.get("n", 0)
            mean = pd.get("mean")
            stdev = pd.get("stdev")
            if mean is None or n == 0:
                row.append("—")
            else:
                row.append(f"{_fmt_num(mean)} ± {_fmt_num(stdev)} (n={n})")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    # Calibrated-judge verdicts (or the D6 terminal-state paragraph
    # when none of the dimensions cleared the threshold). Surface
    # the paragraph independently of ``judge['pairwise']`` because
    # the pairwise list is only built when ``calibrated_dimensions``
    # is non-empty — without this surfacing-on-empty path the D6
    # report state was unreachable (the bug fixed here).
    cal_list = judge["calibrated_dimensions"]
    if not cal_list:
        lines.append("### Calibrated-judge verdicts")
        lines.append("")
        lines.append(
            "_Zero calibrated dimensions — no calibrated-judge "
            "verdicts to declare. Raw ratings above remain "
            "advisory-only. This is spec.md D6's "
            "zero-dimensions-calibrated terminal state: a valid "
            "completed outcome of the empirical research question, "
            "not a build failure. Maintainer recovery options: "
            "revise the rubric (new `rubric-default-vN.md`), try a "
            "different judge model, or accept the negative result "
            "as advisory-only._"
        )
        lines.append("")
    elif judge.get("pairwise"):
        lines.append("### Calibrated-judge verdicts")
        lines.append("")
        header = ["A", "B"] + [f"judge:{d}" for d in cal_list]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for pair in judge["pairwise"]:
            row = [f"`{pair['a']}`", f"`{pair['b']}`"]
            for d in cal_list:
                v = pair["calibrated_judge_verdicts"].get(d, "directional")
                row.append(_fmt_verdict_label(v, pair["a"], pair["b"]))
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    return lines
