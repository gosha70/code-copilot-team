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

    def test_tier_floor_is_a_closed_vocabulary(self) -> None:
        for bad in ("Tier1", "tier3", "", "TIER2"):
            cfg = SimpleNamespace(
                routing_calibration=dict(self._BLOCK, tier_floor=bad))
            with self.assertRaisesRegex(CalibrationError, "tier_floor"):
                policy_from_config(cfg)
        for good in ("tier1", "tier2"):
            cfg = SimpleNamespace(
                routing_calibration=dict(self._BLOCK, tier_floor=good))
            self.assertEqual(policy_from_config(cfg).tier_floor, good)

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
            "trials": 3,
            "descriptors": {"t": {"task_class": "one_file",
                                  "route_class": "primary_only",
                                  "file_scope": 1}},
        }
        self.assertFalse(validate(good, td))
        bad = json.loads(json.dumps(good))
        bad["descriptors"]["t"]["task_class"] = "novel"
        self.assertTrue(validate(bad, td))
        # the DECLARED trial count is required (T2 round-1 P1)
        no_trials = json.loads(json.dumps(good))
        del no_trials["trials"]
        self.assertTrue(validate(no_trials, td))

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


_PROFILE_POLICY = {
    "schema_version": 1,
    "registry_digest": "sha256:reg",
    "profiles": {
        "alpha": {"capability_tier": "tier1", "roles": ["build"]},
        "beta": {"capability_tier": "tier2", "roles": ["build"]},
        "gamma": {"capability_tier": "tier1", "roles": ["review"]},
        "router-prof": {"capability_tier": "tier1", "roles": ["build"]},
    },
}


def _complete(record):
    """G1's completeness shape: a measured cost and a VERIFIED
    effective-model identity on every decision. The E2 fixture record
    carries neither (it exercises the derivation, not telemetry), so
    calibration fixtures opt in explicitly."""
    record = json.loads(json.dumps(record))
    record["cost"] = {"value": 0.01, "provenance": "measured"}
    for decision in record["routing_decisions"]:
        decision["effective_model"] = "m"
    return record


def _descriptored(set_id, report, records, descriptors, trials=1):
    base = _loaded_evidence(report, records)
    from dataclasses import replace as _replace

    return _replace(
        base, set_id=set_id,
        task_descriptors={"schema_version": 1, "preset_digest": "sha256:p",
                          "trials": trials, "descriptors": descriptors},
        profile_policy=_PROFILE_POLICY,
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


def _switch_set(set_id, task="t", trials=1, **descriptor):
    """A set whose E2 label for ``task`` is switch_profile -> alpha."""
    report = _retask(_report(
        _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                     cheapest=(0.4, 0.02)),
        selections=_SELECTIONS,
    ), task)
    record = _complete(_router_record(task, considered=_ADMISSIBLE))
    return _descriptored(set_id, report, [record],
                         {task: _descriptor(**descriptor)}, trials)


def _keep_set(set_id, task="t", trials=1, **descriptor):
    """A set whose E2 label for ``task`` is no_change_recommended."""
    report = _retask(_report(
        _figures_for(router=(1.0, 0.005), best=(0.9, 0.01),
                     cheapest=(0.4, 0.02)),
        selections=_SELECTIONS,
    ), task)
    record = _complete(_router_record(task, considered=_ADMISSIBLE))
    return _descriptored(set_id, report, [record],
                         {task: _descriptor(**descriptor)}, trials)


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

    def test_trial_count_is_the_DECLARED_count_not_the_observed(self) -> None:
        # T2 round-1 P1: the feature reads the scenario's DECLARED
        # trials (a pre-routing corpus property persisted in the
        # descriptors artifact), NEVER the observed per-trial record
        # count. The fixture makes them differ: 5 declared, 1 recorded.
        entry = _switch_set("aa" * 32, task="n1", trials=5)
        self.assertEqual(entry.task_descriptors["trials"], 5)
        (example,) = extract_examples([entry])
        self.assertEqual(example.features["trial_count"], 5)
        # the observed count IS 1 — proving the two differ here, so a
        # record-sourced implementation cannot pass this test
        from session_analytics.routing_evidence import (
            derive_recommendations as _derive,
        )

        (rec,) = _derive(entry)
        self.assertEqual(rec["confidence"]["basis"]["trials"], 1)

    def test_declared_trials_change_distances(self) -> None:
        # the source is load-bearing, not cosmetic: two neighbors that
        # differ ONLY in declared trials sit at different distances, so
        # a record-sourced implementation reorders the neighborhood
        corpus = [
            _switch_set("aa" * 32, task="n1", file_scope=1, trials=1),
            _switch_set("bb" * 32, task="n2", file_scope=1, trials=9),
            _keep_set("cc" * 32, task="n3", file_scope=1, trials=5),
            _switch_set("dd" * 32, task="q", file_scope=1, trials=9),
        ]
        doc = knn_recommendation(corpus, "dd" * 32, "q", _POLICY,
                                 _CURRENT_POLICY)
        self.assertEqual([n["task_id"] for n in doc["neighbors"]],
                         ["n2", "n3", "n1"])

    def test_missing_declared_trials_refuses(self) -> None:
        # a descriptors artifact without the declared count cannot
        # produce features — refusal, never a substituted observation
        entry = _switch_set("aa" * 32, task="n1")
        artifact = dict(entry.task_descriptors)
        del artifact["trials"]
        from dataclasses import replace as _replace

        (example,) = extract_examples(
            [_replace(entry, task_descriptors=artifact)])
        self.assertIsNone(example.features)

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

    def test_neighbor_refs_are_E2_shaped_and_resolve(self) -> None:
        # T2 round-1 P2: neighbors carry the neighbor's OWN E2 refs in
        # the closed E2 shape — ONE resolver serves both surfaces — and
        # every locator resolves against that set's served artifacts.
        doc = self._recommend()
        corpus = {e.set_id: e for e in _corpus()}
        for neighbor in doc["neighbors"]:
            entry = corpus[neighbor["evidence_set_id"]]
            self.assertTrue(neighbor["evidence_refs"])
            arms_seen = set()
            for ref in neighbor["evidence_refs"]:
                self.assertEqual(ref["evidence_set_id"],
                                 neighbor["evidence_set_id"])
                locator = ref["locator"]
                if "arm" in locator:
                    arms_seen.add(locator["arm"])
                    self.assertIn(
                        locator["task"],
                        entry.report["arms"][locator["arm"]]["tasks"])
                elif "record" in locator:
                    self.assertLess(locator["record"], len(entry.records))
                else:
                    self.fail(f"unexpected locator {locator}")
            # not narrowed to cct_router: the neighbor's own refs cover
            # the compared arms, exactly as E2 attaches them
            self.assertTrue(arms_seen - {"cct_router"}, arms_seen)

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


# ── T3: held-out evaluation and the five gates ────────────────────────
from session_analytics.routing_calibration import (  # noqa: E402
    baseline_tier,
    compute_gates,
    evaluate_heldout,
    is_false_downgrade,
    load_evaluation_report,
    write_evaluation_report,
)

_TIER2_FLOOR = replace(_POLICY, tier_floor="tier2")


def _beta_switch_set(set_id, task, trials=1, **descriptor):
    """A set whose E2 label for ``task`` is switch_profile -> beta
    (a TIER-2 profile), used to drive downgrade arithmetic."""
    report = _retask(_report(
        _figures_for(router=(0.5, 0.05), best=(1.0, 0.01),
                     cheapest=(0.4, 0.02)),
        selections={"always_best": {"t": "beta"},
                    "always_cheapest": {"t": "beta"}},
    ), task)
    beta_admissible = (
        {"id": "beta", "verdict": "selected",
         "reason": "healthy — selected", "state": "healthy"},
    )
    record = _complete(_router_record(task, considered=beta_admissible,
                                      selected="beta"))
    return _descriptored(set_id, report, [record],
                         {task: _descriptor(**descriptor)}, trials)


def _config(**overrides):
    block = {
        "min_sufficiency": 0.95, "min_tasks": 1, "min_trials": 1,
        "min_sets": 1, "min_coverage": 0.8,
        "max_false_downgrade_rate": 0.05, "k": 5, "k_min": 3,
        "distance_metric": "l2_v1", "vote_epsilon": 1e-6,
        "tier_floor": "tier1", "policy_source": "",
    }
    block.update(overrides)
    return SimpleNamespace(routing_calibration=block)


class TestFalseDowngradeArithmetic(unittest.TestCase):
    """Decision 7, BOTH baseline branches, hand-checked."""

    def test_baseline_is_the_truth_tier_when_truth_switches(self) -> None:
        # The two branches must DISAGREE or the test proves nothing:
        # truth switches to a TIER-2 profile while the router ran only
        # tier1, so the truth branch says tier2 and the actual branch
        # would say tier1 — and the judgment flips with them.
        truth = {"outcome": "switch_profile",
                 "suggested": {"arm": "always_best", "profile_id": "beta"}}
        actual = {"per_trial": [{"trial": 0, "chain": ["router-prof"],
                                 "delegated": False, "reconciled": False}]}
        self.assertEqual(
            baseline_tier(truth, actual, _PROFILE_POLICY), "tier2")
        self.assertEqual(
            baseline_tier({"outcome": "no_change_recommended",
                           "suggested": None}, actual, _PROFILE_POLICY),
            "tier1", "the branches must differ for this to discriminate")
        predicted = {"outcome": "switch_profile",
                     "suggested": {"arm": "always_best",
                                   "profile_id": "beta"}}
        # against the TRUTH baseline (tier2) beta is not a downgrade;
        # under the wrong (actual) baseline it would be flagged
        self.assertFalse(is_false_downgrade(
            predicted, baseline_tier(truth, actual, _PROFILE_POLICY),
            _PROFILE_POLICY))
        self.assertTrue(is_false_downgrade(predicted, "tier1",
                                           _PROFILE_POLICY))
        # the round-1 rule still holds: tier2 against a within-tier-1
        # truth switch IS a downgrade
        alpha_truth = {"outcome": "switch_profile",
                       "suggested": {"arm": "always_best",
                                     "profile_id": "alpha"}}
        self.assertTrue(is_false_downgrade(
            predicted,
            baseline_tier(alpha_truth, actual, _PROFILE_POLICY),
            _PROFILE_POLICY))

    def test_baseline_is_the_actual_tier_when_truth_keeps(self) -> None:
        truth = {"outcome": "no_change_recommended", "suggested": None}
        tier1_actual = {"per_trial": [
            {"trial": 0, "chain": ["router-prof"], "delegated": False,
             "reconciled": False}]}
        self.assertEqual(
            baseline_tier(truth, tier1_actual, _PROFILE_POLICY), "tier1")
        # T3 round-1 P1: a chain is a COMPOSITION, not a menu. A
        # delegated task ran [tier1 orchestrator, tier2 delegate];
        # recommending the tier2 profile DROPS the tier1 leg, so the
        # baseline is the HIGHEST tier engaged and the delegated task
        # remains capable of a false downgrade.
        delegated_actual = {"per_trial": [
            {"trial": 0, "chain": ["router-prof", "beta"],
             "delegated": True, "reconciled": True}]}
        self.assertEqual(
            baseline_tier(truth, delegated_actual, _PROFILE_POLICY),
            "tier1")
        predicted = {"outcome": "switch_profile",
                     "suggested": {"arm": "always_best",
                                   "profile_id": "beta"}}
        self.assertTrue(is_false_downgrade(
            predicted,
            baseline_tier(truth, delegated_actual, _PROFILE_POLICY),
            _PROFILE_POLICY),
            "a delegated task must still be able to fail the gate")
        # a router that ran ONLY tier2 is genuinely at tier2
        self.assertEqual(
            baseline_tier(truth, {"per_trial": [
                {"trial": 0, "chain": ["beta"], "delegated": True,
                 "reconciled": False}]}, _PROFILE_POLICY), "tier2")
        self.assertFalse(is_false_downgrade(predicted, "tier2",
                                            _PROFILE_POLICY))

    def test_unresolvable_tiers_never_count_either_way(self) -> None:
        truth = {"outcome": "switch_profile",
                 "suggested": {"arm": "always_best",
                               "profile_id": "ghost"}}
        actual = {"per_trial": []}
        self.assertIsNone(baseline_tier(truth, actual, _PROFILE_POLICY))
        self.assertIsNone(baseline_tier(
            {"outcome": "no_change_recommended", "suggested": None},
            actual, None))
        predicted = {"outcome": "switch_profile",
                     "suggested": {"arm": "always_best",
                                   "profile_id": "beta"}}
        self.assertFalse(is_false_downgrade(predicted, None,
                                            _PROFILE_POLICY))
        self.assertFalse(is_false_downgrade(
            {"outcome": "no_change_recommended", "suggested": None},
            "tier1", _PROFILE_POLICY))


class TestHeldoutEvaluation(unittest.TestCase):
    def _downgrade_corpus(self):
        """Every neighbor is labeled switch->beta (tier2) while each
        held-out task's own truth is switch->beta as well; with a
        tier2 floor the predictions land on beta, and the baselines are
        tier2, so NOTHING is a false downgrade — the arithmetic is
        exercised without a violation."""
        return [
            _beta_switch_set("aa" * 32, "n1", file_scope=1),
            _beta_switch_set("bb" * 32, "n2", file_scope=2),
            _beta_switch_set("cc" * 32, "n3", file_scope=3),
            _beta_switch_set("dd" * 32, "n4", file_scope=4),
        ]

    def test_report_shape_and_arithmetic(self) -> None:
        report = evaluate_heldout(self._downgrade_corpus(), _TIER2_FLOOR,
                                  _CURRENT_POLICY)
        self.assertEqual(report["split"], "leave_one_task_out")
        self.assertEqual(report["evaluated"], 4)
        self.assertEqual(report["compared"], 4)
        self.assertEqual(report["refused"], 0)
        self.assertEqual(report["unresolved_tier"], 0)
        self.assertEqual(report["unevaluable"], 0)
        self.assertEqual(report["false_downgrades"], 0)
        self.assertEqual(report["false_downgrade_rate"], 0.0)
        self.assertEqual(report["floor_violations"], 0)
        self.assertEqual(report["agreement"], 1.0)
        self.assertEqual(report["policy"]["tier_floor"], "tier2")

    def test_downgrade_counted_against_a_tier1_baseline(self) -> None:
        # three beta (tier2) neighbours outvote nothing, so each held-out
        # task predicts switch->beta; the ALPHA-truth task's baseline is
        # tier1, so its prediction IS a false downgrade
        corpus = self._downgrade_corpus() + [
            _switch_set("ee" * 32, task="q", file_scope=2),
        ]
        report = evaluate_heldout(corpus, _TIER2_FLOOR, _CURRENT_POLICY)
        flags = {r["task_id"]: r["downgrade_flag"]
                 for r in report["results"]}
        self.assertTrue(flags["q"])
        self.assertEqual(report["false_downgrades"], 1)
        self.assertEqual(report["evaluated"], 5)
        self.assertAlmostEqual(report["false_downgrade_rate"], 1 / 5)

    def test_unlabeled_examples_are_unevaluable_not_denominator(self) -> None:
        corpus = self._downgrade_corpus()
        plain = _loaded_evidence(
            _retask(_report(_figures_for(router=(0.5, 0.05),
                                         best=(1.0, 0.01),
                                         cheapest=(0.4, 0.02)),
                            selections=_SELECTIONS), "u1"),
            [_router_record("u1", considered=_ADMISSIBLE)],
        )
        from dataclasses import replace as _replace

        corpus.append(_replace(plain, set_id="ff" * 32))
        report = evaluate_heldout(corpus, _TIER2_FLOOR, _CURRENT_POLICY)
        self.assertEqual(report["unevaluable"], 1)
        self.assertEqual(report["evaluated"], 4)
        self.assertNotIn("u1", [r["task_id"] for r in report["results"]])

    def test_heldout_task_never_votes_for_itself(self) -> None:
        # LEAKAGE (a): a same-task example in another set would let the
        # fold see its own answer. Two sets carry task "q" with
        # OPPOSITE labels; if the twin voted, the prediction would
        # follow it. All other neighbours are keep-labeled, so a
        # leaking implementation predicts switch for the switch twin.
        corpus = [
            _keep_set("aa" * 32, task="n1", file_scope=9),
            _keep_set("bb" * 32, task="n2", file_scope=9),
            _keep_set("cc" * 32, task="n3", file_scope=9),
            _switch_set("dd" * 32, task="q", file_scope=1),
            _switch_set("ee" * 32, task="q", file_scope=1),
        ]
        report = evaluate_heldout(corpus, _POLICY, _CURRENT_POLICY)
        for result in report["results"]:
            if result["task_id"] == "q":
                self.assertEqual(result["predicted"]["outcome"],
                                 "no_change_recommended")

    def test_bounds_fit_on_the_eligibility_filtered_pool(self) -> None:
        # An INELIGIBLE example with an extreme file_scope must not
        # stretch the fold's normalization bounds. HAND-COMPUTED:
        # eligible file_scope = {1, 2, 3} -> bounds [1, 3]; the query
        # (3) normalizes to 1.0 and the neighbours to 0, 0.5, 1.0, so
        # the distances are exactly 1.0, 0.5, 0.0. If the tier-2
        # outlier (10000) stretched the bounds, every distance would
        # collapse to ~1e-4 — asserting the ABSOLUTE values catches the
        # mutation, where comparing evaluation to serving cannot
        # (the mutation moves both together).
        corpus = [
            _switch_set("aa" * 32, task="n1", file_scope=1),
            _switch_set("bb" * 32, task="n2", file_scope=2),
            _keep_set("cc" * 32, task="n3", file_scope=3),
            _beta_switch_set("dd" * 32, "outlier", file_scope=10000),
            _switch_set("ee" * 32, task="q", file_scope=3),
        ]
        served = knn_recommendation(corpus, "ee" * 32, "q", _POLICY,
                                    _CURRENT_POLICY)
        by_task = {n["task_id"]: n["distance"] for n in served["neighbors"]}
        self.assertNotIn("outlier", by_task,
                         "a below-floor example must never be a neighbour")
        self.assertAlmostEqual(by_task["n3"], 0.0, places=12)
        self.assertAlmostEqual(by_task["n2"], 0.5, places=12)
        self.assertAlmostEqual(by_task["n1"], 1.0, places=12)
        # and the fold reproduces serving exactly
        report = evaluate_heldout(corpus, _POLICY, _CURRENT_POLICY)
        evaluated = next(r for r in report["results"]
                         if r["task_id"] == "q")
        self.assertEqual(evaluated["predicted"]["outcome"],
                         served["outcome"])


class TestRefusalsAndExclusions(unittest.TestCase):
    """T3 round-1 P1/P2: a refusal is not a recommendation. It must
    never dilute the false-downgrade rate nor count as held-out
    coverage, and a tier comparison that cannot resolve is UNJUDGED,
    not judged safe."""

    def _gates(self, report, corpus, policy=_POLICY):
        doc = compute_gates(corpus, _config(), policy, _CURRENT_POLICY,
                            report)
        return {g["id"]: g for g in doc["gates"]}, doc

    def test_all_refusing_recommender_cannot_pass(self) -> None:
        # two labeled examples against k_min=3: every fold refuses
        corpus = [
            _switch_set("aa" * 32, task="n1", file_scope=1),
            _switch_set("bb" * 32, task="n2", file_scope=2),
        ]
        report = evaluate_heldout(corpus, _POLICY, _CURRENT_POLICY)
        self.assertEqual(report["refused"], 2)
        self.assertEqual(report["compared"], 0)
        self.assertEqual(report["evaluated"], 0)
        self.assertIsNone(report["false_downgrade_rate"],
                          "an all-refusing run has no rate, not 0.0")
        gates, doc = self._gates(report, corpus)
        self.assertEqual(gates["false_downgrade"]["status"],
                         "insufficient_data")
        self.assertEqual(gates["heldout_evaluated"]["measured"], 0.0)
        self.assertEqual(gates["heldout_evaluated"]["status"], "fail")
        self.assertFalse(doc["calibrated"],
                         "an all-refusing recommender must never "
                         "reach calibrated")

    def test_refusals_do_not_dilute_the_rate(self) -> None:
        # the reviewer's arithmetic: 90 refusals + 10 judged
        # recommendations with 2 false downgrades is 0.20, not 0.02 —
        # and 0.20 fails the 0.05 threshold that 0.02 would pass.
        corpus = _corpus()
        base = evaluate_heldout(corpus, _POLICY, _CURRENT_POLICY)
        diluted = dict(
            base, results=[], refused=90, compared=10, evaluated=10,
            unresolved_tier=0, false_downgrades=2,
            false_downgrade_rate=2 / 10,
        )
        gates, _ = self._gates(diluted, corpus)
        self.assertEqual(gates["false_downgrade"]["status"], "fail")
        self.assertAlmostEqual(gates["false_downgrade"]["measured"], 0.2)
        self.assertIn("90 refused", gates["false_downgrade"]["reason"])

    def test_refusals_are_not_heldout_coverage(self) -> None:
        corpus = _corpus()
        report = evaluate_heldout(corpus, _POLICY, _CURRENT_POLICY)
        refusing = json.loads(json.dumps(report))
        for result in refusing["results"]:
            result["predicted"] = {"outcome": "insufficient_data",
                                   "suggested": None}
        gates, _ = self._gates(refusing, corpus)
        self.assertEqual(gates["heldout_evaluated"]["measured"], 0.0)
        self.assertEqual(gates["heldout_evaluated"]["status"], "fail")

    def test_unresolvable_tiers_leave_the_denominator(self) -> None:
        # the queried set's persisted policy does not declare the
        # predicted profile, so the comparison cannot resolve
        from dataclasses import replace as _replace

        corpus = _corpus()
        thin_policy = {
            "schema_version": 1, "registry_digest": "sha256:reg",
            "profiles": {"router-prof": {"capability_tier": "tier1",
                                         "roles": ["build"]}},
        }
        corpus = [
            _replace(e, profile_policy=thin_policy)
            if e.set_id == "dd" * 32 else e
            for e in corpus
        ]
        report = evaluate_heldout(corpus, _POLICY, _CURRENT_POLICY)
        self.assertGreaterEqual(report["unresolved_tier"], 1)
        self.assertEqual(
            report["evaluated"],
            report["compared"] - report["unresolved_tier"],
            "tier-unresolved predictions leave the judged denominator")
        self.assertEqual(report["false_downgrades"], 0)


class TestEvaluationReportPersistence(unittest.TestCase):
    def test_atomic_write_and_reload(self) -> None:
        import tempfile

        report = evaluate_heldout(_corpus(), _POLICY, _CURRENT_POLICY)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_evaluation_report(report, tmp)
            self.assertTrue(path.is_file())
            self.assertFalse(list(Path(tmp).glob("*.tmp")))
            self.assertEqual(load_evaluation_report(tmp), report)

    def test_absent_or_invalid_reports_load_as_none(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_evaluation_report(tmp))
            self.assertIsNone(load_evaluation_report(None))
            (Path(tmp) / "evaluation-report.json").write_text(
                '{"schema_version": 1}', encoding="utf-8")
            self.assertIsNone(load_evaluation_report(tmp))

    def test_invalid_report_is_never_persisted(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CalibrationError):
                write_evaluation_report({"schema_version": 1}, tmp)
            self.assertFalse(list(Path(tmp).iterdir()))


class TestGates(unittest.TestCase):
    def _gates(self, report, config=None, corpus=None,
               policy=_TIER2_FLOOR, current=_CURRENT_POLICY):
        doc = compute_gates(corpus if corpus is not None else _corpus(),
                            config or _config(), policy, current, report)
        return {g["id"]: g for g in doc["gates"]}, doc

    def _healthy(self):
        corpus = [
            _beta_switch_set("aa" * 32, "n1", file_scope=1),
            _beta_switch_set("bb" * 32, "n2", file_scope=2),
            _beta_switch_set("cc" * 32, "n3", file_scope=3),
            _beta_switch_set("dd" * 32, "n4", file_scope=4),
        ]
        policy = replace(_TIER2_FLOOR,
                         policy_source_digest="ab" * 32)
        report = evaluate_heldout(corpus, policy, _CURRENT_POLICY)
        return corpus, policy, report

    def test_all_five_gates_can_pass_together(self) -> None:
        corpus, policy, report = self._healthy()
        gates, doc = self._gates(report, corpus=corpus, policy=policy)
        self.assertEqual(sorted(gates), sorted(GATE_IDS))
        for gate_id, gate in gates.items():
            self.assertEqual(gate["status"], "pass",
                             f"{gate_id}: {gate['reason']}")
        self.assertTrue(doc["calibrated"])

    def test_missing_report_makes_three_gates_insufficient(self) -> None:
        corpus, policy, _ = self._healthy()
        gates, doc = self._gates(None, corpus=corpus, policy=policy)
        for gate_id in ("heldout_evaluated", "false_downgrade",
                        "floors_authoritative"):
            self.assertEqual(gates[gate_id]["status"], "insufficient_data")
        self.assertFalse(doc["calibrated"])

    def test_stale_corpus_and_stale_policy_are_insufficient(self) -> None:
        corpus, policy, report = self._healthy()
        stale_corpus = dict(report, corpus_id="ff" * 32)
        gates, _ = self._gates(stale_corpus, corpus=corpus, policy=policy)
        self.assertEqual(gates["heldout_evaluated"]["status"],
                         "insufficient_data")
        self.assertIn("corpus_changed",
                      gates["heldout_evaluated"]["reason"])
        stale_policy = dict(report, policy_id="ff" * 32)
        gates, _ = self._gates(stale_policy, corpus=corpus, policy=policy)
        self.assertEqual(gates["heldout_evaluated"]["status"],
                         "insufficient_data")
        self.assertIn("policy_changed",
                      gates["heldout_evaluated"]["reason"])
        self.assertEqual(gates["false_downgrade"]["status"],
                         "insufficient_data")

    def test_g1_measures_telemetry_completeness(self) -> None:
        corpus, policy, report = self._healthy()
        gates, _ = self._gates(report, corpus=corpus, policy=policy)
        self.assertEqual(gates["telemetry_complete"]["measured"], 1.0)
        # a record whose effective model is UNVERIFIED drops the
        # fraction below the threshold
        import copy

        from dataclasses import replace as _replace

        broken = copy.deepcopy(list(corpus[0].records))
        broken[0]["routing_decisions"][0]["effective_model"] = None
        corpus = [_replace(corpus[0], records=broken)] + corpus[1:]
        gates, _ = self._gates(report, corpus=corpus, policy=policy)
        self.assertEqual(gates["telemetry_complete"]["status"], "fail")
        self.assertLess(gates["telemetry_complete"]["measured"], 1.0)

    def test_g2_cannot_pass_on_an_unlabeled_corpus(self) -> None:
        plain = _loaded_evidence(
            _retask(_report(_figures_for(router=(0.5, 0.05),
                                         best=(1.0, 0.01),
                                         cheapest=(0.4, 0.02)),
                            selections=_SELECTIONS), "u1"),
            [_router_record("u1", considered=_ADMISSIBLE)],
        )
        gates, doc = self._gates(None, corpus=[plain])
        self.assertEqual(gates["labeled_volume"]["status"],
                         "insufficient_data")
        self.assertEqual(doc["corpus"]["labeled_tasks"], 0)
        self.assertFalse(doc["calibrated"])

    def test_g2_requires_trials_within_one_set(self) -> None:
        corpus, policy, report = self._healthy()
        gates, _ = self._gates(report, config=_config(min_trials=2),
                               corpus=corpus, policy=policy)
        self.assertEqual(gates["labeled_volume"]["status"], "fail")
        self.assertEqual(gates["labeled_volume"]["measured"], 0)

    def test_g4_fails_above_the_declared_threshold(self) -> None:
        corpus, policy, report = self._healthy()
        downgraded = dict(report, false_downgrades=2, evaluated=4,
                          false_downgrade_rate=0.5)
        gates, _ = self._gates(downgraded, corpus=corpus, policy=policy)
        self.assertEqual(gates["false_downgrade"]["status"], "fail")
        self.assertEqual(gates["false_downgrade"]["measured"], 0.5)

    def test_g5_three_conjuncts(self) -> None:
        corpus, policy, report = self._healthy()
        # (a) no current policy -> insufficient
        gates, _ = self._gates(report, corpus=corpus, policy=policy,
                               current=None)
        self.assertEqual(gates["floors_authoritative"]["status"],
                         "insufficient_data")
        # (b) a violation recorded in the report -> fail, never dropped
        violating = dict(report, floor_violations=1)
        gates, _ = self._gates(violating, corpus=corpus, policy=policy)
        self.assertEqual(gates["floors_authoritative"]["status"], "fail")
        self.assertIn("zero_violations",
                      gates["floors_authoritative"]["reason"])
        # (c) the report's policy digest must bind the CURRENT policy
        unbound = json.loads(json.dumps(report))
        unbound["policy"]["policy_source_digest"] = "cd" * 32
        gates, _ = self._gates(unbound, corpus=corpus, policy=policy)
        self.assertEqual(gates["floors_authoritative"]["status"], "fail")
        self.assertIn("policy_digest_bound",
                      gates["floors_authoritative"]["reason"])

    def test_gate_thresholds_are_never_completed_from_code(self) -> None:
        corpus, policy, report = self._healthy()
        for key in ("min_sufficiency", "min_tasks", "min_trials",
                    "min_sets", "min_coverage"):
            block = dict(_config().routing_calibration)
            del block[key]
            with self.assertRaisesRegex(CalibrationError, key):
                compute_gates(corpus, SimpleNamespace(
                    routing_calibration=block), policy,
                    _CURRENT_POLICY, report)


from session_analytics.routing_calibration import (  # noqa: E402
    calibration_payload,
    evaluation_payload,
    knn_payload,
)


class TestServedPayloads(unittest.TestCase):
    """T4 / decision 10: the payload builders. Every state is explicit
    (no-data, insufficient, gates-mixed, gates-all-pass, stale), the
    sanitization floor holds over the new payloads, and the evaluation
    aggregates — agreement included — ride beside the verdicts."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        from benchmark_runner.tests.test_routing_eval_quality import (
            _REGISTRY,
        )

        self.registry = str(_REGISTRY)
        # A deliberately identifiable root: the sweep below asserts no
        # payload ever echoes it (the E2 SENSITIVE-root idiom).
        self.root = Path(tempfile.mkdtemp(prefix="SENSITIVE-CALIB-ROOT."))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _cfg(self, **overrides):
        block = {"policy_source": self.registry, "root": str(self.root)}
        block.update(overrides)
        return _config(**block)

    def _healthy(self):
        """Four labeled sets whose truth switches to a tier-2 profile —
        the shape that makes a downgrade POSSIBLE, so a passing G4 is a
        measurement and not a vacuous one."""
        return [
            _beta_switch_set("aa" * 32, "n1", file_scope=1),
            _beta_switch_set("bb" * 32, "n2", file_scope=2),
            _beta_switch_set("cc" * 32, "n3", file_scope=3),
            _beta_switch_set("dd" * 32, "n4", file_scope=4),
        ]

    def _persist(self, corpus, cfg, mutate=None):
        policy = policy_from_config(cfg)
        report = dict(evaluate_heldout(corpus, policy,
                                       load_current_policy(cfg)))
        if mutate is not None:
            report = mutate(report)
        write_evaluation_report(report, self.root)
        return report

    # ── the five rendered states ──
    def test_no_data_state(self) -> None:
        payload = calibration_payload([], self._cfg())
        self.assertEqual(payload["state"], "report")
        self.assertFalse(payload["report"]["calibrated"])
        self.assertEqual(payload["report"]["corpus"]["sets"], 0)
        self.assertTrue(all(g["status"] == "insufficient_data"
                            for g in payload["report"]["gates"]))
        self.assertFalse(payload["evaluation"]["present"])
        # one shape renders every state: the aggregates exist as nulls
        for key in ("agreement", "compared", "false_downgrade_rate"):
            self.assertIsNone(payload["evaluation"][key])

    def test_insufficient_state_when_policy_cannot_be_assembled(self):
        block = dict(self._cfg().routing_calibration)
        del block["k"]
        payload = calibration_payload(
            self._healthy(), SimpleNamespace(routing_calibration=block))
        self.assertEqual(payload["state"], "insufficient_data")
        self.assertIn("'k'", payload["reason"])
        self.assertIsNone(payload["report"])
        self.assertIsNone(payload["policy"])
        self.assertFalse(payload["evaluation"]["present"])

    def test_gates_mixed_state(self) -> None:
        corpus = self._healthy()
        cfg = self._cfg()
        self._persist(corpus, cfg)
        # an impossible telemetry threshold fails G1 alone
        payload = calibration_payload(corpus, self._cfg(min_sufficiency=1.1))
        statuses = {g["id"]: g["status"] for g in payload["report"]["gates"]}
        self.assertEqual(statuses["telemetry_complete"], "fail")
        self.assertIn("pass", statuses.values())
        self.assertFalse(payload["report"]["calibrated"])

    def test_gates_all_pass_state(self) -> None:
        corpus = self._healthy()
        cfg = self._cfg()
        self._persist(corpus, cfg)
        payload = calibration_payload(corpus, cfg)
        self.assertTrue(payload["report"]["calibrated"],
                        [g for g in payload["report"]["gates"]
                         if g["status"] != "pass"])
        self.assertTrue(payload["evaluation"]["present"])
        self.assertFalse(payload["evaluation"]["stale"])
        self.assertEqual(payload["policy"]["feature_vocabulary"],
                         FEATURE_VOCABULARY_VERSION)

    def test_stale_state_is_explicit_in_both_payloads(self) -> None:
        corpus = self._healthy()
        cfg = self._cfg()
        self._persist(corpus, cfg, mutate=lambda r: dict(
            r, corpus_id="ff" * 32, policy_id="ff" * 32))
        payload = calibration_payload(corpus, cfg)
        self.assertTrue(payload["evaluation"]["present"])
        self.assertTrue(payload["evaluation"]["stale"])
        self.assertEqual(sorted(payload["evaluation"]["stale_reasons"]),
                         ["corpus_changed", "policy_changed"])
        # and a stale report satisfies no gate
        statuses = {g["id"]: g["status"] for g in payload["report"]["gates"]}
        for gate_id in ("heldout_evaluated", "false_downgrade",
                        "floors_authoritative"):
            self.assertEqual(statuses[gate_id], "insufficient_data")
        self.assertFalse(payload["report"]["calibrated"])

        evaluation = evaluation_payload(corpus, cfg)
        self.assertEqual(evaluation["state"], "report")
        self.assertTrue(evaluation["staleness"]["stale"])
        self.assertEqual(sorted(evaluation["staleness"]["reasons"]),
                         ["corpus_changed", "policy_changed"])

    # ── agreement beside the verdicts (the T3-review forward note) ──
    def test_an_inert_recommender_passes_every_gate(self) -> None:
        """The gates are a SAFETY floor and cannot, by construction,
        distinguish a useful recommender from one that proposes
        nothing: a keep-everything recommender makes real
        recommendations, none of which can be a downgrade, so it earns
        a truthful 0.0 rate and full coverage. Agreement is the only
        number that separates them, so it must be ON the payload."""
        corpus = self._healthy()
        cfg = self._cfg()

        def inert(report):
            results = [dict(r, predicted={"outcome": "no_change_recommended",
                                          "suggested": None},
                            downgrade_flag=False)
                       for r in report["results"]]
            # truth switches for every task here, so an all-keep
            # recommender agrees with NONE of them
            self.assertTrue(results, "the fixture must produce results")
            self.assertTrue(all(r["truth"]["outcome"] == "switch_profile"
                                for r in results))
            return dict(report, results=results, agreement=0.0,
                        false_downgrades=0, false_downgrade_rate=0.0,
                        compared=len(results), evaluated=len(results),
                        refused=0, unresolved_tier=0, unevaluable=0,
                        floor_violations=0)

        self._persist(corpus, cfg, mutate=inert)
        payload = calibration_payload(corpus, cfg)
        # every gate passes — this is the honest verdict, not a bug
        self.assertTrue(payload["report"]["calibrated"])
        # ...and the payload still shows the operator WHY it is inert
        self.assertEqual(payload["evaluation"]["agreement"], 0.0)
        self.assertEqual(payload["evaluation"]["false_downgrade_rate"], 0.0)
        self.assertEqual(payload["evaluation"]["compared"], 4)

    def test_every_evaluation_aggregate_reaches_the_payload(self) -> None:
        # a mutation that drops any aggregate from the served summary
        # must be caught: the promotion decision reads ALL of them
        corpus = self._healthy()
        cfg = self._cfg()
        report = self._persist(corpus, cfg)
        summary = calibration_payload(corpus, cfg)["evaluation"]
        for key in ("agreement", "compared", "evaluated", "refused",
                    "unresolved_tier", "unevaluable", "false_downgrades",
                    "false_downgrade_rate", "floor_violations"):
            self.assertIn(key, summary)
            self.assertEqual(summary[key], report[key], key)

    # ── the sanitization floor over the NEW payloads ──
    def test_no_payload_echoes_a_configured_path(self) -> None:
        corpus = self._healthy()
        cfg = self._cfg()
        self._persist(corpus, cfg)
        broken = dict(cfg.routing_calibration)
        del broken["k"]
        payloads = [
            calibration_payload(corpus, cfg),
            calibration_payload([], cfg),
            calibration_payload(corpus,
                                SimpleNamespace(routing_calibration=broken)),
            evaluation_payload(corpus, cfg),
            evaluation_payload(corpus, SimpleNamespace(
                routing_calibration=broken)),
            knn_payload(corpus, "aa" * 32, cfg),
            knn_payload(corpus, "aa" * 32,
                        SimpleNamespace(routing_calibration=broken)),
        ]
        for payload in payloads:
            text = json.dumps(payload, sort_keys=True)
            self.assertNotIn("SENSITIVE-CALIB-ROOT", text)
            self.assertNotIn(str(self.root), text)
            self.assertNotIn(self.registry, text)
        # the policy echo carries the DIGEST of the source, not a path
        self.assertEqual(
            len(calibration_payload(corpus, cfg)["policy"]
                ["policy_source_digest"]), 64)

    # ── the kNN surface ──
    def test_knn_payload_covers_every_task_of_the_set(self) -> None:
        corpus = self._healthy()
        cfg = self._cfg()
        payload = knn_payload(corpus, "aa" * 32, cfg)
        self.assertEqual(payload["state"], "report")
        self.assertEqual(payload["set_id"], "aa" * 32)
        tasks = [r["task_id"] for r in payload["recommendations"]]
        self.assertEqual(tasks, ["n1"])
        for rec in payload["recommendations"]:
            self.assertEqual(rec["evidence_set_id"], "aa" * 32)
            self.assertFalse(validate(rec,
                                      load_schema("knn-recommendation")))

    def test_knn_payload_refuses_per_task_never_globally(self) -> None:
        # one undescriptored set beside labeled neighbors: the task
        # refuses with ITS reason while the payload still serves
        corpus = self._healthy()
        corpus.append(replace(_switch_set("ee" * 32, task="bare"),
                              task_descriptors=None))
        payload = knn_payload(corpus, "ee" * 32, self._cfg())
        self.assertEqual(payload["state"], "report")
        (rec,) = payload["recommendations"]
        self.assertEqual(rec["outcome"], "insufficient_data")
        self.assertIn("descriptor", rec["insufficient_reason"])

    def test_knn_payload_insufficient_when_policy_is_unassemblable(self):
        block = dict(self._cfg().routing_calibration)
        del block["k_min"]
        payload = knn_payload(self._healthy(), "aa" * 32,
                              SimpleNamespace(routing_calibration=block))
        self.assertEqual(payload["state"], "insufficient_data")
        self.assertEqual(payload["recommendations"], [])

    # ── the evaluation endpoint's own absent state ──
    def test_evaluation_payload_without_a_persisted_report(self) -> None:
        payload = evaluation_payload(self._healthy(), self._cfg())
        self.assertEqual(payload["state"], "insufficient_data")
        self.assertIsNone(payload["report"])
        self.assertIsNone(payload["staleness"])
        self.assertIn("calibration root", payload["reason"])


if __name__ == "__main__":
    unittest.main()
