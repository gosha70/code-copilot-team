# benchmark_runner.report — report aggregation (Phase 0/1 stub).
#
# Phase 1 implements a minimal aggregator (per-task pass/fail, mean/stdev
# placeholders). Phase 4 implements the full winner-declaration rule and
# A/B comparison output.

from __future__ import annotations

from pathlib import Path


def render_report(run_dir: Path) -> Path:
    """Phase 1+: aggregate ``run_dir`` into report.md + report.json.

    Returns the path to ``report.md``. Phase 0 raises NotImplementedError.
    """
    raise NotImplementedError(
        "report aggregation lands in Phase 1 (see specs/benchmark-harness/plan.md)"
    )
