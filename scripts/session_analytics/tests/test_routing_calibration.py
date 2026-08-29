# session_analytics.tests.test_routing_calibration — routing-calibration T1.
#
# The identities everything else binds to (plan decision 3): corpus_id
# over the valid sets only; policy_id over the FULL evaluation policy,
# changing for EVERY policy dimension; staleness that voids gate
# satisfaction on either mismatch. Plus the operator-policy rule
# (decision 8): a missing configuration key is a refusal, never a code
# default; and schema-level inverse tests for the new closed
# vocabularies.

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from benchmark_runner.routing_eval.record_check import load_schema, validate
from session_analytics.routing_calibration import (
    FEATURE_VOCABULARY_VERSION,
    GATE_IDS,
    CalibrationError,
    EvaluationPolicy,
    corpus_id,
    policy_from_config,
    policy_id,
    policy_source_digest,
    report_staleness,
)
from session_analytics.routing_evidence import (
    InvalidEvidenceSet,
    LoadedEvidenceSet,
)


def _loaded(set_id: str) -> LoadedEvidenceSet:
    return LoadedEvidenceSet(
        set_id=set_id, path=Path("/dev/null"), manifest={}, report={},
        matrix={}, records=(),
    )


def _invalid(label: str) -> InvalidEvidenceSet:
    return InvalidEvidenceSet(label=label, code="hash_mismatch",
                              artifact="report.json", detail="d")


_POLICY = EvaluationPolicy(
    feature_vocabulary=FEATURE_VOCABULARY_VERSION,
    k=5, k_min=3, distance_metric="l2_v1", vote_epsilon=1e-6,
    normalization="minmax_fold_v1", tier_floor="tier1",
    policy_source_digest="ab" * 32, max_false_downgrade_rate=0.05,
)


class TestCorpusIdentity(unittest.TestCase):
    def test_valid_sets_only_sorted(self) -> None:
        a, b = _loaded("aa" * 32), _loaded("bb" * 32)
        self.assertEqual(corpus_id([a, b]), corpus_id([b, a]))
        self.assertNotEqual(corpus_id([a]), corpus_id([a, b]))
        # an INVALID set is never part of the corpus
        self.assertEqual(corpus_id([a, b]), corpus_id([a, b, _invalid("x")]))
        # invalidating a set (valid -> invalid) changes the identity
        self.assertNotEqual(corpus_id([a, b]),
                            corpus_id([a, _invalid("bb" * 32)]))


class TestPolicyIdentity(unittest.TestCase):
    def test_every_dimension_changes_the_identity(self) -> None:
        base = policy_id(_POLICY)
        variants = (
            replace(_POLICY, k=7),
            replace(_POLICY, k_min=2),
            replace(_POLICY, distance_metric="l2_v2"),
            replace(_POLICY, vote_epsilon=1e-5),
            replace(_POLICY, tier_floor="tier2"),
            replace(_POLICY, policy_source_digest="cd" * 32),
            replace(_POLICY, policy_source_digest=None),
            replace(_POLICY, max_false_downgrade_rate=0.1),
            replace(_POLICY, feature_vocabulary="fv2"),
            replace(_POLICY, normalization="minmax_fold_v2"),
        )
        ids = [policy_id(v) for v in variants]
        for i, variant_id in enumerate(ids):
            self.assertNotEqual(base, variant_id, variants[i])
        self.assertEqual(len(set(ids)), len(ids), "dimension collisions")
        self.assertEqual(base, policy_id(replace(_POLICY)))

    def test_policy_source_digest_tracks_bytes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "policy.toml"
            self.assertIsNone(policy_source_digest(p))
            self.assertIsNone(policy_source_digest(""))
            self.assertIsNone(policy_source_digest(None))
            p.write_text("tier_floor = 'tier1'\n", encoding="utf-8")
            first = policy_source_digest(p)
            self.assertIsNotNone(first)
            p.write_text("tier_floor = 'tier2'\n", encoding="utf-8")
            self.assertNotEqual(first, policy_source_digest(p))


class TestPolicyFromConfig(unittest.TestCase):
    _BLOCK = {
        "k": 5, "k_min": 3, "distance_metric": "l2_v1",
        "vote_epsilon": 1e-6, "tier_floor": "tier1",
        "policy_source": "", "max_false_downgrade_rate": 0.05,
    }

    def test_assembles_from_the_layered_block(self) -> None:
        cfg = SimpleNamespace(routing_calibration=dict(self._BLOCK))
        policy = policy_from_config(cfg)
        self.assertEqual(policy.k, 5)
        self.assertEqual(policy.feature_vocabulary,
                         FEATURE_VOCABULARY_VERSION)
        self.assertIsNone(policy.policy_source_digest)

    def test_missing_key_refuses_never_defaults(self) -> None:
        for key in self._BLOCK:
            block = dict(self._BLOCK)
            del block[key]
            cfg = SimpleNamespace(routing_calibration=block)
            with self.assertRaisesRegex(CalibrationError, key):
                policy_from_config(cfg)

    def test_defaults_file_ships_every_required_key(self) -> None:
        from session_analytics.config import load_config

        policy = policy_from_config(load_config())
        self.assertEqual(policy.distance_metric, "l2_v1")

    def test_env_override_layering(self) -> None:
        import os
        from unittest import mock

        from session_analytics.config import load_config

        with mock.patch.dict(os.environ, {"CCT_SA_CALIBRATION_K": "9"}):
            policy = policy_from_config(load_config())
        self.assertEqual(policy.k, 9)


class TestStaleness(unittest.TestCase):
    def test_either_mismatch_is_stale_with_reasons(self) -> None:
        c, p = "aa" * 32, "bb" * 32
        report = {"corpus_id": c, "policy_id": p}
        fresh = report_staleness(report, c, p)
        self.assertEqual(fresh, {"stale": False, "reasons": []})
        self.assertEqual(
            report_staleness(report, "cc" * 32, p)["reasons"],
            ["corpus_changed"])
        self.assertEqual(
            report_staleness(report, c, "dd" * 32)["reasons"],
            ["policy_changed"])
        both = report_staleness(report, "cc" * 32, "dd" * 32)
        self.assertTrue(both["stale"])
        self.assertEqual(both["reasons"],
                         ["corpus_changed", "policy_changed"])


class TestSchemaVocabularies(unittest.TestCase):
    """Schema-level inverse tests: the closed vocabularies refuse."""

    def _gate(self, **overrides):
        gate = {
            "id": "telemetry_complete", "status": "pass", "measured": 0.99,
            "threshold": 0.95, "reason": None, "evidence_refs": [],
        }
        gate.update(overrides)
        return gate

    def _calibration_report(self, gates):
        return {
            "schema_version": 1, "corpus_id": "aa" * 32,
            "policy_id": "bb" * 32,
            "corpus": {"sets": 1, "invalid_sets": 0, "labeled_tasks": 1},
            "gates": gates, "calibrated": False,
        }

    def test_calibration_report_closed_vocabularies(self) -> None:
        schema = load_schema("calibration-report")
        gates = [self._gate(id=g) for g in GATE_IDS]
        self.assertFalse(validate(self._calibration_report(gates), schema))
        bad_id = [self._gate(id="novel_gate")] + gates[1:]
        self.assertTrue(validate(self._calibration_report(bad_id), schema))
        bad_status = [self._gate(status="maybe")] + gates[1:]
        self.assertTrue(validate(self._calibration_report(bad_status),
                                 schema))
        short = gates[:4]
        self.assertTrue(validate(self._calibration_report(short), schema))

    def test_descriptor_and_policy_closed_vocabularies(self) -> None:
        td = load_schema("task-descriptors")
        good = {
            "schema_version": 1, "preset_digest": "sha256:" + "ab" * 32,
            "descriptors": {"t": {"task_class": "one_file",
                                  "route_class": "primary_only",
                                  "file_scope": 1}},
        }
        self.assertFalse(validate(good, td))
        bad = json.loads(json.dumps(good))
        bad["descriptors"]["t"]["task_class"] = "novel"
        self.assertTrue(validate(bad, td))

        pp = load_schema("profile-policy")
        good = {
            "schema_version": 1, "registry_digest": "sha256:" + "ab" * 32,
            "profiles": {"p": {"capability_tier": "tier1", "roles": []}},
        }
        self.assertFalse(validate(good, pp))
        bad = json.loads(json.dumps(good))
        bad["profiles"]["p"]["capability_tier"] = "tier3"
        self.assertTrue(validate(bad, pp))

    def test_knn_metric_is_const(self) -> None:
        schema = load_schema("knn-recommendation")
        good = {
            "schema_version": 1, "evidence_set_id": "aa" * 32,
            "task_id": "t", "policy_id": "bb" * 32,
            "outcome": "insufficient_data", "suggested": None,
            "neighbors": [], "k": 5, "k_min": 3,
            "distance_metric": "l2_v1",
            "insufficient_reason": "corpus too thin",
        }
        self.assertFalse(validate(good, schema))
        bad = dict(good, distance_metric="cosine")
        self.assertTrue(validate(bad, schema))


# ── T2: features, labels, and the kNN recommender ─────────────────────
from session_analytics.routing_calibration import (  # noqa: E402
    FEATURE_NAMES,
    Example,
    extract_examples,
    knn_recommendation,
    load_current_policy,
)
from session_analytics.tests.test_routing_evidence import (  # noqa: E402
    _ADMISSIBLE,
    _SELECTIONS,
    _loaded as _loaded_evidence,
    _report,
    _figures_for,
    _router_record,
)


def _descriptored(set_id, report, records, descriptors):
    base = _loaded_evidence(report, records)
    from dataclasses import replace as _replace

    return _replace(
        base, set_id=set_id,
        task_descriptors={"schema_version": 1, "preset_digest": "sha256:p",
                          "descriptors": descriptors},
    )


def _descriptor(task_class="one_file", route_class="primary_only",
                file_scope=1):
    return {"task_class": task_class, "route_class": route_class,
            "file_scope": file_scope}


def _retask(report, task):
    """The E2 fixture helpers key everything on task "t"; rename the
    per-task tables to ``task`` so multi-set corpora carry distinct
    tasks."""
    doc = json.loads(json.dumps(report))
    for arm in doc["arms"].values():
        tasks = arm.get("tasks") or {}
        if "t" in tasks:
            arm["tasks"] = {task: tasks["t"]}
        selections = arm.get("selections") or {}
        if "t" in selections:
            arm["selections"] = {task: selections["t"]}
    return doc


def _switch_set(set_id, task="t", **descriptor):
    """A set whose E2 label for ``task`` is switch_profile -> alpha."""
    report = _retask(_report(
        _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                     cheapest=(0.4, 0.02)),
        selections=_SELECTIONS,
    ), task)
    record = _router_record(task, considered=_ADMISSIBLE)
    return _descriptored(set_id, report, [record],
                         {task: _descriptor(**descriptor)})


def _keep_set(set_id, task="t", **descriptor):
    """A set whose E2 label for ``task`` is no_change_recommended."""
    report = _retask(_report(
        _figures_for(router=(1.0, 0.005), best=(0.9, 0.01),
                     cheapest=(0.4, 0.02)),
        selections=_SELECTIONS,
    ), task)
    record = _router_record(task, considered=_ADMISSIBLE)
    return _descriptored(set_id, report, [record],
                         {task: _descriptor(**descriptor)})


_CURRENT_POLICY = {
    "schema_version": 1,
    "registry_digest": "current",
    "profiles": {
        "alpha": {"capability_tier": "tier1", "roles": ["build"]},
        "beta": {"capability_tier": "tier2", "roles": ["build"]},
        "gamma": {"capability_tier": "tier1", "roles": ["review"]},
    },
}


def _corpus():
    """Three labeled neighbor sets for task-distinct queries: two
    switch-labeled, one keep-labeled, distinct tasks so any query task
    keeps them all in the pool."""
    return [
        _switch_set("aa" * 32, task="n1", file_scope=1),
        _switch_set("bb" * 32, task="n2", file_scope=2),
        _keep_set("cc" * 32, task="n3", file_scope=8),
        _switch_set("dd" * 32, task="q", file_scope=1),
    ]


class TestFeatureExtraction(unittest.TestCase):
    def test_vocabulary_is_closed_and_pre_routing_only(self) -> None:
        # THE pre-routing ban pin: the encoded vocabulary is exactly
        # these names — a post-execution figure can only enter by
        # growing this tuple, which this test refuses.
        self.assertEqual(FEATURE_NAMES, (
            "task_class=one_file", "task_class=multi_file_feature",
            "task_class=refactor", "task_class=reproduced_bug",
            "task_class=integration", "task_class=negative_control",
            "route_class=primary_only", "route_class=tier1_only",
            "route_class=tier2_fallback", "route_class=tier2_preferred",
            "file_scope", "trial_count",
        ))

    def test_examples_from_descriptors_and_labels(self) -> None:
        examples = extract_examples(_corpus())
        by_key = {(e.evidence_set_id, e.task_id): e for e in examples}
        switch = by_key[("aa" * 32, "n1")]
        self.assertEqual(switch.label["outcome"], "switch_profile")
        self.assertEqual(switch.features["task_class"], "one_file")
        keep = by_key[("cc" * 32, "n3")]
        self.assertEqual(keep.label["outcome"], "no_change_recommended")

    def test_missing_descriptors_are_refused_not_imputed(self) -> None:
        plain = _loaded_evidence(
            _report(_figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                                 cheapest=(0.4, 0.02)),
                    selections=_SELECTIONS),
            [_router_record("t", considered=_ADMISSIBLE)],
        )
        (example,) = extract_examples([plain])
        self.assertIsNone(example.features)
        self.assertIn("no task descriptors", example.missing)


class TestCurrentPolicySource(unittest.TestCase):
    def test_reads_through_the_production_parser(self) -> None:
        import tempfile

        from benchmark_runner.tests.test_routing_eval_quality import (
            _REGISTRY,
        )

        cfg = SimpleNamespace(routing_calibration={
            "policy_source": str(_REGISTRY)})
        policy = load_current_policy(cfg)
        self.assertEqual(policy["profiles"]["alpha"]["capability_tier"],
                         "tier1")
        # absent / unparseable sources are None, never fabricated
        self.assertIsNone(load_current_policy(
            SimpleNamespace(routing_calibration={"policy_source": ""})))
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "garbage.toml"
            bad.write_text("not a registry\n", encoding="utf-8")
            self.assertIsNone(load_current_policy(SimpleNamespace(
                routing_calibration={"policy_source": str(bad)})))


class TestKnnRecommendation(unittest.TestCase):
    def _recommend(self, corpus=None, policy=_POLICY,
                   current=_CURRENT_POLICY, set_id="dd" * 32, task="q"):
        return knn_recommendation(corpus or _corpus(), set_id, task,
                                  policy, current)

    def test_byte_identical_on_identical_corpus_and_policy(self) -> None:
        a = self._recommend()
        b = self._recommend(corpus=list(reversed(_corpus())))
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))

    def test_switch_majority_recommends_the_winning_suggestion(self) -> None:
        doc = self._recommend()
        self.assertEqual(doc["outcome"], "switch_profile")
        self.assertEqual(doc["suggested"]["profile_id"], "alpha")
        self.assertTrue(doc["neighbors"])

    def test_k_min_insufficiency(self) -> None:
        doc = self._recommend(corpus=[
            _switch_set("aa" * 32, task="n1"),
            _switch_set("dd" * 32, task="q"),
        ])
        self.assertEqual(doc["outcome"], "insufficient_data")
        self.assertIn("k_min", doc["insufficient_reason"])

    def test_no_current_policy_is_insufficient(self) -> None:
        doc = self._recommend(current=None)
        self.assertEqual(doc["outcome"], "insufficient_data")
        self.assertIn("policy source", doc["insufficient_reason"])

    def test_query_without_descriptor_is_insufficient(self) -> None:
        corpus = _corpus()
        plain_query = _loaded_evidence(
            _retask(_report(_figures_for(router=(0.5, 0.05),
                                         best=(1.0, 0.01),
                                         cheapest=(0.4, 0.02)),
                            selections=_SELECTIONS), "q2"),
            [_router_record("q2", considered=_ADMISSIBLE)],
        )
        from dataclasses import replace as _replace

        corpus.append(_replace(plain_query, set_id="ee" * 32))
        doc = self._recommend(corpus=corpus, set_id="ee" * 32, task="q2")
        self.assertEqual(doc["outcome"], "insufficient_data")
        self.assertIn("descriptor", doc["insufficient_reason"])

    def test_same_task_examples_never_join_the_pool(self) -> None:
        # serving parity with leave-one-task-out: another set's example
        # of the SAME task (whose label derives from that task's own
        # figures) must not vote
        corpus = _corpus() + [_switch_set("ee" * 32, task="q")]
        doc = self._recommend(corpus=corpus)
        self.assertNotIn("q", [n["task_id"] for n in doc["neighbors"]])

    def test_filter_before_ranking(self) -> None:
        # the NEAREST neighbor's suggestion names a below-floor profile
        # (beta = tier2 under a tier1 floor): it must be removed BEFORE
        # ranking, so the eligible neighbors decide; with k=1 a
        # filter-after-ranking implementation would instead select the
        # ineligible nearest and have nothing left to vote
        report = _retask(_report(
            _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                         cheapest=(0.4, 0.02)),
            selections={"always_best": {"t": "beta"},
                        "always_cheapest": {"t": "beta"}},
        ), "n1")
        beta_admissible = (
            {"id": "beta", "verdict": "selected",
             "reason": "healthy — selected", "state": "healthy"},
        )
        nearest_ineligible = _descriptored(
            "ab" * 32, report,
            [_router_record("n1", considered=beta_admissible,
                            selected="beta")],
            {"n1": _descriptor(file_scope=1)},
        )
        corpus = [
            nearest_ineligible,
            _switch_set("cd" * 32, task="n2", file_scope=1),
            _switch_set("ef" * 32, task="n3", file_scope=1),
            _keep_set("ff" * 32, task="n4", file_scope=1),
            _switch_set("dd" * 32, task="q", file_scope=1),
        ]
        policy = replace(_POLICY, k=1, k_min=1)
        doc = self._recommend(corpus=corpus, policy=policy)
        self.assertEqual(doc["outcome"], "switch_profile")
        self.assertEqual(doc["suggested"]["profile_id"], "alpha")
        self.assertNotIn("n1", [n["task_id"] for n in doc["neighbors"]])

    def test_role_ineligible_profile_is_filtered(self) -> None:
        from session_analytics.routing_calibration import (
            _eligible_under_policy,
        )

        self.assertFalse(_eligible_under_policy(
            {"arm": "always_best", "profile_id": "gamma"},
            _CURRENT_POLICY, "tier2"))
        self.assertFalse(_eligible_under_policy(
            {"arm": "always_best", "profile_id": "ghost"},
            _CURRENT_POLICY, "tier2"))
        self.assertTrue(_eligible_under_policy(
            {"arm": "always_best", "profile_id": "beta"},
            _CURRENT_POLICY, "tier2"))
        self.assertFalse(_eligible_under_policy(
            {"arm": "always_best", "profile_id": "beta"},
            _CURRENT_POLICY, "tier1"))
        self.assertTrue(_eligible_under_policy(None, _CURRENT_POLICY,
                                               "tier1"))

    def test_conservative_tie_never_switches(self) -> None:
        # one switch voter and one keep voter at IDENTICAL distance:
        # equal weights, and the tie resolves to no_change
        corpus = [
            _switch_set("aa" * 32, task="n1", file_scope=3),
            _keep_set("bb" * 32, task="n2", file_scope=3),
            _switch_set("dd" * 32, task="q", file_scope=3),
        ]
        policy = replace(_POLICY, k=2, k_min=2)
        doc = self._recommend(corpus=corpus, policy=policy)
        self.assertEqual(doc["outcome"], "no_change_recommended")
        self.assertIsNone(doc["suggested"])

    def test_neighbor_refs_resolve_against_served_artifacts(self) -> None:
        # the E2 followability precedent: every neighbor ref is an
        # artifact-relative pointer that resolves in that set's served
        # report
        doc = self._recommend()
        corpus = {e.set_id: e for e in _corpus()}
        for neighbor in doc["neighbors"]:
            entry = corpus[neighbor["evidence_set_id"]]
            for ref in neighbor["evidence_refs"]:
                artifact, pointer = ref.split("/", 1)
                self.assertEqual(artifact, "report")
                node = entry.report
                for token in pointer.split("/"):
                    self.assertIn(token, node, ref)
                    node = node[token]
                self.assertIn("per_trial", node)

    def test_hand_computed_distances_and_outcome(self) -> None:
        # HAND-COMPUTED, not a golden from the implementation. Query
        # fs=9; pool fs = 1, 2, 8 -> fold bounds [1, 8], so the query
        # normalizes to clamp((9-1)/7) = 1.0 and the pool to 0, 1/7, 1.
        # trial_count is degenerate (all 1) -> 0.0. Distances: keep-set
        # n3 at 0.0 (nearest), n2 at 6/7, n1 at 1.0. Distance weighting
        # makes the adjacent keep voter dominate two farther switch
        # voters -> no_change (an unweighted count would say switch).
        corpus = [
            _switch_set("aa" * 32, task="n1", file_scope=1),
            _switch_set("bb" * 32, task="n2", file_scope=2),
            _keep_set("cc" * 32, task="n3", file_scope=8),
            _switch_set("dd" * 32, task="q", file_scope=9),
        ]
        doc = self._recommend(corpus=corpus)
        self.assertEqual(
            [n["task_id"] for n in doc["neighbors"]], ["n3", "n2", "n1"])
        expected = [0.0, 6.0 / 7.0, 1.0]
        for neighbor, distance in zip(doc["neighbors"], expected):
            self.assertAlmostEqual(neighbor["distance"], distance,
                                   places=12)
        self.assertEqual(doc["outcome"], "no_change_recommended")

    def test_output_is_schema_valid(self) -> None:
        schema = load_schema("knn-recommendation")
        for doc in (self._recommend(), self._recommend(current=None)):
            self.assertFalse(validate(doc, schema))


if __name__ == "__main__":
    unittest.main()
