# Tests for #287 T1 — compatibility rule, pure similarity math, config.
# No store, no graph, no backend anywhere in this file: T1 is pure.

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from session_analytics import config as cfgmod
from session_analytics.embedding.similarity import (
    SpaceGroups,
    cosine,
    group_by_space,
    space_key,
    top_k_neighbors,
)


def _env(provider="ollama", model="nomic-embed-text", dim=3,
         vector=(0.1, -0.2, 0.3)):
    return {
        "schema_version": 1, "provider": provider, "model": model,
        "dim": dim, "embedded_at": "2026-09-02T18:00:00+00:00",
        "vector": list(vector),
    }


class TestSpaceKey(unittest.TestCase):
    """FR-A: the triple, and nothing weaker."""

    def test_equal_triples_share_a_space(self) -> None:
        self.assertEqual(space_key(_env()), space_key(_env()))

    def test_each_component_alone_separates(self) -> None:
        base = space_key(_env())
        self.assertNotEqual(base, space_key(_env(provider="other")))
        self.assertNotEqual(base, space_key(_env(model="other-model")))
        self.assertNotEqual(
            base, space_key(_env(dim=4, vector=(0.1, 0.2, 0.3, 0.4))))

    def test_unvalidated_envelope_is_refused_not_keyed(self) -> None:
        # A space is a comparison license; an invalid envelope must not
        # get one. The refusal carries the FR-9 reason.
        bad = _env(vector=(0.0, 0.0, 0.0))  # zero vector: FR-9 refuses
        with self.assertRaises(ValueError) as ctx:
            space_key(bad)
        self.assertIn("zero vector", str(ctx.exception))


class TestGrouping(unittest.TestCase):
    """FR-A grouping + dim_conflict surfacing; validated-only."""

    def test_two_spaces_partition(self) -> None:
        g = group_by_space({
            1: _env(), 2: _env(),
            3: _env(model="other-model"),
        })
        self.assertEqual(len(g.groups), 2)
        self.assertEqual(g.groups[space_key(_env())], [1, 2])

    def test_invalid_envelope_excluded_with_reason(self) -> None:
        g = group_by_space({
            1: _env(),
            2: {"schema_version": 1},  # missing fields
            3: "not even a mapping",   # type: ignore[dict-item]
        })
        self.assertEqual(sorted(g.excluded_invalid), [2, 3])
        self.assertIn("missing fields", g.excluded_invalid[2])
        self.assertEqual(sum(len(v) for v in g.groups.values()), 1)

    def test_dim_conflict_reported_and_nobody_disqualified(self) -> None:
        # THE THREE-SESSION DISCRIMINATOR (review round 3): two valid
        # 3-dim sessions plus one same-named 4-dim session. The
        # conflict is reported with both dims; the 3-dim PAIR remains
        # comparable (same group); the 4-dim session stays eligible in
        # its OWN group. A conflict never disqualifies either group.
        g = group_by_space({
            1: _env(), 2: _env(),
            3: _env(dim=4, vector=(0.1, 0.2, 0.3, 0.4)),
        })
        self.assertEqual(
            g.dim_conflicts, {("ollama", "nomic-embed-text"): (3, 4)})
        self.assertEqual(g.groups[("ollama", "nomic-embed-text", 3)], [1, 2])
        self.assertEqual(g.groups[("ollama", "nomic-embed-text", 4)], [3])
        self.assertEqual(g.excluded_invalid, {})

    def test_no_conflict_when_dims_agree(self) -> None:
        g = group_by_space({1: _env(), 2: _env()})
        self.assertEqual(g.dim_conflicts, {})

    def test_deterministic_partition(self) -> None:
        envs = {i: _env() for i in (5, 1, 3)}
        a, b = group_by_space(envs), group_by_space(dict(reversed(list(envs.items()))))
        self.assertEqual(a, b)
        self.assertEqual(a.groups[space_key(_env())], [1, 3, 5])


class TestCosine(unittest.TestCase):
    """FR-C: hand-computed fixtures; the zero-norm contract."""

    def test_identical_is_one(self) -> None:
        self.assertAlmostEqual(cosine([1.0, 2.0], [1.0, 2.0]), 1.0)

    def test_orthogonal_is_zero(self) -> None:
        self.assertAlmostEqual(cosine([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_opposite_is_minus_one(self) -> None:
        self.assertAlmostEqual(cosine([1.0, 0.0], [-1.0, 0.0]), -1.0)

    def test_hand_computed_value(self) -> None:
        # (1,1)·(1,0) / (√2·1) = 1/√2
        self.assertAlmostEqual(cosine([1.0, 1.0], [1.0, 0.0]), 0.7071067811865475)

    def test_dim_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            cosine([1.0], [1.0, 2.0])

    def test_zero_norm_is_a_caller_bug_not_a_score(self) -> None:
        # FR-9 refuses zero vectors upstream; reaching cosine with one
        # is a broken caller and must raise, never return a number.
        with self.assertRaises(ValueError) as ctx:
            cosine([0.0, 0.0], [1.0, 0.0])
        self.assertIn("FR-9", str(ctx.exception))


class TestTopK(unittest.TestCase):
    def test_threshold_and_k_respected(self) -> None:
        vectors = {
            1: [1.0, 0.0], 2: [1.0, 0.1], 3: [0.0, 1.0], 4: [1.0, 0.05],
        }
        out = top_k_neighbors(vectors, k=1, threshold=0.9)
        # 1's best is 4 (cos≈0.99875) over 2 (cos≈0.99504); 3 is near-
        # orthogonal to all and below threshold everywhere.
        self.assertEqual([n for n, _ in out[1]], [4])
        self.assertEqual(out[3], [])
        for pairs in out.values():
            self.assertLessEqual(len(pairs), 1)

    def test_scores_are_symmetric_membership_is_not(self) -> None:
        vectors = {1: [1.0, 0.0], 2: [1.0, 0.1], 3: [1.0, 0.11]}
        out = top_k_neighbors(vectors, k=1, threshold=0.0)
        # 2 and 3 pick each other (closest); 1 picks 2 but is nobody's
        # top-1 — kNN membership is asymmetric by nature.
        self.assertEqual([n for n, _ in out[2]], [3])
        self.assertEqual([n for n, _ in out[3]], [2])
        self.assertEqual([n for n, _ in out[1]], [2])

    def test_deterministic_tie_break_by_ascending_id(self) -> None:
        vectors = {1: [1.0, 0.0], 5: [2.0, 0.0], 3: [3.0, 0.0]}
        out = top_k_neighbors(vectors, k=2, threshold=0.0)
        # all pairs score exactly 1.0: ties break by ascending id.
        self.assertEqual([n for n, _ in out[1]], [3, 5])
        self.assertEqual([n for n, _ in out[5]], [1, 3])

    def test_nonpositive_k_refused(self) -> None:
        with self.assertRaises(ValueError):
            top_k_neighbors({1: [1.0]}, k=0, threshold=0.5)

    def test_below_threshold_yields_empty_healthy(self) -> None:
        vectors = {1: [1.0, 0.0], 2: [0.0, 1.0]}
        out = top_k_neighbors(vectors, k=3, threshold=0.9)
        self.assertEqual(out, {1: [], 2: []})


class TestSimilarityConfig(unittest.TestCase):
    """FR-C knobs through the proven five-layer precedence (the #285
    T1 hermetic harness pattern)."""

    def _load(self, *, user_json=None, dotenv=None, environ=None, cli=None):
        tmp = Path(tempfile.mkdtemp())
        user_path = tmp / "session-analytics.json"
        if user_json is not None:
            user_path.write_text(json.dumps(user_json), encoding="utf-8")
        base = {k: v for k, v in os.environ.items()
                if not k.startswith("CCT_SA_")}
        base.update(environ or {})
        with mock.patch.object(cfgmod, "_USER_CONFIG", user_path), \
             mock.patch.object(cfgmod, "parse_env_file",
                               lambda *a, **k: dict(dotenv or {})), \
             mock.patch.dict("os.environ", base, clear=True):
            return cfgmod.load_config(
                extra_overrides={"similarity": cli} if cli is not None else None
            )

    def test_defaults_layer(self) -> None:
        sim = self._load().similarity
        self.assertEqual((sim.threshold, sim.top_k), (0.55, 5))

    def test_five_layer_ladder(self) -> None:
        sim = self._load(
            user_json={"similarity": {"top_k": 2}},
            dotenv={cfgmod.ENV_SIMILARITY_TOP_K: "3"},
            environ={cfgmod.ENV_SIMILARITY_TOP_K: "4"},
            cli={"top_k": 9},
        ).similarity
        self.assertEqual(sim.top_k, 9)
        sim = self._load(
            user_json={"similarity": {"top_k": 2}},
            dotenv={cfgmod.ENV_SIMILARITY_TOP_K: "3"},
            environ={cfgmod.ENV_SIMILARITY_TOP_K: "4"},
        ).similarity
        self.assertEqual(sim.top_k, 4)
        sim = self._load(
            user_json={"similarity": {"top_k": 2}},
            dotenv={cfgmod.ENV_SIMILARITY_TOP_K: "3"},
        ).similarity
        self.assertEqual(sim.top_k, 3)
        sim = self._load(user_json={"similarity": {"top_k": 2}}).similarity
        self.assertEqual(sim.top_k, 2)

    def test_missing_block_refused_not_reconstructed(self) -> None:
        base_defaults = cfgmod._read_defaults()
        stripped = {k: v for k, v in base_defaults.items() if k != "similarity"}
        with mock.patch.object(cfgmod, "_read_defaults", lambda: stripped):
            with self.assertRaises(ValueError) as ctx:
                self._load()
        self.assertIn("single source of similarity defaults", str(ctx.exception))

    def test_missing_key_named(self) -> None:
        base_defaults = cfgmod._read_defaults()
        crippled = json.loads(json.dumps(base_defaults))
        del crippled["similarity"]["threshold"]
        with mock.patch.object(cfgmod, "_read_defaults", lambda: crippled):
            with self.assertRaises(ValueError) as ctx:
                self._load()
        self.assertIn("threshold", str(ctx.exception))

    def test_sentinel_flows_from_the_data_file(self) -> None:
        base_defaults = cfgmod._read_defaults()
        sentinel = json.loads(json.dumps(base_defaults))
        sentinel["similarity"]["threshold"] = 0.123
        with mock.patch.object(cfgmod, "_read_defaults", lambda: sentinel):
            self.assertEqual(self._load().similarity.threshold, 0.123)


if __name__ == "__main__":
    unittest.main()
