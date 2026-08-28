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

import atexit
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmark_runner.routing_eval.injection import preset_digest
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
from benchmark_runner.routing_eval.supervisor_runner import registry_digest_of

# ── selector authority is DERIVED from real declarations, so the
# fixtures are real files: production-valid registries (rc_validate
# passes) and scenario-config namespaces whose digests the matrix
# fingerprints carry. There is no way to hand build_report a fabricated
# context — only paths to declarations. ──
_FIXDIR = Path(tempfile.mkdtemp(prefix="rq-fixture."))
atexit.register(lambda: shutil.rmtree(_FIXDIR, ignore_errors=True))


def _write_registry(name, profiles):
    """A PRODUCTION-VALID registry: every required profile key, both
    scenario route classes; rc_validate must pass or the builder
    refuses."""
    lines = [
        "schema_version = 1",
        "[policy]",
        "enabled = true",
        "[route_classes.tier1_only]",
        'tier_order = ["tier1"]',
        "[route_classes.tier2_preferred]",
        'tier_order = ["tier2", "tier1"]',
    ]
    for i, p in enumerate(profiles):
        roles = ", ".join(
            f'"{r}"' for r in p.get("roles", ("build", "bounded-build"))
        )
        lines += [
            "[[profiles]]",
            f'id = "{p["id"]}"',
            'backend = "claude-code"',
            f'provider = "prov-{i}"',
            'model = "m"',
            f'capability_tier = "{p.get("tier", "tier1")}"',
            f'priority = {p.get("priority", (i + 1) * 10)}',
            f'quota_pool = "pool-{i}"',
            f"roles = [{roles}]",
            'tool_profile = "full-cct"',
            'credential_mode = "claude-login"',
            'data_policy = "approved-cloud"',
        ]
    path = _FIXDIR / f"{name}.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _config(*, budget=None, delegate=()):
    return SimpleNamespace(
        scenario="hybrid-routing", benchmark=None, arms=[],
        cost_basis="measured", trials=1, trial_seeds=[1],
        event_stream=[], budget_ceiling_usd=budget, task_filter=None,
        tier1_only_tasks=[], delegate_tasks=list(delegate),
    )


#: The default authority pair most fixtures share: alpha priority 10
#: (always_best), beta priority 20, both tier1 with build+bounded-build.
_REGISTRY = _write_registry(
    "default", [{"id": "alpha", "priority": 10}, {"id": "beta", "priority": 20}]
)
_REG_DIGEST = registry_digest_of(_REGISTRY)
_CONFIG = _config()
_PRESET = preset_digest(_CONFIG)


def _fp(profiles=("alpha", "beta"), *, registry_digest=None, preset=None):
    return Fingerprint(
        registry_digest=registry_digest or _REG_DIGEST,
        preset_digest=preset or _PRESET,
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


def _matrix(cells, *, trials=1, seeds=(1,), basis="measured",
            registry_digest=None, preset=None):
    tasks, profiles = {}, {}
    for c in cells:
        tasks.setdefault(c.task_id, None)
        profiles.setdefault(c.profile_id, None)
    return OutcomeMatrix(
        fingerprint=_fp(tuple(profiles), registry_digest=registry_digest,
                        preset=preset),
        task_ids=tuple(tasks),
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
        "registry_digest": _REG_DIGEST,
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
                              expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)
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
                                 expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_insufficient_control_never_satisfies_the_gate(self) -> None:
        matrix, controls, records = self._fixture()
        controls["always_cheapest"] = _selection(
            "always_cheapest", [], {"t1": "no basis-satisfying cost"}
        )
        with self.assertRaisesRegex(ControlSetIncomplete, "insufficient"):
            build_report(matrix, controls, records,
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_preset_digest_binds_matrix_and_router(self) -> None:
        matrix, controls, records = self._fixture()
        with self.assertRaisesRegex(ControlSetIncomplete, "another preset"):
            build_report(matrix, controls, records,
                         expected_preset_digest="sha256:" + "99" * 32,
                         registry_path=_REGISTRY, config=_CONFIG)
        records[0]["preset_digest"] = "sha256:" + "77" * 32
        with self.assertRaisesRegex(ControlSetIncomplete, "preset_digest"):
            build_report(matrix, controls, records,
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

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
                                 expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_unprovable_identity_component_refuses(self) -> None:
        # A null toolchain cannot PROVE comparability — refusal, never
        # silent assumption of equality.
        matrix, controls, records = self._fixture()
        records[0]["toolchain_digest"] = None
        with self.assertRaisesRegex(ControlSetIncomplete, "cannot prove"):
            build_report(matrix, controls, records,
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_cost_basis_violation_refuses_at_the_cheapest_control(self) -> None:
        # Under selector exactness this scenario cannot produce a
        # report at all: a profile with no basis-satisfying cell makes
        # the RECOMPUTED always_cheapest insufficient, and the gate is
        # a hard error — a hand-made cheapest selection over the
        # violating cell is no longer representable. (The
        # frontier-withheld-while-Q-reported separation lives on the
        # router arm — see TestT6ContagiousInsufficiency.)
        from benchmark_runner.routing_eval.outcome_matrix import (
            select_always_cheapest,
        )

        cells = [
            _cell("t1", "alpha", 0, cost=0.05, prov="estimated"),
            _cell("t1", "beta", 0, cost=0.01),
        ]
        matrix = _matrix(cells)  # basis measured; alpha's cell violates
        cheapest = select_always_cheapest(matrix)
        self.assertIn("t1", cheapest.insufficient)
        controls = {
            "always_best": _selection("always_best", [cells[0]]),
            "always_cheapest": cheapest,
            "oracle": _selection("oracle", [cells[0]]),
        }
        with self.assertRaisesRegex(ControlSetIncomplete, "insufficient"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_the_metric_set_is_closed(self) -> None:
        matrix, controls, records = self._fixture()
        report = build_report(matrix, controls, records,
                              expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)
        allowed = {c.name for c in COMPONENTS} | {
            "tier2_accepted_unchanged", "reconciliation_rework_ratio", "rollbacks",
        }
        for kind, arm in report["arms"].items():
            with self.subTest(arm=kind):
                self.assertTrue(set(arm["metrics"]) <= allowed,
                                set(arm["metrics"]) - allowed)


class TestControlsAreMatrixBound(unittest.TestCase):
    """T7 (owner finding): 'computed from the same outcome matrix' is
    proven, not assumed. A control selection carrying any cell that is
    not identically an eligible cell of the declared matrix refuses
    the report before any figure exists."""

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
        return cells, matrix, controls

    def test_a_foreign_cell_is_refused(self) -> None:
        # The owner's reproduction: a task/profile the matrix never
        # swept, smuggled in as always_best. Previously accepted with
        # Q ~= 1.0; now no comparative figure may exist.
        _cells, matrix, controls = self._fixture()
        foreign = _cell("NOT-IN-MATRIX", "ghost", 0, cost=0.001)
        controls["always_best"] = _selection("always_best", [foreign])
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "not.*in the declared outcome matrix"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_a_tampered_cell_with_matrix_coordinates_is_refused(self) -> None:
        # Same coordinates, different measures: the matrix swept a
        # FAIL for (t1, beta) — a selection claiming a pass there is
        # re-measured evidence, not a selection.
        _cells, matrix, controls = self._fixture()
        tampered = _cell("t1", "beta", 0, result="pass", cost=0.01)
        controls["always_cheapest"] = _selection("always_cheapest", [tampered])
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "never re-measured or edited"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_the_optional_arm_is_bound_too(self) -> None:
        _cells, matrix, controls = self._fixture()
        controls["oracle_budget"] = _selection(
            "oracle_budget", [_cell("t9", "alpha", 0, cost=0.001)]
        )
        with self.assertRaisesRegex(ControlSetIncomplete, "oracle_budget"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_genuine_matrix_cells_still_report(self) -> None:
        _cells, matrix, controls = self._fixture()
        report = build_report(matrix, controls, [_router_record("t1", 0)],
                              expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)
        self.assertIsNotNone(report["arms"]["always_best"]["quality"])

    # ── membership is necessary but NOT sufficient: genuine eligible
    # cells can still violate the declared selector. The reporting
    # boundary recomputes each selector and refuses any difference. ──

    def test_a_partial_genuine_selection_is_refused(self) -> None:
        # Two trials swept; always_best supplied with only trial 0 of
        # the right profile. Every cell is a genuine eligible matrix
        # member — and the selection still isn't the selector's output.
        cells = [
            _cell("t1", "alpha", 0, cost=0.05),
            _cell("t1", "alpha", 1, cost=0.05),
            _cell("t1", "beta", 0, result="fail", cost=0.01),
            _cell("t1", "beta", 1, result="fail", cost=0.01),
        ]
        matrix = _matrix(cells, trials=2, seeds=(1, 2))
        controls = {
            "always_best": _selection("always_best", [cells[0]]),  # trial 1 omitted
            "always_cheapest": _selection("always_cheapest", [cells[2], cells[3]]),
            "oracle": _selection("oracle", [cells[0], cells[1]]),
        }
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "always_best.*declared selector"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_the_wrong_genuine_profile_is_refused(self) -> None:
        # always_cheapest handed the genuine but EXPENSIVE profile's
        # cell: a matrix member, eligible, honestly measured — and not
        # what the cheapest selector chooses.
        cells, matrix, controls = self._fixture()
        controls["always_cheapest"] = _selection("always_cheapest", [cells[0]])
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "always_cheapest.*declared selector"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_a_non_optimal_genuine_oracle_cell_is_refused(self) -> None:
        # the oracle handed the failing genuine cell instead of the
        # best observed one: hindsight that isn't hindsight.
        cells, matrix, controls = self._fixture()
        controls["oracle"] = _selection("oracle", [cells[1]])
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "oracle.*declared selector"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_oracle_budget_without_its_ceiling_is_refused(self) -> None:
        cells, matrix, controls = self._fixture()
        controls["oracle_budget"] = _selection("oracle_budget", [cells[0]])
        with self.assertRaisesRegex(ControlSetIncomplete, "ceiling"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    # ── selector AUTHORITY: derived inside the boundary from the
    # registry file and validated config — never accepted from a
    # caller, digest-verified against the matrix fingerprint. ──

    def test_declared_priorities_beat_lexical_order(self) -> None:
        # The owner's reproduction, from a REAL registry: declared
        # priorities make beta the strongest profile. The lexical
        # winner (alpha) must refuse; the declared winner (beta) must
        # report. There is no metadata argument to fabricate — only
        # the registry file itself.
        best_beta = _write_registry(
            "bestbeta",
            [{"id": "alpha", "priority": 20}, {"id": "beta", "priority": 10}],
        )
        digest = registry_digest_of(best_beta)
        cells = [
            _cell("t1", "alpha", 0, cost=0.05),
            _cell("t1", "beta", 0, result="fail", cost=0.01),
        ]
        matrix = _matrix(cells, registry_digest=digest)
        record = _router_record("t1", 0)
        record["registry_digest"] = digest
        controls = {
            "always_best": _selection("always_best", [cells[0]]),  # lexical
            "always_cheapest": _selection("always_cheapest", [cells[1]]),
            "oracle": _selection("oracle", [cells[0]]),
        }
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "always_best.*declared selector"):
            build_report(matrix, controls, [record],
                         expected_preset_digest=_PRESET,
                         registry_path=best_beta, config=_CONFIG)
        controls["always_best"] = _selection("always_best", [cells[1]])
        report = build_report(matrix, controls, [record],
                              expected_preset_digest=_PRESET,
                              registry_path=best_beta, config=_CONFIG)
        self.assertIn("always_best", report["arms"])

    def test_a_matrix_profile_the_registry_does_not_declare_refuses(self) -> None:
        # A matrix profile absent from the registry would silently
        # degrade always_best to lexical ordering — refused, never
        # defaulted.
        cells = [
            _cell("t1", "alpha", 0),
            _cell("t1", "beta", 0),
            _cell("t1", "ghost", 0),
        ]
        matrix = _matrix(cells)
        controls = {
            "always_best": _selection("always_best", [cells[0]]),
            "always_cheapest": _selection("always_cheapest", [cells[0]]),
            "oracle": _selection("oracle", [cells[0]]),
        }
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "no declared capability tier"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)

    def test_registry_eligibility_contradicting_the_matrix_refuses(self) -> None:
        # The derived predicate is the production selector's: beta
        # holds only the reconcile role, so it cannot execute ordinary
        # build work — but the matrix persisted beta's cells as
        # eligible. The flags are bound to the registry's authority
        # (T3's binding) and the contradiction refuses.
        from benchmark_runner.routing_eval.outcome_matrix import (
            MatrixIntegrityError,
        )

        no_build = _write_registry(
            "nobuild",
            [{"id": "alpha", "priority": 10},
             {"id": "beta", "priority": 20, "roles": ("reconcile",)}],
        )
        digest = registry_digest_of(no_build)
        cells = [
            _cell("t1", "alpha", 0, cost=0.05),
            _cell("t1", "beta", 0, result="fail", cost=0.01),
        ]
        matrix = _matrix(cells, registry_digest=digest)
        record = _router_record("t1", 0)
        record["registry_digest"] = digest
        controls = {
            "always_best": _selection("always_best", [cells[0]]),
            "always_cheapest": _selection("always_cheapest", [cells[1]]),
            "oracle": _selection("oracle", [cells[0]]),
        }
        with self.assertRaises(MatrixIntegrityError):
            build_report(matrix, controls, [record],
                         expected_preset_digest=_PRESET,
                         registry_path=no_build, config=_CONFIG)

    def test_another_registry_or_config_authorizes_nothing(self) -> None:
        # The matrix was swept under the default registry/config;
        # deriving authority from any OTHER declarations refuses on
        # the digest, before any figure exists.
        _cells, matrix, controls = self._fixture()
        other_registry = _write_registry(
            "other", [{"id": "alpha", "priority": 11},
                      {"id": "beta", "priority": 21}]
        )
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "registry.*authorizes nothing"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=other_registry, config=_CONFIG)
        other_config = _config()
        other_config.trials = 7
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "preset.*authorizes nothing"):
            build_report(matrix, controls, [_router_record("t1", 0)],
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=other_config)

    def test_a_declared_budget_arm_cannot_be_silently_dropped(self) -> None:
        budget_config = _config(budget=0.10)
        budget_preset = preset_digest(budget_config)
        cells = [
            _cell("t1", "alpha", 0, cost=0.05),
            _cell("t1", "beta", 0, result="fail", cost=0.01),
        ]
        matrix = _matrix(cells, preset=budget_preset)
        record = _router_record("t1", 0)
        record["preset_digest"] = budget_preset
        controls = {
            "always_best": _selection("always_best", [cells[0]]),
            "always_cheapest": _selection("always_cheapest", [cells[1]]),
            "oracle": _selection("oracle", [cells[0]]),
        }
        with self.assertRaisesRegex(ControlSetIncomplete, "silently dropped"):
            build_report(matrix, controls, [record],
                         expected_preset_digest=budget_preset,
                         registry_path=_REGISTRY, config=budget_config)

    def test_the_context_builder_uses_the_production_grammar(self) -> None:
        # The owner's reproduction: the builder must parse the SHIPPED
        # registry template (repeated [[profiles]] tables with id
        # fields — the only shape the production validator accepts)
        # and derive ELIGIBILITY from the registry's route-class AND
        # role semantics. Nothing is caller-supplied.
        from benchmark_runner.routing_eval.routing_quality import (
            selector_context_from_registry,
        )

        template = (
            Path(__file__).resolve().parents[3]
            / "shared" / "templates" / "routing" / "routing.toml.example"
        )
        self.assertTrue(template.is_file(), template)
        config = _config(budget=0.25, delegate=("python/book-store",))
        ctx = selector_context_from_registry(template, config)
        self.assertEqual(ctx.profile_meta["anthropic-sonnet"]["tier"], "tier1")
        self.assertEqual(ctx.profile_meta["anthropic-sonnet"]["priority"], 10)
        # COMPLETE multi-element arrays: str.splitlines() would treat
        # the RC_RS separator (0x1e) as a line boundary and truncate
        # this to ("build",).
        self.assertEqual(ctx.profile_meta["anthropic-sonnet"]["roles"],
                         ("build", "reconcile", "land"))
        self.assertEqual(ctx.profile_meta["local-qwen"]["tier"], "tier2")
        self.assertEqual(ctx.profile_meta["local-qwen"]["roles"],
                         ("bounded-build",))
        self.assertEqual(ctx.oracle_budget_ceiling_usd, 0.25)
        self.assertTrue(ctx.registry_digest.startswith("sha256:"))
        self.assertEqual(ctx.preset_digest, preset_digest(config))
        # the production predicate — tier AND role, not tier alone:
        self.assertFalse(
            ctx.eligible("local-qwen", "go/bowling"),
            "tier1_only ordinary work must reject the tier2 profile",
        )
        self.assertTrue(ctx.eligible("local-qwen", "python/book-store"),
                        "tier2_preferred delegate work admits the "
                        "bounded-build tier2 profile")
        self.assertTrue(ctx.eligible("anthropic-sonnet", "go/bowling"))
        self.assertFalse(
            ctx.eligible("anthropic-sonnet", "python/book-store"),
            "a profile without the bounded-build role can never be the "
            "delegated builder, whatever its tier",
        )

    def test_eligibility_matches_the_production_selector_roles(self) -> None:
        # The owner's two role reproductions, from a real registry:
        # a tier1 profile holding bounded-build IS eligible as the
        # delegated fallback (the complete tier_order ["tier2","tier1"]
        # — a truncated array would wrongly reject it), and a tier2
        # profile holding only reconcile is NEVER eligible for
        # delegation, whatever its tier.
        from benchmark_runner.routing_eval.routing_quality import (
            selector_context_from_registry,
        )

        registry = _write_registry(
            "roles-sem",
            [
                {"id": "t1both", "priority": 10},
                {"id": "t2rev", "tier": "tier2", "priority": 20,
                 "roles": ("reconcile",)},
            ],
        )
        ctx = selector_context_from_registry(
            registry, _config(delegate=("dtask",))
        )
        self.assertTrue(ctx.eligible("t1both", "dtask"),
                        "tier1 + bounded-build is the delegated fallback")
        self.assertFalse(ctx.eligible("t2rev", "dtask"),
                         "reconcile-only never builds a packet")
        self.assertTrue(ctx.eligible("t1both", "otask"))
        self.assertFalse(ctx.eligible("t2rev", "otask"))

    def test_a_grammar_invalid_registry_refuses_the_context(self) -> None:
        # [profile.<id>] is precisely the shape the production
        # validator rejects — and the shape a lookalike parser once
        # accepted. Building a context from it must refuse by name.
        from benchmark_runner.routing_eval.routing_quality import (
            selector_context_from_registry,
        )

        registry = _FIXDIR / "grammar-invalid.toml"
        registry.write_text(
            "schema_version = 1\n"
            "[profile.alpha]\n"
            'capability_tier = "tier1"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "production validator"):
            selector_context_from_registry(registry, _config())

    def test_a_semantically_invalid_registry_refuses_the_context(self) -> None:
        # Grammar-valid but semantically invalid: a profile missing
        # required fields (backend/provider/model/roles/...). rc_parse
        # alone would admit it; the builder runs the production
        # rc_validate path, exactly what the supervisor runs.
        from benchmark_runner.routing_eval.routing_quality import (
            selector_context_from_registry,
        )

        registry = _FIXDIR / "semantic-invalid.toml"
        registry.write_text(
            "schema_version = 1\n"
            "[policy]\n"
            "enabled = true\n"
            "[[profiles]]\n"
            'id = "hollow"\n'
            'capability_tier = "tier1"\n'
            "priority = 10\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ControlSetIncomplete,
                                    "production validator"):
            selector_context_from_registry(registry, _config())


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
                              expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)
        arm = report["arms"]["cct_router"]
        self.assertEqual(arm["metrics"]["reconciliation_rework_ratio"],
                         INSUFFICIENT)
        self.assertEqual(arm["metrics"]["tier2_accepted_unchanged"],
                         INSUFFICIENT)
        self.assertIn("sequence_dependent", arm["insufficient"])
        # rows 9-11 are outside quality_fn: Q stays reported
        self.assertIsNotNone(arm["quality"])

    def test_oracle_budget_insufficiency_is_carried_not_dropped(self) -> None:
        from benchmark_runner.routing_eval.outcome_matrix import select_oracle
        from benchmark_runner.routing_eval.quality_fn import (
            cell_quality,
            compute_mask,
        )
        from benchmark_runner.routing_eval.routing_quality import INSUFFICIENT

        budget_config = _config(budget=0.001)
        budget_preset = preset_digest(budget_config)
        cells = [
            _cell("t1", "alpha", 0, cost=0.05),
            _cell("t1", "beta", 0, result="fail", cost=0.01),
        ]
        matrix = _matrix(cells, preset=budget_preset)
        controls = {
            "always_best": _selection("always_best", [cells[0]]),
            "always_cheapest": _selection("always_cheapest", [cells[1]]),
            "oracle": _selection("oracle", [cells[0]]),
        }
        # a ceiling below every cell's cost: the SELECTOR ITSELF yields
        # a genuinely insufficient oracle_budget selection
        mask = compute_mask(matrix)
        controls["oracle_budget"] = select_oracle(
            matrix, lambda c: cell_quality(c, mask), 0.001
        )
        self.assertTrue(controls["oracle_budget"].insufficient)
        record = _router_record("t1", 0)
        record["preset_digest"] = budget_preset
        report = build_report(matrix, controls, [record],
                              expected_preset_digest=budget_preset,
                              registry_path=_REGISTRY, config=budget_config)
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
                              expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)
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
                         expected_preset_digest=_PRESET,
                         registry_path=_REGISTRY, config=_CONFIG)


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
