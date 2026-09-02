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

    def __init__(self, nodes=(), edges=None):
        self.nodes = set(nodes)
        self.edges: dict[tuple[str, str], float] = dict(edges or {})
        self._tx: dict[tuple[str, str], float] | None = None
        self.begin_calls = 0
        self.fail_on_write: int | None = None  # fail the Nth write_edge
        self._writes = 0

    def _view(self):
        return self._tx if self._tx is not None else self.edges

    def begin(self):
        self.begin_calls += 1
        self._tx = dict(self.edges)

    def commit(self):
        assert self._tx is not None, "commit outside a transaction"
        self.edges = self._tx
        self._tx = None

    def rollback(self):
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
            previous = store.existing_edge_sources()
            self.assertEqual(len(previous), 2)

            # inject a failure on the first edge write of the next pass
            real_write = store.write_edge

            def poisoned(src, dst, score):
                raise RuntimeError("injected live failure")

            store.write_edge = poisoned  # type: ignore[method-assign]
            with self.assertRaises(RuntimeError):
                run_similar(db, cfg, store)
            store.write_edge = real_write  # type: ignore[method-assign]
            # previous edge set intact after rollback
            self.assertEqual(store.existing_edge_sources(), previous)
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
            rc = climod.main(["similar", "--dsn", dsn, *argv])
        return rc, captured

    def test_cli_flags_reach_the_resolved_config(self) -> None:
        rc, cap = self._main(["--threshold", "0.8", "--top-k", "2"])
        self.assertEqual(rc, 0)
        self.assertEqual(cap["cfg"].threshold, 0.8)
        self.assertEqual(cap["cfg"].top_k, 2)

    def test_refused_knob_is_usage_error_not_traceback(self) -> None:
        rc, _ = self._main(["--threshold", "nan"])
        self.assertEqual(rc, 2)  # EXIT_USAGE, message names the setting

    def test_invalid_envelopes_exit_nonzero(self) -> None:
        from session_analytics.embedding.similar_runner import SimilarStats

        rc, _ = self._main(
            [], run_stub=lambda: SimilarStats(excluded_invalid={7: "bad"}))
        self.assertEqual(rc, 3)  # failed-class condition
