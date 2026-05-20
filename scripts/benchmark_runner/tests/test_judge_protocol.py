# tests/test_judge_protocol.py — Judge protocol + dataclass shape tests.
#
# Mirrors test_contracts.py for the backend contracts: frozen-ness,
# null defaults, runtime_checkable conformance. No live LLM; no
# fake-CLI shim either — this module covers the dataclass + Protocol
# surface only. The fake-CLI suite for the claude_code judge lives
# in test_claude_code_judge.py (TB1.2).

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from benchmark_runner.judge.contracts import (
    JUDGE_RATING_MAX,
    JUDGE_RATING_MIN,
    SEED_CONTROL_AVAILABLE_NOT_PINNED,
    SEED_CONTROL_SUPPORTED,
    SEED_CONTROL_UNSUPPORTED,
    TEMPERATURE_CONTROL_AVAILABLE_NOT_PINNED,
    TEMPERATURE_CONTROL_SUPPORTED,
    TEMPERATURE_CONTROL_UNSUPPORTED,
    DimensionRating,
    Judge,
    JudgeInput,
    JudgeInvocation,
    JudgeResult,
    RubricSpec,
)


# ── Module constants ───────────────────────────────────────────────────


class TestRatingBounds(unittest.TestCase):
    def test_rating_bounds_are_inclusive_and_sane(self) -> None:
        self.assertEqual(JUDGE_RATING_MIN, 1)
        self.assertEqual(JUDGE_RATING_MAX, 5)
        self.assertLess(JUDGE_RATING_MIN, JUDGE_RATING_MAX)


class TestControlSentinels(unittest.TestCase):
    def test_temperature_control_sentinels_distinct(self) -> None:
        # The three sentinels must be distinct strings so the report
        # can tell "knob doesn't exist" apart from "knob exists,
        # judge chose not to pin" apart from "pinned to recorded
        # value." A future schema migration would notice if any two
        # collided.
        sentinels = {
            TEMPERATURE_CONTROL_SUPPORTED,
            TEMPERATURE_CONTROL_UNSUPPORTED,
            TEMPERATURE_CONTROL_AVAILABLE_NOT_PINNED,
        }
        self.assertEqual(len(sentinels), 3)

    def test_seed_control_sentinels_distinct(self) -> None:
        sentinels = {
            SEED_CONTROL_SUPPORTED,
            SEED_CONTROL_UNSUPPORTED,
            SEED_CONTROL_AVAILABLE_NOT_PINNED,
        }
        self.assertEqual(len(sentinels), 3)


# ── RubricSpec ─────────────────────────────────────────────────────────


class TestRubricSpec(unittest.TestCase):
    def test_frozen(self) -> None:
        r = RubricSpec(
            name="default-v1",
            dimensions=("idiomaticity",),
            prompt_template="rate {diff}",
        )
        with self.assertRaises(FrozenInstanceError):
            r.name = "other"  # type: ignore[misc]

    def test_dimensions_is_tuple_not_list(self) -> None:
        # Tuple is immutable; List would allow caller-side mutation
        # to silently change the rubric after the spec was captured.
        r = RubricSpec(
            name="x",
            dimensions=("a", "b", "c"),
            prompt_template="t",
        )
        self.assertIsInstance(r.dimensions, tuple)


# ── JudgeInput ─────────────────────────────────────────────────────────


class TestJudgeInput(unittest.TestCase):
    def _rubric(self) -> RubricSpec:
        return RubricSpec(
            name="default-v1",
            dimensions=("idiomaticity",),
            prompt_template="rate {diff}",
        )

    def test_frozen(self) -> None:
        ji = JudgeInput(
            attempt_dir=Path("/tmp/a"),
            task_id="python/bowling",
            benchmark_id="aider-polyglot",
            diff_path=Path("/tmp/a/diff.patch"),
            prompt_path=Path("/tmp/a/prompt.md"),
            verify_output="ok",
            rubric=self._rubric(),
        )
        with self.assertRaises(FrozenInstanceError):
            ji.task_id = "other"  # type: ignore[misc]

    def test_verify_output_is_string_not_path(self) -> None:
        # The runner sometimes truncates verify output before writing
        # it; the judge prompt wants the content inline. Passing a
        # path would force the judge to re-read and would lose the
        # truncation context. The field is str by contract.
        ji = JudgeInput(
            attempt_dir=Path("/tmp/a"),
            task_id="t",
            benchmark_id="b",
            diff_path=Path("/tmp/a/diff.patch"),
            prompt_path=Path("/tmp/a/prompt.md"),
            verify_output="multi\nline\noutput",
            rubric=self._rubric(),
        )
        self.assertIsInstance(ji.verify_output, str)
        self.assertIn("\n", ji.verify_output)


# ── DimensionRating ────────────────────────────────────────────────────


class TestDimensionRating(unittest.TestCase):
    def test_frozen(self) -> None:
        d = DimensionRating(rating=4, explanation="ok", prompt_sha256="abc")
        with self.assertRaises(FrozenInstanceError):
            d.rating = 5  # type: ignore[misc]

    def test_null_rating_is_distinct_from_zero(self) -> None:
        # rating=None means "structurally inapplicable"; rating=1 is
        # the lowest-quality rating. They must not be coerced.
        # (Zero is outside the rating bounds entirely; this test
        # documents the None-vs-bottom-rating distinction.)
        inapplicable = DimensionRating(
            rating=None,
            explanation="task forbids editing tests",
            prompt_sha256="x",
        )
        low = DimensionRating(
            rating=JUDGE_RATING_MIN,
            explanation="no tests on a task that allowed them",
            prompt_sha256="y",
        )
        self.assertIsNone(inapplicable.rating)
        self.assertEqual(low.rating, 1)
        self.assertNotEqual(inapplicable, low)

    def test_explanation_required_for_null_rating(self) -> None:
        # The rubric requires a one-line justification when rating
        # is null. The dataclass doesn't enforce non-empty (that's
        # the judge implementation's job), but the field is
        # required (no default) — verified by attempting to
        # construct without it.
        with self.assertRaises(TypeError):
            DimensionRating(  # type: ignore[call-arg]
                rating=None,
                prompt_sha256="x",
            )

    def test_rating_in_bounds_accepted(self) -> None:
        # Every value in [JUDGE_RATING_MIN, JUDGE_RATING_MAX] must
        # construct without raising. Documents the inclusive range.
        for r in range(JUDGE_RATING_MIN, JUDGE_RATING_MAX + 1):
            DimensionRating(rating=r, explanation="ok", prompt_sha256="x")

    def test_rating_zero_rejected(self) -> None:
        # Zero is outside the 1..5 band. The reviewer-flagged case:
        # a parser bug that writes 0 must be rejected by the
        # dataclass before judge.json is written, not silently
        # propagated into Spearman.
        with self.assertRaises(ValueError):
            DimensionRating(rating=0, explanation="ok", prompt_sha256="x")

    def test_rating_six_rejected(self) -> None:
        # Six is above the band — the reviewer-flagged symmetric
        # case.
        with self.assertRaises(ValueError):
            DimensionRating(rating=6, explanation="ok", prompt_sha256="x")

    def test_rating_far_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DimensionRating(rating=99, explanation="ok", prompt_sha256="x")
        with self.assertRaises(ValueError):
            DimensionRating(rating=-1, explanation="ok", prompt_sha256="x")

    def test_rating_bool_rejected(self) -> None:
        # ``bool`` is a subclass of ``int``; ``True``/``False`` would
        # otherwise pass the range check (True == 1, False == 0).
        # Rejecting them defends the null-vs-zero / null-vs-true
        # silent-coercion failure mode.
        with self.assertRaises(TypeError):
            DimensionRating(rating=True, explanation="ok", prompt_sha256="x")
        with self.assertRaises(TypeError):
            DimensionRating(rating=False, explanation="ok", prompt_sha256="x")

    def test_rating_float_rejected(self) -> None:
        # Spearman ranks floats fine, but the rubric is integers
        # 1..5; a float would indicate a parser bug.
        with self.assertRaises(TypeError):
            DimensionRating(rating=3.5, explanation="ok", prompt_sha256="x")  # type: ignore[arg-type]


# ── JudgeInvocation ────────────────────────────────────────────────────


class TestJudgeInvocation(unittest.TestCase):
    def test_temperature_and_seed_default_to_none(self) -> None:
        # Default = the corrected determinism contract: claude-code
        # CLI exposes neither knob, so the judge does not pretend
        # to pin them.
        inv = JudgeInvocation(model="sonnet")
        self.assertIsNone(inv.temperature)
        self.assertIsNone(inv.seed)
        self.assertEqual(inv.temperature_control, TEMPERATURE_CONTROL_UNSUPPORTED)
        self.assertEqual(inv.seed_control, SEED_CONTROL_UNSUPPORTED)

    def test_temperature_zero_distinct_from_temperature_none(self) -> None:
        # A future judge backend whose CLI does expose --temperature
        # would record temperature=0.0 + control="supported". That
        # is distinct from temperature=None + control="unsupported",
        # which is the claude-code path. The two must never be
        # silently coerced.
        pinned = JudgeInvocation(
            model="m",
            temperature=0.0,
            temperature_control=TEMPERATURE_CONTROL_SUPPORTED,
        )
        unsupported = JudgeInvocation(model="m")
        self.assertEqual(pinned.temperature, 0.0)
        self.assertIsNone(unsupported.temperature)
        self.assertNotEqual(pinned.temperature_control, unsupported.temperature_control)

    def test_provider_endpoint_present_is_boolean_not_url(self) -> None:
        # Per the backends' provider-env discipline: presence
        # boolean only, NEVER the endpoint URL or any secret.
        inv = JudgeInvocation(
            model="sonnet",
            provider_endpoint_present=True,
        )
        self.assertIs(inv.provider_endpoint_present, True)
        # And the field type is bool — not Optional[str], not
        # Optional[bool]. A future contributor cannot stuff a URL
        # in without changing the dataclass signature.
        self.assertIsInstance(inv.provider_endpoint_present, bool)

    def test_frozen(self) -> None:
        inv = JudgeInvocation(model="sonnet")
        with self.assertRaises(FrozenInstanceError):
            inv.model = "other"  # type: ignore[misc]


# ── JudgeResult ────────────────────────────────────────────────────────


class TestJudgeResult(unittest.TestCase):
    def _make_result(
        self,
        *,
        tokens_input: object = "__unset__",
        tokens_output: object = "__unset__",
    ) -> JudgeResult:
        kwargs: dict = dict(
            judge_id="claude-code-judge",
            judge_model="sonnet",
            judge_backend_id="claude-code",
            rubric_name="default-v1",
            ratings={
                "idiomaticity": DimensionRating(
                    rating=4, explanation="ok", prompt_sha256="x"
                ),
            },
            invocation=JudgeInvocation(model="sonnet"),
        )
        if tokens_input != "__unset__":
            kwargs["tokens_input"] = tokens_input
        if tokens_output != "__unset__":
            kwargs["tokens_output"] = tokens_output
        return JudgeResult(**kwargs)

    def test_token_fields_default_none(self) -> None:
        r = self._make_result()
        self.assertIsNone(r.tokens_input)
        self.assertIsNone(r.tokens_output)

    def test_token_zero_distinct_from_none(self) -> None:
        # Mirrors BackendResult: None means "judge did not provide";
        # 0 means "judge reported zero." Do not coerce.
        none_r = self._make_result()
        zero_r = self._make_result(tokens_input=0, tokens_output=0)
        self.assertIsNone(none_r.tokens_input)
        self.assertEqual(zero_r.tokens_input, 0)
        self.assertNotEqual(none_r.tokens_input, zero_r.tokens_input)

    def test_metadata_default_empty(self) -> None:
        r = self._make_result()
        self.assertEqual(dict(r.judge_metadata), {})

    def test_frozen(self) -> None:
        r = self._make_result()
        with self.assertRaises(FrozenInstanceError):
            r.judge_id = "other"  # type: ignore[misc]


# ── Protocol conformance ───────────────────────────────────────────────


class _MinimalJudge:
    """Smallest possible Judge implementation — satisfies the Protocol
    without doing real work. Used to verify ``isinstance(..., Judge)``
    accepts a structural match.
    """

    judge_id = "minimal"

    def rate(self, attempt: JudgeInput) -> JudgeResult:
        return JudgeResult(
            judge_id=self.judge_id,
            judge_model="",
            judge_backend_id="",
            rubric_name=attempt.rubric.name,
            ratings={
                d: DimensionRating(rating=None, explanation="stub", prompt_sha256="")
                for d in attempt.rubric.dimensions
            },
            invocation=JudgeInvocation(model=""),
        )


class _NotAJudge:
    """Missing both the attribute and the method."""


class _MissingMethod:
    judge_id = "incomplete"


class TestJudgeProtocol(unittest.TestCase):
    def test_minimal_judge_satisfies_protocol(self) -> None:
        j = _MinimalJudge()
        self.assertIsInstance(j, Judge)

    def test_non_judge_rejected(self) -> None:
        self.assertNotIsInstance(_NotAJudge(), Judge)

    def test_missing_method_rejected(self) -> None:
        # runtime_checkable Protocols check method existence, not
        # signature. A class with judge_id but no rate() should not
        # satisfy the Protocol.
        self.assertNotIsInstance(_MissingMethod(), Judge)


if __name__ == "__main__":
    unittest.main()
