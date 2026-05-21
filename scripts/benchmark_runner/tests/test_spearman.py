# tests/test_spearman.py — Spearman ρ + helpers (stdlib-only).
#
# Golden vectors come from two sources so a regression has to fail
# both before slipping through:
#   1. Wikipedia "Spearman's rank correlation coefficient" worked
#      example (IQ vs TV-hours, n=10, no ties).
#   2. Hand-computed three-point examples (perfect ±1, single-tie
#      case where the rank averaging is the only thing the test
#      can be measuring).

from __future__ import annotations

import math
import unittest

from benchmark_runner.calibration.spearman import (
    exact_match_rate,
    rank_average_ties,
    spearman,
)


# ── rank_average_ties ─────────────────────────────────────────────────


class TestRankAverageTies(unittest.TestCase):
    def test_strictly_ascending(self) -> None:
        self.assertEqual(rank_average_ties([10, 20, 30, 40]), [1.0, 2.0, 3.0, 4.0])

    def test_strictly_descending(self) -> None:
        # The HIGHEST-value element ranks last (rank 4); the LOWEST
        # ranks first (rank 1). Order in the input is preserved in
        # the output, which means ranks come out reversed.
        self.assertEqual(rank_average_ties([40, 30, 20, 10]), [4.0, 3.0, 2.0, 1.0])

    def test_pair_of_ties(self) -> None:
        # Two 20s share ranks 2 and 3 → both get the average 2.5.
        self.assertEqual(rank_average_ties([10, 20, 20, 30]), [1.0, 2.5, 2.5, 4.0])

    def test_triple_tie(self) -> None:
        # Three 20s share ranks 2, 3, 4 → each gets the average 3.0.
        self.assertEqual(
            rank_average_ties([10, 20, 20, 20, 50]),
            [1.0, 3.0, 3.0, 3.0, 5.0],
        )

    def test_all_tied(self) -> None:
        # All four elements share ranks 1..4 → each gets 2.5.
        # ``spearman`` later rejects all-tied inputs as undefined,
        # but the rank helper itself is well-defined here.
        self.assertEqual(rank_average_ties([7, 7, 7, 7]), [2.5, 2.5, 2.5, 2.5])

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(rank_average_ties([]), [])

    def test_single_element_rank_is_one(self) -> None:
        self.assertEqual(rank_average_ties([42.0]), [1.0])

    def test_does_not_mutate_input(self) -> None:
        xs = [3, 1, 2]
        _ = rank_average_ties(xs)
        self.assertEqual(xs, [3, 1, 2])


# ── spearman: hand-computed and published vectors ─────────────────────


class TestSpearman(unittest.TestCase):
    def test_perfect_positive_correlation(self) -> None:
        # Strict monotonic increase → ρ = 1.0 exactly.
        self.assertEqual(spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]), 1.0)

    def test_perfect_negative_correlation(self) -> None:
        # Strict monotonic decrease → ρ = -1.0 exactly.
        self.assertEqual(spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]), -1.0)

    def test_two_point_correlation(self) -> None:
        # n=2 is the smallest allowed case. With distinct values on
        # both sides, ρ is either +1.0 or -1.0.
        self.assertEqual(spearman([1, 2], [10, 20]), 1.0)
        self.assertEqual(spearman([1, 2], [20, 10]), -1.0)

    def test_wikipedia_iq_tv_example(self) -> None:
        # From en.wikipedia.org/wiki/Spearman%27s_rank_correlation_coefficient
        # IQ vs TV-hours/week worked example (n=10, no ties in either
        # vector). Expected ρ = -0.17575757575757575.
        iq = [86, 97, 99, 100, 101, 103, 106, 110, 112, 113]
        tv = [0, 20, 28, 27, 50, 29, 7, 17, 6, 12]
        expected = 1 - 6 * 194 / (10 * (100 - 1))  # -0.175757575...
        self.assertAlmostEqual(spearman(iq, tv), expected, places=12)

    def test_single_pair_tie_hand_computed(self) -> None:
        # xs=[1,2,3], ys=[10,20,20].
        # rx = [1, 2, 3]; ry = [1, 2.5, 2.5].
        # cov = 1.5, var_x = 2, var_y = 1.5; denom = sqrt(3).
        # ρ = 1.5/sqrt(3) = sqrt(3)/2 ≈ 0.8660254037844386.
        self.assertAlmostEqual(
            spearman([1, 2, 3], [10, 20, 20]),
            math.sqrt(3) / 2,
            places=12,
        )

    def test_ties_on_both_sides_hand_computed(self) -> None:
        # xs=[1,1,2,3], ys=[10,20,20,30].
        # rx = [1.5, 1.5, 3.0, 4.0]; ry = [1.0, 2.5, 2.5, 4.0].
        # mean_x = 2.5, mean_y = 2.5.
        # dx = [-1.0, -1.0, 0.5, 1.5]; dy = [-1.5, 0.0, 0.0, 1.5].
        # cov = 1.5 + 0 + 0 + 2.25 = 3.75.
        # var_x = 1.0 + 1.0 + 0.25 + 2.25 = 4.5.
        # var_y = 2.25 + 0 + 0 + 2.25 = 4.5.
        # denom = sqrt(4.5 * 4.5) = 4.5.
        # ρ = 3.75 / 4.5 = 0.8333333...
        self.assertAlmostEqual(
            spearman([1, 1, 2, 3], [10, 20, 20, 30]),
            3.75 / 4.5,
            places=12,
        )

    def test_result_clamped_to_unit_interval(self) -> None:
        # Sanity invariant of Spearman: result must be in [-1, 1].
        for xs, ys in (
            ([1, 2, 3], [3, 2, 1]),
            ([1, 2, 3, 4], [4, 1, 3, 2]),
            ([5, 3, 7, 1, 9], [2, 8, 4, 6, 0]),
        ):
            r = spearman(xs, ys)
            self.assertGreaterEqual(r, -1.0, msg=f"out of range for {xs}, {ys}")
            self.assertLessEqual(r, 1.0, msg=f"out of range for {xs}, {ys}")


# ── spearman: error paths ─────────────────────────────────────────────


class TestSpearmanErrors(unittest.TestCase):
    def test_mismatched_lengths_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "parallel"):
            spearman([1, 2, 3], [10, 20])

    def test_empty_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 2"):
            spearman([], [])

    def test_single_pair_raises(self) -> None:
        # n=1 has undefined variance; ρ is meaningless. Surface as
        # an error rather than NaN — calibration callers want to
        # treat "too few points" as "no signal," not as 0.0.
        with self.assertRaisesRegex(ValueError, "at least 2"):
            spearman([7.0], [42.0])

    def test_all_xs_equal_raises(self) -> None:
        # Zero variation on one side → undefined. The judge-side
        # equivalent is "judge gave every attempt the same rating";
        # the human-side equivalent is "reviewer gave every attempt
        # the same rating." Either way, no signal — must surface.
        with self.assertRaisesRegex(ValueError, "no variation"):
            spearman([5, 5, 5, 5], [1, 2, 3, 4])

    def test_all_ys_equal_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "no variation"):
            spearman([1, 2, 3, 4], [5, 5, 5, 5])

    def test_both_constant_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "no variation"):
            spearman([3, 3, 3], [4, 4, 4])


# ── exact_match_rate ──────────────────────────────────────────────────


class TestExactMatchRate(unittest.TestCase):
    def test_all_match(self) -> None:
        self.assertEqual(exact_match_rate([1, 2, 3], [1, 2, 3]), 1.0)

    def test_none_match(self) -> None:
        self.assertEqual(exact_match_rate([1, 2, 3], [4, 5, 6]), 0.0)

    def test_partial_match(self) -> None:
        # 2/4 match → 0.5.
        self.assertEqual(exact_match_rate([1, 2, 3, 4], [1, 9, 3, 9]), 0.5)

    def test_float_equality(self) -> None:
        # Both sides come from the calibration step as int ratings
        # 1..5, but the helper accepts floats too. Exact equality
        # is fine for our use (ratings are integers).
        self.assertEqual(exact_match_rate([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0)

    def test_single_pair(self) -> None:
        # n=1 is allowed for exact_match_rate (no variance needed).
        self.assertEqual(exact_match_rate([5], [5]), 1.0)
        self.assertEqual(exact_match_rate([5], [4]), 0.0)

    def test_mismatched_lengths_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "parallel"):
            exact_match_rate([1, 2], [1, 2, 3])

    def test_empty_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty"):
            exact_match_rate([], [])


if __name__ == "__main__":
    unittest.main()
