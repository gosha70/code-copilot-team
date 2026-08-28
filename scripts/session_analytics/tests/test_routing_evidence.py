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


class TestDeclaredInsufficiencyPropagates(unittest.TestCase):
    """T2 round-1 finding 1: arm-level insufficiency entries and a
    withheld frontier govern BEFORE dominance — numeric per-task
    figures do not launder them."""

    def _base(self):
        return _report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )

    def test_router_arm_insufficiency_yields_insufficient_data(self) -> None:
        report = self._base()
        report["arms"]["cct_router"]["insufficient"] = {
            "sequence_dependent": "delegated cells lack line counts"
        }
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "insufficient_data")
        self.assertTrue(any(
            ref.startswith("cct_router/insufficient/sequence_dependent")
            for ref in rec["confidence"]["basis"]["insufficiency_refs"]
        ))

    def test_a_withheld_frontier_yields_insufficient_data(self) -> None:
        report = self._base()
        report["pareto"] = {"status": "insufficient_evidence",
                            "reason": "an arm's cost does not satisfy the basis"}
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "insufficient_data")
        self.assertTrue(any(
            ref.startswith("pareto:")
            for ref in rec["confidence"]["basis"]["insufficiency_refs"]
        ))

    def test_candidate_arm_insufficiency_yields_insufficient_data(self) -> None:
        report = self._base()
        report["arms"]["always_cheapest"]["insufficient"] = {
            "cost": "mixed provenance"
        }
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "insufficient_data")


class TestToleranceAwareTieBreak(unittest.TestCase):
    def test_sub_tolerance_quality_never_picks_the_costlier_arm(self) -> None:
        # The owner's exact counterexample: both candidates dominate;
        # their qualities differ by 5e-10 (a tie under the declared
        # tolerance), so the LOWER-COST arm must win — exact-float
        # ordering would pick always_best on the phantom 5e-10 edge.
        report = _report(
            {
                "cct_router": {"t": _task(0.5, 0.10)},
                "always_best": {"t": _task(1.0 + 5e-10, 0.09)},
                "always_cheapest": {"t": _task(1.0, 0.01)},
                "oracle": {"t": _task(1.0, 0.01)},
            },
            selections=_SELECTIONS,
        )
        records = [_router_record("t", considered=_ADMISSIBLE)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["outcome"], "switch_profile")
        self.assertEqual(rec["suggested"]["arm"], "always_cheapest",
                         "harmless rounding must never change WHICH "
                         "profile is recommended")


class TestMaskIdentity(unittest.TestCase):
    def _five_trial_report(self, components):
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
        return _report(figures, selections=_SELECTIONS,
                       components=components)

    def test_a_duplicated_and_omitted_component_never_grades_high(self) -> None:
        # right LENGTH, wrong SET: one component duplicated, another
        # omitted — a count check would grade high
        broken = list(_FULL_MASK)
        broken[-1] = broken[0]
        self.assertEqual(len(broken), len(_FULL_MASK))
        report = self._five_trial_report(broken)
        records = [_router_record("t", trial=i, considered=_ADMISSIBLE)
                   for i in range(5)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["confidence"]["grade"], "low")

    def test_the_exact_set_still_grades_high(self) -> None:
        report = self._five_trial_report(list(_FULL_MASK))
        records = [_router_record("t", trial=i, considered=_ADMISSIBLE)
                   for i in range(5)]
        (rec,) = derive_recommendations(_loaded(report, records))
        self.assertEqual(rec["confidence"]["grade"], "high")


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

    def test_a_failed_reconciliation_is_not_rendered_reconciled(self) -> None:
        # "reconciled" means the reconciliation SUCCEEDED, not that a
        # reconciliation record exists
        report = _report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        record = _router_record("t", considered=_ADMISSIBLE,
                                delegated=True, reconciled=True)
        record["reconciliation"]["outcome"] = "failed"
        (rec,) = derive_recommendations(_loaded(report, [record]))
        self.assertFalse(rec["actual"]["per_trial"][0]["reconciled"])
        self.assertEqual(
            rec["oracle_ceiling"],
            {"quality": 0.9, "cost": 0.05, "sources": {
                "quality": {"artifact": "report",
                            "pointer": "/arms/oracle/tasks/t/quality"},
                "cost": {"artifact": "report",
                         "pointer": "/arms/oracle/tasks/t/cost"},
            }},
        )


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
            secret_values=(),
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

    def test_malformed_utf8_runs_surface_as_invalid_never_raise(self) -> None:
        # genuinely invalid BYTES (not merely malformed JSON): the
        # closed invalid_evidence boundary must hold — a raw exception
        # here becomes a future API 500 instead of the sanitized state
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            published = self._publish_fixture(base)
            runs = published.path / "routing-runs.jsonl"
            runs.write_bytes(b"\xff\xfe\x00broken\x80bytes")
            loaded = load_evidence_sets([base / "out"])
            self.assertEqual(len(loaded), 1)
            (entry,) = loaded
            self.assertIsInstance(entry, InvalidEvidenceSet)
            # the loader decodes runs BEFORE the hash bindings, so the
            # UTF-8 failure is deterministically schema_invalid
            self.assertEqual(entry.code, "schema_invalid")
            self.assertEqual(entry.state, "invalid_evidence")

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


class TestApiPayloadBoundary(unittest.TestCase):
    """T3's highest-value acceptance gate (the owner's words): a
    deliberately sensitive evidence root must never leak through
    settings, valid evidence, recommendations, invalid-evidence
    responses, or referenced-evidence serving — and no unverified
    artifact byte is ever served."""

    def _sensitive_fixture(self):
        import tempfile

        base = Path(tempfile.mkdtemp(prefix="SENSITIVE-SECRET-DIR."))
        self.addCleanup(__import__("shutil").rmtree, base,
                        ignore_errors=True)
        published = TestEvidenceLoading._publish_fixture(self, base)
        return base, published

    def test_no_payload_carries_the_sensitive_root(self) -> None:
        from session_analytics.routing_evidence import (
            evidence_detail,
            evidence_index,
            recommendations_payload,
            serve_evidence_file,
        )

        base, published = self._sensitive_fixture()
        sensitive = str(base)
        entries = load_evidence_sets([base / "out"])
        payloads = [evidence_index(entries)]
        (loaded,) = entries
        payloads.append(evidence_detail(loaded))
        payloads.append(recommendations_payload(loaded))
        for ref in loaded.manifest.get("evidence_files") or {}:
            payloads.append(serve_evidence_file(loaded, ref))
        # an invalid variant: tamper a copy and list it too
        import shutil as _shutil

        tampered_root = base / "out2"
        _shutil.copytree(base / "out", tampered_root)
        (set_dir,) = [p for p in tampered_root.iterdir() if p.is_dir()]
        (set_dir / "report.json").write_text("{not json", encoding="utf-8")
        payloads.append(evidence_index(load_evidence_sets([tampered_root])))
        for payload in payloads:
            text = json.dumps(payload)
            self.assertNotIn(sensitive, text,
                             "a payload leaked the evidence root path")
            self.assertNotIn("SENSITIVE-SECRET-DIR", text)

    def test_settings_shape_is_sanitized(self) -> None:
        from types import SimpleNamespace

        from session_analytics.routing_evidence import (
            routing_evidence_settings,
        )

        cfg = SimpleNamespace(routing_evidence_roots=(
            "/Users/someone/SENSITIVE-SECRET-DIR/evidence",
            "/var/other/root",
        ))
        shape = routing_evidence_settings(cfg)
        self.assertEqual(shape, {"configured": True, "root_count": 2})
        self.assertNotIn("SENSITIVE", json.dumps(shape))
        self.assertEqual(
            routing_evidence_settings(
                SimpleNamespace(routing_evidence_roots=())
            ),
            {"configured": False, "root_count": 0},
        )

    def test_evidence_file_serving_is_hash_verified(self) -> None:
        from session_analytics.routing_evidence import (
            EvidenceFileUnavailable,
            serve_evidence_file,
        )

        base, published = self._sensitive_fixture()
        (loaded,) = load_evidence_sets([base / "out"])
        refs = sorted(loaded.manifest.get("evidence_files") or {})
        self.assertTrue(refs, "the fixture set carries evidence files")
        ref = refs[0]
        served = serve_evidence_file(loaded, ref)
        self.assertEqual(served["ref"], ref)
        self.assertIn("ok", served["content"])
        # unknown reference: closed refusal, never a probe primitive
        with self.assertRaises(EvidenceFileUnavailable) as caught:
            serve_evidence_file(loaded, "not/in/manifest.txt")
        self.assertEqual(caught.exception.code, "unknown_reference")
        with self.assertRaises(EvidenceFileUnavailable) as caught:
            serve_evidence_file(loaded, "../outside.txt")
        self.assertEqual(caught.exception.code, "unknown_reference")
        # tampered content: manifest hash refuses — unverified bytes
        # are never served
        (loaded.path / ref).write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(EvidenceFileUnavailable) as caught:
            serve_evidence_file(loaded, ref)
        self.assertEqual(caught.exception.code, "hash_mismatch")


class TestFigureProvenanceGate(unittest.TestCase):
    """Decision 9: every numeric figure the API serves is semantically
    equal to its artifact field, or the declared subtraction of two
    named fields — nothing is recomputed, rounded, or re-derived on
    the way out."""

    def test_served_figures_are_the_artifact_figures(self) -> None:
        import tempfile

        from session_analytics.routing_evidence import (
            evidence_detail,
            recommendations_payload,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            TestEvidenceLoading._publish_fixture(self, base)
            (loaded,) = load_evidence_sets([base / "out"])
            # ONE canonical parse of the persisted artifact
            artifact = json.loads(
                (loaded.path / "report.json").read_text(encoding="utf-8")
            )
            detail = evidence_detail(loaded)
            for arm, arm_doc in detail["report"]["arms"].items():
                source_arm = artifact["arms"][arm]
                self.assertEqual(arm_doc["quality"], source_arm["quality"])
                self.assertEqual(arm_doc["cost"], source_arm["cost"])
                for task, figures in (arm_doc.get("tasks") or {}).items():
                    src = source_arm["tasks"][task]
                    self.assertEqual(figures["quality"], src["quality"])
                    self.assertEqual(figures["cost"], src["cost"])
                    self.assertEqual(figures["per_trial"], src["per_trial"])
            # recommendation deltas are the DECLARED float64
            # subtraction of the two pointed-at artifact fields
            recs = recommendations_payload(loaded)["recommendations"]
            for rec in recs:
                task = rec["task_id"]
                router = artifact["arms"]["cct_router"]["tasks"][task]
                for arm, delta in rec["divergence"].items():
                    cand = artifact["arms"][arm]["tasks"][task]
                    if delta["quality_delta"] is not None:
                        self.assertEqual(
                            delta["quality_delta"],
                            router["quality"] - cand["quality"],
                        )
                    if delta["cost_delta"] is not None:
                        self.assertEqual(
                            delta["cost_delta"],
                            router["cost"] - cand["cost"],
                        )

    def test_payload_carries_resolvable_sources(self) -> None:
        # T3 round-1 finding 2 (Option A): the served payload CARRIES
        # the pointers — every non-null figure resolves independently
        # against one canonical parse of the persisted artifact
        import tempfile

        from session_analytics.routing_evidence import (
            recommendations_payload,
        )

        def resolve(doc, pointer):
            node = doc
            for raw in pointer.split("/")[1:]:
                node = node[raw.replace("~1", "/").replace("~0", "~")]
            return node

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            TestEvidenceLoading._publish_fixture(self, base)
            (loaded,) = load_evidence_sets([base / "out"])
            artifact = json.loads(
                (loaded.path / "report.json").read_text(encoding="utf-8")
            )
            recs = recommendations_payload(loaded)["recommendations"]
            self.assertTrue(recs)
            for rec in recs:
                ceiling = rec["oracle_ceiling"]
                for field in ("quality", "cost"):
                    source = ceiling["sources"][field]
                    if ceiling[field] is None:
                        self.assertIsNone(source)
                        continue
                    self.assertEqual(source["artifact"], "report")
                    self.assertEqual(
                        resolve(artifact, source["pointer"]), ceiling[field]
                    )
                for delta in rec["divergence"].values():
                    for field in ("quality_delta", "cost_delta"):
                        source = delta["sources"][field]
                        if delta[field] is None:
                            self.assertIsNone(source)
                            continue
                        self.assertEqual(source["operation"], "subtract")
                        lhs = resolve(artifact, source["lhs"]["pointer"])
                        rhs = resolve(artifact, source["rhs"]["pointer"])
                        self.assertEqual(lhs - rhs, delta[field])

    def test_missing_pointer_refuses(self) -> None:
        from session_analytics.routing_evidence import (
            DerivationError,
            verify_recommendation_provenance,
        )

        loaded, records = self._derived()
        records[0]["oracle_ceiling"]["sources"]["quality"] = None
        with self.assertRaisesRegex(DerivationError, "no source pointer"):
            verify_recommendation_provenance(loaded, records)

    def test_unresolvable_pointer_refuses(self) -> None:
        # the descriptor is CANONICAL (identity binding passes) but the
        # artifact drifted underneath it — resolution itself must refuse
        from session_analytics.routing_evidence import (
            DerivationError,
            verify_recommendation_provenance,
        )

        loaded, records = self._derived()
        del loaded.report["arms"]["oracle"]["tasks"]["t"]
        with self.assertRaisesRegex(DerivationError, "does not resolve"):
            verify_recommendation_provenance(loaded, records)

    def test_delta_differing_from_recomputation_refuses(self) -> None:
        from session_analytics.routing_evidence import (
            DerivationError,
            verify_recommendation_provenance,
        )

        loaded, records = self._derived()
        entry = records[0]["divergence"]["always_best"]
        self.assertIsNotNone(entry["quality_delta"])
        entry["quality_delta"] += 1e-12
        with self.assertRaisesRegex(DerivationError, "recomputed subtraction"):
            verify_recommendation_provenance(loaded, records)

    def test_wrong_operand_pointer_refuses(self) -> None:
        # a pointer that resolves but names the WRONG field refuses at
        # the identity binding, before any value is even compared
        from session_analytics.routing_evidence import (
            DerivationError,
            verify_recommendation_provenance,
        )

        loaded, records = self._derived()
        source = records[0]["divergence"]["always_best"]["sources"][
            "quality_delta"]
        source["rhs"] = dict(source["lhs"])
        with self.assertRaisesRegex(DerivationError, "does not name"):
            verify_recommendation_provenance(loaded, records)

    def test_wrong_but_equal_valued_pointer_refuses(self) -> None:
        # T3 round-2 finding 2: "exact source" is identity-bound. The
        # owner's collision — the always_best quality operand repointed
        # at the oracle quality field whose VALUE IS EQUAL — must
        # refuse: value reproduction is not source identity.
        from session_analytics.routing_evidence import (
            DerivationError,
            verify_recommendation_provenance,
        )

        report = _report(
            _figures_for(router=(0.5, 0.05), best=(0.9, 0.01),
                         cheapest=(0.4, 0.02)),  # oracle quality also 0.9
            selections=_SELECTIONS,
        )
        loaded = _loaded(
            report, [_router_record("t", considered=_ADMISSIBLE)]
        )
        records = [
            json.loads(json.dumps(rec))
            for rec in derive_recommendations(loaded)
        ]
        source = records[0]["divergence"]["always_best"]["sources"][
            "quality_delta"]
        source["rhs"]["pointer"] = "/arms/oracle/tasks/t/quality"
        self.assertEqual(  # the collision is real: same value, wrong field
            loaded.report["arms"]["oracle"]["tasks"]["t"]["quality"],
            loaded.report["arms"]["always_best"]["tasks"]["t"]["quality"],
        )
        with self.assertRaisesRegex(DerivationError, "does not name"):
            verify_recommendation_provenance(loaded, records)

    def test_forged_basis_refuses_with_checked_values_intact(self) -> None:
        # T3 round-3: the gate trusts NOTHING the payload asserts about
        # itself — components_included and insufficiency_refs are both
        # fabricated while trials, agreement, unevaluated trials, and
        # the grade (everything the round-2 gate compared) stay
        # untouched; the full-basis re-derivation must still refuse
        from session_analytics.routing_evidence import (
            DerivationError,
            verify_recommendation_provenance,
        )

        loaded, records = self._derived()
        basis = records[0]["confidence"]["basis"]
        checked_before = (
            basis["trials"], basis["agreement"],
            basis.get("unevaluated_trials"),
            records[0]["confidence"]["grade"],
        )
        basis["components_included"] = ["fabricated_component"]
        basis["insufficiency_refs"] = ["fabricated: never derived"]
        self.assertEqual(
            checked_before,
            (basis["trials"], basis["agreement"],
             basis.get("unevaluated_trials"),
             records[0]["confidence"]["grade"]),
        )
        with self.assertRaisesRegex(DerivationError, "re-derivation"):
            verify_recommendation_provenance(loaded, records)

    def test_tampered_confidence_refuses(self) -> None:
        # T3 round-2 finding 3: confidence statistics are gated by
        # recomputation — a one-trial record claiming grade high with
        # agreement 0.0 never leaves the server
        from session_analytics.routing_evidence import (
            DerivationError,
            verify_recommendation_provenance,
        )

        loaded, records = self._derived()
        self.assertEqual(records[0]["confidence"]["basis"]["trials"], 1)
        records[0]["confidence"]["grade"] = "high"
        records[0]["confidence"]["basis"]["agreement"] = 0.0
        with self.assertRaisesRegex(DerivationError, "re-derivation"):
            verify_recommendation_provenance(loaded, records)

    def test_schema_enforces_null_source_pairing(self) -> None:
        # T3 round-2 finding 4: the persisted contract itself refuses
        # both inverse pairings — runtime gates are not the only wall
        loaded, records = self._derived()
        schema = load_schema("recommendation")
        numeric_null = json.loads(json.dumps(records[0]))
        self.assertIsNotNone(numeric_null["oracle_ceiling"]["quality"])
        numeric_null["oracle_ceiling"]["sources"]["quality"] = None
        self.assertTrue(validate(numeric_null, schema))
        null_sourced = json.loads(json.dumps(records[0]))
        null_sourced["oracle_ceiling"]["quality"] = None
        self.assertTrue(validate(null_sourced, schema))
        delta_numeric_null = json.loads(json.dumps(records[0]))
        entry = delta_numeric_null["divergence"]["always_best"]
        self.assertIsNotNone(entry["quality_delta"])
        entry["sources"]["quality_delta"] = None
        self.assertTrue(validate(delta_numeric_null, schema))
        delta_null_sourced = json.loads(json.dumps(records[0]))
        delta_null_sourced["divergence"]["always_best"]["quality_delta"] = None
        self.assertTrue(validate(delta_null_sourced, schema))

    def test_gate_runs_at_serving(self) -> None:
        # the resolver is wired INTO the payload path — a derivation
        # that emitted an unsourced figure never leaves the server
        from unittest import mock

        from session_analytics import routing_evidence
        from session_analytics.routing_evidence import (
            DerivationError,
            recommendations_payload,
        )

        loaded, records = self._derived()
        records[0]["oracle_ceiling"]["sources"]["cost"] = None
        with mock.patch.object(
            routing_evidence, "derive_recommendations",
            return_value=records,
        ):
            with self.assertRaises(DerivationError):
                recommendations_payload(loaded)

    def _derived(self):
        report = _report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections=_SELECTIONS,
        )
        loaded = _loaded(
            report, [_router_record("t", considered=_ADMISSIBLE)]
        )
        records = [
            json.loads(json.dumps(rec))
            for rec in derive_recommendations(loaded)
        ]
        return loaded, records


class TestAuthorityGuard(unittest.TestCase):
    """Decision 7: nothing the router executes references this layer,
    and this layer writes nothing outside the analytics store."""

    _PRODUCTION = (
        "scripts/routing-cli.sh",
        "scripts/cooldown-supervisor.sh",
    )

    def test_no_production_routing_script_references_this_layer(self) -> None:
        repo = Path(__file__).resolve().parents[3]
        needles = ("routing_evidence", "recommendation.schema",
                   "routing_evidence_roots", "CCT_SA_ROUTING")
        files = [repo / p for p in self._PRODUCTION]
        files += sorted((repo / "scripts" / "lib").glob("routing-*.sh"))
        for f in files:
            text = f.read_text(encoding="utf-8")
            for needle in needles:
                self.assertNotIn(
                    needle, text,
                    f"{f.name} references {needle} — the router must not "
                    f"be able to read recommendation machinery",
                )

    def test_the_consumer_never_writes_into_an_evidence_set(self) -> None:
        import hashlib
        import tempfile

        from session_analytics.routing_evidence import (
            evidence_detail,
            recommendations_payload,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            TestEvidenceLoading._publish_fixture(self, base)
            (loaded,) = load_evidence_sets([base / "out"])

            def _digest():
                h = hashlib.sha256()
                for p in sorted(loaded.path.rglob("*")):
                    if p.is_file():
                        h.update(p.name.encode())
                        h.update(p.read_bytes())
                return h.hexdigest()

            before = _digest()
            evidence_detail(loaded)
            recommendations_payload(loaded)
            load_evidence_sets([base / "out"])
            self.assertEqual(_digest(), before,
                             "consumption mutated the evidence set")

    def test_the_module_source_performs_no_writes(self) -> None:
        import re as _re

        source = (Path(__file__).resolve().parents[1]
                  / "routing_evidence.py").read_text(encoding="utf-8")
        self.assertIsNone(
            _re.search(r"write_text|write_bytes|open\([^)]*[\"'](?:w|a)",
                       source),
            "the consumer module must be read-only",
        )


class TestEvidenceRootsConfig(unittest.TestCase):
    def test_env_overrides_file_layering(self) -> None:
        import os as _os
        from unittest import mock

        from session_analytics.config import load_config

        with mock.patch.dict(_os.environ,
                             {"CCT_SA_ROUTING_EVIDENCE_ROOTS": ""}):
            _os.environ.pop("CCT_SA_ROUTING_EVIDENCE_ROOTS")
            cfg = load_config(extra_overrides={
                "routing_evidence_roots": ["/from/file/a", "/from/file/b"],
            })
            self.assertEqual(cfg.routing_evidence_roots,
                             ("/from/file/a", "/from/file/b"))
        with mock.patch.dict(_os.environ, {
            "CCT_SA_ROUTING_EVIDENCE_ROOTS":
                _os.pathsep.join(["/from/env/x", "/from/env/y"]),
        }):
            cfg = load_config(extra_overrides={
                "routing_evidence_roots": ["/from/file/a"],
            })
            self.assertEqual(cfg.routing_evidence_roots,
                             ("/from/env/x", "/from/env/y"),
                             "real env wins over file layering")


class TestEvidenceFileRedactionChain(unittest.TestCase):
    """T3 round-1 finding 1: verified dangerous bytes are still
    dangerous bytes. Referenced evidence files pass through the SAME
    write-time scrub as everything else at PUBLICATION, the manifest
    hashes the scrubbed bytes, and the API serves only what survived
    — proven with the full chain: registry credential_env -> boring
    env value -> raw verifier evidence -> publication -> HTTP-shaped
    payloads."""

    _BORING = "correct-horse-X7"

    def test_published_and_served_evidence_is_scrubbed(self) -> None:
        import tempfile
        from unittest import mock

        from benchmark_runner.routing_eval.redaction import (
            secret_values_from_registry,
        )
        from session_analytics.routing_evidence import serve_evidence_file

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # the credential chain: the registry declares the env
            # reference; the environment holds a boring value no
            # static pattern matches
            registry = base / "registry.toml"
            registry.write_text(
                "schema_version = 1\n[[profiles]]\nid = \"p\"\n"
                "credential_env = \"E2_BORING_TOKEN\"\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                "os.environ", {"E2_BORING_TOKEN": self._BORING}
            ):
                secrets = secret_values_from_registry(registry)
            self.assertIn(self._BORING, secrets)
            # RAW verifier evidence carrying the token and a sensitive
            # absolute home path — exactly what a real tool log leaks
            # (the machine's OWN home: decision 8's guarantee is that
            # the user home prefix collapses to ~ so no username ships)
            sensitive_path = str(Path.home() / "private/customer-x/repo")
            raw = (f"provider failed with {self._BORING}\n"
                   f"worktree: {sensitive_path}\n"
                   f"tests ok\n")
            published = self._publish_with_evidence(base, raw, secrets)
            # 1) the PERSISTED evidence-file bytes are scrubbed
            manifest = json.loads(
                (published.path / "manifest.json").read_text(
                    encoding="utf-8")
            )
            for ref in manifest["evidence_files"]:
                persisted = (published.path / ref).read_text(
                    encoding="utf-8")
                self.assertNotIn(self._BORING, persisted)
                self.assertNotIn(sensitive_path, persisted)
                # the SCRUBBED forms are present — proof the scrub ran,
                # not that the leak merely never reached the file
                self.assertIn("[REDACTED]", persisted)
                self.assertIn("~/private/customer-x/repo", persisted)
                self.assertIn("tests ok", persisted)
            # 2) the set VALIDATES (the manifest hashed the SCRUBBED
            # bytes) and the API serves only what survived
            (entry,) = load_evidence_sets([base / "out"])
            self.assertIsInstance(entry, LoadedEvidenceSet)
            for ref in manifest["evidence_files"]:
                served = serve_evidence_file(entry, ref)
                self.assertNotIn(self._BORING, served["content"])
                self.assertNotIn(sensitive_path, served["content"])

    def _publish_with_evidence(self, base, raw_evidence, secrets):
        from benchmark_runner.routing_eval.evidence_set import _publish
        from benchmark_runner.routing_eval.redaction import (
            write_run_records,
        )
        from benchmark_runner.routing_eval.routing_quality import (
            build_report,
        )
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
        # overwrite the fixture's evidence file with the RAW leak
        ledger = base / "ledger"
        (ledger / "feat" / "verify.txt").write_text(raw_evidence,
                                                    encoding="utf-8")
        report = build_report(matrix, controls, [record],
                              expected_preset_digest=_PRESET,
                              registry_path=_REGISTRY, config=_CONFIG)
        report.pop("source_artifacts", None)
        runs = write_run_records([record], ledger / "runs.jsonl",
                                 evidence_root=ledger,
                                 secret_values=secrets)
        return _publish(
            base / "out",
            runs_path=runs,
            evidence_root=ledger,
            records=[record],
            matrix=matrix,
            report=dict(report),
            fingerprint=matrix.fingerprint,
            secret_values=secrets,
        )
