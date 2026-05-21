# benchmark_runner.calibration.spearman — stdlib-only Spearman ρ.
#
# Spearman's rank correlation coefficient: Pearson correlation
# computed on the RANKS of the values rather than the values
# themselves. Captures monotonic agreement (not just linear) — the
# right metric for "does the judge order attempts the same way a
# human reviewer does," which is what the calibration step measures.
#
# Tie handling: average rank (a.k.a. "fractional rank"). When two
# values tie, both receive the average of the ranks they'd occupy
# under a stable arbitrary tiebreak. This is the standard variant
# scipy.stats.spearmanr uses; matches the published vectors the
# golden-numbers test pins against.
#
# Why stdlib-only: the harness already has a no-new-Python-dependency
# posture (see benchmark_runner.report's existing stdlib stats use).
# Spearman on N ≤ a few hundred labels is trivial without scipy.
#
# Pure function, no I/O. Exposed entry points: ``spearman``,
# ``exact_match_rate``, ``rank_average_ties``.

from __future__ import annotations

import math
from typing import Sequence


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Return Spearman's ρ for two parallel sequences.

    Raises ``ValueError`` if the sequences have different lengths,
    if either is empty, or if either has fewer than two distinct
    values (ρ is undefined when all ranks tie — the "no variation"
    degenerate case).

    Returns a float in ``[-1.0, 1.0]``. ``1.0`` is perfect
    monotonic agreement; ``-1.0`` is perfect monotonic disagreement;
    ``0.0`` is no monotonic relationship.
    """
    if len(xs) != len(ys):
        raise ValueError(
            f"spearman: sequences must be parallel; "
            f"got len(xs)={len(xs)}, len(ys)={len(ys)}"
        )
    n = len(xs)
    if n < 2:
        raise ValueError(
            f"spearman: need at least 2 paired observations; got {n}"
        )

    rx = rank_average_ties(xs)
    ry = rank_average_ties(ys)

    # If either side has zero variation (all ranks identical),
    # Spearman is undefined (division by zero on the Pearson
    # denominator). The calibration step treats "no variation" as
    # "judge didn't differentiate" or "human didn't differentiate"
    # — both produce no useful correlation signal and must be
    # surfaced as such, not silently coerced to 0.0.
    if _all_equal(rx) or _all_equal(ry):
        raise ValueError(
            "spearman: undefined when either sequence has no variation "
            "(all ranks identical). Caller should treat as 'no signal' "
            "and exclude this dimension from calibration."
        )

    return _pearson(rx, ry)


def rank_average_ties(xs: Sequence[float]) -> list[float]:
    """Return the rank of each element of ``xs`` (smallest = rank 1).

    Ties receive the average of the ranks they'd occupy under any
    stable tiebreak. E.g. ``rank_average_ties([10, 20, 20, 30])`` →
    ``[1.0, 2.5, 2.5, 4.0]`` (the two 20s share ranks 2 and 3, so
    each gets the average 2.5).

    Pure function. Returns a NEW list; input is not mutated.
    """
    n = len(xs)
    # Build (value, original_index) and sort by value; stable sort
    # preserves original order within ties so the tie-averaging
    # below sees groups as contiguous runs.
    indexed = sorted(range(n), key=lambda i: xs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        # Find the end of a run of equal values starting at i.
        j = i
        while j + 1 < n and xs[indexed[j + 1]] == xs[indexed[i]]:
            j += 1
        # Ranks i+1, i+2, ..., j+1 (1-indexed); average them.
        avg_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def exact_match_rate(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Return the fraction of paired observations where xs[i] == ys[i].

    Calibration uses this alongside Spearman ρ as a sanity check:
    high ρ + low exact-match means the judge ranks consistently
    with the human but on a shifted scale; low ρ + high exact-match
    is statistically impossible (would imply matches without
    monotonic agreement) and indicates a parser/join bug.

    Raises ``ValueError`` on mismatched / empty inputs.
    """
    if len(xs) != len(ys):
        raise ValueError(
            f"exact_match_rate: sequences must be parallel; "
            f"got len(xs)={len(xs)}, len(ys)={len(ys)}"
        )
    n = len(xs)
    if n == 0:
        raise ValueError("exact_match_rate: empty input")
    matches = sum(1 for a, b in zip(xs, ys) if a == b)
    return matches / n


# ── Internals ─────────────────────────────────────────────────────────


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation on two parallel sequences.

    Assumes len(xs) == len(ys) >= 2 and neither side is constant
    (callers — only ``spearman`` here — guarantee this).
    """
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        dy = y - mean_y
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy
    denom = math.sqrt(var_x * var_y)
    # Defensive: if the caller bypassed the _all_equal guard, surface
    # the divide-by-zero as a clear error rather than producing nan.
    if denom == 0:
        raise ValueError(
            "_pearson: zero variance in one or both sequences "
            "(divide-by-zero); spearman's _all_equal guard should "
            "have caught this — programmer error"
        )
    return cov / denom


def _all_equal(xs: Sequence[float]) -> bool:
    if not xs:
        return True
    first = xs[0]
    for x in xs[1:]:
        if x != first:
            return False
    return True
