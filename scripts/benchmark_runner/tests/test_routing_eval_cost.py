# tests/test_routing_eval_cost.py — routing-eval cost provenance (T1).
#
# The regressions T1 requires, plus two boundaries that keep this
# increment honest. First: a "measured" cost is read from the
# transcript's final type:"result" record ONLY (mirroring
# rb_measured_cost) — an assistant message containing total_cost_usd is
# in-band model output and must never become accounting. Second: E1
# reads cost into its OWN record and must not put cost into the shared
# harness; the last test class asserts E1 did not quietly reverse
# specs/benchmark-harness/spec.md's no-cost-slot constraint.

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ..routing_eval.cost_reader import (
    ESTIMATED,
    MEASURED,
    UNAVAILABLE,
    Cost,
    estimate_cost,
    load_price_table,
    measured_cost,
    resolve_cost,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PRICE_TABLE = REPO_ROOT / "benchmarks" / "pricing" / "price-table-v1.json"

_TOKENS = {"input": 1_000_000, "output": 1_000_000}

#: A minimal REPRODUCIBLE estimator-inputs shape: both required buckets,
#: each pairing a token count with its rate.
_VALID_INPUTS = {
    "input": {"tokens": 1000, "rate_per_million": 3.0},
    "output": {"tokens": 500, "rate_per_million": 15.0},
}
#: The only value those inputs recompute to — Cost binds value to
#: inputs at construction, so tests must use the honest number.
_VALID_INPUTS_VALUE = 1000 / 1_000_000 * 3.0 + 500 / 1_000_000 * 15.0


def _result_transcript(cost) -> str:
    """A minimal Claude-Code-shaped JSONL transcript ending in a result."""
    records = [
        {"type": "assistant", "message": {"content": "working on it"}},
        {"type": "result", "result": "done", "total_cost_usd": cost},
    ]
    return "\n".join(json.dumps(r) for r in records)


class TestMeasuredCostSelection(unittest.TestCase):
    """rb_measured_cost's selection rule: the final result record only."""

    def test_reads_cost_from_the_result_record(self) -> None:
        self.assertEqual(measured_cost(_result_transcript(0.0412)), 0.0412)

    def test_last_result_record_wins(self) -> None:
        text = "\n".join(
            [
                json.dumps({"type": "result", "total_cost_usd": 1.0}),
                json.dumps({"type": "result", "total_cost_usd": 2.0}),
            ]
        )
        self.assertEqual(measured_cost(text), 2.0)

    def test_assistant_record_cannot_forge_a_measured_cost(self) -> None:
        # In-band model output with a total_cost_usd key is not accounting.
        text = "\n".join(
            [
                json.dumps({"type": "assistant", "total_cost_usd": 0.0001}),
                json.dumps({"type": "assistant", "message": "here: total_cost_usd 0"}),
            ]
        )
        self.assertIsNone(measured_cost(text))

    def test_arbitrary_mapping_is_not_a_transcript(self) -> None:
        # A typed non-result record never supplies cost, even alone.
        self.assertIsNone(
            measured_cost(json.dumps({"type": "system", "total_cost_usd": 5.0}))
        )

    def test_single_untyped_object_counts_as_its_own_result(self) -> None:
        # Bare-JSON transcripts (no type field) — rb_measured_cost parity.
        self.assertEqual(measured_cost(json.dumps({"total_cost_usd": 0.5})), 0.5)

    def test_top_level_array_flattens(self) -> None:
        text = json.dumps(
            [{"type": "assistant"}, {"type": "result", "total_cost_usd": 0.25}]
        )
        self.assertEqual(measured_cost(text), 0.25)

    def test_unparseable_lines_are_skipped_not_fatal(self) -> None:
        text = "claude-code: update available\n" + _result_transcript(0.1)
        self.assertEqual(measured_cost(text), 0.1)

    def test_zero_is_measured_not_missing(self) -> None:
        self.assertEqual(measured_cost(_result_transcript(0)), 0.0)

    def test_invalid_values_are_not_measured(self) -> None:
        for bad in (-1.0, "0.04", None, True, float("nan"), float("inf")):
            with self.subTest(value=bad):
                self.assertIsNone(measured_cost(_result_transcript(bad)))

    def test_no_result_record_is_not_measured(self) -> None:
        self.assertIsNone(measured_cost(json.dumps({"type": "assistant"})))
        self.assertIsNone(measured_cost(""))


class TestCostInvariants(unittest.TestCase):
    """The documented pairings are enforced at construction."""

    def test_unavailable_must_be_empty(self) -> None:
        Cost(None, UNAVAILABLE)  # valid
        with self.assertRaises(ValueError):
            Cost(1.0, UNAVAILABLE)
        with self.assertRaises(ValueError):
            Cost(None, UNAVAILABLE, estimator="v1")

    def test_measured_must_carry_a_finite_value_and_nothing_else(self) -> None:
        Cost(0.0, MEASURED)  # valid
        for bad_value in (None, -1.0, float("nan"), float("inf")):
            with self.subTest(value=bad_value):
                with self.assertRaises(ValueError):
                    Cost(bad_value, MEASURED)
        with self.assertRaises(ValueError):
            Cost(1.0, MEASURED, estimator="v1")

    def test_estimated_requires_estimator_and_recomputable_inputs(self) -> None:
        Cost(_VALID_INPUTS_VALUE, ESTIMATED, estimator="v1", inputs=_VALID_INPUTS)  # valid
        with self.assertRaises(ValueError):
            Cost(1.0, ESTIMATED)
        with self.assertRaises(ValueError):
            Cost(1.0, ESTIMATED, estimator="v1")  # inputs missing
        with self.assertRaises(ValueError):
            # Empty inputs cannot be recomputed — reproducibility is
            # the whole reason inputs exist.
            Cost(1.0, ESTIMATED, estimator="v1", inputs={})

    def test_estimated_inputs_shape_is_closed_and_paired(self) -> None:
        # Non-empty is not enough: {"input": {"tokens": 1}} carries no
        # rate and no output bucket, so the estimate it claims to
        # explain cannot be recomputed from it.
        bad_inputs = {
            "tokens without rate": {"input": {"tokens": 1}, "output": {"tokens": 1}},
            "missing output bucket": {"input": {"tokens": 1, "rate_per_million": 1.0}},
            "unknown bucket": {**_VALID_INPUTS, "vibes": {"tokens": 1, "rate_per_million": 1.0}},
            "negative rate": {
                "input": {"tokens": 1, "rate_per_million": -1.0},
                "output": {"tokens": 1, "rate_per_million": 1.0},
            },
            "non-mapping bucket": {"input": 3.0, "output": {"tokens": 1, "rate_per_million": 1.0}},
        }
        for label, inputs in bad_inputs.items():
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    Cost(1.0, ESTIMATED, estimator="v1", inputs=inputs)

    def test_estimated_value_is_bound_to_its_inputs(self) -> None:
        # The owner's reproduction: value=1.0 with inputs recomputing to
        # ~0.000002 was accepted — a structurally valid understated (or
        # inflated) cost that always_cheapest would trust. Now the value
        # must equal the recomputed total.
        with self.assertRaisesRegex(ValueError, "not bound to its evidence"):
            Cost(1.0, ESTIMATED, estimator="v1", inputs=_VALID_INPUTS)
        with self.assertRaisesRegex(ValueError, "not bound to its evidence"):
            Cost(
                1.0,
                ESTIMATED,
                estimator="v1",
                inputs={
                    "input": {"tokens": 1, "rate_per_million": 1.0},
                    "output": {"tokens": 1, "rate_per_million": 1.0},
                },
            )
        # The honest value constructs fine.
        Cost(_VALID_INPUTS_VALUE, ESTIMATED, estimator="v1", inputs=_VALID_INPUTS)

    def test_estimate_cost_output_is_always_recomputable(self) -> None:
        # The producer and the invariant must agree: whatever
        # estimate_cost emits reconstructs to the same value.
        table = {"version": "v", "models": {"m": {"input": 3.0, "output": 15.0}}}
        cost = estimate_cost(_TOKENS, "m", table)
        recomputed = sum(
            b["tokens"] / 1_000_000 * b["rate_per_million"] for b in cost.inputs.values()
        )
        self.assertAlmostEqual(recomputed, cost.value)

    def test_unknown_provenance_cannot_exist(self) -> None:
        with self.assertRaises(ValueError):
            Cost(1.0, "vibes")


class TestEstimatorStrictness(unittest.TestCase):
    def setUp(self) -> None:
        self.table = {
            "version": "price-table-test",
            "models": {"m": {"input": 3.0, "output": 15.0, "cache_read": 0.3}},
        }

    def test_valid_estimate(self) -> None:
        cost = estimate_cost(_TOKENS, "m", self.table)
        self.assertEqual(cost.provenance, ESTIMATED)
        self.assertAlmostEqual(cost.value, 18.0)
        self.assertEqual(cost.estimator, "price-table-test")
        self.assertEqual(cost.inputs["input"]["rate_per_million"], 3.0)

    def test_missing_output_count_refuses_rather_than_understates(self) -> None:
        for tokens in ({"input": 1000}, {"input": 1000, "output": None}):
            with self.subTest(tokens=tokens):
                cost = estimate_cost(tokens, "m", self.table)
                self.assertEqual(cost.provenance, UNAVAILABLE)

    def test_negative_or_nonfinite_counts_refuse_the_estimate(self) -> None:
        for bad in (-1, float("nan"), float("inf"), True, "many"):
            with self.subTest(count=bad):
                cost = estimate_cost({"input": bad, "output": 10}, "m", self.table)
                self.assertEqual(cost.provenance, UNAVAILABLE)

    def test_negative_rate_refuses_the_estimate(self) -> None:
        table = {"version": "v", "models": {"m": {"input": -3.0, "output": 15.0}}}
        cost = estimate_cost(_TOKENS, "m", table)
        self.assertEqual(cost.provenance, UNAVAILABLE)

    def test_consumed_cache_tokens_without_a_rate_refuse(self) -> None:
        # cache_write consumed, table prices only cache_read: an estimate
        # that dropped the bucket would understate and win always_cheapest.
        tokens = dict(_TOKENS, cache_write=50_000)
        cost = estimate_cost(tokens, "m", self.table)
        self.assertEqual(cost.provenance, UNAVAILABLE)

    def test_zero_or_absent_cache_tokens_are_fine(self) -> None:
        tokens = dict(_TOKENS, cache_read=0)
        cost = estimate_cost(tokens, "m", self.table)
        self.assertEqual(cost.provenance, ESTIMATED)
        self.assertAlmostEqual(cost.value, 18.0)

    def test_priced_cache_tokens_are_included(self) -> None:
        tokens = dict(_TOKENS, cache_read=1_000_000)
        cost = estimate_cost(tokens, "m", self.table)
        self.assertAlmostEqual(cost.value, 18.3)

    def test_unlisted_model_is_unavailable_not_guessed(self) -> None:
        cost = estimate_cost(_TOKENS, "not-in-table", self.table)
        self.assertEqual(cost.provenance, UNAVAILABLE)
        self.assertIsNone(cost.value)

    def test_no_model_is_unavailable(self) -> None:
        cost = estimate_cost(_TOKENS, None, self.table)
        self.assertEqual(cost.provenance, UNAVAILABLE)

    def test_malformed_table_roots_are_unavailable_not_a_crash(self) -> None:
        # A broken table marks one cell insufficient; it must never
        # take the whole run down with an AttributeError.
        for bad in (None, [], "table", 7, {"version": "v", "models": ["m"]}):
            with self.subTest(table=bad):
                cost = estimate_cost(_TOKENS, "m", bad)
                self.assertEqual(cost.provenance, UNAVAILABLE)


class TestResolutionOrder(unittest.TestCase):
    def setUp(self) -> None:
        self.table = {"version": "v", "models": {"m": {"input": 3.0, "output": 15.0}}}

    def test_measured_outranks_estimator(self) -> None:
        cost = resolve_cost(_result_transcript(0.5), _TOKENS, "m", self.table)
        self.assertEqual(cost.provenance, MEASURED)
        self.assertEqual(cost.value, 0.5)

    def test_missing_measured_falls_through_to_estimator(self) -> None:
        cost = resolve_cost(_result_transcript("bogus"), _TOKENS, "m", self.table)
        self.assertEqual(cost.provenance, ESTIMATED)
        self.assertAlmostEqual(cost.value, 18.0)

    def test_no_transcript_no_table_is_unavailable(self) -> None:
        cost = resolve_cost(None, _TOKENS, "m", None)
        self.assertEqual(cost.provenance, UNAVAILABLE)
        self.assertIsNone(cost.value)


class TestShippedPriceTable(unittest.TestCase):
    def test_ships_and_declares_version(self) -> None:
        table = load_price_table(PRICE_TABLE)
        self.assertEqual(table["version"], "price-table-v1")

    def test_non_object_root_raises_a_named_error(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("[1, 2, 3]")
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            load_price_table(Path(f.name))

    def test_unlisted_model_yields_unavailable(self) -> None:
        table = load_price_table(PRICE_TABLE)
        cost = estimate_cost(_TOKENS, "sonnet", table)
        self.assertEqual(cost.provenance, UNAVAILABLE)


class TestCostBasisHomogeneity(unittest.TestCase):
    """Provenance is never mixed wherever cost is used."""

    def test_measured_basis_accepts_only_measured(self) -> None:
        self.assertTrue(Cost(1.0, MEASURED).satisfies("measured"))
        self.assertFalse(
            Cost(_VALID_INPUTS_VALUE, ESTIMATED, estimator="price-table-v1", inputs=_VALID_INPUTS).satisfies("measured")
        )
        self.assertFalse(Cost(None, UNAVAILABLE).satisfies("measured"))

    def test_estimated_basis_pins_the_table_version(self) -> None:
        basis = "estimated@price-table-v1"
        self.assertTrue(
            Cost(_VALID_INPUTS_VALUE, ESTIMATED, estimator="price-table-v1", inputs=_VALID_INPUTS).satisfies(basis)
        )
        self.assertFalse(
            Cost(_VALID_INPUTS_VALUE, ESTIMATED, estimator="price-table-v2", inputs=_VALID_INPUTS).satisfies(basis)
        )
        self.assertFalse(Cost(1.0, MEASURED).satisfies(basis))

    def test_unavailable_satisfies_nothing(self) -> None:
        for basis in ("measured", "estimated@price-table-v1"):
            with self.subTest(basis=basis):
                self.assertFalse(Cost(None, UNAVAILABLE).satisfies(basis))


class TestRecordShape(unittest.TestCase):
    def test_measured_record_has_null_estimator_fields(self) -> None:
        record = Cost(0.04, MEASURED).as_record()
        self.assertEqual(record["provenance"], MEASURED)
        self.assertIsNone(record["estimator"])
        self.assertIsNone(record["inputs"])

    def test_estimated_record_carries_estimator_and_inputs(self) -> None:
        table = {"version": "v", "models": {"m": {"input": 1.0, "output": 1.0}}}
        record = estimate_cost(_TOKENS, "m", table).as_record()
        self.assertEqual(record["provenance"], ESTIMATED)
        self.assertEqual(record["estimator"], "v")
        self.assertIsNotNone(record["inputs"])

    def test_unavailable_record_has_null_value(self) -> None:
        record = Cost(None, UNAVAILABLE).as_record()
        self.assertIsNone(record["value"])


class TestHarnessCostConstraintPreserved(unittest.TestCase):
    """E1 must not reverse the harness's no-cost contract."""

    def test_backend_result_has_no_cost_field(self) -> None:
        from ..contracts import BackendResult

        fields = set(BackendResult.__dataclass_fields__)
        for forbidden in ("cost_usd", "cost", "cost_provenance", "total_cost_usd"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, fields)

    def test_shared_schemas_have_no_cost_amount(self) -> None:
        schema_dir = REPO_ROOT / "benchmarks" / "schema"
        for name in ("stats", "score", "run-record"):
            with self.subTest(schema=name):
                payload = json.loads(
                    (schema_dir / f"{name}.schema.json").read_text(encoding="utf-8")
                )
                props = payload.get("properties", {})
                self.assertNotIn("cost_usd", props)
                self.assertNotIn("total_cost_usd", props)

    def test_stats_cost_reporting_stays_disabled(self) -> None:
        stats = json.loads(
            (REPO_ROOT / "benchmarks" / "schema" / "stats.schema.json").read_text(
                encoding="utf-8"
            )
        )
        enabled = stats["properties"]["cost_reporting"]["properties"]["enabled"]
        self.assertIs(enabled.get("const"), False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
