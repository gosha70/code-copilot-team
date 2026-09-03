# Tests for #289 T3 — the MCP `session_clusters` surface (FR-F).
# The ladder tests are kuzu-free; the live class below drives a real
# store and the REAL server factory (CI installs kuzu + mcp).

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from session_analytics.mcp.tools import session_clusters

_KUZU = importlib.util.find_spec("kuzu") is not None
_MCP = importlib.util.find_spec("mcp") is not None


class _FakeDb:
    """Just enough relational store: id -> (copilot, native_id)."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def query_one(self, _sql, params):
        return self.rows.get(params[0])

    def close(self):
        pass


class TestUnknownSessionAndAbsentGraph(unittest.TestCase):
    """FR-F: the ladder, before any store is opened."""

    def test_unknown_session_is_an_error(self) -> None:
        out = session_clusters(_FakeDb(), "/some/path", session_id=42)
        self.assertIn("not found", out["error"])
        self.assertNotIn("prerequisite", out)

    def test_absent_graph_is_a_graph_prerequisite(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-mcp-clusters-"))
        ghost = tmp / "nope"
        out = session_clusters(
            _FakeDb({1: ("claude-code", "a")}), str(ghost), session_id=1)
        self.assertEqual(out["prerequisite"], "graph")
        self.assertIn("absent", out["error"])
        self.assertIn("graph", out["guidance"])
        self.assertFalse(ghost.exists(), "the read path created the store")

    def test_unset_path_is_a_graph_prerequisite(self) -> None:
        out = session_clusters(_FakeDb(), "", session_id=None)
        self.assertEqual(out["prerequisite"], "graph")
        self.assertIn("(unset)", out["error"])

    def test_disappearing_path_is_refused_not_repaired(self) -> None:
        from session_analytics.graph.schema import GraphDatabase

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-mcp-race-"))
        store = tmp / "vanished"
        store.mkdir()  # exists() passes, the open then fails

        def _vanished(path):
            raise RuntimeError("Cannot create an empty database under "
                               "READ ONLY mode")

        with mock.patch.object(GraphDatabase, "connect_read_only", _vanished):
            out = session_clusters(_FakeDb(), str(store))
        self.assertEqual(out["prerequisite"], "graph")
        self.assertIn("absent or unopenable", out["error"])


class TestLadderMatchesSimilarSessions(unittest.TestCase):
    """FR-F: no NEW outcome literal; reuse the #287 response shape."""

    def _with_snapshot(self, snapshot, rows=None):
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.mcp import tools as tools_mod

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-mcp-snap-"))
        store = tmp / "g"
        store.mkdir()
        gdb = mock.Mock()
        gdb.close = mock.Mock()
        with mock.patch.object(GraphDatabase, "connect_read_only",
                               lambda p: gdb), \
             mock.patch(
                 "session_analytics.embedding.cluster_reader."
                 "KuzuGraphSnapshot", lambda g: snapshot):
            return tools_mod.session_clusters(
                _FakeDb(rows or {}), str(store),
                session_id=self.session_id, limit=self.limit)

    session_id = None
    limit = 10

    def test_relational_session_absent_from_graph_gets_graph_guidance(self):
        """THE discriminator: a missing graph node is a PREREQUISITE,
        never the word "unclustered" — and it uses the exact shape
        `similar_sessions` already answers with."""
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        self.session_id = 7
        out = self._with_snapshot(
            _FakeSnapshot(nodes={"claude-code:other"}, edges=()),
            rows={7: ("claude-code", "ghost")})
        self.assertEqual(out["prerequisite"], "graph")
        self.assertIn("graph node", out["error"])
        self.assertIn("sync the graph", out["guidance"])
        self.assertNotIn("unclustered", json.dumps(out))
        self.assertNotIn("missing_graph_node", json.dumps(out))

    def test_graph_member_without_edges_is_unclustered_not_a_prerequisite(self):
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        self.session_id = 7
        out = self._with_snapshot(
            _FakeSnapshot(nodes={"claude-code:a"}, edges=()),
            rows={7: ("claude-code", "a")})
        self.assertEqual(out["outcome"], "unclustered")
        self.assertIsNone(out["cluster"])
        self.assertNotIn("prerequisite", out)
        self.assertNotIn("error", out)

    def test_self_loop_member_is_not_reported_unclustered(self) -> None:
        """THE incidence discriminator, and the agreement between the
        two surfaces.

        A graph member whose only stored edge is a self-loop HAS an
        incident edge, so T2's report excludes it from the unclustered
        count; T1 suppresses its size-one component, so it is not in a
        cluster. It is deliberately NEITHER, and the MCP answer must
        not flatten that into "unclustered" — which is what deriving
        the answer from cluster membership would do.
        """
        from session_analytics.embedding.cluster_reader import run_clusters
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        snapshot = _FakeSnapshot(
            nodes={"claude-code:a", "claude-code:b"},
            edges=(("claude-code:a", "claude-code:a", 0.9),))

        self.session_id = 7
        out = self._with_snapshot(snapshot, rows={7: ("claude-code", "a")})
        self.assertIsNone(out["outcome"])
        self.assertIsNone(out["cluster"])
        self.assertNotIn("prerequisite", out)

        # and the CLI report agrees: 'a' is not counted as unclustered
        report = run_clusters(snapshot)
        self.assertEqual(report.unclustered_sessions, 1)  # 'b' only
        self.assertFalse(report.is_unclustered("claude-code:a"))
        self.assertTrue(report.is_unclustered("claude-code:b"))

    def test_tool_reads_the_inventory_once(self) -> None:
        """Every classification describes ONE snapshot.

        `run_clusters` already reads the inventory; the tool must not
        read it again to decide graph presence, or the prerequisite
        answer and the cluster answer can describe different states.
        """
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.mcp import tools as tools_mod
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        class _Counting(_FakeSnapshot):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.keys_calls = 0

            def session_keys(self):
                self.keys_calls += 1
                return super().session_keys()

        snapshot = _Counting(
            nodes={"claude-code:a", "claude-code:b"},
            edges=(("claude-code:a", "claude-code:b", 0.9),))
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-mcp-once-"))
        store = tmp / "g"
        store.mkdir()
        gdb = mock.Mock()
        gdb.close = mock.Mock()
        with mock.patch.object(GraphDatabase, "connect_read_only",
                               lambda p: gdb), \
             mock.patch(
                 "session_analytics.embedding.cluster_reader."
                 "KuzuGraphSnapshot", lambda g: snapshot):
            out = tools_mod.session_clusters(
                _FakeDb({7: ("claude-code", "a")}), str(store), session_id=7)
        self.assertEqual(out["outcome"], "clustered")
        self.assertEqual(snapshot.keys_calls, 1)

    def test_edgeless_member_is_still_plainly_unclustered(self) -> None:
        # the other side of the discriminator: no incident edge at all
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        self.session_id = 7
        out = self._with_snapshot(
            _FakeSnapshot(nodes={"claude-code:a", "claude-code:b"},
                          edges=(("claude-code:b", "claude-code:b", 0.9),)),
            rows={7: ("claude-code", "a")})
        self.assertEqual(out["outcome"], "unclustered")

    def test_unbuilt_graph_is_a_graph_prerequisite(self) -> None:
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        self.session_id = None
        out = self._with_snapshot(_FakeSnapshot(ready=False))
        self.assertEqual(out["prerequisite"], "graph")
        self.assertIn("Session table", out["error"])

    def test_clustered_session_returns_its_unnamed_cluster(self) -> None:
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        self.session_id = 7
        out = self._with_snapshot(
            _FakeSnapshot(nodes={"claude-code:a", "claude-code:b"},
                          edges=(("claude-code:a", "claude-code:b", 0.9),)),
            rows={7: ("claude-code", "a")})
        self.assertEqual(out["outcome"], "clustered")
        self.assertEqual(out["cluster"]["members"],
                         ["claude-code:a", "claude-code:b"])
        self.assertEqual(out["cluster"]["directed_edge_count"], 1)


class TestListModeAndHonesty(unittest.TestCase):
    """FR-F: largest-first, bounded, basis-honest, never pairwise."""

    def _run(self, snapshot, **kw):
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.mcp import tools as tools_mod

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-mcp-list-"))
        store = tmp / "g"
        store.mkdir()
        gdb = mock.Mock()
        gdb.close = mock.Mock()
        with mock.patch.object(GraphDatabase, "connect_read_only",
                               lambda p: gdb), \
             mock.patch(
                 "session_analytics.embedding.cluster_reader."
                 "KuzuGraphSnapshot", lambda g: snapshot):
            return tools_mod.session_clusters(_FakeDb(), str(store), **kw)

    def _three(self):
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        return _FakeSnapshot(
            nodes={"a", "b", "c", "p", "q", "x", "y", "lonely"},
            edges=(("a", "b", 0.9), ("b", "c", 0.8),
                   ("p", "q", 0.7), ("x", "y", 0.6)))

    def test_list_mode_is_largest_first(self) -> None:
        out = self._run(self._three())
        sizes = [c["size"] for c in out["clusters"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(out["clusters"][0]["members"], ["a", "b", "c"])

    def test_limit_bounds_the_list_but_not_the_count(self) -> None:
        out = self._run(self._three(), limit=1)
        self.assertEqual(len(out["clusters"]), 1)
        self.assertEqual(out["cluster_count"], 3)  # honest total

    def test_zero_limit_returns_no_rows_without_error(self) -> None:
        out = self._run(self._three(), limit=0)
        self.assertEqual(out["clusters"], [])
        self.assertEqual(out["cluster_count"], 3)
        self.assertNotIn("error", out)

    def test_negative_limit_is_refused_by_name_before_any_open(self) -> None:
        """Invalid input is refused, never reinterpreted as an empty
        page — which would look like a successful answer."""
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.mcp import tools as tools_mod

        opens = []

        def _record(path):
            opens.append(path)
            raise AssertionError("the graph must not be opened")

        with mock.patch.object(GraphDatabase, "connect_read_only", _record):
            out = tools_mod.session_clusters(
                _FakeDb(), "/any/path", limit=-1)
        self.assertIn("limit", out["error"])
        self.assertIn("-1", out["error"])
        self.assertNotIn("clusters", out)
        self.assertEqual(opens, [], "input was invalid; nothing may open")

    def test_non_integer_limits_are_refused_never_coerced(self) -> None:
        """int() would ACCEPT these by silently coercing.

        `int(1.5)` is 1 and `bool` is an int subclass, so a fractional
        page size and `True` would both slip past a coercing guard —
        contradicting the integer-only contract the error promises.
        """
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.mcp import tools as tools_mod

        def _record(path):
            raise AssertionError("the graph must not be opened")

        for bad in ("x", 1.5, 2.0, True, False, None, [1]):
            with self.subTest(limit=bad):
                with mock.patch.object(GraphDatabase, "connect_read_only",
                                       _record):
                    out = tools_mod.session_clusters(
                        _FakeDb(), "/any/path", limit=bad)
                self.assertIn("limit must be an integer", out["error"])
                self.assertIn(repr(bad), out["error"])
                self.assertNotIn("clusters", out)

    def test_valid_integer_limits_are_still_accepted(self) -> None:
        # the guard must not over-refuse: plain ints pass through
        for good in (0, 1, 3, 99):
            with self.subTest(limit=good):
                out = self._run(self._three(), limit=good)
                self.assertNotIn("error", out)
                self.assertEqual(len(out["clusters"]), min(good, 3))

    def test_results_are_basis_honest_and_carry_provenance(self) -> None:
        out = self._run(self._three())
        self.assertEqual(out["basis"], "embedding")
        self.assertNotEqual(out["membership_basis"], out["inventory_basis"])
        limitations = " ".join(out["limitations"])
        self.assertIn("transitive discovery grouping", limitations)
        self.assertIn("does not assert that every pair", limitations)
        self.assertIn("does not assert that members currently share",
                      limitations)

    def test_no_space_triple_and_no_score_in_the_payload(self) -> None:
        blob = json.dumps(self._run(self._three()))
        for forbidden in ("provider", "\"model\"", "\"dim\"", "score"):
            self.assertNotIn(forbidden, blob)

    def test_surfaces_share_one_provenance_source(self) -> None:
        # the CLI and the MCP tool must not drift apart
        from session_analytics.embedding import cluster_reader as cr

        out = self._run(self._three())
        self.assertEqual(out["membership_basis"], cr.MEMBERSHIP_BASIS_TEXT)
        self.assertEqual(out["inventory_basis"], cr.INVENTORY_BASIS_TEXT)
        self.assertEqual(out["limitations"], list(cr.LIMITATIONS_TEXT))


@unittest.skipUnless(_MCP, "mcp SDK not installed; registration test skipped")
class TestRegisteredOnTheRealServer(unittest.TestCase):
    """T3: the tool is actually registered, on the plumbed kuzu_path."""

    def test_session_clusters_is_registered_beside_the_others(self) -> None:
        import asyncio

        from session_analytics.mcp.server import build_server

        server = build_server("sqlite:///unused.db", kuzu_path="/nondefault/g")
        names = {t.name for t in asyncio.run(server.list_tools())}
        self.assertIn("session_clusters", names)
        # the existing five are untouched
        for existing in ("search_sessions", "get_session_details",
                         "analyze_patterns", "compare_approaches",
                         "similar_sessions"):
            self.assertIn(existing, names)

    def test_registered_tool_uses_the_nondefault_kuzu_path(self) -> None:
        from session_analytics.mcp import server as server_mod
        from session_analytics.mcp.server import build_server

        seen = {}

        def _spy(db, kuzu_path, session_id=None, limit=10):
            seen["kuzu_path"] = kuzu_path
            seen["session_id"] = session_id
            seen["limit"] = limit
            return {"ok": True}

        with mock.patch.object(server_mod.tools, "session_clusters", _spy), \
             mock.patch.object(server_mod, "Database") as db_cls:
            db_cls.connect.return_value = mock.Mock()
            server = build_server("sqlite:///unused.db",
                                  kuzu_path="/nondefault/graph")
            import asyncio
            asyncio.run(server.call_tool("session_clusters", {"limit": 3}))
        self.assertEqual(seen["kuzu_path"], "/nondefault/graph")
        # omitting session_id means LIST mode — no sentinel value
        self.assertIsNone(seen["session_id"])
        self.assertEqual(seen["limit"], 3)

    def test_negative_limit_is_refused_through_the_real_server(self) -> None:
        """The refusal must hold at the PUBLISHED boundary, not only in
        the direct function call."""
        import asyncio

        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.mcp import server as server_mod
        from session_analytics.mcp.server import build_server

        opens = []

        def _record(path):
            opens.append(path)
            raise AssertionError("the graph must not be opened")

        with mock.patch.object(server_mod, "Database") as db_cls, \
             mock.patch.object(GraphDatabase, "connect_read_only", _record):
            db_cls.connect.return_value = mock.Mock()
            server = build_server("sqlite:///unused.db", kuzu_path="/g")
            _content, payload = asyncio.run(
                server.call_tool("session_clusters", {"limit": -1}))
        self.assertIn("limit", payload["error"])
        self.assertIn("-1", payload["error"])
        self.assertEqual(opens, [])

    def test_session_id_is_optional_in_the_published_schema(self) -> None:
        """The advertised signature matches FR-F: session_id=None."""
        import asyncio

        from session_analytics.mcp.server import build_server

        server = build_server("sqlite:///unused.db", kuzu_path="/g")
        tool = next(t for t in asyncio.run(server.list_tools())
                    if t.name == "session_clusters")
        prop = tool.inputSchema["properties"]["session_id"]
        self.assertIsNone(prop["default"])
        self.assertIn({"type": "null"}, prop["anyOf"])
        self.assertNotIn("session_id",
                         tool.inputSchema.get("required", []))


@unittest.skipUnless(_KUZU, "kuzu not installed; live MCP cluster read skipped")
class TestSessionClustersLiveKuzu(unittest.TestCase):
    """Against a real store built by the REAL #287 producer."""

    def _world(self):
        from session_analytics.config import SimilarityConfig
        from session_analytics.embedding.similar_runner import (
            KuzuEdgeStore, run_similar)
        from session_analytics.graph import builder
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.relational.db import Database, apply_ddl

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-mcp-live-"))
        db = Database.connect(f"sqlite:///{tmp / 'sa.db'}")
        apply_ddl(db)
        self.addCleanup(db.close)

        def env(vec):
            return {"schema_version": 1, "provider": "ollama",
                    "model": "nomic-embed-text", "dim": 3,
                    "embedded_at": "2026-09-03T12:00:00+00:00",
                    "vector": list(vec)}

        ids = {}
        for native, vec in (("a", (1.0, 0.0, 0.0)), ("b", (0.99, 0.01, 0.0)),
                            ("lonely", (0.0, 0.0, 1.0))):
            ids[native] = db.insert_returning_id(
                "INSERT INTO copilot_session (copilot, session_id, "
                "turn_count, session_embedding) VALUES (?, ?, ?, ?) "
                "RETURNING id",
                ("claude-code", native, 0, json.dumps(env(vec))))
        db.commit()
        graph_path = str(tmp / "g")
        builder.build(db, graph_path)
        gdb = GraphDatabase.connect(graph_path)
        try:
            run_similar(db, SimilarityConfig(threshold=0.5, top_k=3),
                        KuzuEdgeStore(gdb))
        finally:
            gdb.close()
        return db, graph_path, ids

    def test_clustered_unclustered_and_missing_node_on_a_real_store(self):
        db, graph_path, ids = self._world()

        clustered = session_clusters(db, graph_path, session_id=ids["a"])
        self.assertEqual(clustered["outcome"], "clustered")
        self.assertIn("claude-code:b", clustered["cluster"]["members"])

        lonely = session_clusters(db, graph_path, session_id=ids["lonely"])
        self.assertEqual(lonely["outcome"], "unclustered")

        # a session added AFTER the graph build has no node yet
        late = db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count) "
            "VALUES (?, ?, ?) RETURNING id", ("claude-code", "late", 0))
        db.commit()
        out = session_clusters(db, graph_path, session_id=late)
        self.assertEqual(out["prerequisite"], "graph")
        self.assertIn("graph node", out["error"])

    def test_list_mode_on_a_real_store(self) -> None:
        db, graph_path, _ids = self._world()
        out = session_clusters(db, graph_path)
        self.assertEqual(out["cluster_count"], 1)
        self.assertEqual(out["unclustered_sessions"], 1)
        self.assertEqual(out["graph_sessions"], 3)

    def test_read_path_creates_and_mutates_nothing(self) -> None:
        from session_analytics.graph.schema import GraphDatabase

        db, graph_path, _ids = self._world()

        def count():
            gdb = GraphDatabase.connect_read_only(graph_path)
            try:
                res = gdb.execute("MATCH (a:Session)-[r:SIMILAR_TO]->() "
                                  "RETURN count(r)")
                return res.get_next()[0]
            finally:
                gdb.close()

        before = count()
        session_clusters(db, graph_path)
        self.assertEqual(count(), before)


if __name__ == "__main__":
    unittest.main()
