# session_analytics.tests.test_routing_evidence — routing-shadow T2.
#
# Shadow-mode recommendation derivation as a deterministic projection
# of E1's served figures. The owner's top discriminator is pinned
# first: a control arm may dominate NUMERICALLY, but if its suggested
# profile is unavailable according to the router's durable candidate
# evidence, the result is insufficient_data — never an inactionable
# switch_profile. That is the boundary between T1's
# availability-neutral capability matrix and T2's actionable
# recommendation semantics.

from __future__ import annotations

import json
import unittest
from pathlib import Path

from benchmark_runner.routing_eval.quality_fn import COMPONENTS
from benchmark_runner.routing_eval.record_check import load_schema, validate
from session_analytics.routing_evidence import (
    EXECUTABLE_CANDIDATES,
    InvalidEvidenceSet,
    LoadedEvidenceSet,
    derive_recommendations,
    load_evidence_sets,
)

_SET_ID = "ab" * 32
_FULL_MASK = [c.name for c in COMPONENTS]


def _report(task_figures, selections=None, components=None):
    """A minimal report shape carrying exactly what derivation
    consumes: per-arm per-task figures with per-trial rows, selection
    provenance, the mask, and the basis."""
    arms = {}
    for arm, tasks in task_figures.items():
        arms[arm] = {
            "quality": 1.0, "metrics": {}, "cost": {"value": 0.1,
                                                    "status": "ok",
                                                    "reason": None},
            "insufficient": {},
            "selections": (selections or {}).get(arm, {}),
            "tasks": tasks,
        }
    return {
        "schema_version": 1,
        "quality_fn": "v1",
        "components_included": components or list(_FULL_MASK),
        "cost_basis": "measured",
        "preset_digest": "sha256:" + "cd" * 32,
        "arms": arms,
        "pareto": {"status": "ok", "frontier": []},
    }


def _task(quality, cost, per_trial=None):
    return {
        "quality": quality,
        "cost": cost,
        "per_trial": per_trial if per_trial is not None else [
            {"trial": 0, "quality": quality, "cost": cost}
        ],
    }


def _router_record(task, trial=0, considered=(), selected="router-prof",
                   delegated=False, reconciled=False):
    record = {
        "task_id": task,
        "trial": trial,
        "routing_decisions": [{
            "considered": list(considered),
            "selected": selected,
        }],
        "tier2": {"delegated": delegated},
        "reconciliation": (
            {"packet_id": "p", "packet_digest": "d", "outcome": "reconciled"}
            if reconciled else None
        ),
    }
    return record


def _loaded(report, records) -> LoadedEvidenceSet:
    return LoadedEvidenceSet(
        set_id=_SET_ID,
        path=Path("/nonexistent"),
        manifest={},
        report=report,
        matrix={},
        records=list(records),
    )


def _figures_for(*, router, best, cheapest, oracle=(0.9, 0.05)):
    return {
        "cct_router": {"t": _task(*router)},
        "always_best": {"t": _task(*best)},
        "always_cheapest": {"t": _task(*cheapest)},
        "oracle": {"t": _task(*oracle)},
    }


_ADMISSIBLE = ({"id": "alpha", "verdict": "eligible",
                "reason": "eligible in tier1", "state": "healthy"},)
_UNAVAILABLE = ({"id": "alpha", "verdict": "rejected",
                 "reason": "cooling until X (cooldown)",
                 "state": "cooldown"},)
_SELECTIONS = {"always_best": {"t": "alpha"},
               "always_cheapest": {"t": "alpha"}}


class TestAvailabilityGuard(unittest.TestCase):
    """The owner's named T2 discriminator."""

    def test_a_dominating_but_unavailable_profile_never_switches(self) -> None:
        # alpha dominates numerically (better quality, cheaper) — but
        # the router's durable candidate evidence shows it ONLY as
        # availability-rejected for this task.
        report = _report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_UNAVAILABLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "insufficient_data")
        self.assertIsNone(rec["suggested"])
        self.assertTrue(any(
            ref.startswith("availability/")
            for ref in rec["confidence"]["basis"]["insufficiency_refs"]
        ))
        # the availability evidence is addressable
        self.assertTrue(any(
            ref["artifact"] == "routing_runs"
            for ref in rec["evidence_refs"]
        ))

    def test_an_admissible_dominating_profile_switches(self) -> None:
        report = _report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "switch_profile")
        self.assertEqual(rec["suggested"],
                         {"arm": "always_best", "profile_id": "alpha"})

    def test_a_profile_absent_from_all_candidate_evidence_never_switches(
        self,
    ) -> None:
        report = _report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=())]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "insufficient_data")


class TestDominanceRule(unittest.TestCase):
    def test_router_outperforming_every_control_is_no_change(self) -> None:
        # The plan's founding counterexample: configured-best is not
        # observed-best; identity difference alone recommends nothing.
        report = _report(
            _figures_for(router=(1.0, 0.01), best=(0.5, 0.05),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "no_change_recommended")
        self.assertIsNone(rec["suggested"])

    def test_equal_quality_strictly_cheaper_switches(self) -> None:
        report = _report(
            _figures_for(router=(1.0, 0.05), best=(0.5, 0.05),
                         cheapest=(1.0, 0.01)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "switch_profile")
        self.assertEqual(rec["suggested"]["arm"], "always_cheapest")

    def test_within_tolerance_differences_never_flip_an_outcome(self) -> None:
        # harmless float noise: candidate "better" by less than the
        # declared 1e-9 tolerance is a tie, not dominance
        report = _report(
            _figures_for(router=(1.0, 0.05),
                         best=(1.0 + 5e-10, 0.05),
                         cheapest=(0.4, 0.05 - 5e-10)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "no_change_recommended")

    def test_divergence_is_the_declared_subtraction(self) -> None:
        report = _report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertAlmostEqual(
            rec["divergence"]["always_best"]["quality_delta"], -0.5
        )
        self.assertAlmostEqual(
            rec["divergence"]["always_best"]["cost_delta"], 0.04
        )
        self.assertEqual(rec["divergence"]["always_best"]["cost_basis"],
                         "measured")


class TestInsufficiencyNeverCollapses(unittest.TestCase):
    def test_missing_candidate_figures_yield_insufficient_data(self) -> None:
        figures = _figures_for(router=(0.5, 0.05), best=(None, None),
                               cheapest=(0.4, 0.02))
        report = _report(figures, selections=_SELECTIONS)
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "insufficient_data")
        self.assertTrue(rec["confidence"]["basis"]["insufficiency_refs"])
        self.assertEqual(rec["confidence"]["grade"], "low")

    def test_a_task_absent_from_a_candidate_table_is_insufficient(self) -> None:
        figures = _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                               cheapest=(0.4, 0.02))
        del figures["always_cheapest"]["t"]
        report = _report(figures, selections=_SELECTIONS)
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "insufficient_data")

    def test_missing_router_figures_are_insufficient(self) -> None:
        report = _report(
            _figures_for(router=(None, None), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "insufficient_data")


class TestConfidence(unittest.TestCase):
    def _three_trial_report(self, candidate_costs):
        router_rows = [{"trial": i, "quality": 0.5, "cost": 0.02}
                       for i in range(3)]
        best_rows = [{"trial": i, "quality": 1.0, "cost": candidate_costs[i]}
                     for i in range(3)]
        figures = {
            "cct_router": {"t": {"quality": 0.5, "cost": 0.02,
                                 "per_trial": router_rows}},
            "always_best": {"t": {
                "quality": 1.0,
                "cost": sum(candidate_costs) / 3,
                "per_trial": best_rows,
            }},
            "always_cheapest": {"t": _task(0.1, 0.05)},
            "oracle": {"t": _task(1.0, 0.01)},
        }
        return _report(figures, selections=_SELECTIONS)

    def test_agreement_uses_the_two_axis_predicate(self) -> None:
        # aggregate dominance holds (mean cost 0.02 == router, quality
        # strictly better) but per-trial the candidate is MORE
        # expensive in 2 of 3 trials: two-axis agreement is 1/3 and
        # the grade is low. A quality-only agreement would score 3/3
        # high — the declared discriminating mutation.
        report = self._three_trial_report([0.03, 0.03, 0.0])
        records = [_router_record("t", trial=i, considered=_ADMISSIBLE)
                   for i in range(3)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "switch_profile")
        self.assertAlmostEqual(
            rec["confidence"]["basis"]["agreement"], 1 / 3
        )
        self.assertEqual(rec["confidence"]["grade"], "low")

    def test_unpriced_per_trial_cost_caps_the_grade_at_low(self) -> None:
        report = self._three_trial_report([0.01, 0.01, 0.01])
        report["arms"]["always_best"]["tasks"]["t"]["per_trial"][1][
            "cost"
        ] = None
        records = [_router_record("t", trial=i, considered=_ADMISSIBLE)
                   for i in range(3)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["confidence"]["grade"], "low")
        self.assertEqual(
            rec["confidence"]["basis"]["unevaluated_trials"], [1],
            "the unpriced trial is NAMED as insufficient confidence "
            "evidence",
        )

    def test_full_agreement_with_enough_trials_grades_high(self) -> None:
        router_rows = [{"trial": i, "quality": 0.5, "cost": 0.02}
                       for i in range(5)]
        best_rows = [{"trial": i, "quality": 1.0, "cost": 0.01}
                     for i in range(5)]
        figures = {
            "cct_router": {"t": {"quality": 0.5, "cost": 0.02,
                                 "per_trial": router_rows}},
            "always_best": {"t": {"quality": 1.0, "cost": 0.01,
                                  "per_trial": best_rows}},
            "always_cheapest": {"t": _task(0.1, 0.05)},
            "oracle": {"t": _task(1.0, 0.01)},
        }
        report = _report(figures, selections=_SELECTIONS)
        records = [_router_record("t", trial=i, considered=_ADMISSIBLE)
                   for i in range(5)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["confidence"]["grade"], "high")
        self.assertAlmostEqual(rec["confidence"]["basis"]["agreement"], 1.0)

    def test_a_masked_component_caps_below_high(self) -> None:
        router_rows = [{"trial": i, "quality": 0.5, "cost": 0.02}
                       for i in range(5)]
        best_rows = [{"trial": i, "quality": 1.0, "cost": 0.01}
                     for i in range(5)]
        figures = {
            "cct_router": {"t": {"quality": 0.5, "cost": 0.02,
                                 "per_trial": router_rows}},
            "always_best": {"t": {"quality": 1.0, "cost": 0.01,
                                  "per_trial": best_rows}},
            "always_cheapest": {"t": _task(0.1, 0.05)},
            "oracle": {"t": _task(1.0, 0.01)},
        }
        report = _report(figures, selections=_SELECTIONS,
                         components=list(_FULL_MASK)[:-1])
        records = [_router_record("t", trial=i, considered=_ADMISSIBLE)
                   for i in range(5)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["confidence"]["grade"], "low")


class TestDeterminismAndContract(unittest.TestCase):
    def test_identical_inputs_give_byte_identical_records(self) -> None:
        report = _report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_ADMISSIBLE)]
        a = derive_recommendations(_loaded(report, records))
        b = derive_recommendations(_loaded(report, records))
        self.assertEqual(
            json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True)
        )

    def test_every_record_validates_and_the_actual_chain_is_carried(self) -> None:
        report = _report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_ADMISSIBLE,
                                  selected="router-prof",
                                  delegated=True, reconciled=True)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(validate(rec, load_schema("recommendation")), [])
        trial = rec["actual"]["per_trial"][0]
        self.assertEqual(trial["chain"], ["router-prof"])
        self.assertTrue(trial["delegated"])
        self.assertTrue(trial["reconciled"])
        self.assertEqual(rec["oracle_ceiling"], {"quality": 0.9,
                                                 "cost": 0.05})


class TestEvidenceLoading(unittest.TestCase):
    """Loading through E1's OWN validation, against a REAL published
    set built with the T1 writers (no supervisor needed)."""

    def _publish_fixture(self, base: Path):
        import dataclasses

        from benchmark_runner.routing_eval.evidence_set import _publish
        from benchmark_runner.routing_eval.outcome_matrix import (
            Cell,
            Fingerprint,
            OutcomeMatrix,
        )
        from benchmark_runner.routing_eval.redaction import write_run_records
        from benchmark_runner.tests.test_routing_eval_quality import (
            _CONFIG,
            _PRESET,
            _REG_DIGEST,
            _REGISTRY,
            _cell,
            _matrix,
            _selection,
        )
        from benchmark_runner.tests.test_routing_eval_redaction import (
            _valid_record,
        )
        from benchmark_runner.routing_eval.routing_quality import build_report

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
        # a FULLY schema-valid routing-run record whose shared
        # fingerprint components match the matrix, with evaluable
        # evidence for every quality component
        record = _valid_record(base)
        record.update({
            "task_id": "t1", "trial": 0, "trial_seed": 1,
            "registry_digest": _REG_DIGEST, "preset_digest": _PRESET,
            "task_set_revision": "rev", "toolchain_digest": "sha256:tc",
            "baseline": {"lint_passed": True, "typecheck_passed": True},
            "quality_gates": {
                "coverage": {"before": 80.0, "after": 80.0},
                "security": {"findings_by_severity":
                             {"before": {}, "after": {}}},
            },
            "cost": {"value": 0.02, "provenance": "measured",
                     "estimator": None, "inputs": None},
        })
        record.pop("insufficient_evidence", None)
        report = build_report(matrix, controls, [record],
                              expected_preset_digest=_PRESET,
                              registry_path=_REGISTRY, config=_CONFIG)
        report.pop("source_artifacts", None)
        ledger = base / "ledger"
        runs = write_run_records([record], ledger / "runs.jsonl",
                                 evidence_root=ledger, secret_values=())
        return _publish(
            base / "out",
            runs_path=runs,
            evidence_root=ledger,
            records=[record],
            matrix=matrix,
            report=dict(report),
            fingerprint=matrix.fingerprint,
        )

    def test_valid_sets_load_and_derive_schema_valid_records(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            published = self._publish_fixture(base)
            loaded = load_evidence_sets([base / "out"])
            self.assertEqual(len(loaded), 1)
            (entry,) = loaded
            self.assertIsInstance(entry, LoadedEvidenceSet)
            self.assertEqual(entry.set_id, published.set_id)
            recs = derive_recommendations(entry)
            schema = load_schema("recommendation")
            for rec in recs:
                self.assertEqual(validate(rec, schema), [])
                self.assertEqual(rec["evidence_set_id"], published.set_id)

    def test_a_tampered_set_surfaces_as_invalid_never_skipped(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            published = self._publish_fixture(base)
            report_path = published.path / "report.json"
            doc = json.loads(report_path.read_text(encoding="utf-8"))
            doc["arms"]["always_best"]["quality"] = 0.42
            report_path.write_text(
                json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            loaded = load_evidence_sets([base / "out"])
            self.assertEqual(len(loaded), 1)
            (entry,) = loaded
            self.assertIsInstance(entry, InvalidEvidenceSet)
            self.assertEqual(entry.state, "invalid_evidence")
            self.assertEqual(entry.code, "hash_mismatch")
            # sanitized: no path fragment in the surfaced detail
            self.assertNotIn(tmp, entry.detail)
            self.assertNotIn("/", entry.detail.replace("<path>", ""))


if __name__ == "__main__":
    unittest.main()
