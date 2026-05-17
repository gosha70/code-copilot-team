# benchmark_runner.report_winner — calibrated winner-declaration rule.
#
# Pure function, no side effects. Lives in its own module so the rule
# is grep-able as one unit and the tests can be exhaustive without
# entangling them with report-rendering tests.
#
# Rule (per specs/benchmark-harness/spec.md § "Winner-declaration rule"):
#
#   declare_winner(metric, A, B) iff:
#     (mean_A − mean_B) > 2 × max(σ_A, σ_B)   AND
#     abs(delta) ≥ 1 deterministic point  OR  abs(delta) ≥ 10% on continuous metrics
#
# Otherwise the rule abstains: returns ``directional``.
#
# Two metric kinds:
#   - "deterministic": pass counts, file counts, scores. Threshold is
#     an absolute number of points (default 1.0). E.g. pass-rate
#     differences below 1 percentage point are considered noise.
#   - "continuous": elapsed_seconds, tokens, etc. Threshold is a
#     relative fraction (default 0.10 = 10%) of the smaller of the
#     two means.
#
# Direction:
#   - higher_is_better=True (default): A wins iff its mean is higher.
#   - higher_is_better=False: A wins iff its mean is LOWER (e.g.
#     elapsed_seconds — faster is better).
#
# Single-run fallback:
#   - If either side has fewer than ``min_samples_for_winner``
#     samples (default 2), the rule returns ``directional`` because
#     a single observation can't establish significance. This stays
#     consistent with the report's null-vs-zero discipline elsewhere.

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Literal, Optional, Sequence


MetricKind = Literal["deterministic", "continuous"]
Verdict = Literal["A", "B", "directional"]


@dataclass(frozen=True)
class MetricSpec:
    """Description of a metric being compared.

    The kind determines the threshold logic; the direction determines
    which side ``A`` represents when interpreting the verdict.
    """

    name: str
    kind: MetricKind
    higher_is_better: bool = True
    deterministic_threshold: float = 1.0
    continuous_threshold_relative: float = 0.10
    min_samples_for_winner: int = 2


def declare_winner(
    metric: MetricSpec,
    samples_a: Sequence[Optional[float]],
    samples_b: Sequence[Optional[float]],
) -> Verdict:
    """Return ``"A"`` / ``"B"`` / ``"directional"`` per the calibrated rule.

    None values in either input are filtered out before computation
    (preserves the null-vs-zero discipline — runs that didn't produce
    a value don't get coerced to 0).
    """
    a = [x for x in samples_a if x is not None]
    b = [x for x in samples_b if x is not None]

    if len(a) < metric.min_samples_for_winner:
        return "directional"
    if len(b) < metric.min_samples_for_winner:
        return "directional"

    mean_a = statistics.fmean(a)
    mean_b = statistics.fmean(b)
    stdev_a = statistics.stdev(a) if len(a) > 1 else 0.0
    stdev_b = statistics.stdev(b) if len(b) > 1 else 0.0

    delta = mean_a - mean_b  # positive: A's mean is higher
    abs_delta = abs(delta)
    max_stdev = max(stdev_a, stdev_b)

    # Significance gate: delta must clear 2 * max(σ_A, σ_B).
    # When both stdevs are 0 (constant samples), this gate is trivially
    # passed by any non-zero delta, which is fine — we still apply the
    # threshold gate below.
    if abs_delta <= 2 * max_stdev:
        return "directional"

    # Threshold gate.
    if metric.kind == "deterministic":
        threshold = metric.deterministic_threshold
    else:
        # Relative to the smaller of the two means (so a 10% delta on
        # a small base is the same significance as 10% on a large
        # base). Falls back to abs(mean_a) when mean_b is 0.
        base = min(abs(mean_a), abs(mean_b))
        if base == 0:
            base = max(abs(mean_a), abs(mean_b)) or 1.0
        threshold = metric.continuous_threshold_relative * base

    if abs_delta < threshold:
        return "directional"

    # Direction. ``a_higher`` means A's mean is numerically larger than
    # B's. If higher_is_better, A wins; if lower_is_better, B wins.
    a_higher = delta > 0
    a_better = a_higher == metric.higher_is_better
    return "A" if a_better else "B"


def deferred_directional_note() -> str:
    """Used by the report skeleton when there's nothing to compare yet."""
    return (
        "directional, no winner declared "
        "(rule abstained — see report_winner.py)"
    )
