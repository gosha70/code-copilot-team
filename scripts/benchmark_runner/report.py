# benchmark_runner.report — Phase 1 report skeleton.
#
# Aggregates a run directory into report.md + report.json. Per-task
# pass/fail and per-backend totals; mean/stdev across runs where the
# data permits.
#
# The winner-declaration rule from spec.md § "Winner-declaration rule"
# is *not* yet active — Phase 1 emits "directional, no winner declared"
# whenever two backends are present, regardless of the deltas. Phase 4
# replaces this with the unit-tested pure function that enforces the
# (Δ > 2σ AND ≥ threshold) gate.

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping


WINNER_DEFERRED_NOTE = (
    "directional, no winner declared (Phase 1 reporter; the calibrated "
    "winner-declaration rule lands in Phase 4)"
)


def render_report(run_dir: Path) -> Path:
    """Aggregate ``run_dir`` into report.md + report.json.

    Returns the path to ``report.md``. Raises ``FileNotFoundError`` if
    the run-dir doesn't exist or contains no score files.
    """
    if not run_dir.exists():
        raise FileNotFoundError(f"run-dir not found: {run_dir}")

    scores = _load_scores(run_dir)
    if not scores:
        raise FileNotFoundError(
            f"no score.json files found under {run_dir}; nothing to report"
        )

    summary = _summarize(scores)

    report_md_path = run_dir / "report.md"
    report_json_path = run_dir / "report.json"

    report_md_path.write_text(_render_markdown(summary), encoding="utf-8")
    report_json_path.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return report_md_path


# ── Loading + aggregation ──────────────────────────────────────────────


def _load_scores(run_dir: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(run_dir.rglob("score.json")):
        with path.open(encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def _summarize(scores: list[dict]) -> dict[str, Any]:
    by_backend: dict[str, list[dict]] = defaultdict(list)
    for s in scores:
        by_backend[s["backend_id"]].append(s)

    backends = {}
    for backend_id, rows in by_backend.items():
        backends[backend_id] = _backend_summary(rows)

    winner_verdict: str | None = None
    if len(by_backend) >= 2:
        winner_verdict = WINNER_DEFERRED_NOTE

    return {
        "run_count": len(scores),
        "backends": backends,
        "winner_verdict": winner_verdict,
    }


def _backend_summary(rows: list[dict]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for r in rows if r["result"] == "pass")
    elapsed_values = [r["derived"]["elapsed_seconds"] for r in rows]

    return {
        "total_attempts": total,
        "passed": passed,
        "pass_rate": _safe_div(passed, total),
        "elapsed_seconds_mean": _mean(elapsed_values),
        "elapsed_seconds_stdev": _stdev(elapsed_values),
        "per_task": _per_task(rows),
    }


def _per_task(rows: list[dict]) -> dict[str, Any]:
    by_task: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_task[r["task_id"]].append(r)

    out: dict[str, Any] = {}
    for task_id, attempts in by_task.items():
        total = len(attempts)
        passed = sum(1 for a in attempts if a["result"] == "pass")
        elapsed_values = [a["derived"]["elapsed_seconds"] for a in attempts]
        out[task_id] = {
            "attempts": total,
            "passed": passed,
            "pass_rate": _safe_div(passed, total),
            "elapsed_seconds_mean": _mean(elapsed_values),
            "elapsed_seconds_stdev": _stdev(elapsed_values),
        }
    return out


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

    for backend_id, b in summary["backends"].items():
        lines.append(f"## Backend `{backend_id}`")
        lines.append("")
        lines.append(
            f"- Total attempts: {b['total_attempts']}  "
            f"\n- Passed: {b['passed']}  "
            f"\n- Pass rate: {_fmt_pct(b['pass_rate'])}  "
            f"\n- Elapsed (s): mean {_fmt_num(b['elapsed_seconds_mean'])}, "
            f"stdev {_fmt_num(b['elapsed_seconds_stdev'])}"
        )
        lines.append("")

        if b["per_task"]:
            lines.append("### Per-task")
            lines.append("")
            lines.append("| task | attempts | passed | pass-rate | elapsed (mean ± stdev) |")
            lines.append("| --- | --- | --- | --- | --- |")
            for task_id, t in sorted(b["per_task"].items()):
                lines.append(
                    f"| `{task_id}` | {t['attempts']} | {t['passed']} | "
                    f"{_fmt_pct(t['pass_rate'])} | "
                    f"{_fmt_num(t['elapsed_seconds_mean'])} ± "
                    f"{_fmt_num(t['elapsed_seconds_stdev'])} |"
                )
            lines.append("")

    if summary["winner_verdict"]:
        lines.append("## Winner verdict")
        lines.append("")
        lines.append(f"_{summary['winner_verdict']}_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


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
