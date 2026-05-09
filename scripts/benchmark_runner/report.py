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


def render_report(run_dir: Path) -> Path:
    """Aggregate ``run_dir`` into report.md + report.json.

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

    summary = _summarize(attempts)

    report_md_path = run_dir / "report.md"
    report_json_path = run_dir / "report.json"

    report_md_path.write_text(_render_markdown(summary), encoding="utf-8")
    report_json_path.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
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
        out.append({"score": score, "run_record": run_record})
    return out


def _group_key(attempt: dict) -> tuple[str, str]:
    backend_id = attempt["score"]["backend_id"]
    model = (
        attempt["run_record"].get("backend_invocation", {}).get("model", "")
        or attempt["score"].get("model", "")
        or ""
    )
    return backend_id, model


def _provider_endpoint_for(attempt: dict) -> str | None:
    return (
        attempt["run_record"]
        .get("backend", {})
        .get("metadata", {})
        .get("provider_endpoint")
    )


REPORT_SCHEMA_VERSION = "1"
"""Bumped on any breaking change to the report JSON shape.

Consumers of report.json (the dogfood subcommand internally; future
external tools) should branch on this value rather than the absence
or presence of fields. Phase 4a introduces the v1 shape (top-level
``groups`` and ``verdicts``); a v2 bump would happen if those keys
moved or got renamed.
"""


def _summarize(attempts: list[dict]) -> dict[str, Any]:
    by_group: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for a in attempts:
        by_group[_group_key(a)].append(a)

    groups: dict[str, dict[str, Any]] = {}
    for (backend_id, model), rows in by_group.items():
        groups[_label(backend_id, model)] = _group_summary(backend_id, model, rows)

    verdicts = _verdicts_across_groups(by_group) if len(by_group) >= 2 else None

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_count": len(attempts),
        "groups": groups,
        "verdicts": verdicts,
    }


def _label(backend_id: str, model: str) -> str:
    return f"{backend_id}:{model}" if model else backend_id


def _group_summary(
    backend_id: str, model: str, rows: list[dict]
) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for r in rows if r["score"]["result"] == "pass")
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
        "total_attempts": total,
        "passed": passed,
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
    by_group: Mapping[tuple[str, str], list[dict]],
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
        lines.append(
            f"- Total attempts: {g['total_attempts']}  "
            f"\n- Passed: {g['passed']}  "
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
