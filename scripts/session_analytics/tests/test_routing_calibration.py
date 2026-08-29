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


if __name__ == "__main__":
    unittest.main()
