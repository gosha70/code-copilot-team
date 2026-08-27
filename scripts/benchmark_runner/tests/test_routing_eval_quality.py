# tests/test_routing_eval_quality.py — routing-eval (E1 of #109) T5.
#
# quality_fn v1 and the report, proven against plan.md's normative
# sections: the fixed weight table; renormalization when a component is
# globally masked; Q withheld entirely on a missing primary outcome;
# ONE global mask used for arms and the oracle alike; the §Metric
# contract aggregations (mean-over-trials -> mean-over-tasks; ratios as
# sum/sum with zero denominators not_applicable); the control-set gate
# as a hard error; cost and the Pareto frontier withheld — never
# partially drawn — under basis violations; and NO AIQ anywhere.

from __future__ import annotations

import unittest

from benchmark_runner.routing_eval.outcome_matrix import (
    NOT_APPLICABLE,
    ArmSelection,
    Cell,
    Fingerprint,
    OutcomeMatrix,
    select_oracle,
)
from benchmark_runner.routing_eval.quality_fn import (
    COMPONENTS,
    QUALITY_FN_VERSION,
    QualityInsufficient,
    arm_quality,
    cell_quality,
    compute_mask,
)
from benchmark_runner.routing_eval.routing_quality import (
    ControlSetIncomplete,
    build_report,
    router_cells_from_records,
)

_PRESET = "sha256:" + "ab" * 32


def _fp(profiles=("alpha", "beta")):
    return Fingerprint(
        registry_digest="sha256:reg",
        preset_digest=_PRESET,
        execution_identity=tuple(
            {"profile_id": p, "backend": "b", "provider": "prov",
             "requested_model": "m", "effective_model": "m",
             "tool_profile": "t", "endpoint": "e"}
            for p in sorted(profiles)
        ),
        task_set_revision="rev",
        toolchain_digest="sha256:tc",
    )


def _cell(task, profile, trial, *, result="pass", cost=0.01,
          regressions=None, scope=False, repair=False, intervention=False,
          prov="measured"):
    return Cell(
        task_id=task, profile_id=profile, trial=trial, seed=trial + 1,
        eligible=True, result=result,
        regressions=regressions
        or {"lint": False, "typecheck": False, "coverage": False, "security": False},
        scope_violation=scope, repeated_repair=repair, intervention=intervention,
        cost_value=cost, cost_provenance=prov, cost_estimator=None,
        elapsed_seconds=1.0,
    )


def _matrix(cells, *, trials=1, seeds=(1,), basis="measured"):
    tasks, profiles = {}, {}
    for c in cells:
        tasks.setdefault(c.task_id, None)
        profiles.setdefault(c.profile_id, None)
    return OutcomeMatrix(
        fingerprint=_fp(tuple(profiles)), task_ids=tuple(tasks),
        trials=trials, trial_seeds=tuple(seeds), cost_basis=basis,
        cells=tuple(cells),
    )


def _selection(kind, cells, insufficient=None):
    return ArmSelection(kind, tuple(cells), insufficient or {})


def _router_record(task, trial, *, verifier_exit=0, cost=0.02,
                   delegated=False, diff_lines=None, delegated_lines=None):
    tier2 = {"delegated": False, "packet_id": None, "packet_digest": None,
             "builder_id": None, "builder_tier": None,
             "builder_provider": None, "builder_model": None,
             "delegated_lines": None, "reconciliation_diff_lines": None}
    if delegated:
        tier2 = {**tier2, "delegated": True, "packet_id": "p", "packet_digest": "d",
                 "builder_id": "b", "builder_tier": "tier2",
                 "builder_provider": "pv", "builder_model": "mm",
                 "delegated_lines": delegated_lines,
                 "reconciliation_diff_lines": diff_lines}
    return {
        "task_id": task, "trial": trial, "trial_seed": trial + 1,
        "preset_digest": _PRESET,
        "registry_digest": "sha256:reg",
        "task_set_revision": "rev",
        "toolchain_digest": "sha256:tc",
        "verifiers": [{"command": "v", "exit_status": verifier_exit,
                       "evidence_ref": "e"}],
        "baseline": {"lint_passed": True, "typecheck_passed": True},
        "quality_gates": {"coverage": {"before": 80.0, "after": 80.0},
                          "security": {"findings_by_severity":
                                       {"before": {}, "after": {}}}},
        "scope_violations": [], "repair_cycles": [], "interventions": [],
        "cost": {"value": cost, "provenance": "measured", "estimator": None,
                 "inputs": None},
        "tier2": tier2, "rollbacks": [],
    }


class TestWeightTable(unittest.TestCase):
    def test_v1_weights_are_the_declared_table(self) -> None:
        expected = {
            "verifier_pass_rate": 0.50,
            "lint_regression": 0.075,
            "typecheck_regression": 0.075,
            "coverage_regression": 0.075,
            "security_regression": 0.075,
            "scope_violation": 0.10,
            "repeated_repair": 0.05,
            "intervention": 0.05,
        }
        self.assertEqual({c.name: c.weight for c in COMPONENTS}, expected)
        self.assertEqual([c.name for c in COMPONENTS], list(expected))
        self.assertAlmostEqual(sum(c.weight for c in COMPONENTS), 1.0)

    def test_known_vector_computes_the_expected_q(self) -> None:
        # pass with one scope violation: 0.5*1 + 0.375*1 + 0.10*0 + ...
        cell = _cell("t", "a", 0, scope=True)
        mask = tuple(c.name for c in COMPONENTS)
        self.assertAlmostEqual(cell_quality(cell, mask), 0.90)
        clean = _cell("t", "a", 0)
        self.assertAlmostEqual(cell_quality(clean, mask), 1.0)
        failing = _cell("t", "a", 0, result="fail")
        self.assertAlmostEqual(cell_quality(failing, mask), 0.50)


class TestGlobalMask(unittest.TestCase):
    def test_component_unevaluable_anywhere_is_dropped_everywhere(self) -> None:
        cells = [
            _cell("t1", "alpha", 0),
            _cell("t1", "beta", 0,
                  regressions={"lint": False, "typecheck": False,
                               "coverage": None, "security": False}),
        ]
        mask = compute_mask(_matrix(cells))
        self.assertNotIn("coverage_regression", mask)
        self.assertIn("verifier_pass_rate", mask)
        # renormalization: remaining weights re-sum to 1, so a clean
        # cell still scores exactly 1.0 under the reduced mask.
        self.assertAlmostEqual(cell_quality(cells[0], mask), 1.0)

    def test_missing_primary_outcome_withholds_q_entirely(self) -> None:
        cells = [_cell("t1", "alpha", 0),
                 _cell("t1", "beta", 0, result=None)]
        with self.assertRaisesRegex(QualityInsufficient, "primary component"):
            compute_mask(_matrix(cells))

    def test_the_same_mask_governs_the_oracles_choice(self) -> None:
        # gamma's coverage is unevaluable, so coverage is masked out
        # GLOBALLY: beta's regressed coverage cannot lower beta's Q,
        # and beta ties gamma at Q ~= 1.0 — the proof that one mask
        # governed every cell (per-cell masking would have scored beta
        # lower and gamma not at all). The tie then resolves by the
        # DECLARED sequence on the raw vector — regression count
        # ascending — which picks gamma.
        cells = [
            _cell("t1", "alpha", 0, result="fail"),
            _cell("t1", "beta", 0,
                  regressions={"lint": False, "typecheck": False,
                               "coverage": True, "security": False}),
            _cell("t1", "gamma", 0, result="pass", cost=9.0,
                  regressions={"lint": False, "typecheck": False,
                               "coverage": None, "security": False}),
        ]
        m = _matrix(cells)
        mask = compute_mask(m)
        self.assertNotIn("coverage_regression", mask)
        self.assertAlmostEqual(
            cell_quality(cells[1], mask), cell_quality(cells[2], mask)
        )
        sel = select_oracle(m, lambda c: cell_quality(c, mask))
        self.assertEqual(sel.chosen[0].profile_id, "gamma")

    def test_determinism_under_permutation(self) -> None:
        cells = [_cell("t1", "alpha", 0), _cell("t2", "alpha", 0, result="fail"),
                 _cell("t1", "beta", 0), _cell("t2", "beta", 0)]
        m1, m2 = _matrix(cells), _matrix(list(reversed(cells)))
        self.assertEqual(compute_mask(m1), compute_mask(m2))
        mask = compute_mask(m1)
        self.assertEqual(
            arm_quality([c for c in cells if c.profile_id == "alpha"], mask),
            arm_quality(list(reversed([c for c in cells if c.profile_id == "alpha"])), mask),
        )


class TestAggregation(unittest.TestCase):
    def test_mean_over_trials_then_mean_over_tasks(self) -> None:
        mask = tuple(c.name for c in COMPONENTS)
        # t1: pass+fail (0.5); t2: pass (1.0) -> task means avg = 0.75
        cells = [_cell("t1", "a", 0), _cell("t1", "a", 1, result="fail"),
                 _cell("t2", "a", 0)]
        q = arm_quality(cells, mask)
        self.assertAlmostEqual(q, 0.50 * 0.75 + 0.50 * 1.0)

    def test_empty_arm_has_no_quality(self) -> None:
        with self.assertRaises(QualityInsufficient):
            arm_quality([], tuple(c.name for c in COMPONENTS))


class TestRouterCellReduction(unittest.TestCase):
    def test_verifier_evidence_reduces_to_pass_fail_or_none(self) -> None:
        passing = router_cells_from_records([_router_record("t", 0)])[0]
        self.assertEqual(passing.result, "pass")
        failing = router_cells_from_records(
            [_router_record("t", 0, verifier_exit=1)]
        )[0]
        self.assertEqual(failing.result, "fail")
        record = _router_record("t", 0)
        record["verifiers"] = []
        empty = router_cells_from_records([record])[0]
        self.assertIsNone(empty.result, "absence of evidence is never a pass")

    def test_sequence_dependent_ratio_is_sum_over_sum(self) -> None:
        from benchmark_runner.routing_eval.routing_quality import (
            _sequence_dependent_from_records,
        )

        records = [
            _router_record("t1", 0, delegated=True, delegated_lines=100,
                           diff_lines=50),
            _router_record("t2", 0, delegated=True, delegated_lines=300,
                           diff_lines=0),
        ]
        seq = _sequence_dependent_from_records(records)
        # sum-num/sum-den = 50/400, NOT mean(50/100, 0/300)
        self.assertAlmostEqual(seq["reconciliation_rework_ratio"], 0.125)
        self.assertAlmostEqual(seq["tier2_accepted_unchanged"], 0.5)

    def test_zero_denominator_is_not_applicable_never_zero(self) -> None:
        from benchmark_runner.routing_eval.routing_quality import (
            _sequence_dependent_from_records,
        )

        seq = _sequence_dependent_from_records(
            [_router_record("t1", 0, delegated=True, delegated_lines=0,
                            diff_lines=0)]
        )
        self.assertEqual(seq["reconciliation_rework_ratio"], NOT_APPLICABLE)


class TestReport(unittest.TestCase):
    def _fixture(self):
        cells = [
            _cell("t1", "alpha", 0, cost=0.05),
            _cell("t1", "beta", 0, result="fail", cost=0.01),
        ]
        matrix = _matrix(cells)
        controls = {
            "always_best": _selection("always_best", [cells[0]]),
            "always_cheapest": _selection("always_cheapest", [cells[1]]),
            "oracle": _selection("oracle", [cells[0]]),
        }
        records = [_router_record("t1", 0)]
        return matrix, controls, records

    def test_complete_report_shape(self) -> None:
        matrix, controls, records = self._fixture()
        report = build_report(matrix, controls, records,
                              expected_preset_digest=_PRESET)
        self.assertEqual(report["quality_fn"], QUALITY_FN_VERSION)
        self.assertNotIn("aiq", str(report).lower())
        arms = report["arms"]
        self.assertEqual(
            set(arms), {"always_best", "always_cheapest", "oracle", "cct_router"}
        )
        # Q beside the FULL vector, never alone; sequence-dependent rows
        # not_applicable for derived arms, measured for the router.
        for kind, arm in arms.items():
            self.assertIsNotNone(arm["quality"])
            self.assertIn("verifier_pass_rate", arm["metrics"])
        self.assertEqual(
            arms["always_best"]["metrics"]["reconciliation_rework_ratio"],
            NOT_APPLICABLE,
        )
        self.assertEqual(report["pareto"]["status"], "ok")
        frontier_arms = [p["arm"] for p in report["pareto"]["frontier"]]
        self.assertIn("cct_router", str(frontier_arms) + str(arms))

    def test_missing_control_is_a_hard_error(self) -> None:
        matrix, controls, records = self._fixture()
        for missing in ("always_best", "always_cheapest", "oracle"):
            with self.subTest(missing=missing):
                partial = {k: v for k, v in controls.items() if k != missing}
                with self.assertRaisesRegex(ControlSetIncomplete, missing):
                    build_report(matrix, partial, records,
                                 expected_preset_digest=_PRESET)

    def test_insufficient_control_never_satisfies_the_gate(self) -> None:
        matrix, controls, records = self._fixture()
        controls["always_cheapest"] = _selection(
            "always_cheapest", [], {"t1": "no basis-satisfying cost"}
        )
        with self.assertRaisesRegex(ControlSetIncomplete, "insufficient"):
            build_report(matrix, controls, records,
                         expected_preset_digest=_PRESET)

    def test_preset_digest_binds_matrix_and_router(self) -> None:
        matrix, controls, records = self._fixture()
        with self.assertRaisesRegex(ControlSetIncomplete, "another preset"):
            build_report(matrix, controls, records,
                         expected_preset_digest="sha256:" + "99" * 32)
        records[0]["preset_digest"] = "sha256:" + "77" * 32
        with self.assertRaisesRegex(ControlSetIncomplete, "preset_digest"):
            build_report(matrix, controls, records,
                         expected_preset_digest=_PRESET)

    def test_comparison_identity_is_the_full_fingerprint(self) -> None:
        # The owner's counterexample: same preset, different registry —
        # the router and its controls did not run in the same routing
        # universe, so no comparative figure may exist. The same rule
        # covers every fingerprint component durably carried by both
        # sides.
        for component, foreign in (
            ("registry_digest", "sha256:" + "55" * 32),
            ("task_set_revision", "other-rev"),
            ("toolchain_digest", "sha256:" + "44" * 32),
        ):
            with self.subTest(component=component):
                matrix, controls, records = self._fixture()
                records[0][component] = foreign
                with self.assertRaisesRegex(ControlSetIncomplete, component):
                    build_report(matrix, controls, records,
                                 expected_preset_digest=_PRESET)

    def test_unprovable_identity_component_refuses(self) -> None:
        # A null toolchain cannot PROVE comparability — refusal, never
        # silent assumption of equality.
        matrix, controls, records = self._fixture()
        records[0]["toolchain_digest"] = None
        with self.assertRaisesRegex(ControlSetIncomplete, "cannot prove"):
            build_report(matrix, controls, records,
                         expected_preset_digest=_PRESET)

    def test_cost_basis_violation_withholds_the_frontier_not_q(self) -> None:
        cells = [
            _cell("t1", "alpha", 0, cost=0.05),
            _cell("t1", "beta", 0, cost=0.01, prov="estimated"),
        ]
        matrix = _matrix(cells)  # basis measured; beta's cell violates
        controls = {
            "always_best": _selection("always_best", [cells[0]]),
            "always_cheapest": _selection("always_cheapest", [cells[1]]),
            "oracle": _selection("oracle", [cells[0]]),
        }
        report = build_report(matrix, controls, [_router_record("t1", 0)],
                              expected_preset_digest=_PRESET)
        cheapest = report["arms"]["always_cheapest"]
        self.assertIsNotNone(cheapest["quality"])  # Q stays reported
        self.assertEqual(cheapest["cost"]["status"], "insufficient_evidence")
        self.assertIsNone(cheapest["cost"]["value"])  # never zero
        self.assertEqual(report["pareto"]["status"], "insufficient_evidence")

    def test_the_metric_set_is_closed(self) -> None:
        matrix, controls, records = self._fixture()
        report = build_report(matrix, controls, records,
                              expected_preset_digest=_PRESET)
        allowed = {c.name for c in COMPONENTS} | {
            "tier2_accepted_unchanged", "reconciliation_rework_ratio", "rollbacks",
        }
        for kind, arm in report["arms"].items():
            with self.subTest(arm=kind):
                self.assertTrue(set(arm["metrics"]) <= allowed,
                                set(arm["metrics"]) - allowed)


class TestT6ContagiousInsufficiency(unittest.TestCase):
    """T6 (plan decision 9): insufficiency is first-class and
    contagious — never a zero, never a default, never a silently
    dropped arm, and unreconciled delegation is never zero rework."""

    def _report_fixture(self):
        cells = [
            _cell("t1", "alpha", 0, cost=0.05),
            _cell("t1", "beta", 0, result="fail", cost=0.01),
        ]
        matrix = _matrix(cells)
        controls = {
            "always_best": _selection("always_best", [cells[0]]),
            "always_cheapest": _selection("always_cheapest", [cells[1]]),
            "oracle": _selection("oracle", [cells[0]]),
        }
        return cells, matrix, controls

    def test_delegate_and_reconcile_legs_pair_per_cell(self) -> None:
        from benchmark_runner.routing_eval.routing_quality import (
            _sequence_dependent_from_records,
        )

        # ONE delegated (task, trial) across its two invocation
        # records: the delegate leg carries the builder's denominator,
        # the reconcile leg carries the pair. Counted once — 25/100,
        # never 25/200.
        legs = [
            _router_record("t1", 0, delegated=True, delegated_lines=100,
                           diff_lines=None),
            _router_record("t1", 0, delegated=True, delegated_lines=100,
                           diff_lines=25),
        ]
        seq = _sequence_dependent_from_records(legs)
        self.assertAlmostEqual(seq["reconciliation_rework_ratio"], 0.25)
        self.assertAlmostEqual(seq["tier2_accepted_unchanged"], 0.0)

    def test_missing_reconcile_evidence_is_insufficient_never_zero(self) -> None:
        from benchmark_runner.routing_eval.routing_quality import (
            INSUFFICIENT,
            _sequence_dependent_from_records,
        )

        seq = _sequence_dependent_from_records(
            [_router_record("t1", 0, delegated=True, delegated_lines=100,
                            diff_lines=None)]
        )
        # the old failure mode: None -> 0 rework -> "accepted unchanged"
        self.assertEqual(seq["reconciliation_rework_ratio"], INSUFFICIENT)
        self.assertEqual(seq["tier2_accepted_unchanged"], INSUFFICIENT)
        self.assertIn("never rendered as zero", seq["insufficient_reason"])

    def test_conflicting_durable_evidence_is_insufficient(self) -> None:
        from benchmark_runner.routing_eval.routing_quality import (
            INSUFFICIENT,
            _sequence_dependent_from_records,
        )

        seq = _sequence_dependent_from_records([
            _router_record("t1", 0, delegated=True, delegated_lines=100,
                           diff_lines=5),
            _router_record("t1", 0, delegated=True, delegated_lines=200,
                           diff_lines=5),
        ])
        self.assertEqual(seq["reconciliation_rework_ratio"], INSUFFICIENT)
        self.assertIn("conflicting", seq["insufficient_reason"])

    def test_sequence_insufficiency_reaches_the_report(self) -> None:
        from benchmark_runner.routing_eval.routing_quality import INSUFFICIENT

        _cells, matrix, controls = self._report_fixture()
        records = [_router_record("t1", 0, delegated=True,
                                  delegated_lines=100, diff_lines=None)]
        report = build_report(matrix, controls, records,
                              expected_preset_digest=_PRESET)
        arm = report["arms"]["cct_router"]
        self.assertEqual(arm["metrics"]["reconciliation_rework_ratio"],
                         INSUFFICIENT)
        self.assertEqual(arm["metrics"]["tier2_accepted_unchanged"],
                         INSUFFICIENT)
        self.assertIn("sequence_dependent", arm["insufficient"])
        # rows 9-11 are outside quality_fn: Q stays reported
        self.assertIsNotNone(arm["quality"])

    def test_oracle_budget_insufficiency_is_carried_not_dropped(self) -> None:
        from benchmark_runner.routing_eval.routing_quality import INSUFFICIENT

        cells, matrix, controls = self._report_fixture()
        controls["oracle_budget"] = _selection(
            "oracle_budget", [cells[0]],
            {"t1/trial-0": "the ceiling admits no cell"},
        )
        records = [_router_record("t1", 0)]
        report = build_report(matrix, controls, records,
                              expected_preset_digest=_PRESET)
        arm = report["arms"]["oracle_budget"]
        # carried through AS insufficiency: present in the report, Q
        # withheld (never computed over partial coverage), reasons kept
        self.assertIsNone(arm["quality"])
        self.assertIn("selection:t1/trial-0", arm["insufficient"])
        self.assertIn("quality", arm["insufficient"])
        # the frontier is withheld whole — the arm is never silently
        # dropped from the Pareto set
        self.assertEqual(report["pareto"]["status"], INSUFFICIENT)

    def test_unavailable_cost_contaminates_cost_axis_and_pareto(self) -> None:
        from benchmark_runner.routing_eval.routing_quality import INSUFFICIENT

        _cells, matrix, controls = self._report_fixture()
        record = _router_record("t1", 0)
        # harvest's honest default: transcripts transient, no measured cost
        record["cost"] = {"value": None, "provenance": "unavailable",
                          "estimator": None, "inputs": None}
        report = build_report(matrix, controls, [record],
                              expected_preset_digest=_PRESET)
        arm = report["arms"]["cct_router"]
        self.assertEqual(arm["cost"]["status"], INSUFFICIENT)
        self.assertIsNone(arm["cost"]["value"])
        self.assertEqual(report["pareto"]["status"], INSUFFICIENT)
        # Q is not suppressed by a cost violation
        self.assertIsNotNone(arm["quality"])

    def test_unavailable_provenance_insufficiency_refuses_the_gate(self) -> None:
        from benchmark_runner.routing_eval.outcome_matrix import (
            select_always_cheapest,
        )

        cells = [
            _cell("t1", "alpha", 0, cost=None, prov="unavailable"),
            _cell("t1", "beta", 0, cost=0.01),
        ]
        matrix = _matrix(cells)
        selection = select_always_cheapest(matrix)
        # ANY eligible profile without a basis-satisfying cost makes the
        # task insufficient — unavailable is never priced, never zero
        self.assertIn("t1", selection.insufficient)
        controls = {
            "always_best": _selection("always_best", [cells[1]]),
            "always_cheapest": selection,
            "oracle": _selection("oracle", [cells[1]]),
        }
        with self.assertRaisesRegex(ControlSetIncomplete, "insufficient"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET)


class TestValidatorFailsClosedOnNewKeywords(unittest.TestCase):
    """The standing pin: a schema keyword the production validator does
    not implement must refuse loudly, never silently validate."""

    def test_unimplemented_keyword_refuses(self) -> None:
        from benchmark_runner.routing_eval.record_check import (
            SchemaUnsupported,
            validate,
        )

        for schema in ({"type": "array", "maxItems": 3},
                       {"type": "string", "maxLength": 5},
                       {"type": "object", "patternProperties": {}}):
            with self.subTest(keyword=sorted(set(schema) - {"type"})):
                with self.assertRaises(SchemaUnsupported):
                    validate([], schema)

    def test_annotations_remain_ignorable(self) -> None:
        from benchmark_runner.routing_eval.record_check import validate

        self.assertEqual(
            validate("x", {"type": "string", "title": "t",
                           "description": "d", "default": "y"}),
            [],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
