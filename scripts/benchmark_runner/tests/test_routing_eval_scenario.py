# tests/test_routing_eval_scenario.py — routing-eval (E1 of #109) T4.
#
# The pinned rule: leg completeness is proven from durable routing-run
# evidence, never a visited-legs list. This round hardens the verifier
# against the owner's direct counterexamples, each now a regression:
# reordered records, cross-trial evidence stitching, prose traps
# ("rate" inside "accurate"), incomplete packet identity, and records
# not bound to the run's identity. Every synthetic record here is
# SCHEMA-VALID — asserted by a test — so the verifier is never proven
# against evidence its own schema would reject.

from __future__ import annotations

import json
import unittest
from pathlib import Path

from benchmark_runner.routing_eval.scenario import (
    ARC_LEGS,
    ArcIncomplete,
    RecordInvalid,
    run_scenario,
    verify_arc,
)
from benchmark_runner.routing_eval.scenario_config import validate_scenario_config
from benchmark_runner.tests.test_routing_eval_schemas import _load_json, validate

REPO_ROOT = Path(__file__).resolve().parents[3]

_PREFERRED = "anthropic-sonnet"
_FALLBACK = "deepseek-v4-pro"
_TIER2 = "local-qwen"
_PKT_ID = "pkt-0042"
_PKT_DIGEST = "sha256:feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface"
_PRESET_DIGEST = "sha256:" + "ab" * 32
_REGISTRY_DIGEST = "sha256:" + "cd" * 32


def _c(pid, verdict, reason, state="unknown"):
    return {"id": pid, "verdict": verdict, "reason": reason, "state": state}


def _decision(considered, selected, provisional_outcome=None, route_class=None):
    return {
        "considered": considered,
        "selected": selected,
        "reason": "decision",
        "requested_model": "m",
        "effective_model": "m",
        "endpoint": "endpoint",
        "failure_classification": None,
        "provisional_outcome": provisional_outcome,
        "route_class": route_class,
    }


def _record(task, trial, decisions, *, tier2=None, reconciliation=None,
            seed=None, injected_events=()):
    """A COMPLETE, schema-valid routing-run record."""
    return {
        "schema_version": 1,
        "registry_digest": _REGISTRY_DIGEST,
        "preset_digest": _PRESET_DIGEST,
        "task_set_revision": "polyglot@3a1f9c2",
        "toolchain_digest": "sha256:" + "ef" * 32,
        "task_id": task,
        "trial": trial,
        "trial_seed": (1701 + trial) if seed is None else seed,
        "mode": "cct_router",
        "profile_id": None,
        "injected_events": list(injected_events),
        "routing_decisions": decisions,
        "tokens": {"input": 100, "output": 50, "cache_read": 0, "cache_write": 0},
        "cost": {"value": 0.01, "provenance": "measured", "estimator": None, "inputs": None},
        "baseline": {"lint_passed": True, "typecheck_passed": True},
        "quality_gates": {
            "coverage": {"before": 80.0, "after": 80.0},
            "security": {"findings_by_severity": {"before": {}, "after": {}}},
        },
        "scope_violations": [],
        "verifiers": [
            {"command": "pytest -q", "exit_status": 0, "evidence_ref": "v/pytest.log"}
        ],
        "repair_cycles": [],
        "interventions": [],
        "tier2": tier2
        or {"delegated": False, "packet_id": None, "packet_digest": None,
            "builder_id": None, "builder_tier": None,
            "builder_provider": None, "builder_model": None,
            "delegated_lines": None, "reconciliation_diff_lines": None},
        "rollbacks": [],
        "reconciliation": reconciliation,
        "insufficient_evidence": None,
    }


def _trial_arc(trial):
    """One complete ordered witness for a single trial."""
    return [
        # initial: the preferred profile is selected for ordinary work.
        _record(f"t0", trial, [_decision(
            [_c(_PREFERRED, "selected", "eligible in tier1 at priority 10", "healthy")],
            _PREFERRED,
        )]),
        # failover: preferred rejected in the closed cooldown STATE.
        _record(f"t1", trial, [_decision(
            [_c(_PREFERRED, "rejected", "cooling until 2099-07-01T00:00:00Z", "cooldown"),
             _c(_FALLBACK, "selected", "eligible in tier1 at priority 20", "unknown")],
            _FALLBACK,
        )]),
        # provisional: delegated with complete packet identity.
        _record(
            f"t2", trial,
            [_decision(
                [_c(_TIER2, "selected", "tier2_fallback unlocked", "unknown")],
                _TIER2, provisional_outcome="verified_provisional",
                route_class="tier2_fallback",
            )],
            tier2={"delegated": True, "packet_id": _PKT_ID,
                   "packet_digest": _PKT_DIGEST,
                   "builder_id": _TIER2, "builder_tier": "tier2",
                   "builder_provider": "local-vllm",
                   "builder_model": "qwen-coder",
                   "delegated_lines": 120,
                   "reconciliation_diff_lines": None},
        ),
        # negative control: route_class tier1_only rejects the tier2 candidate.
        _record(f"t3", trial, [_decision(
            [_c(_TIER2, "rejected", "class tier1_only removes tier2", "unknown"),
             _c(_FALLBACK, "selected", "eligible in tier1", "unknown")],
            _FALLBACK, route_class="tier1_only",
        )]),
        # recovery: an ORDINARY decision selects the preferred profile.
        _record(f"t4", trial, [_decision(
            [_c(_PREFERRED, "selected", "probe-qualified; failback at boundary", "healthy")],
            _PREFERRED,
        )]),
        # reconciliation of the SAME packet (id AND digest).
        _record(
            f"t5", trial,
            [_decision([_c(_PREFERRED, "selected", "reconcile on tier1", "healthy")],
                       _PREFERRED)],
            reconciliation={"packet_id": _PKT_ID, "packet_digest": _PKT_DIGEST,
                            "outcome": "reconciled",
                            "reconciler_id": _PREFERRED,
                            "reconciler_tier": "tier1",
                            "reconciler_provider": "anthropic-subscription",
                            "reconciler_model": "sonnet"},
        ),
    ]


def _verify(records, *, trials=1, tier1_only=("t3",), preset=_PRESET_DIGEST,
            registry=_REGISTRY_DIGEST):
    return verify_arc(
        records,
        preferred_profile=_PREFERRED,
        tier2_profiles=frozenset({_TIER2}),
        tier1_only_tasks=list(tier1_only),
        expected_trials=trials,
        expected_preset_digest=preset,
        expected_registry_digest=registry,
    )


class TestSyntheticRecordsAreSchemaValid(unittest.TestCase):
    """The verifier is never proven against evidence its schema rejects."""

    def test_every_synthetic_record_validates(self) -> None:
        schema = _load_json(REPO_ROOT / "benchmarks" / "schema" / "routing-run.schema.json")
        for i, record in enumerate(_trial_arc(0)):
            with self.subTest(record=i):
                errors = validate(record, schema)
                self.assertEqual(errors, [], errors)


class TestArcProof(unittest.TestCase):
    def test_the_complete_arc_verifies_in_order(self) -> None:
        report = _verify(_trial_arc(0))
        self.assertTrue(report.complete, [(t, l.reason) for t, l in report.missing()])
        legs = {l.leg: l for l in report.trials[0].legs}
        self.assertEqual(tuple(l.leg for l in report.trials[0].legs), ARC_LEGS)
        self.assertEqual(legs["initial_preferred"].evidence, (0,))
        self.assertEqual(legs["failover"].evidence, (1,))
        self.assertEqual(legs["tier2_provisional"].evidence, (2,))
        self.assertEqual(legs["recovery_selection"].evidence, (4,))
        self.assertEqual(legs["reconciliation"].evidence, (2, 5))
        self.assertEqual(legs["tier1_only_refusal"].evidence, (3,))

    def test_the_owners_reorder_counterexample_fails(self) -> None:
        # provisional -> reconciliation -> failover -> recovery -> refusal:
        # previously verified complete; the ordered witness refuses it.
        base = _trial_arc(0)
        reordered = [base[2], base[5], base[1], base[4], base[3], base[0]]
        report = _verify(reordered)
        self.assertFalse(report.complete)

    def test_each_removed_record_fails_its_leg(self) -> None:
        base = _trial_arc(0)
        # Dropping the initial record makes the RECOVERY record the
        # earliest preferred-selection, so the chain honestly breaks at
        # failover — either blame proves the arc broken.
        drops = {
            "initial_preferred": (0, {"initial_preferred", "failover"}),
            "failover": (1, {"failover"}),
            "tier2_provisional": (2, {"tier2_provisional"}),
            "recovery_selection": (4, {"recovery_selection"}),
            "reconciliation": (5, {"reconciliation"}),
        }
        for leg, (drop, accepted) in drops.items():
            with self.subTest(leg=leg):
                records = [r for i, r in enumerate(base) if i != drop]
                report = _verify(records)
                self.assertFalse(report.complete)
                missing = {l.leg for _t, l in report.missing()}
                self.assertTrue(missing & accepted, f"missing={missing}")

    def test_cross_trial_evidence_never_combines(self) -> None:
        # The owner's counterexample: initial+failover+provisional in
        # trial 0, recovery+reconciliation+refusal in trial 1. Neither
        # trial completes the arc; the report must fail BOTH.
        t0 = _trial_arc(0)[:3]
        t1 = [_record(r["task_id"], 1, r["routing_decisions"],
                      tier2=r["tier2"], reconciliation=r["reconciliation"])
              for r in _trial_arc(0)[3:]]
        report = _verify(t0 + t1, trials=2)
        self.assertFalse(report.complete)
        missing_trials = {t for t, _l in report.missing()}
        self.assertEqual(missing_trials, {0, 1})

    def test_every_declared_trial_must_prove_the_arc(self) -> None:
        # A complete trial 0 does not cover a silent trial 1.
        report = _verify(_trial_arc(0), trials=2)
        self.assertFalse(report.complete)
        self.assertIn(1, {t for t, _l in report.missing()})
        # Both trials complete -> the report completes.
        report2 = _verify(_trial_arc(0) + _trial_arc(1), trials=2)
        self.assertTrue(report2.complete)

    def test_packet_join_requires_both_id_and_digest(self) -> None:
        for field, value in (("packet_id", "pkt-9999"),
                             ("packet_digest", "sha256:" + "0" * 64)):
            with self.subTest(mismatched=field):
                records = _trial_arc(0)
                records[5] = dict(records[5])
                records[5]["reconciliation"] = {
                    **records[5]["reconciliation"], field: value
                }
                report = _verify(records)
                self.assertIn(
                    "reconciliation", [l.leg for _t, l in report.missing()]
                )

    def test_contradictory_tier_evidence_fails_its_leg(self) -> None:
        # The owner's gap: 'delegated' + packet join passed without the
        # EXECUTING tier. A tier1 builder fails the Tier-2 leg; a tier2
        # reconciler fails the reconciliation leg.
        records = _trial_arc(0)
        records[2] = dict(records[2])
        records[2]["tier2"] = {**records[2]["tier2"], "builder_tier": "tier1"}
        report = _verify(records)
        self.assertIn("tier2_provisional", [l.leg for _t, l in report.missing()])

        records2 = _trial_arc(0)
        records2[5] = dict(records2[5])
        records2[5]["reconciliation"] = {
            **records2[5]["reconciliation"], "reconciler_tier": "tier2"
        }
        report2 = _verify(records2)
        self.assertIn("reconciliation", [l.leg for _t, l in report2.missing()])

    def test_unknown_builder_identity_fails_the_tier2_leg(self) -> None:
        records = _trial_arc(0)
        records[2] = dict(records[2])
        records[2]["tier2"] = {**records[2]["tier2"], "builder_id": "stranger",
                               "builder_tier": "tier2"}
        report = _verify(records)
        self.assertIn("tier2_provisional", [l.leg for _t, l in report.missing()])

    def test_probe_due_is_also_closed_unavailability_evidence(self) -> None:
        # A past provider reset makes the state probe_due at the
        # boundary — expired-but-unprobed is still unavailable-pending-
        # recovery, and still a closed state, never prose.
        records = _trial_arc(0)
        records[1] = _record("t1", 0, [_decision(
            [_c(_PREFERRED, "rejected", "recovery pending", "pool:probe_due"),
             _c(_FALLBACK, "selected", "eligible in tier1", "unknown")],
            _FALLBACK,
        )])
        report = _verify(records)
        self.assertTrue(report.complete, [(t, l.reason) for t, l in report.missing()])

    def test_a_contaminated_control_fails_even_with_a_valid_refusal(self) -> None:
        # The owner's counterexample: the control task ALSO carries a
        # Tier-2 provisional record before its valid refusal. The
        # refusal witness alone must never certify the control — any
        # Tier-2 execution evidence in the control's stream fails it.
        records = _trial_arc(0)
        contaminating = _record(
            "t3", 0,
            [_decision([_c(_TIER2, "selected", "delegated", "unknown")],
                       _TIER2, provisional_outcome="verified_provisional",
                       route_class="tier2_preferred")],
            tier2={"delegated": True, "packet_id": "pkt-evil",
                   "packet_digest": "sha256:" + "e" * 64,
                   "builder_id": _TIER2, "builder_tier": "tier2",
                   "builder_provider": "local-vllm",
                   "builder_model": "qwen-coder",
                   "delegated_lines": 5,
                   "reconciliation_diff_lines": None},
        )
        records.insert(3, contaminating)  # before t3's valid refusal record
        report = _verify(records)
        by_leg = {l.leg: l for l in report.trials[0].legs}
        self.assertFalse(by_leg["tier1_only_refusal"].satisfied)
        self.assertIn("CONTAMINATED control", by_leg["tier1_only_refusal"].reason)

    def test_reconciliation_requires_independence_not_just_tier1(self) -> None:
        # Increment C's frozen predicate, verified from the records:
        # same provider refuses; same model refuses even across
        # providers; unknown identity is unevaluable, never successful.
        cases = {
            "same provider": {"reconciler_provider": "local-vllm"},
            "same model across providers": {"reconciler_model": "qwen-coder"},
        }
        for label, override in cases.items():
            with self.subTest(case=label):
                records = _trial_arc(0)
                records[5] = dict(records[5])
                records[5]["reconciliation"] = {
                    **records[5]["reconciliation"], **override
                }
                report = _verify(records)
                self.assertIn(
                    "reconciliation", [l.leg for _t, l in report.missing()]
                )

    def test_unknown_identity_is_unevaluable_never_independent(self) -> None:
        # Missing builder identity makes independence unverifiable; the
        # witness must fail rather than succeed. (Schema-level nulls in
        # a delegated block are separately rejected; this mutation
        # blanks the builder provider via a schema-valid non-delegated
        # shape being impossible, so we blank the reconciler's model —
        # the same unevaluable branch of the predicate.)
        records = _trial_arc(0)
        records[5] = dict(records[5])
        records[5]["reconciliation"] = {
            **records[5]["reconciliation"], "reconciler_model": "x"
        }
        records[2] = dict(records[2])
        records[2]["tier2"] = {**records[2]["tier2"], "builder_model": "x"}
        # equal models -> collision -> unverifiable witness
        report = _verify(records)
        self.assertIn("reconciliation", [l.leg for _t, l in report.missing()])

    def test_prose_never_proves_a_state(self) -> None:
        # The owner's traps: "accurate" contains "rate"; "tier1 is
        # cheaper" mentions tier1. Neither the cooling rejection nor
        # the route refusal may be proven by prose.
        records = _trial_arc(0)
        records[1] = _record("t1", 0, [_decision(
            [_c(_PREFERRED, "rejected",
                "rejected because this model is accurate but ineligible", "unknown"),
             _c(_FALLBACK, "selected", "selected", "unknown")],
            _FALLBACK,
        )])
        records[3] = _record("t3", 0, [_decision(
            [_c(_TIER2, "rejected", "tier2 rejected because tier1 is cheaper", "unknown"),
             _c(_FALLBACK, "selected", "selected", "unknown")],
            _FALLBACK, route_class=None,
        )])
        report = _verify(records)
        missing = [l.leg for _t, l in report.missing()]
        self.assertIn("failover", missing)
        self.assertIn("tier1_only_refusal", missing)

    def test_a_passing_probe_is_not_recovery(self) -> None:
        records = _trial_arc(0)
        records[4] = _record("t4", 0, [_decision(
            [_c(_PREFERRED, "eligible", "probe passed; healthy", "healthy"),
             _c(_FALLBACK, "selected", "still active", "unknown")],
            _FALLBACK,
        )])
        report = _verify(records)
        missing = [l.leg for _t, l in report.missing()]
        self.assertIn("recovery_selection", missing)

    def test_the_reconciliation_run_is_not_recovery_evidence(self) -> None:
        records = [r for i, r in enumerate(_trial_arc(0)) if i != 4]
        report = _verify(records)
        self.assertIn("recovery_selection", [l.leg for _t, l in report.missing()])

    def test_no_declared_negative_controls_is_not_a_pass(self) -> None:
        report = _verify(_trial_arc(0), tier1_only=())
        self.assertIn("tier1_only_refusal", [l.leg for _t, l in report.missing()])


class TestRecordIdentityBinding(unittest.TestCase):
    def test_foreign_preset_digest_is_refused(self) -> None:
        records = _trial_arc(0)
        records[2] = dict(records[2], preset_digest="sha256:" + "99" * 32)
        with self.assertRaisesRegex(RecordInvalid, "another preset"):
            _verify(records)

    def test_mixed_registry_digests_are_refused(self) -> None:
        records = _trial_arc(0)
        records[3] = dict(records[3], registry_digest="sha256:" + "77" * 32)
        with self.assertRaisesRegex(RecordInvalid, "foreign registry"):
            _verify(records)

    def test_matrix_sweep_cells_are_not_arc_evidence(self) -> None:
        records = _trial_arc(0)
        records[1] = dict(records[1], mode="profile_sweep", profile_id=_FALLBACK)
        with self.assertRaisesRegex(RecordInvalid, "cct_router"):
            _verify(records)

    def test_undeclared_trial_indices_are_refused(self) -> None:
        records = _trial_arc(0) + _trial_arc(7)
        with self.assertRaisesRegex(RecordInvalid, "undeclared trial"):
            _verify(records, trials=1)

    def test_missing_required_shape_is_refused(self) -> None:
        records = _trial_arc(0)
        broken = dict(records[0])
        del broken["registry_digest"]
        records[0] = broken
        with self.assertRaisesRegex(RecordInvalid, "registry_digest"):
            _verify(records)


class TestScenarioDriver(unittest.TestCase):
    def _config(self, **overrides):
        payload = {
            "benchmark": "stub",
            "scenario": "hybrid-routing",
            "cost_basis": "measured",
            "trials": 1,
            "trial_seeds": [1701],
            "task": ["t0", "t1", "t2", "t3", "t4", "t5"],
            "tier1_only_tasks": ["t3"],
            "event_stream": [
                {"at_task_index": 1, "outcome": "usage_limit",
                 "reset_at": "2099-07-01T00:00:00Z", "retry_after_sec": 900},
            ],
            "arms": [
                {"kind": "always_best"},
                {"kind": "always_cheapest"},
                {"kind": "oracle"},
                {"kind": "cct_router", "registry": "routing.toml"},
            ],
        }
        payload.update(overrides)
        return validate_scenario_config(payload)

    @staticmethod
    def _bound_records(config):
        """Arc records bound to the config's invocation identity."""
        from benchmark_runner.routing_eval.injection import (
            events_for_task, preset_digest,
        )

        digest = preset_digest(config)
        seed = config.trial_seeds[0]
        by_task = {}
        for r in _trial_arc(0):
            task_index = config.task_filter.index(r["task_id"])
            scheduled = events_for_task(config.event_stream, task_index)
            by_task[r["task_id"]] = dict(
                r, preset_digest=digest, trial_seed=seed,
                injected_events=[
                    {"at_task_index": e.at_task_index, "outcome": e.outcome,
                     "reset_at": e.reset_at, "retry_after_sec": e.retry_after_sec}
                    for e in scheduled
                ],
            )
        return by_task

    def test_complete_run_produces_a_verified_artifact(self) -> None:
        from benchmark_runner.routing_eval.injection import preset_digest

        config = self._config()
        digest = preset_digest(config)
        by_task = self._bound_records(config)
        seen_events = {}

        def run_task(task, trial, seed, events):
            seen_events[task] = [e.outcome for e in events]
            return [by_task[task]]

        artifact = run_scenario(
            config, run_task,
            preferred_profile=_PREFERRED, tier2_profiles={_TIER2},
            expected_registry_digest=_REGISTRY_DIGEST,
        )
        self.assertTrue(artifact.arc.complete)
        self.assertEqual(artifact.preset_digest, digest)
        self.assertEqual(len(artifact.records), 6)
        self.assertEqual(seen_events["t1"], ["usage_limit"])
        self.assertEqual(seen_events["t0"], [])

    def test_a_partial_arc_is_never_reported_as_a_run(self) -> None:
        config = self._config()
        by_task = self._bound_records(config)
        by_task["t5"] = dict(by_task["t5"], reconciliation=None)
        with self.assertRaisesRegex(ArcIncomplete, "reconciliation"):
            run_scenario(
                config, lambda t, tr, s, e: [by_task[t]],
                preferred_profile=_PREFERRED, tier2_profiles={_TIER2},
                expected_registry_digest=_REGISTRY_DIGEST,
            )


class TestInvocationBinding(unittest.TestCase):
    """Records are bound to the run_task invocation that produced them."""

    def _config(self):
        return TestScenarioDriver._config(TestScenarioDriver())

    def test_one_callback_cannot_return_the_whole_arc(self) -> None:
        # The owner's reproduction: everything returned during t0,
        # nothing after — previously complete=True.
        config = self._config()
        by_task = TestScenarioDriver._bound_records(config)
        all_records = [by_task[t] for t in config.task_filter]

        def run_task(task, trial, seed, events):
            return all_records if task == "t0" else []

        with self.assertRaisesRegex(RecordInvalid, "bound to the invocation"):
            run_scenario(
                config, run_task,
                preferred_profile=_PREFERRED, tier2_profiles={_TIER2},
                expected_registry_digest=_REGISTRY_DIGEST,
            )

    def test_wrong_seed_is_refused(self) -> None:
        config = self._config()
        by_task = TestScenarioDriver._bound_records(config)
        by_task["t0"] = dict(by_task["t0"], trial_seed=9999)
        with self.assertRaisesRegex(RecordInvalid, "bound to the invocation"):
            run_scenario(
                config, lambda t, tr, s, e: [by_task[t]],
                preferred_profile=_PREFERRED, tier2_profiles={_TIER2},
                expected_registry_digest=_REGISTRY_DIGEST,
            )

    def test_false_event_provenance_is_refused(self) -> None:
        # A record claiming no events for the task that received the
        # quota event is knowingly false provenance.
        config = self._config()
        by_task = TestScenarioDriver._bound_records(config)
        by_task["t1"] = dict(by_task["t1"], injected_events=[])
        with self.assertRaisesRegex(RecordInvalid, "event provenance"):
            run_scenario(
                config, lambda t, tr, s, e: [by_task[t]],
                preferred_profile=_PREFERRED, tier2_profiles={_TIER2},
                expected_registry_digest=_REGISTRY_DIGEST,
            )

    def test_schema_violating_record_is_refused_at_runtime(self) -> None:
        # The owner's reproduction: tokens removed from every record
        # still verified. The FULL schema now gates verification.
        records = _trial_arc(0)
        for r in records:
            del r["tokens"]
        with self.assertRaisesRegex(RecordInvalid, "routing-run.schema.json"):
            _verify(records)


class TestHybridPreset(unittest.TestCase):
    def test_checked_in_preset_parses_and_validates(self) -> None:
        from benchmark_runner.routing_eval.scenario_config import load_scenario_config

        path = REPO_ROOT / "benchmarks" / "presets" / "hybrid-routing.json"
        cfg = load_scenario_config(path)
        self.assertEqual(len(cfg.task_filter), 6)
        self.assertEqual(len(cfg.tier1_only_tasks), 2)
        self.assertEqual(cfg.delegate_tasks, ["python/book-store"])
        self.assertEqual(cfg.trials, 3)
        # Deterministic and immediately probeable: the provider reset
        # is in the past, and no event lands on the delegated task.
        quota = [e for e in cfg.event_stream if e.outcome == "quota_exhausted"]
        self.assertEqual(quota[0].reset_at, "2000-01-01T00:00:00Z")
        delegated_index = cfg.task_filter.index("python/book-store")
        self.assertFalse(
            [e for e in cfg.event_stream if e.at_task_index == delegated_index]
        )
        schema = _load_json(REPO_ROOT / "benchmarks" / "schema" / "compare-config.schema.json")
        self.assertEqual(validate(_load_json(path), schema), [])

    def test_negative_controls_change_the_preset_digest(self) -> None:
        from benchmark_runner.routing_eval.injection import preset_digest

        base = TestScenarioDriver._config(TestScenarioDriver())
        changed = TestScenarioDriver._config(
            TestScenarioDriver(), tier1_only_tasks=["t3", "t4"]
        )
        self.assertNotEqual(preset_digest(base), preset_digest(changed))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
