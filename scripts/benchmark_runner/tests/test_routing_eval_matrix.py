# tests/test_routing_eval_matrix.py — routing-eval (E1 of #109) T3.
#
# The invariants that make the derived-control design VALID, each as a
# regression: trials are a dimension; reuse refuses per fingerprint
# component; always_cheapest never selects on mixed provenance; the
# oracle chooses per (task, trial) and bounds quality, not cost;
# oracle_budget's ceiling holds per selected cell with no claim about
# summed cost; and derived arms expose rows 9-11 only as
# not_applicable.

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ..routing_eval.outcome_matrix import (
    MatrixIntegrityError,
    NOT_APPLICABLE,
    SEQUENCE_DEPENDENT_MEASURES,
    Cell,
    Fingerprint,
    OutcomeMatrix,
    ReuseRefused,
    assert_reusable,
    build_matrix,
    check_reuse,
    matrix_dumps,
    matrix_from_record,
    matrix_to_record,
    verify_matrix,
    select_always_best,
    select_always_cheapest,
    select_oracle,
    tie_break_key,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

def _identity(pid: str) -> dict:
    return {"profile_id": pid, "backend": "claude-code", "provider": "anthropic",
            "requested_model": "sonnet", "effective_model": "sonnet",
            "tool_profile": "full-cct", "endpoint": "api.anthropic.com"}


def _fp(profiles=("alpha",)) -> Fingerprint:
    return Fingerprint(
        registry_digest="sha256:reg",
        preset_digest="sha256:preset",
        execution_identity=tuple(_identity(p) for p in sorted(profiles)),
        task_set_revision="polyglot@3a1f9c2",
        toolchain_digest="sha256:tc",
    )


_FP = _fp()

_META = {
    "alpha": {"tier": "tier1", "priority": 10},
    "beta": {"tier": "tier1", "priority": 20},
    "qwen": {"tier": "tier2", "priority": 10},
}


def _cell(task, profile, trial, *, result="pass", cost=0.01, prov="measured",
          estimator=None, eligible=True, regressions=None, seed=None, **kw) -> Cell:
    return Cell(
        task_id=task, profile_id=profile, trial=trial,
        seed=(trial + 1) if seed is None else seed,  # pairs with _matrix's (1, 2, ...) seeds
        eligible=eligible,
        result=result if eligible else None,
        regressions=regressions or {"lint": False, "typecheck": False},
        scope_violation=kw.get("scope_violation", False),
        repeated_repair=kw.get("repeated_repair", False),
        intervention=kw.get("intervention", False),
        cost_value=cost if eligible else None,
        cost_provenance=prov if eligible else "unavailable",
        cost_estimator=estimator,
        elapsed_seconds=1.0 if eligible else None,
    )


def _matrix(cells, *, trials=2, basis="measured", seeds=(1, 2)) -> OutcomeMatrix:
    """An honest matrix around the given cells: the declared task list
    and profile identities are derived from the cells, so coverage must
    genuinely hold — tests construct complete sweeps, not fragments."""
    task_order: dict[str, None] = {}
    profiles: dict[str, None] = {}
    for c in cells:
        task_order.setdefault(c.task_id, None)
        profiles.setdefault(c.profile_id, None)
    return OutcomeMatrix(
        fingerprint=_fp(tuple(profiles)),
        task_ids=tuple(task_order),
        trials=trials, trial_seeds=tuple(seeds),
        cost_basis=basis, cells=tuple(cells),
    )


def _quality(cell: Cell) -> float:
    """A simple injected projection for selector tests (T5 wires v1)."""
    return 1.0 if cell.result == "pass" else 0.0


class TestBuildMatrix(unittest.TestCase):
    def test_trials_are_a_dimension_not_an_average(self) -> None:
        calls = []

        def execute(task, profile, trial, seed):
            calls.append((task, profile, trial, seed))
            return _cell(task, profile, trial, cost=0.01 * (trial + 1), seed=seed)

        m = build_matrix(_FP, ["t1"], ["alpha"], [11, 22], "measured",
                         lambda p, t: True, execute)
        self.assertEqual(m.trials, 2)
        self.assertEqual(len(m.cells), 2)
        self.assertEqual({c.trial for c in m.cells}, {0, 1})
        # each trial got its paired seed, in order
        self.assertEqual(calls, [("t1", "alpha", 0, 11), ("t1", "alpha", 1, 22)])

    def test_ineligible_pairs_get_explicit_cells(self) -> None:
        m = build_matrix(_fp(("alpha", "qwen")), ["t1"], ["alpha", "qwen"], [1],
                         "measured", lambda p, t: p != "qwen",
                         lambda t, p, tr, s: _cell(t, p, tr, seed=s))
        qwen = [c for c in m.cells if c.profile_id == "qwen"]
        self.assertEqual(len(qwen), 1)
        self.assertFalse(qwen[0].eligible)
        self.assertIsNone(qwen[0].result)

    def test_executor_cannot_mislabel_a_cell(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected t1/alpha/trial-0"):
            build_matrix(_FP, ["t1"], ["alpha"], [1], "measured",
                         lambda p, t: True,
                         lambda t, p, tr, s: _cell("other", p, tr, seed=s))

    def test_round_trip_and_canonical_bytes(self) -> None:
        m = build_matrix(_FP, ["t1"], ["alpha"], [1, 2], "measured",
                         lambda p, t: True, lambda t, p, tr, s: _cell(t, p, tr, seed=s))
        record = matrix_to_record(m)
        self.assertEqual(matrix_from_record(record), m)
        self.assertEqual(matrix_dumps(m), matrix_dumps(matrix_from_record(record)))

    def test_record_satisfies_the_schema(self) -> None:
        from .test_routing_eval_schemas import _load_json, validate

        m = build_matrix(_FP, ["t1"], ["alpha"], [1], "measured",
                         lambda p, t: True, lambda t, p, tr, s: _cell(t, p, tr, seed=s))
        schema = _load_json(REPO_ROOT / "benchmarks" / "schema" / "outcome-matrix.schema.json")
        errors = validate(json.loads(matrix_dumps(m)), schema)
        self.assertEqual(errors, [], errors)


class TestReuseGate(unittest.TestCase):
    def test_matching_fingerprint_is_reusable(self) -> None:
        m = _matrix([_cell("t1", "alpha", 0), _cell("t1", "alpha", 1)])
        self.assertEqual(check_reuse(m.fingerprint, _FP), [])
        assert_reusable(m, _FP)  # no raise

    def test_each_component_mismatch_refuses_by_name(self) -> None:
        variants = {
            "registry_digest": {"registry_digest": "sha256:other"},
            "preset_digest": {"preset_digest": "sha256:other"},
            "execution_identity": {"execution_identity": ()},
            "task_set_revision": {"task_set_revision": "polyglot@ffffff"},
            "toolchain_digest": {"toolchain_digest": "sha256:other"},
        }
        m = _matrix([_cell("t1", "alpha", 0), _cell("t1", "alpha", 1)])
        for component, override in variants.items():
            with self.subTest(component=component):
                expected = Fingerprint(**{**_FP.__dict__, **override})
                self.assertEqual(check_reuse(m.fingerprint, expected), [component])
                with self.assertRaisesRegex(ReuseRefused, component):
                    assert_reusable(m, expected)


class TestAlwaysBest(unittest.TestCase):
    def test_tier1_outranks_tier2_then_priority_then_id(self) -> None:
        cells = [
            _cell("t1", "alpha", 0), _cell("t1", "alpha", 1),
            _cell("t1", "beta", 0), _cell("t1", "beta", 1),
            _cell("t1", "qwen", 0), _cell("t1", "qwen", 1),
        ]
        sel = select_always_best(_matrix(cells), _META)
        self.assertEqual({c.profile_id for c in sel.chosen}, {"alpha"})  # tier1 prio 10
        self.assertEqual(len(sel.chosen), 2)  # both trials, not collapsed

    def test_eligibility_varies_by_task(self) -> None:
        cells = [
            _cell("t1", "alpha", 0), _cell("t1", "beta", 0),
            _cell("t2", "alpha", 0, eligible=False), _cell("t2", "beta", 0),
        ]
        sel = select_always_best(_matrix(cells, trials=1, seeds=(1,)), _META)
        by_task = {c.task_id: c.profile_id for c in sel.chosen}
        self.assertEqual(by_task, {"t1": "alpha", "t2": "beta"})

    def test_no_eligible_profile_is_insufficient_not_zero(self) -> None:
        cells = [_cell("t1", "alpha", 0, eligible=False)]
        sel = select_always_best(_matrix(cells, trials=1, seeds=(1,)), _META)
        self.assertEqual(sel.chosen, ())
        self.assertIn("t1", sel.insufficient)


class TestAlwaysCheapest(unittest.TestCase):
    def test_selects_on_mean_cost_across_trials(self) -> None:
        cells = [
            _cell("t1", "alpha", 0, cost=0.01), _cell("t1", "alpha", 1, cost=0.09),
            _cell("t1", "beta", 0, cost=0.04), _cell("t1", "beta", 1, cost=0.04),
        ]
        # alpha mean 0.05 > beta mean 0.04 despite alpha's cheap trial
        sel = select_always_cheapest(_matrix(cells))
        self.assertEqual({c.profile_id for c in sel.chosen}, {"beta"})

    def test_any_unpriced_eligible_profile_blocks_the_task(self) -> None:
        cells = [
            _cell("t1", "alpha", 0, cost=0.01),
            _cell("t1", "beta", 0, cost=None, prov="unavailable"),
        ]
        sel = select_always_cheapest(_matrix(cells, trials=1, seeds=(1,)))
        self.assertEqual(sel.chosen, ())
        self.assertIn("mixed provenance", sel.insufficient["t1"])

    def test_estimated_basis_pins_the_table_version(self) -> None:
        cells = [
            _cell("t1", "alpha", 0, cost=0.01, prov="estimated", estimator="price-table-v1"),
            _cell("t1", "beta", 0, cost=0.02, prov="estimated", estimator="price-table-v2"),
        ]
        sel = select_always_cheapest(
            _matrix(cells, trials=1, seeds=(1,), basis="estimated@price-table-v1")
        )
        # beta's v2 estimate does not satisfy the declared basis: the
        # task is insufficient, never selected across table versions.
        self.assertEqual(sel.chosen, ())
        self.assertIn("t1", sel.insufficient)

    def test_measured_basis_rejects_estimated_cells(self) -> None:
        cells = [
            _cell("t1", "alpha", 0, cost=0.01),
            _cell("t1", "beta", 0, cost=0.001, prov="estimated", estimator="price-table-v1"),
        ]
        sel = select_always_cheapest(_matrix(cells, trials=1, seeds=(1,)))
        # beta's cheaper ESTIMATED cost may not win under measured basis
        self.assertEqual(sel.chosen, ())
        self.assertIn("t1", sel.insufficient)


class TestOracle(unittest.TestCase):
    def test_chooses_per_task_and_trial_not_after_aggregation(self) -> None:
        # alpha wins trial 0, beta wins trial 1: a per-task-aggregated
        # oracle would pick one profile for both; the true hindsight
        # bound picks each trial's winner.
        cells = [
            _cell("t1", "alpha", 0, result="pass"), _cell("t1", "alpha", 1, result="fail"),
            _cell("t1", "beta", 0, result="fail"), _cell("t1", "beta", 1, result="pass"),
        ]
        sel = select_oracle(_matrix(cells), _quality)
        winners = {(c.trial): c.profile_id for c in sel.chosen}
        self.assertEqual(winners, {0: "alpha", 1: "beta"})

    def test_oracle_quality_bounds_every_other_arm(self) -> None:
        cells = [
            _cell("t1", "alpha", 0, result="pass", cost=0.09),
            _cell("t1", "beta", 0, result="fail", cost=0.01),
            _cell("t2", "alpha", 0, result="fail", cost=0.09),
            _cell("t2", "beta", 0, result="pass", cost=0.01),
        ]
        m = _matrix(cells, trials=1, seeds=(1,))
        oracle = select_oracle(m, _quality)
        best = select_always_best(m, _META)
        cheapest = select_always_cheapest(m)

        def mean_q(sel):
            return sum(_quality(c) for c in sel.chosen) / len(sel.chosen)

        self.assertGreaterEqual(mean_q(oracle), mean_q(best))
        self.assertGreaterEqual(mean_q(oracle), mean_q(cheapest))
        # And deliberately NO cost assertion for the oracle: its chosen
        # cells here cost MORE than always_cheapest's — legitimately.
        self.assertGreater(
            sum(c.cost_value for c in oracle.chosen),
            sum(c.cost_value for c in cheapest.chosen),
        )

    def test_tie_break_is_deterministic_under_permutation(self) -> None:
        a = _cell("t1", "alpha", 0, regressions={"lint": True})
        b = _cell("t1", "beta", 0)  # fewer regressions wins the tie
        for order in ([a, b], [b, a]):
            with self.subTest(order=[c.profile_id for c in order]):
                sel = select_oracle(_matrix(order, trials=1, seeds=(1,)), _quality)
                self.assertEqual(sel.chosen[0].profile_id, "beta")

    def test_final_tie_break_is_profile_id(self) -> None:
        a = _cell("t1", "alpha", 0)
        b = _cell("t1", "beta", 0)
        sel = select_oracle(_matrix([b, a], trials=1, seeds=(1,)), _quality)
        self.assertEqual(sel.chosen[0].profile_id, "alpha")
        self.assertLess(tie_break_key(a), tie_break_key(b))


class TestOracleBudget(unittest.TestCase):
    def test_ceiling_holds_per_selected_cell_only(self) -> None:
        cells = [
            _cell("t1", "alpha", 0, result="pass", cost=0.10),
            _cell("t1", "beta", 0, result="fail", cost=0.02),
            _cell("t2", "alpha", 0, result="pass", cost=0.04),
            _cell("t2", "beta", 0, eligible=False),
        ]
        m = _matrix(cells, trials=1, seeds=(1,))
        sel = select_oracle(m, _quality, budget_ceiling_usd=0.05)
        self.assertEqual(sel.kind, "oracle_budget")
        for c in sel.chosen:
            self.assertLessEqual(c.cost_value, 0.05)
        # t1's passing cell exceeds the ceiling; the failing one within
        # it is selected — the ceiling filters cells, never quality.
        t1 = [c for c in sel.chosen if c.task_id == "t1"]
        self.assertEqual(t1[0].profile_id, "beta")
        # NO assertion exists about the summed arm cost — asserting the
        # per-cell ceiling on a sum would be the semantics confusion the
        # plan forbids. (Sum here is 0.06 > 0.05, and that is FINE.)
        self.assertGreater(sum(c.cost_value for c in sel.chosen), 0.05)

    def test_no_cell_within_ceiling_is_insufficient(self) -> None:
        cells = [_cell("t1", "alpha", 0, cost=0.10)]
        sel = select_oracle(_matrix(cells, trials=1, seeds=(1,)), _quality,
                            budget_ceiling_usd=0.01)
        self.assertEqual(sel.chosen, ())
        self.assertIn("t1/trial-0", sel.insufficient)

    def test_budget_uses_only_basis_satisfying_cells(self) -> None:
        cells = [
            _cell("t1", "alpha", 0, cost=0.001, prov="estimated", estimator="v1"),
        ]
        sel = select_oracle(_matrix(cells, trials=1, seeds=(1,)), _quality,
                            budget_ceiling_usd=1.0)
        self.assertEqual(sel.chosen, ())  # estimated under measured basis


class TestMatrixIntegrity(unittest.TestCase):
    """The sweep is an invariant re-established after load: schema
    validity cannot prove exact Cartesian coverage, and a selector fed
    an incomplete matrix derives silently biased controls."""

    def _complete(self) -> OutcomeMatrix:
        # alpha: $1, $1, $9 (expensive third trial); beta: $2, $2, $2.
        cells = []
        for trial, (a_cost, b_cost) in enumerate([(1.0, 2.0), (1.0, 2.0), (9.0, 2.0)]):
            cells.append(_cell("t1", "alpha", trial, cost=a_cost, seed=trial + 1))
            cells.append(_cell("t1", "beta", trial, cost=b_cost, seed=trial + 1))
        return _matrix(cells, trials=3, seeds=(1, 2, 3))

    def test_the_complete_matrix_verifies_and_beta_wins(self) -> None:
        m = self._complete()
        verify_matrix(m)  # no raise
        sel = select_always_cheapest(m)
        # alpha mean 11/3 ≈ 3.67 > beta mean 2.0 — with FULL evidence.
        self.assertEqual({c.profile_id for c in sel.chosen}, {"beta"})

    def test_losing_the_expensive_trial_refuses_not_biases(self) -> None:
        # The owner's bias scenario: drop alpha's $9 trial and alpha's
        # remaining mean ($1) would beat beta ($2) on incomplete
        # evidence. The selector must refuse the matrix instead.
        m = self._complete()
        pruned = OutcomeMatrix(
            fingerprint=m.fingerprint, task_ids=m.task_ids, trials=m.trials,
            trial_seeds=m.trial_seeds, cost_basis=m.cost_basis,
            cells=tuple(c for c in m.cells
                        if not (c.profile_id == "alpha" and c.trial == 2)),
        )
        with self.assertRaisesRegex(MatrixIntegrityError, "missing cell"):
            select_always_cheapest(pruned)
        with self.assertRaisesRegex(MatrixIntegrityError, "missing cell"):
            select_oracle(pruned, _quality)
        with self.assertRaisesRegex(MatrixIntegrityError, "missing cell"):
            select_always_best(pruned, _META)

    def test_removing_an_ineligible_cell_also_refuses(self) -> None:
        # Explicit ineligibility can never become silence.
        cells = [_cell("t1", "alpha", 0), _cell("t1", "qwen", 0, eligible=False)]
        m = _matrix(cells, trials=1, seeds=(1,))
        verify_matrix(m)
        pruned = OutcomeMatrix(
            fingerprint=m.fingerprint, task_ids=m.task_ids, trials=m.trials,
            trial_seeds=m.trial_seeds, cost_basis=m.cost_basis,
            cells=tuple(c for c in m.cells if c.profile_id != "qwen"),
        )
        with self.assertRaisesRegex(MatrixIntegrityError, "missing cell"):
            verify_matrix(pruned)

    def test_duplicate_cell_identity_refuses(self) -> None:
        cells = [_cell("t1", "alpha", 0), _cell("t1", "alpha", 0, cost=0.5)]
        m = _matrix(cells, trials=1, seeds=(1,))
        with self.assertRaisesRegex(MatrixIntegrityError, "duplicate cell"):
            verify_matrix(m)

    def test_undeclared_cell_refuses(self) -> None:
        cells = [_cell("t1", "alpha", 0), _cell("t1", "alpha", 1)]
        m = OutcomeMatrix(
            fingerprint=_fp(("alpha",)), task_ids=("t1",), trials=1,
            trial_seeds=(1,), cost_basis="measured", cells=tuple(cells),
        )
        with self.assertRaisesRegex(MatrixIntegrityError, "undeclared cell"):
            verify_matrix(m)

    def test_seed_pairing_mismatch_refuses(self) -> None:
        # Trial 0's cell carrying trial 1's seed compares unlike trials.
        cells = [_cell("t1", "alpha", 0, seed=2), _cell("t1", "alpha", 1, seed=2)]
        m = _matrix(cells, trials=2, seeds=(1, 2))
        with self.assertRaisesRegex(MatrixIntegrityError, "declares seed 1"):
            verify_matrix(m)

    def test_integrity_holds_after_persistence_round_trip(self) -> None:
        # The invariant is re-established on the LOADED artifact, and a
        # record mutated after persistence refuses.
        m = self._complete()
        record = matrix_to_record(m)
        verify_matrix(matrix_from_record(record))  # no raise
        record["cells"] = [
            c for c in record["cells"]
            if not (c["profile_id"] == "alpha" and c["trial"] == 2)
        ]
        with self.assertRaisesRegex(MatrixIntegrityError, "missing cell"):
            select_always_cheapest(matrix_from_record(record))


class TestDerivedArmHonesty(unittest.TestCase):
    def test_sequence_dependent_measures_are_not_applicable(self) -> None:
        sel = select_always_best(
            _matrix([_cell("t1", "alpha", 0)], trials=1, seeds=(1,)), _META
        )  # single-profile single-trial sweep: complete by construction
        self.assertEqual(set(sel.sequence_dependent), set(SEQUENCE_DEPENDENT_MEASURES))
        for measure, value in sel.sequence_dependent.items():
            with self.subTest(measure=measure):
                self.assertEqual(value, NOT_APPLICABLE)

    def test_insufficiency_never_reads_as_an_empty_success(self) -> None:
        sel = select_always_cheapest(
            _matrix([_cell("t1", "alpha", 0, cost=None, prov="unavailable")],
                    trials=1, seeds=(1,))
        )
        self.assertEqual(sel.chosen, ())
        self.assertTrue(sel.insufficient)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
