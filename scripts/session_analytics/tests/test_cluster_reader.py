# Tests for #289 T2 — snapshot reader + CLI (FR-A, FR-D, FR-E).
# The fake-snapshot classes are kuzu-free and run everywhere; the live
# Kùzu class below drives the REAL #287 producer (CI installs kuzu).

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from session_analytics import constants as C
from session_analytics.embedding.cluster_reader import (
    KEY_CLUSTERS,
    KEY_INVENTORY_BASIS,
    KEY_MEMBERSHIP_BASIS,
    KEY_UNCLUSTERED,
    ClusterReport,
    run_clusters,
)
from session_analytics.embedding.similar_runner import GraphNotReadyError


class _FakeSnapshot:
    """A GraphSnapshot with NO write method — the read-only seam.

    Mirrors #287's `_FakeEdgeStore` in spirit, restricted to the three
    read operations the reader is allowed to perform.
    """

    def __init__(self, nodes=(), edges=(), ready=True):
        self.nodes = set(nodes)
        self.rows = [(s, d, float(sc)) for s, d, sc in edges]
        self._ready = ready

    def graph_ready(self):
        return self._ready

    def session_keys(self):
        return set(self.nodes)

    def edges(self):
        return list(self.rows)


class TestTwoProvenancesMoveIndependently(unittest.TestCase):
    """FR-A: membership from stored edges, unclustered from inventory.

    THE provenance discriminator. Growing the node inventory while the
    edge set stays byte-identical must leave every cluster unchanged
    and move only the unclustered count.
    """

    EDGES = (("a", "b", 0.9), ("b", "a", 0.9))

    def test_growing_inventory_moves_only_the_unclustered_count(self) -> None:
        before = run_clusters(_FakeSnapshot(nodes={"a", "b"}, edges=self.EDGES))
        after = run_clusters(
            _FakeSnapshot(nodes={"a", "b", "c"}, edges=self.EDGES))

        # membership is byte-identical: the edges did not change
        self.assertEqual(
            [c.as_dict() for c in before.clusters],
            [c.as_dict() for c in after.clusters])
        # only the second provenance moved
        self.assertEqual((before.unclustered_sessions, before.graph_sessions),
                         (0, 2))
        self.assertEqual((after.unclustered_sessions, after.graph_sessions),
                         (1, 3))

    def test_report_labels_the_two_bases_distinctly(self) -> None:
        row = run_clusters(
            _FakeSnapshot(nodes={"a", "b"}, edges=self.EDGES)).as_dict()
        self.assertNotEqual(row[KEY_MEMBERSHIP_BASIS], row[KEY_INVENTORY_BASIS])
        self.assertIn("currently stored", row[KEY_MEMBERSHIP_BASIS])
        self.assertIn("current Session node inventory", row[KEY_INVENTORY_BASIS])

    def test_counts_partition_the_inventory_for_producible_edges(self) -> None:
        # holds for every edge set #287 can write; see the self-loop
        # discriminator below for the one shape where it does not.
        report = run_clusters(
            _FakeSnapshot(nodes={"a", "b", "c", "d"}, edges=self.EDGES))
        self.assertEqual(
            report.clustered_sessions + report.unclustered_sessions,
            report.graph_sessions)


class TestUnclusteredIsDefinedByIncidence(unittest.TestCase):
    """FR-B: unclustered means NO INCIDENT STORED EDGE.

    The discriminator between the normative rule and the tempting
    shortcut `inventory - members_of_reported_clusters`. They agree on
    every edge set the producer can write and disagree on exactly one
    shape, so the shortcut has to be ruled out explicitly.
    """

    def test_self_loop_node_is_neither_clustered_nor_unclustered(self) -> None:
        report = run_clusters(
            _FakeSnapshot(nodes={"a", "b"}, edges=(("a", "a", 0.9),)))
        # 'a' has an incident stored edge, so it is NOT unclustered,
        # while T1 suppresses its size-one component, so it is not in a
        # cluster either. Only 'b' is unclustered.
        self.assertEqual(report.clusters, ())
        self.assertEqual(report.unclustered_sessions, 1)
        self.assertEqual(report.graph_sessions, 2)

    def test_membership_shortcut_would_have_said_two(self) -> None:
        # pins the DIFFERENCE, not just the number: the rejected rule
        # (inventory minus cluster members) would count 'a' as well.
        snapshot = _FakeSnapshot(nodes={"a", "b"}, edges=(("a", "a", 0.9),))
        report = run_clusters(snapshot)
        by_membership = len(
            snapshot.session_keys()
            - {m for c in report.clusters for m in c.members})
        self.assertEqual(by_membership, 2)
        self.assertNotEqual(report.unclustered_sessions, by_membership)

    def test_destination_only_node_is_not_unclustered(self) -> None:
        """Incidence covers BOTH endpoints.

        #287's top-K is asymmetric, so a one-way edge is routine: 'b'
        may never appear as a source. Counting incidence from sources
        alone would report a clustered session as unclustered.
        """
        report = run_clusters(
            _FakeSnapshot(nodes={"a", "b"}, edges=(("a", "b", 0.9),)))
        self.assertEqual(report.clusters[0].members, ("a", "b"))
        self.assertEqual(report.unclustered_sessions, 0)

    def test_one_way_chain_leaves_only_the_isolated_session(self) -> None:
        report = run_clusters(_FakeSnapshot(
            nodes={"a", "b", "c", "solo"},
            edges=(("a", "b", 0.9), ("b", "c", 0.8))))
        self.assertEqual(report.clusters[0].members, ("a", "b", "c"))
        self.assertEqual(report.unclustered_sessions, 1)

    def test_edge_endpoint_outside_the_inventory_never_goes_negative(self) -> None:
        report = run_clusters(
            _FakeSnapshot(nodes={"a"}, edges=(("a", "ghost", 0.9),)))
        self.assertEqual(report.unclustered_sessions, 0)
        self.assertEqual(report.graph_sessions, 1)

    def test_is_unclustered_requires_graph_membership(self) -> None:
        """A key the snapshot never held is NOT unclustered.

        "Unclustered" is a statement about a graph session. Answering
        it for a key outside the inventory would classify something the
        snapshot does not describe — and the MCP surface relies on this
        to keep the missing-graph-node prerequisite distinct.
        """
        report = run_clusters(
            _FakeSnapshot(nodes={"a", "b", "c"}, edges=(("a", "b", 0.9),)))
        self.assertFalse(report.is_unclustered("ghost"))
        self.assertFalse(report.has_session("ghost"))
        self.assertTrue(report.is_unclustered("c"))   # in graph, no edge
        self.assertFalse(report.is_unclustered("a"))  # in graph, clustered

    def test_inventory_is_read_once_per_run(self) -> None:
        """One snapshot for every classification.

        Re-reading the inventory to answer a follow-up question can
        straddle two different reads and produce an internally
        inconsistent answer, so the report retains what it read.
        """
        class _Counting(_FakeSnapshot):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.keys_calls = 0

            def session_keys(self):
                self.keys_calls += 1
                return super().session_keys()

        snapshot = _Counting(nodes={"a", "b"}, edges=(("a", "b", 0.9),))
        report = run_clusters(snapshot)
        self.assertEqual(snapshot.keys_calls, 1)
        # and every classification is answerable WITHOUT another read
        report.has_session("a")
        report.is_unclustered("b")
        self.assertEqual(snapshot.keys_calls, 1)

    def test_edges_are_read_once_per_run(self) -> None:
        # both the grouping and the incidence set must describe the
        # same rows, so the store is round-tripped exactly once.
        class _Counting(_FakeSnapshot):
            calls = 0

            def edges(self):
                type(self).calls += 1
                return super().edges()

        run_clusters(_Counting(nodes={"a", "b"}, edges=(("a", "b", 0.9),)))
        self.assertEqual(_Counting.calls, 1)


class TestReportClaimsNothingItCannotAttest(unittest.TestCase):
    """FR-A: production-time compatibility, never current-envelope."""

    def _row(self):
        return run_clusters(_FakeSnapshot(
            nodes={"a", "b"}, edges=(("a", "b", 0.9),))).as_dict()

    def test_no_space_triple_anywhere_in_the_report(self) -> None:
        blob = json.dumps(self._row())
        for forbidden in ("provider", "model", "dim", "envelope_"):
            self.assertNotIn(forbidden, blob)

    def test_no_claim_that_members_currently_share_an_envelope(self) -> None:
        row = self._row()
        limitations = " ".join(row["limitations"])
        self.assertIn("does not assert that members currently share", limitations)
        self.assertIn("production time", limitations)

    def test_transitive_limitation_is_stated_not_implied(self) -> None:
        limitations = " ".join(self._row()["limitations"])
        self.assertIn("transitive discovery grouping", limitations)
        self.assertIn("does not assert that every pair", limitations)

    def test_no_per_space_grouping_key(self) -> None:
        self.assertNotIn("spaces", self._row())


class TestPrerequisiteLadderAndHealthyEmpty(unittest.TestCase):
    """FR-E: absence of clusters is a RESULT; absence of a graph is not."""

    def test_unbuilt_graph_raises_the_shared_prerequisite_error(self) -> None:
        with self.assertRaises(GraphNotReadyError) as ctx:
            run_clusters(_FakeSnapshot(ready=False))
        self.assertIn("Session table", str(ctx.exception))

    def test_ready_graph_with_zero_edges_is_a_healthy_empty_report(self) -> None:
        report = run_clusters(_FakeSnapshot(nodes={"a", "b"}, edges=()))
        self.assertEqual(report.clusters, ())
        self.assertEqual(report.unclustered_sessions, 2)

    def test_totally_empty_graph_is_also_healthy(self) -> None:
        report = run_clusters(_FakeSnapshot())
        self.assertEqual(
            (report.clusters, report.unclustered_sessions, report.graph_sessions),
            ((), 0, 0))


class TestDeterministicReportBytes(unittest.TestCase):
    """FR-C, over BOTH inputs."""

    def test_same_pair_yields_identical_bytes(self) -> None:
        edges = [("b", "c", 0.8), ("a", "b", 0.9), ("x", "y", 0.7)]
        nodes = {"a", "b", "c", "x", "y", "z"}
        first = json.dumps(
            run_clusters(_FakeSnapshot(nodes, edges)).as_dict(), indent=2)
        for _ in range(10):
            again = json.dumps(
                run_clusters(_FakeSnapshot(set(nodes), list(edges))).as_dict(),
                indent=2)
            self.assertEqual(again, first)

    def test_edge_order_does_not_change_the_bytes(self) -> None:
        nodes = {"a", "b", "c"}
        forward = run_clusters(_FakeSnapshot(
            nodes, [("a", "b", 0.9), ("b", "c", 0.8)])).as_dict()
        reversed_ = run_clusters(_FakeSnapshot(
            nodes, [("b", "c", 0.8), ("a", "b", 0.9)])).as_dict()
        self.assertEqual(json.dumps(forward), json.dumps(reversed_))

    def test_report_key_set_is_a_fixed_contract(self) -> None:
        """The report's shape is a published contract.

        Internal state carried on `ClusterReport` for callers (the
        incidence set, say) must not leak into the serialized bytes,
        and a new key may not appear without this test changing.
        """
        row = run_clusters(_FakeSnapshot(
            {"a", "b"}, [("a", "b", 0.9)])).as_dict()
        self.assertEqual(set(row), {
            "clusters", "cluster_count", "clustered_sessions",
            "unclustered_sessions", "graph_sessions", "basis",
            "membership_basis", "inventory_basis", "limitations",
        })
        self.assertEqual(set(row["clusters"][0]), {
            "identity", "size", "members", "directed_edge_count",
        })

    def test_report_carries_the_directed_edge_count(self) -> None:
        row = run_clusters(_FakeSnapshot(
            {"a", "b"}, [("a", "b", 0.9), ("b", "a", 0.9)])).as_dict()
        self.assertEqual(row[KEY_CLUSTERS][0]["directed_edge_count"], 2)


class TestScoresNeverReachThePureLayer(unittest.TestCase):
    """D1: the reader projects (src, dst, score) -> (src, dst)."""

    def test_scores_do_not_change_grouping_or_counting(self) -> None:
        low = run_clusters(_FakeSnapshot(
            {"a", "b"}, [("a", "b", 0.01)])).as_dict()
        high = run_clusters(_FakeSnapshot(
            {"a", "b"}, [("a", "b", 0.99)])).as_dict()
        self.assertEqual(low, high)

    def test_no_score_appears_in_the_report(self) -> None:
        blob = json.dumps(run_clusters(_FakeSnapshot(
            {"a", "b"}, [("a", "b", 0.4242)])).as_dict())
        self.assertNotIn("0.4242", blob)
        self.assertNotIn("score", blob)


class TestReadOnlyDiscipline(unittest.TestCase):
    """D5: no write path exists in this slice."""

    def test_snapshot_protocol_exposes_no_write_method(self) -> None:
        from session_analytics.embedding import cluster_reader as mod
        for banned in ("write_edge", "begin", "commit", "rollback",
                       "delete_outgoing"):
            self.assertFalse(hasattr(mod.KuzuGraphSnapshot, banned),
                             f"{banned} must not exist on the read-only seam")

    def test_no_cypher_literal_in_the_module_mutates(self) -> None:
        """Scan the STATEMENTS, not the prose.

        Grepping the raw source would trip over comments that discuss
        writing ("cannot create or mutate"); what must be free of
        mutations is every Cypher string the module can actually
        execute.
        """
        import ast

        from session_analytics.embedding import cluster_reader as mod
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        cypher = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and ("MATCH" in node.value or "CALL" in node.value)
        ]
        self.assertTrue(cypher, "expected to find the read queries")
        for stmt in cypher:
            upper = stmt.upper()
            for banned in ("CREATE", "DELETE", "MERGE", "SET ", "DROP"):
                self.assertNotIn(banned, upper,
                                 f"{banned!r} in executable Cypher: {stmt!r}")


class TestClustersCliLadder(unittest.TestCase):
    """FR-E exit codes, and ZERO filesystem creation on the absent path."""

    def _run(self, argv):
        from session_analytics.cli import main
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_absent_path_is_usage_error_with_zero_creation(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-clusters-absent-"))
        ghost = tmp / "not-there"
        code, _out, err = self._run(["clusters", "--db-path", str(ghost)])
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("graph database absent", err)
        self.assertIn("graph", err)
        self.assertFalse(ghost.exists(), "the absent path must not be created")
        # WHICH layer refused matters. The precheck runs BEFORE any open
        # and says "absent at"; the open's own failure says "absent or
        # unopenable at". Without pinning that, deleting the precheck is
        # invisible whenever kuzu is installed — the read-only open
        # refuses too, and the assertions above still pass. The precheck
        # is the guarantee we own; the driver's behaviour is not.
        #
        # BOTH directions, deliberately. The negative alone decays
        # silently: reword the open path to "absent or cannot be opened"
        # and it passes vacuously while the escape returns under a green
        # test. The positive discriminates on its own — "absent or
        # unopenable at" does not contain "absent at" — and also catches
        # message drift in either layer.
        self.assertIn("graph database absent at", err,
                      "the pre-open check's own message must be what ran")
        self.assertNotIn("unopenable", err,
                         "the pre-open check must be what refused")

    def _with_snapshot(self, snapshot, path):
        """Drive the real CLI against a fake snapshot, kuzu-free.

        The command imports both names at call time, so patching the
        module attributes reaches the code under test without a real
        graph — which is what lets the healthy-empty EXIT CODE be
        asserted on a host with no kuzu installed.
        """
        from session_analytics.embedding import cluster_reader as cr
        from session_analytics.graph.schema import GraphDatabase

        gdb = mock.Mock()
        gdb.close = mock.Mock()
        with mock.patch.object(GraphDatabase, "connect_read_only",
                               lambda p: gdb), \
             mock.patch.object(cr, "KuzuGraphSnapshot", lambda g: snapshot):
            return self._run(["clusters", "--db-path", str(path)])

    def test_ready_graph_with_zero_edges_exits_zero(self) -> None:
        # FR-E: absence of clusters is a RESULT, never a failure.
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-clusters-empty-"))
        store = tmp / "g"
        store.mkdir()
        code, out, _err = self._with_snapshot(
            _FakeSnapshot(nodes={"a", "b"}, edges=()), store)
        self.assertEqual(code, C.EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["cluster_count"], 0)
        self.assertEqual(payload[KEY_UNCLUSTERED], 2)

    def test_populated_graph_exits_zero_and_prints_the_report(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-clusters-full-"))
        store = tmp / "g"
        store.mkdir()
        code, out, _err = self._with_snapshot(
            _FakeSnapshot(nodes={"a", "b", "c"},
                          edges=(("a", "b", 0.9), ("b", "a", 0.9))), store)
        self.assertEqual(code, C.EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["cluster_count"], 1)
        self.assertEqual(payload[KEY_CLUSTERS][0]["directed_edge_count"], 2)
        self.assertEqual(payload[KEY_UNCLUSTERED], 1)

    def test_unbuilt_graph_is_a_usage_error(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-clusters-unbuilt-"))
        store = tmp / "g"
        store.mkdir()
        code, _out, err = self._with_snapshot(_FakeSnapshot(ready=False), store)
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("Session table", err)

    def test_refused_config_is_a_usage_error_before_any_graph_open(self) -> None:
        """A refused knob is one named error line, never a traceback.

        Drives the REAL `cli.main(['clusters', ...])`. Configuration is
        refused first, so the graph is never opened — asserted, not
        assumed, because a config failure that still touched the store
        would defeat the read-only-and-non-creating discipline.
        """
        from session_analytics import cli as climod
        from session_analytics.graph.schema import GraphDatabase

        opens = []

        def _record(path):
            opens.append(path)
            raise AssertionError("the graph must not be opened")

        boom = ValueError(
            "similarity.threshold 'nan' is not finite — NaN/inf would "
            "silently empty or saturate every neighbor set")
        with mock.patch.object(climod, "load_config", side_effect=boom), \
             mock.patch.object(GraphDatabase, "connect_read_only", _record):
            code, out, err = self._run(["clusters", "--db-path", "/nope"])

        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("similarity.threshold", err)
        self.assertIn("not finite", err)
        self.assertNotIn("Traceback", err + out)
        self.assertEqual(opens, [], "config was refused; nothing may open")

    def test_unexpected_read_failure_is_reported_not_raised(self) -> None:
        """A store error becomes a runtime exit, never a traceback —
        the discipline `similar` already follows."""
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-clusters-boom-"))
        store = tmp / "g"
        store.mkdir()

        class _Exploding:
            def graph_ready(self):
                raise RuntimeError("store is corrupt")

        code, _out, err = self._with_snapshot(_Exploding(), store)
        self.assertEqual(code, C.EXIT_RUNTIME)
        self.assertIn("clusters failed", err)
        self.assertIn("store is corrupt", err)

    def test_disappearing_path_is_refused_not_repaired(self) -> None:
        """The TOCTOU contract: an open that fails after a passing
        exists() check is REFUSED with the prerequisite exit code, never
        repaired by falling back to a create-capable open.

        The real kuzu behaviour (an absent database raises under
        read_only=True without touching the filesystem) is captured by
        #287 and exercised in the live class below; what this asserts
        is OUR mapping of that failure, so it holds with or without
        kuzu installed.
        """
        from session_analytics.graph.schema import GraphDatabase

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-clusters-race-"))
        ghost = tmp / "vanished"
        ghost.mkdir()  # exists() passes...

        def _vanished(path):  # ...and the open then fails, as in the race
            raise RuntimeError("Cannot create an empty database under "
                               "READ ONLY mode")

        with mock.patch.object(GraphDatabase, "connect_read_only", _vanished):
            code, _out, err = self._run(
                ["clusters", "--db-path", str(ghost)])
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("absent or unopenable", err)
        self.assertIn("graph", err)


_KUZU = importlib.util.find_spec("kuzu") is not None


@unittest.skipUnless(_KUZU, "kuzu not installed; live cluster read skipped (covered in CI)")
class TestClusterReaderLiveKuzu(unittest.TestCase):
    """The real store, and the REAL #287 producer.

    The two-space discriminator must go through `run_similar`, not
    hand-built edge groups: that is what proves compatibility
    inheritance rather than restating graph theory.
    """

    def _world(self, sessions):
        from session_analytics.graph import builder
        from session_analytics.relational.db import Database, apply_ddl

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-clusters-kuzu-"))
        db = Database.connect(f"sqlite:///{tmp / 'sa.db'}")
        apply_ddl(db)
        self.addCleanup(db.close)
        for native_id, env in sessions:
            db.insert_returning_id(
                "INSERT INTO copilot_session (copilot, session_id, "
                "turn_count, session_embedding) VALUES (?, ?, ?, ?) "
                "RETURNING id",
                ("claude-code", native_id, 0, json.dumps(env)),
            )
        db.commit()
        graph_path = str(tmp / "g")
        builder.build(db, graph_path)
        return db, graph_path

    @staticmethod
    def _env(model="nomic-embed-text", dim=3, vector=(1.0, 0.0, 0.0)):
        return {
            "schema_version": 1, "provider": "ollama", "model": model,
            "dim": dim, "embedded_at": "2026-09-03T12:00:00+00:00",
            "vector": list(vector),
        }

    def _produce_edges(self, db, graph_path):
        """Run the REAL #287 producer over the real store."""
        from session_analytics.config import SimilarityConfig
        from session_analytics.embedding.similar_runner import (
            KuzuEdgeStore, run_similar)
        from session_analytics.graph.schema import GraphDatabase

        gdb = GraphDatabase.connect(graph_path)
        try:
            return run_similar(db, SimilarityConfig(threshold=0.2, top_k=3),
                               KuzuEdgeStore(gdb))
        finally:
            gdb.close()

    def _read(self, graph_path):
        from session_analytics.embedding.cluster_reader import (
            KuzuGraphSnapshot, run_clusters)
        from session_analytics.graph.schema import GraphDatabase

        gdb = GraphDatabase.connect_read_only(graph_path)
        try:
            return run_clusters(KuzuGraphSnapshot(gdb))
        finally:
            gdb.close()

    def test_no_cluster_mixes_two_embedding_spaces(self) -> None:
        # two INCOMPATIBLE spaces, each internally similar. The producer
        # forms pairs only inside a space, so clusters inherit that.
        db, graph_path = self._world([
            ("a1", self._env(model="m-one", vector=(1.0, 0.0, 0.0))),
            ("a2", self._env(model="m-one", vector=(0.99, 0.01, 0.0))),
            ("b1", self._env(model="m-two", vector=(1.0, 0.0, 0.0))),
            ("b2", self._env(model="m-two", vector=(0.99, 0.01, 0.0))),
        ])
        self._produce_edges(db, graph_path)
        report = self._read(graph_path)

        space_one = {"claude-code:a1", "claude-code:a2"}
        space_two = {"claude-code:b1", "claude-code:b2"}
        self.assertEqual(len(report.clusters), 2)
        for cluster in report.clusters:
            members = set(cluster.members)
            self.assertTrue(
                members <= space_one or members <= space_two,
                f"cluster {members} spans two embedding spaces")

    def test_incremental_graph_moves_only_the_unclustered_count(self) -> None:
        # the provenance discriminator, against the REAL store
        from session_analytics.graph import builder

        db, graph_path = self._world([
            ("a", self._env(vector=(1.0, 0.0, 0.0))),
            ("b", self._env(vector=(0.99, 0.01, 0.0))),
        ])
        self._produce_edges(db, graph_path)
        before = self._read(graph_path)

        # a new session joins the graph; edges are NOT re-produced
        db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count, "
            "session_embedding) VALUES (?, ?, ?, ?) RETURNING id",
            ("claude-code", "late", 0, json.dumps(self._env())))
        db.commit()
        builder.build(db, graph_path)
        after = self._read(graph_path)

        self.assertEqual([c.as_dict() for c in before.clusters],
                         [c.as_dict() for c in after.clusters])
        self.assertEqual(after.unclustered_sessions,
                         before.unclustered_sessions + 1)
        self.assertEqual(after.graph_sessions, before.graph_sessions + 1)

    def test_read_path_never_creates_or_mutates(self) -> None:
        db, graph_path = self._world([
            ("a", self._env(vector=(1.0, 0.0, 0.0))),
            ("b", self._env(vector=(0.99, 0.01, 0.0))),
        ])
        self._produce_edges(db, graph_path)
        from session_analytics.graph.schema import GraphDatabase

        gdb = GraphDatabase.connect_read_only(graph_path)
        try:
            res = gdb.execute(
                "MATCH (a:Session)-[r:SIMILAR_TO]->(b:Session) RETURN count(r)")
            before = res.get_next()[0]
        finally:
            gdb.close()
        self._read(graph_path)
        gdb = GraphDatabase.connect_read_only(graph_path)
        try:
            res = gdb.execute(
                "MATCH (a:Session)-[r:SIMILAR_TO]->(b:Session) RETURN count(r)")
            self.assertEqual(res.get_next()[0], before)
        finally:
            gdb.close()

    def test_cli_end_to_end_exit_zero_on_ready_graph(self) -> None:
        from session_analytics.cli import main

        db, graph_path = self._world([
            ("a", self._env(vector=(1.0, 0.0, 0.0))),
            ("b", self._env(vector=(0.99, 0.01, 0.0))),
        ])
        self._produce_edges(db, graph_path)
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["clusters", "--db-path", graph_path])
        self.assertEqual(code, C.EXIT_OK)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["cluster_count"], 1)
        self.assertEqual(payload[KEY_UNCLUSTERED], 0)

    def test_unbuilt_graph_is_a_cli_usage_error(self) -> None:
        import kuzu as _kuzu

        from session_analytics.cli import main

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-clusters-bare-"))
        bare = tmp / "bare"
        _kuzu.Database(str(bare))  # exists, no Session table
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["clusters", "--db-path", str(bare)])
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("Session table", err.getvalue())


if __name__ == "__main__":
    unittest.main()
