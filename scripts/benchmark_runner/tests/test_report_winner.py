# tests/test_report_winner.py — calibrated winner-declaration rule.
#
# Pure-function tests against synthetic A/B distributions. The cases
# below cover the corners specified in tasks.md T4.1's done-when:
# clear winners each direction, tied means, high-variance no-winner,
# low-variance just-below / just-above the deterministic threshold,
# continuous-metric exactly-at the 10% boundary, single-run fallback.
# Plus extras for direction-inversion (lower-is-better metrics) and
# null filtering.

from __future__ import annotations

import unittest

from benchmark_runner.report_winner import (
    MetricSpec,
    declare_winner,
)


# Common metric specs reused across cases.
PASS_COUNT = MetricSpec(
    name="passed",
    kind="deterministic",
    higher_is_better=True,
    deterministic_threshold=1.0,
)

ELAPSED_SECONDS = MetricSpec(
    name="elapsed_seconds",
    kind="continuous",
    higher_is_better=False,  # faster is better
    continuous_threshold_relative=0.10,
)


class TestClearWinners(unittest.TestCase):
    def test_clear_a_win_deterministic_higher_better(self) -> None:
        # A=10,10,10 vs B=8,8,8 → delta=2, threshold=1, max_stdev=0,
        # higher is better → A wins.
        v = declare_winner(PASS_COUNT, [10, 10, 10], [8, 8, 8])
        self.assertEqual(v, "A")

    def test_clear_b_win_deterministic_higher_better(self) -> None:
        v = declare_winner(PASS_COUNT, [5, 5, 5], [8, 8, 8])
        self.assertEqual(v, "B")


class TestTiesAndNoise(unittest.TestCase):
    def test_tied_means_returns_directional(self) -> None:
        v = declare_winner(PASS_COUNT, [5, 5, 5], [5, 5, 5])
        self.assertEqual(v, "directional")

    def test_high_variance_swallows_signal(self) -> None:
        # Means: A=10, B=8. Delta=2. But A has stdev=5, B has stdev=4.
        # 2 * max_stdev = 10 ≥ |delta|=2 → directional (significance
        # gate fails, regardless of threshold).
        v = declare_winner(
            PASS_COUNT, [5, 10, 15], [4, 8, 12]
        )
        self.assertEqual(v, "directional")


class TestThresholdBoundaries(unittest.TestCase):
    def test_deterministic_just_below_threshold(self) -> None:
        # Delta=0.5, threshold=1.0, low stdev → fails threshold gate,
        # returns directional.
        v = declare_winner(
            PASS_COUNT, [1.5, 1.5, 1.5], [1.0, 1.0, 1.0]
        )
        self.assertEqual(v, "directional")

    def test_deterministic_just_above_threshold(self) -> None:
        # Delta=1.5, threshold=1.0, low stdev (zero) → passes both
        # gates, A wins.
        v = declare_winner(
            PASS_COUNT, [2.5, 2.5, 2.5], [1.0, 1.0, 1.0]
        )
        self.assertEqual(v, "A")

    def test_continuous_at_10pct_boundary_lower_is_better(self) -> None:
        # ELAPSED_SECONDS — lower is better. A=100s vs B=90s, delta=10,
        # base=90, threshold=9. abs_delta=10 > 9, max_stdev=0 → passes
        # both gates. delta=+10 means A's mean is HIGHER (slower) →
        # since lower is better, B wins.
        v = declare_winner(
            ELAPSED_SECONDS, [100, 100, 100], [90, 90, 90]
        )
        self.assertEqual(v, "B")

    def test_continuous_just_below_10pct(self) -> None:
        # Same shape but A=98 — only 8.9% slower. Below 10% threshold
        # → directional.
        v = declare_winner(
            ELAPSED_SECONDS, [98, 98, 98], [90, 90, 90]
        )
        self.assertEqual(v, "directional")


class TestSingleRunFallback(unittest.TestCase):
    def test_single_sample_each_side_returns_directional(self) -> None:
        # min_samples_for_winner = 2 by default — n=1 cannot establish
        # significance. Even if delta is "huge" by the deterministic
        # threshold rule, return directional.
        v = declare_winner(PASS_COUNT, [10], [5])
        self.assertEqual(v, "directional")

    def test_single_sample_a_directional(self) -> None:
        # Asymmetric case — A has 1 sample, B has 3. A's stdev can't
        # be computed; we abstain.
        v = declare_winner(PASS_COUNT, [10], [5, 5, 5])
        self.assertEqual(v, "directional")

    def test_relaxed_min_samples_allows_n_equal_1(self) -> None:
        # When the caller explicitly relaxes the minimum to 1, n=1 is
        # accepted and the threshold rule applies. With deterministic
        # threshold=1.0 and stdev=0 (single sample), delta=5 > 1 → A.
        relaxed = MetricSpec(
            name="passed",
            kind="deterministic",
            higher_is_better=True,
            deterministic_threshold=1.0,
            min_samples_for_winner=1,
        )
        v = declare_winner(relaxed, [10], [5])
        self.assertEqual(v, "A")


class TestNullFiltering(unittest.TestCase):
    def test_none_values_are_filtered_before_computation(self) -> None:
        # The runner records null when a backend doesn't report a
        # token-count; the report shouldn't fabricate. Filter Nones,
        # then compute on what remains.
        v = declare_winner(
            PASS_COUNT, [10, None, 10, 10], [8, 8, None, 8]
        )
        # Effective inputs: [10,10,10] vs [8,8,8] → A wins (clear).
        self.assertEqual(v, "A")

    def test_all_none_one_side_returns_directional(self) -> None:
        v = declare_winner(PASS_COUNT, [None, None, None], [5, 5, 5])
        self.assertEqual(v, "directional")


class TestEmptyInputs(unittest.TestCase):
    def test_empty_a_returns_directional(self) -> None:
        v = declare_winner(PASS_COUNT, [], [5, 5, 5])
        self.assertEqual(v, "directional")

    def test_both_empty_returns_directional(self) -> None:
        v = declare_winner(PASS_COUNT, [], [])
        self.assertEqual(v, "directional")


class TestDirectionInversion(unittest.TestCase):
    def test_lower_is_better_a_higher_means_b_wins(self) -> None:
        # ELAPSED_SECONDS — lower is better. A=200, B=100. Both
        # significance and threshold gates clearly pass. delta=+100
        # means A is slower → B wins.
        v = declare_winner(
            ELAPSED_SECONDS, [200, 200, 200], [100, 100, 100]
        )
        self.assertEqual(v, "B")

    def test_higher_is_better_a_higher_means_a_wins(self) -> None:
        # Sanity check the inversion logic isn't inverted by accident.
        v = declare_winner(
            PASS_COUNT, [200, 200, 200], [100, 100, 100]
        )
        self.assertEqual(v, "A")


if __name__ == "__main__":
    unittest.main()
