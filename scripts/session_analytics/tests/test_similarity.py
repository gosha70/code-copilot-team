# Tests for #287 T1 — compatibility rule, pure similarity math, config.
# No store, no graph, no backend anywhere in this file: T1 is pure.

from __future__ import annotations

import json
import math
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

    def test_grouping_separates_by_provider(self) -> None:
        # THE GROUPING BOUNDARY discriminator (review round 4: a
        # provider-dropping mutation inside group_by_space escaped all
        # 24 tests because the discriminator only covered the
        # standalone helper). These three pins hit the boundary T2
        # consumes.
        g = group_by_space({1: _env(), 2: _env(provider="other")})
        self.assertEqual(len(g.groups), 2)

    def test_grouping_separates_by_model(self) -> None:
        g = group_by_space({1: _env(), 2: _env(model="other-model")})
        self.assertEqual(len(g.groups), 2)

    def test_grouping_separates_by_dim(self) -> None:
        g = group_by_space({
            1: _env(), 2: _env(dim=4, vector=(0.1, 0.2, 0.3, 0.4))})
        self.assertEqual(len(g.groups), 2)

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

    # ── numerical safety: FR-9 bounds finiteness, not magnitude ──────
    def test_huge_components_do_not_overflow_to_nan(self) -> None:
        # [1e200, 1e200] passes FR-9 (finite, nonzero); its naive
        # sum-of-squares is inf and inf/inf is NaN — which top-K would
        # silently read as "no neighbors". Route through validation
        # first to prove these are legitimate envelopes, then score.
        env = _env(dim=2, vector=(1e200, 1e200))
        self.assertEqual(space_key(env), ("ollama", "nomic-embed-text", 2))
        s = cosine([1e200, 1e200], [1e200, 1e200])
        self.assertTrue(math.isfinite(s))
        self.assertAlmostEqual(s, 1.0)

    def test_tiny_components_do_not_underflow_to_false_zero_norm(self) -> None:
        # [1e-200, 1e-200] passes FR-9; its naive squares underflow to
        # 0.0 and the old code raised the "caller bug" zero-norm error
        # for a perfectly valid vector.
        env = _env(dim=2, vector=(1e-200, 1e-200))
        self.assertEqual(space_key(env), ("ollama", "nomic-embed-text", 2))
        s = cosine([1e-200, 1e-200], [1e-200, 1e-200])
        self.assertTrue(math.isfinite(s))
        self.assertAlmostEqual(s, 1.0)

    def test_mixed_magnitudes_stay_finite(self) -> None:
        s = cosine([1e200, 0.0], [1e-200, 0.0])
        self.assertTrue(math.isfinite(s))
        self.assertAlmostEqual(s, 1.0)

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

    # ── validation before coercion (review round 4) ──────────────────
    def test_nan_threshold_refused_via_env(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._load(environ={cfgmod.ENV_SIMILARITY_THRESHOLD: "nan"})
        self.assertIn("similarity.threshold", str(ctx.exception))
        self.assertIn("finite", str(ctx.exception))

    def test_inf_threshold_refused_via_env(self) -> None:
        with self.assertRaises(ValueError):
            self._load(environ={cfgmod.ENV_SIMILARITY_THRESHOLD: "inf"})

    def test_out_of_range_threshold_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._load(cli={"threshold": 1.5})
        self.assertIn("[-1.0, 1.0]", str(ctx.exception))

    def test_boolean_threshold_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._load(cli={"threshold": True})

    def test_fractional_top_k_refused_not_truncated(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._load(user_json={"similarity": {"top_k": 1.9}})
        self.assertIn("similarity.top_k", str(ctx.exception))

    def test_boolean_top_k_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._load(cli={"top_k": True})

    def test_zero_top_k_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._load(cli={"top_k": 0})
        self.assertIn("positive", str(ctx.exception))

    def test_integral_string_top_k_from_env_accepted(self) -> None:
        sim = self._load(
            environ={cfgmod.ENV_SIMILARITY_TOP_K: "4"}).similarity
        self.assertEqual(sim.top_k, 4)

    def test_non_numeric_threshold_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._load(environ={cfgmod.ENV_SIMILARITY_THRESHOLD: "high"})

    def test_sentinel_flows_from_the_data_file(self) -> None:
        base_defaults = cfgmod._read_defaults()
        sentinel = json.loads(json.dumps(base_defaults))
        sentinel["similarity"]["threshold"] = 0.123
        with mock.patch.object(cfgmod, "_read_defaults", lambda: sentinel):
            self.assertEqual(self._load().similarity.threshold, 0.123)


if __name__ == "__main__":
    unittest.main()


class _FakeEdgeStore:
    """GraphEdgeStore with REAL transaction semantics: mutations buffer
    between begin() and commit(); rollback() discards them — so the
    injected-failure test asserts on actual edge state, not on call
    sequences."""

    def __init__(self, nodes=(), edges=None, ready=True):
        self.nodes = set(nodes)
        self.edges: dict[tuple[str, str], float] = dict(edges or {})
        self._tx: dict[tuple[str, str], float] | None = None
        self.begin_calls = 0
        self.rollback_calls = 0
        self.fail_on_write: int | None = None  # fail the Nth write_edge
        self.fail_on_commit = False
        self.rollback_raises = None  # simulate kuzu's auto-abort state
        self._ready = ready
        self._writes = 0

    def graph_ready(self):
        return self._ready

    def _view(self):
        return self._tx if self._tx is not None else self.edges

    def begin(self):
        self.begin_calls += 1
        self._tx = dict(self.edges)

    def commit(self):
        assert self._tx is not None, "commit outside a transaction"
        if self.fail_on_commit:
            raise RuntimeError("injected commit failure")
        self.edges = self._tx
        self._tx = None

    def rollback(self):
        self.rollback_calls += 1
        if self.rollback_raises is not None:
            raise self.rollback_raises
        assert self._tx is not None, "rollback outside a transaction"
        self._tx = None

    def existing_edge_sources(self):
        return {src for src, _ in self._view()}

    def node_exists(self, session_key):
        return session_key in self.nodes

    def delete_outgoing(self, session_key):
        view = self._view()
        gone = [k for k in view if k[0] == session_key]
        for k in gone:
            del view[k]
        return len(gone)

    def write_edge(self, src_key, dst_key, score):
        self._writes += 1
        if self.fail_on_write is not None and self._writes >= self.fail_on_write:
            raise RuntimeError("injected write failure")
        self._view()[(src_key, dst_key)] = score


class TestSimilarRunner(unittest.TestCase):
    """T2 — FR-D reconciliation + FR-E lifecycle, against the fake
    store (kuzu-free); the Kùzu store itself is exercised by the
    kuzu-marked class below (CI installs kuzu)."""

    def setUp(self) -> None:
        from session_analytics.config import SimilarityConfig
        from session_analytics.relational.db import Database, apply_ddl

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-similar-"))
        self.db = Database.connect(f"sqlite:///{tmp / 'sa.db'}")
        apply_ddl(self.db)
        self.addCleanup(self.db.close)
        self.cfg = SimilarityConfig(threshold=0.2, top_k=3)

    def _session(self, native_id, envelope):
        stored = json.dumps(envelope) if isinstance(envelope, dict) else envelope
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count, "
            "session_embedding) VALUES (?, ?, ?, ?) RETURNING id",
            ("claude-code", native_id, 0, stored),
        )
        self.db.commit()
        return sid, f"claude-code:{native_id}"

    def _run(self, store):
        from session_analytics.embedding.similar_runner import run_similar

        return run_similar(self.db, self.cfg, store)

    def test_edges_written_within_a_space(self) -> None:
        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(vector=(0.9, 0.1, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})
        stats = self._run(store)
        self.assertEqual(stats.action, "reconciled")
        self.assertIn((ka, kb), store.edges)
        self.assertIn((kb, ka), store.edges)
        self.assertEqual(stats.written_edges, 2)

    def test_cross_space_edges_are_impossible(self) -> None:
        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(model="other", vector=(1.0, 0.0, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})
        self._run(store)
        self.assertEqual(store.edges, {})  # identical vectors, different space

    def test_run_twice_converges(self) -> None:
        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(vector=(0.9, 0.1, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})
        self._run(store)
        first = dict(store.edges)
        stats2 = self._run(store)
        self.assertEqual(store.edges, first)
        self.assertEqual(stats2.written_edges, 2)  # rewritten, same set

    def test_removed_source_edges_are_retired(self) -> None:
        # THE COUNTER-EXAMPLE from plan review: A→B exists, A's
        # envelope goes away — A is no longer eligible, and its edge
        # must retire anyway.
        sid_a, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(vector=(0.9, 0.1, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})
        self._run(store)
        self.db.execute(
            "UPDATE copilot_session SET session_embedding = NULL WHERE id = ?",
            (sid_a,))
        self.db.commit()
        stats = self._run(store)
        self.assertEqual([k for k in store.edges if k[0] == ka], [])
        self.assertGreaterEqual(stats.retired_sources, 1)

    def test_all_ineligible_retires_everything_and_says_so(self) -> None:
        sid_a, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        sid_b, kb = self._session("b", _env(vector=(0.9, 0.1, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})
        self._run(store)
        for sid in (sid_a, sid_b):
            self.db.execute(
                "UPDATE copilot_session SET session_embedding = NULL "
                "WHERE id = ?", (sid,))
        self.db.commit()
        stats = self._run(store)
        self.assertEqual(store.edges, {})
        self.assertEqual(stats.action, "reconciled")  # retirement RAN
        self.assertEqual(stats.retired_edges, 2)

    def test_truly_empty_store_is_nothing_to_do(self) -> None:
        store = _FakeEdgeStore()
        stats = self._run(store)
        self.assertEqual(stats.action, "nothing-to-do")
        self.assertEqual(store.begin_calls, 0)  # no tx at all

    def test_missing_graph_node_counted_never_created(self) -> None:
        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(vector=(0.9, 0.1, 0.0)))
        store = _FakeEdgeStore(nodes={ka})  # b has no graph node
        stats = self._run(store)
        self.assertEqual(stats.missing_graph_node, 1)
        self.assertEqual(store.edges, {})   # a alone: no neighbors
        self.assertEqual(store.nodes, {ka})  # nothing created

    def test_invalid_envelope_excluded_and_reported(self) -> None:
        self._session("bad", "not json")
        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        store = _FakeEdgeStore(nodes={ka})
        stats = self._run(store)
        self.assertEqual(len(stats.excluded_invalid), 1)

    def test_injected_write_failure_preserves_previous_edge_set(self) -> None:
        # THE T2 INTEGRATION REQUIREMENT: the mutation phase is
        # transactional, so a mid-write failure leaves the PREVIOUS
        # complete edge set intact — scores describe the last COMPLETED
        # pass.
        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(vector=(0.9, 0.1, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})
        self._run(store)
        previous = dict(store.edges)
        self.assertTrue(previous)
        store.fail_on_write = 1  # next pass: first write explodes
        with self.assertRaises(RuntimeError):
            self._run(store)
        self.assertEqual(store.edges, previous)  # rolled back, intact

    def test_commit_failure_triggers_rollback_and_preserves_edges(self) -> None:
        # Review round: commit sat OUTSIDE the try, so a commit failure
        # triggered zero rollbacks and left the pending replacement
        # exposed on the live connection. Commit is now part of the
        # protected phase.
        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(vector=(0.9, 0.1, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})
        self._run(store)
        previous = dict(store.edges)
        store.fail_on_commit = True
        with self.assertRaises(RuntimeError):
            self._run(store)
        self.assertEqual(store.rollback_calls, 1)
        self.assertEqual(store.edges, previous)

    def test_cleanup_never_replaces_the_original_error(self) -> None:
        # Kùzu auto-aborts some in-tx failures; ROLLBACK then raises
        # "No active transaction". The ORIGINAL failure must propagate,
        # not the cleanup's.
        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(vector=(0.9, 0.1, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})
        store.fail_on_write = 1
        store.rollback_raises = RuntimeError("No active transaction for ROLLBACK.")
        with self.assertRaises(RuntimeError) as ctx:
            self._run(store)
        self.assertIn("injected write failure", str(ctx.exception))
        self.assertNotIn("No active transaction", str(ctx.exception))

    def test_unready_graph_is_a_prerequisite_error_before_any_read(self) -> None:
        from session_analytics.embedding.similar_runner import GraphNotReadyError

        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        store = _FakeEdgeStore(nodes={ka}, ready=False)
        with self.assertRaises(GraphNotReadyError) as ctx:
            self._run(store)
        self.assertIn("graph", str(ctx.exception))
        self.assertEqual(store.begin_calls, 0)  # nothing was attempted
        self.assertEqual(store.nodes, {ka})     # nothing created

    def test_no_embedding_backend_is_ever_consulted(self) -> None:
        # FR-E: strictly local. The embedding registry must not be
        # touched by this pass under any input.
        from session_analytics.embedding import registry as embreg

        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(vector=(0.9, 0.1, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})

        def _forbidden(*a, **k):
            raise AssertionError("embedding backend consulted by `similar`")

        with mock.patch.object(embreg, "get_embedding", _forbidden):
            stats = self._run(store)
        self.assertEqual(stats.written_edges, 2)

    def test_threshold_and_top_k_govern_edges(self) -> None:
        from session_analytics.config import SimilarityConfig

        _, ka = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        _, kb = self._session("b", _env(vector=(0.0, 1.0, 0.0)))
        store = _FakeEdgeStore(nodes={ka, kb})
        self.cfg = SimilarityConfig(threshold=0.9, top_k=3)
        stats = self._run(store)
        self.assertEqual(store.edges, {})  # orthogonal: below threshold
        self.assertEqual(stats.action, "reconciled")


_KUZU = __import__("importlib").util.find_spec("kuzu") is not None


@unittest.skipUnless(_KUZU, "kuzu not installed; live graph pass skipped (covered in CI)")
class TestSimilarRunnerLiveKuzu(unittest.TestCase):
    """The KuzuEdgeStore against a real Kùzu database (CI)."""

    def _stores(self):
        from session_analytics.graph import builder
        from session_analytics.relational.db import Database, apply_ddl

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-similar-kuzu-"))
        db = Database.connect(f"sqlite:///{tmp / 'sa.db'}")
        apply_ddl(db)
        self.addCleanup(db.close)
        for native_id, vec in (("a", (1.0, 0.0, 0.0)), ("b", (0.9, 0.1, 0.0))):
            db.insert_returning_id(
                "INSERT INTO copilot_session (copilot, session_id, turn_count, "
                "session_embedding) VALUES (?, ?, ?, ?) RETURNING id",
                ("claude-code", native_id, 0, json.dumps(_env(vector=vec))),
            )
        db.commit()
        graph_path = str(tmp / "g")
        builder.build(db, graph_path)  # creates the Session nodes
        return db, graph_path

    @staticmethod
    def _all_edges(gdb):
        """Complete (source, target, score) rows — the comparison the
        review demanded, not merely the source set."""
        res = gdb.execute(
            "MATCH (a:Session)-[r:SIMILAR_TO]->(b:Session) "
            "RETURN a.session_key, b.session_key, r.score")
        rows = set()
        while res.has_next():
            src, dst, score = res.get_next()
            rows.add((src, dst, round(float(score), 9)))
        return rows

    def test_live_pass_writes_and_survives_injected_failure(self) -> None:
        from session_analytics.config import SimilarityConfig
        from session_analytics.embedding.similar_runner import (
            KuzuEdgeStore, run_similar)
        from session_analytics.graph.schema import GraphDatabase

        db, graph_path = self._stores()
        cfg = SimilarityConfig(threshold=0.2, top_k=3)

        gdb = GraphDatabase.connect(graph_path)
        try:
            store = KuzuEdgeStore(gdb)
            stats = run_similar(db, cfg, store)
            self.assertEqual(stats.written_edges, 2)
            previous = self._all_edges(gdb)
            self.assertEqual(len(previous), 2)

            # 1. failure raised by OUR code mid-write: rollback runs.
            real_write = store.write_edge

            def poisoned(src, dst, score):
                raise RuntimeError("injected live failure")

            store.write_edge = poisoned  # type: ignore[method-assign]
            with self.assertRaises(RuntimeError) as ctx:
                run_similar(db, cfg, store)
            self.assertIn("injected live failure", str(ctx.exception))
            store.write_edge = real_write  # type: ignore[method-assign]
            self.assertEqual(self._all_edges(gdb), previous)

            # 2. COMMIT failure: commit is in the protected phase, so
            #    the pending replacement is rolled back, not left open
            #    on the connection.
            real_commit = store.commit

            def commit_fails():
                raise RuntimeError("injected commit failure")

            store.commit = commit_fails  # type: ignore[method-assign]
            with self.assertRaises(RuntimeError) as ctx:
                run_similar(db, cfg, store)
            self.assertIn("injected commit failure", str(ctx.exception))
            store.commit = real_commit  # type: ignore[method-assign]
            self.assertEqual(self._all_edges(gdb), previous)

            # 3. a STATEMENT failure kuzu auto-aborts: our rollback
            #    then raises "No active transaction" — which must be
            #    suppressed so the ORIGINAL Binder error propagates.
            def statement_failure(src, dst, score):
                gdb.execute("MATCH (x:NoSuchTable) RETURN x")

            store.write_edge = statement_failure  # type: ignore[method-assign]
            with self.assertRaises(RuntimeError) as ctx:
                run_similar(db, cfg, store)
            self.assertIn("NoSuchTable", str(ctx.exception))
            self.assertNotIn("No active transaction", str(ctx.exception))
            store.write_edge = real_write  # type: ignore[method-assign]
            self.assertEqual(self._all_edges(gdb), previous)
        finally:
            gdb.close()

    def test_live_cli_unready_graph_and_happy_path(self) -> None:
        # Real CLI, real kuzu, NO mocks on the graph path — the
        # regressions the review asked for.
        from session_analytics import cli as climod
        from session_analytics import config as cfg_mod
        import kuzu as _kuzu

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-simcli-live-"))
        dsn = f"sqlite:///{tmp / 'sa.db'}"
        from session_analytics.relational.db import Database, apply_ddl

        rdb = Database.connect(dsn)
        apply_ddl(rdb)
        for native_id, vec in (("a", (1.0, 0.0, 0.0)), ("b", (0.9, 0.1, 0.0))):
            rdb.insert_returning_id(
                "INSERT INTO copilot_session (copilot, session_id, "
                "turn_count, session_embedding) VALUES (?, ?, ?, ?) "
                "RETURNING id",
                ("claude-code", native_id, 0, json.dumps(_env(vector=vec))))
        rdb.commit()
        rdb.close()

        base = {k: v for k, v in os.environ.items()
                if not k.startswith("CCT_SA_")}
        env_patch = [
            mock.patch.object(cfg_mod, "_USER_CONFIG",
                              tmp / "session-analytics.json"),
            mock.patch.object(cfg_mod, "parse_env_file", lambda *a, **k: {}),
            mock.patch.dict("os.environ", base, clear=True),
        ]

        # uninitialized graph: a bare kuzu db with no schema
        bare = tmp / "bare-graph"
        _kuzu.Database(str(bare))  # creates, no Session table
        with env_patch[0], env_patch[1], env_patch[2]:
            rc = climod.main(
                ["similar", "--dsn", dsn, "--db-path", str(bare)])
        self.assertEqual(rc, 2)  # prerequisite guidance, not exit 3

        # happy path: graph built, then similar succeeds end to end
        from session_analytics.graph import builder

        rdb = Database.connect(dsn)
        graph2 = str(tmp / "real-graph")
        builder.build(rdb, graph2)
        rdb.close()
        with env_patch[0], env_patch[1], env_patch[2]:
            rc = climod.main(
                ["similar", "--dsn", dsn, "--db-path", graph2])
        self.assertEqual(rc, 0)
        from session_analytics.graph.schema import GraphDatabase

        gdb = GraphDatabase.connect(graph2)
        try:
            self.assertEqual(len(self._all_edges(gdb)), 2)
        finally:
            gdb.close()


class TestSimilarCli(unittest.TestCase):
    """T2 — the CLI seam: flags → extra_overrides → runner; exits."""

    def _main(self, argv, run_stub=None):
        from session_analytics import cli as climod
        import session_analytics.embedding.similar_runner as runner_mod
        from session_analytics.embedding.similar_runner import SimilarStats

        captured = {}

        def fake_run_similar(db, similarity_cfg, store):
            captured["cfg"] = similarity_cfg
            return (run_stub or SimilarStats)()

        class _FakeGdb:
            def close(self):
                pass

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-simcli-"))
        dsn = f"sqlite:///{tmp / 'sa.db'}"
        graph_dir = tmp / "graph"
        graph_dir.mkdir()  # the absent-path guard is tested separately
        base = {k: v for k, v in os.environ.items()
                if not k.startswith("CCT_SA_")}
        from session_analytics.graph import schema as schema_mod
        with mock.patch.object(runner_mod, "run_similar", fake_run_similar), \
             mock.patch.object(schema_mod.GraphDatabase, "connect",
                               staticmethod(lambda path: _FakeGdb())), \
             mock.patch.object(cfgmod, "_USER_CONFIG",
                               tmp / "session-analytics.json"), \
             mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", base, clear=True):
            rc = climod.main(
                ["similar", "--dsn", dsn, "--db-path", str(graph_dir), *argv])
        return rc, captured

    def test_cli_flags_reach_the_resolved_config(self) -> None:
        rc, cap = self._main(["--threshold", "0.8", "--top-k", "2"])
        self.assertEqual(rc, 0)
        self.assertEqual(cap["cfg"].threshold, 0.8)
        self.assertEqual(cap["cfg"].top_k, 2)

    def test_refused_knob_is_usage_error_not_traceback(self) -> None:
        rc, _ = self._main(["--threshold", "nan"])
        self.assertEqual(rc, 2)  # EXIT_USAGE, message names the setting

    def test_absent_graph_path_is_usage_error_with_zero_creation(self) -> None:
        # Reviewed defect: a fresh --db-path used to be CREATED by
        # GraphDatabase.connect and then die on the missing Session
        # table with exit 3. The guard now fires BEFORE connect. No
        # mocks on the graph here — the real code path runs.
        from session_analytics import cli as climod

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-simcli-abs-"))
        dsn = f"sqlite:///{tmp / 'sa.db'}"
        missing = tmp / "never-created-graph"
        base = {k: v for k, v in os.environ.items()
                if not k.startswith("CCT_SA_")}
        with mock.patch.object(cfgmod, "_USER_CONFIG",
                               tmp / "session-analytics.json"), \
             mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", base, clear=True):
            rc = climod.main(
                ["similar", "--dsn", dsn, "--db-path", str(missing)])
        self.assertEqual(rc, 2)
        self.assertFalse(missing.exists())  # ZERO filesystem creation

    def test_invalid_envelopes_exit_nonzero(self) -> None:
        from session_analytics.embedding.similar_runner import SimilarStats

        rc, _ = self._main(
            [], run_stub=lambda: SimilarStats(excluded_invalid={7: "bad"}))
        self.assertEqual(rc, 3)  # failed-class condition


class TestSimilarSessionsTool(unittest.TestCase):
    """T3 — the MCP tool's prerequisite ladder, kuzu-free: every branch
    here is independently established from the relational store or the
    filesystem, BEFORE any graph connect."""

    def setUp(self) -> None:
        from session_analytics.relational.db import Database, apply_ddl

        self.tmp = Path(tempfile.mkdtemp(prefix="cct-sa-mcp-sim-"))
        self.db = Database.connect(f"sqlite:///{self.tmp / 'sa.db'}")
        apply_ddl(self.db)
        self.addCleanup(self.db.close)

    def _session(self, native_id, envelope):
        stored = (json.dumps(envelope) if isinstance(envelope, dict)
                  else envelope)
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count, "
            "session_embedding) VALUES (?, ?, ?, ?) RETURNING id",
            ("claude-code", native_id, 0, stored))
        self.db.commit()
        return sid

    def _tool(self, session_id, kuzu_path=""):
        from session_analytics.mcp.tools import similar_sessions

        return similar_sessions(self.db, kuzu_path, session_id)

    def test_unknown_session_is_an_error(self) -> None:
        out = self._tool(999999)
        self.assertIn("not found", out["error"])

    def test_missing_envelope_gets_embedding_guidance(self) -> None:
        sid = self._session("a", None)
        out = self._tool(sid)
        self.assertEqual(out["prerequisite"], "embedding")
        self.assertIn("embed", out["guidance"])

    def test_invalid_envelope_gets_targeted_overwrite_guidance(self) -> None:
        # T3 review: an ordinary embed pass SKIPS existing envelopes,
        # so "run embed" cannot repair an invalid non-null one. The
        # guidance must name the explicit targeted overwrite.
        sid = self._session("a", "not json")
        out = self._tool(sid)
        self.assertEqual(out["prerequisite"], "embedding")
        self.assertIn("INVALID", out["error"])
        self.assertIn("--overwrite", out["guidance"])
        self.assertIn(f"--session-id {sid}", out["guidance"])

    def test_missing_envelope_guidance_is_plain_embed(self) -> None:
        sid = self._session("a", None)
        out = self._tool(sid)
        self.assertNotIn("--overwrite", out["guidance"])

    def test_advised_recovery_actually_replaces_the_invalid_value(self) -> None:
        # Follow the guidance end to end: overwrite + session-id
        # through run_embed replaces the invalid envelope with a valid
        # one — proving the advice repairs what it claims to.
        from session_analytics.config import EmbeddingConfig
        from session_analytics.embedding.contracts import (
            EmbeddingResult, validate_envelope)
        from session_analytics.embedding.registry import (
            _reset_for_tests, register_embedding)
        from session_analytics.embedding.runner import run_embed

        sid = self._session("bad-recovery", "not json")
        self.db.execute(
            "INSERT INTO copilot_turn (session_id, sequence_num, role, "
            "content_preview, content_length) VALUES (?, ?, ?, ?, ?)",
            (sid, 0, "user", "some preview text", 17))
        self.db.commit()

        class _Backend:
            def probe(self):
                pass

            def embed(self, text):
                return EmbeddingResult(
                    vector=(0.1, 0.2, 0.3), resolved_model="fixed-model")

        _reset_for_tests()
        self.addCleanup(_reset_for_tests)
        register_embedding("fixed", lambda model, *, base_url="": _Backend())
        stats = run_embed(
            self.db,
            EmbeddingConfig(backend="fixed", model="m", ollama_url="",
                            input_cap_chars=8000, workers=1),
            overwrite=True, session_id=sid)
        self.assertEqual(stats.embedded, 1)
        stored = self.db.query_one(
            "SELECT session_embedding FROM copilot_session WHERE id = ?",
            (sid,))[0]
        self.assertIsNone(validate_envelope(json.loads(stored)))

    def test_ordinary_embed_does_not_repair_invalid_envelopes(self) -> None:
        # The premise of the guidance, pinned: WITHOUT overwrite the
        # invalid value is skipped_existing and unchanged.
        from session_analytics.config import EmbeddingConfig
        from session_analytics.embedding.registry import _reset_for_tests
        from session_analytics.embedding.runner import run_embed

        sid = self._session("bad-stays", "not json")
        _reset_for_tests()
        self.addCleanup(_reset_for_tests)
        stats = run_embed(
            self.db,
            EmbeddingConfig(backend="none-needed", model="m", ollama_url="",
                            input_cap_chars=8000, workers=1),
            session_id=sid)
        self.assertEqual(stats.skipped_existing, 1)
        stored = self.db.query_one(
            "SELECT session_embedding FROM copilot_session WHERE id = ?",
            (sid,))[0]
        self.assertEqual(stored, "not json")

    def test_absent_graph_gets_graph_guidance_with_zero_creation(self) -> None:
        sid = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        missing = self.tmp / "never-created"
        out = self._tool(sid, kuzu_path=str(missing))
        self.assertEqual(out["prerequisite"], "graph")
        self.assertFalse(missing.exists())  # NON-CREATING read path

    def test_unset_kuzu_path_is_graph_prerequisite_not_a_crash(self) -> None:
        sid = self._session("a", _env(vector=(1.0, 0.0, 0.0)))
        out = self._tool(sid, kuzu_path="")
        self.assertEqual(out["prerequisite"], "graph")

    def test_compare_approaches_output_is_untouched(self) -> None:
        # FR-F: the keyword tool's shape is unchanged — match_score,
        # no basis field. Byte-level pin on its fixture output.
        from session_analytics.mcp.tools import compare_approaches

        self.db.execute(
            "UPDATE copilot_session SET project_path = ? WHERE 1=1",
            ("/home/x/login-bug-fix",))
        self.db.commit()
        self._session("kw", None)
        self.db.execute(
            "UPDATE copilot_session SET project_path = ?",
            ("/home/x/login-bug-fix",))
        self.db.commit()
        out = compare_approaches(self.db, "login bug fix")
        self.assertTrue(out)
        for row in out:
            self.assertIn("match_score", row)
            self.assertNotIn("basis", row)


@unittest.skipUnless(_KUZU, "kuzu not installed; live MCP-tool graph paths skipped (covered where kuzu is present)")
class TestSimilarSessionsToolLiveKuzu(unittest.TestCase):
    """T3 — the tool's graph-backed branches against real Kùzu."""

    def _world(self, *, build_graph=True, run_pass=True):
        from session_analytics.config import SimilarityConfig
        from session_analytics.embedding.similar_runner import (
            KuzuEdgeStore, run_similar)
        from session_analytics.graph import builder
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.relational.db import Database, apply_ddl

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-mcp-simlive-"))
        db = Database.connect(f"sqlite:///{tmp / 'sa.db'}")
        apply_ddl(db)
        self.addCleanup(db.close)
        sids = {}
        for native_id, vec in (("a", (1.0, 0.0, 0.0)),
                               ("b", (0.9, 0.1, 0.0)),
                               ("lone", (0.0, 0.0, 1.0))):
            sids[native_id] = db.insert_returning_id(
                "INSERT INTO copilot_session (copilot, session_id, "
                "turn_count, session_embedding) VALUES (?, ?, ?, ?) "
                "RETURNING id",
                ("claude-code", native_id, 0,
                 json.dumps(_env(vector=vec))))
        db.commit()
        graph_path = str(tmp / "g")
        if build_graph:
            builder.build(db, graph_path)
            if run_pass:
                gdb = GraphDatabase.connect(graph_path)
                try:
                    run_similar(db, SimilarityConfig(threshold=0.5, top_k=3),
                                KuzuEdgeStore(gdb))
                finally:
                    gdb.close()
        return db, graph_path, sids, tmp

    def test_neighbors_carry_score_basis_and_snapshot_note(self) -> None:
        from session_analytics.mcp.tools import similar_sessions

        db, graph_path, sids, _ = self._world()
        out = similar_sessions(db, graph_path, sids["a"])
        self.assertEqual(out["basis"], "embedding")
        self.assertIn("snapshot", out["scores_are"])
        self.assertEqual(len(out["neighbors"]), 1)
        n = out["neighbors"][0]
        self.assertEqual(n["session_key"], "claude-code:b")
        self.assertEqual(n["basis"], "embedding")
        self.assertGreater(n["score"], 0.5)
        self.assertEqual(n["id"], sids["b"])

    def test_healthy_empty_for_a_below_threshold_session(self) -> None:
        # "lone" is orthogonal to everything: no edges is the HEALTHY
        # outcome, with no error and no remedial instruction.
        from session_analytics.mcp.tools import similar_sessions

        db, graph_path, sids, _ = self._world()
        out = similar_sessions(db, graph_path, sids["lone"])
        self.assertEqual(out["neighbors"], [])
        self.assertNotIn("error", out)
        self.assertNotIn("guidance", out)

    def test_uninitialized_graph_gets_graph_guidance(self) -> None:
        import kuzu as _kuzu

        from session_analytics.mcp.tools import similar_sessions

        db, _, sids, tmp = self._world(build_graph=False)
        bare = tmp / "bare"
        _kuzu.Database(str(bare))  # exists, no schema
        out = similar_sessions(db, str(bare), sids["a"])
        self.assertEqual(out["prerequisite"], "graph")

    def test_neighbor_kpis_included_with_rubric_and_honest_absence(self) -> None:
        # Spec scenario 1 promises score AND KPIs. Existing KPI rows
        # ride along with their rubric identity; a neighbor without
        # one carries kpi: null — nothing is computed here.
        from session_analytics.mcp.tools import similar_sessions

        db, graph_path, sids, _ = self._world()
        db.execute(
            "INSERT INTO session_kpi (session_id, rubric_name, "
            "labeled_turn_count, correction_rate, rework_rate, "
            "avg_interaction_quality) VALUES (?, ?, ?, ?, ?, ?)",
            (sids["b"], "cct-heuristic-v1", 4, 0.25, 0.0, 4.5))
        db.commit()
        out = similar_sessions(db, graph_path, sids["a"])
        kpi = out["neighbors"][0]["kpi"]
        self.assertEqual(kpi["rubric_name"], "cct-heuristic-v1")
        self.assertEqual(kpi["correction_rate"], 0.25)
        # and honest absence from the other direction:
        out_b = similar_sessions(db, graph_path, sids["b"])
        self.assertIsNone(out_b["neighbors"][0]["kpi"])

    def test_disappearing_path_is_refused_not_recreated(self) -> None:
        # T3 review's TOCTOU: the path passes the exists() precheck but
        # is gone at open time. The read-only open must REFUSE without
        # creating anything — the precheck alone was the earlier test's
        # only protection.
        from session_analytics.mcp import tools as tools_mod
        from session_analytics.mcp.tools import similar_sessions

        db, _, sids, tmp = self._world(build_graph=False)
        ghost = tmp / "ghost-graph"

        class _AlwaysThere:
            def __init__(self, *a):
                pass

            def exists(self):
                return True

        with mock.patch.object(tools_mod, "Path", _AlwaysThere):
            out = similar_sessions(db, str(ghost), sids["a"])
        self.assertEqual(out["prerequisite"], "graph")
        self.assertFalse(ghost.exists())  # nothing was created

    def test_missing_graph_node_gets_graph_sync_guidance(self) -> None:
        from session_analytics.mcp.tools import similar_sessions
        from session_analytics.relational.db import Database

        db, graph_path, sids, tmp = self._world()
        # a session added AFTER the graph build has no node yet
        late = db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count, "
            "session_embedding) VALUES (?, ?, ?, ?) RETURNING id",
            ("claude-code", "late", 0,
             json.dumps(_env(vector=(0.5, 0.5, 0.0)))))
        db.commit()
        out = similar_sessions(db, graph_path, late)
        self.assertEqual(out["prerequisite"], "graph")
        self.assertIn("graph node", out["error"])


_MCP_SDK = __import__("importlib").util.find_spec("mcp") is not None


@unittest.skipUnless(_KUZU and _MCP_SDK,
                     "kuzu+mcp not installed; registered-tool test skipped (runs where both are present)")
class TestRegisteredMcpTool(unittest.TestCase):
    """T3 — the REAL server factory, with a NONDEFAULT kuzu_path: the
    config plumbing itself is the test target, not a shortcut around
    it."""

    def test_registered_tool_reads_the_configured_graph(self) -> None:
        import anyio

        from session_analytics.config import SimilarityConfig
        from session_analytics.embedding.similar_runner import (
            KuzuEdgeStore, run_similar)
        from session_analytics.graph import builder
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.mcp.server import build_server
        from session_analytics.relational.db import Database, apply_ddl

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-mcp-reg-"))
        dsn = f"sqlite:///{tmp / 'sa.db'}"
        db = Database.connect(dsn)
        apply_ddl(db)
        sid_a = db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count, "
            "session_embedding) VALUES (?, ?, ?, ?) RETURNING id",
            ("claude-code", "a", 0, json.dumps(_env(vector=(1.0, 0.0, 0.0)))))
        db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count, "
            "session_embedding) VALUES (?, ?, ?, ?) RETURNING id",
            ("claude-code", "b", 0, json.dumps(_env(vector=(0.9, 0.1, 0.0)))))
        db.commit()
        nondefault_graph = str(tmp / "nondefault" / "graph-here")
        builder.build(db, nondefault_graph)
        gdb = GraphDatabase.connect(nondefault_graph)
        try:
            run_similar(db, SimilarityConfig(threshold=0.5, top_k=3),
                        KuzuEdgeStore(gdb))
        finally:
            gdb.close()
        db.close()

        server = build_server(dsn, nondefault_graph)

        async def _call():
            return await server.call_tool(
                "similar_sessions", {"session_id": sid_a})

        result = anyio.run(_call)
        # FastMCP returns content blocks; find our payload
        text = "".join(
            getattr(block, "text", "") for block in
            (result if isinstance(result, list) else result[0]))
        self.assertIn('"basis": "embedding"', text)
        self.assertIn("claude-code:b", text)
