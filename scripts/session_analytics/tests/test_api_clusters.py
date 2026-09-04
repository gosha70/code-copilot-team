# Tests for #293 T1 — the read-only clusters / similar endpoints.
#
# Same fastapi gate as test_api.py: these skip without fastapi+httpx,
# so a run that reports "green" without them has measured NOTHING here.
# The closure evidence must state the executed count and the
# environment, not just that a suite passed.

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_FASTAPI = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)


def _client(kuzu_path: str):
    from fastapi.testclient import TestClient

    from session_analytics.api.server import create_app

    # #103: TestClient's default `Host: testserver` is deliberately not
    # allowlisted, so point at an allowlisted host.
    return TestClient(create_app("sqlite:///:memory:", kuzu_path=kuzu_path),
                      base_url="http://127.0.0.1:8765")


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class TestClustersEndpointPrerequisites(unittest.TestCase):
    """FR-B: #289's ladder, reached over HTTP, creating nothing."""

    def test_each_prerequisite_names_the_state_the_server_determined(self) -> None:
        """The endpoint knows WHICH state it is in at each raise site.

        Encoding that only into English would force the client to
        reconstruct it with a substring match on the error text — the
        signal would be present, discarded, and re-derived. Each of the
        three sites therefore carries an explicit `state`, and the
        values must be distinct or the client cannot tell them apart.
        """
        from session_analytics.embedding import cluster_reader as cr
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        seen = {}

        # absent: refused before any open
        tmp = Path(tempfile.mkdtemp(prefix="cct-api-state-absent-"))
        r = _client(str(tmp / "nope")).get("/api/clusters")
        seen["absent"] = r.json()["detail"]["state"]

        # unopenable: exists(), then the open fails (the TOCTOU race)
        store = tmp / "vanished"
        store.mkdir()

        def _vanished(path):
            raise RuntimeError("READ ONLY mode")

        with mock.patch.object(GraphDatabase, "connect_read_only", _vanished):
            r = _client(str(store)).get("/api/clusters")
        seen["unopenable"] = r.json()["detail"]["state"]

        # unbuilt: opens, but holds no Session table
        gdb = mock.Mock()
        gdb.close = mock.Mock()
        with mock.patch.object(GraphDatabase, "connect_read_only",
                               lambda p: gdb), \
             mock.patch.object(cr, "KuzuGraphSnapshot",
                               lambda g: _FakeSnapshot(ready=False)):
            r = _client(str(store)).get("/api/clusters")
        seen["unbuilt"] = r.json()["detail"]["state"]

        self.assertEqual(seen, {"absent": "absent",
                                "unopenable": "unopenable",
                                "unbuilt": "unbuilt"})
        self.assertEqual(len(set(seen.values())), 3,
                         "the three states must be distinguishable")

    def test_absent_path_is_a_prerequisite_and_creates_nothing(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-api-clusters-absent-"))
        ghost = tmp / "nope"
        r = _client(str(ghost)).get("/api/clusters")
        self.assertEqual(r.status_code, 503)
        detail = r.json()["detail"]
        self.assertEqual(detail["prerequisite"], "graph")
        self.assertIn("absent", detail["error"])
        self.assertIn("graph", detail["guidance"])
        self.assertFalse(ghost.exists(), "the read path created the store")
        # the PRE-OPEN check must be what refused, not the open itself
        self.assertNotIn("unopenable", detail["error"])

    def test_unset_path_is_a_prerequisite(self) -> None:
        with mock.patch("session_analytics.api.server.load_config") as lc:
            lc.return_value = mock.Mock(kuzu_path="")
            r = _client("").get("/api/clusters")
        self.assertEqual(r.status_code, 503)
        self.assertIn("(unset)", r.json()["detail"]["error"])

    def test_disappearing_path_is_refused_not_repaired(self) -> None:
        from session_analytics.graph.schema import GraphDatabase

        tmp = Path(tempfile.mkdtemp(prefix="cct-api-clusters-race-"))
        store = tmp / "vanished"
        store.mkdir()  # exists() passes; the open then fails

        def _vanished(path):
            raise RuntimeError("Cannot create an empty database under "
                               "READ ONLY mode")

        with mock.patch.object(GraphDatabase, "connect_read_only", _vanished):
            r = _client(str(store)).get("/api/clusters")
        self.assertEqual(r.status_code, 503)
        self.assertIn("absent or unopenable", r.json()["detail"]["error"])

    def test_unbuilt_graph_is_a_prerequisite_not_an_empty_result(self) -> None:
        from session_analytics.embedding import cluster_reader as cr
        from session_analytics.graph.schema import GraphDatabase
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        tmp = Path(tempfile.mkdtemp(prefix="cct-api-clusters-unbuilt-"))
        store = tmp / "g"
        store.mkdir()
        gdb = mock.Mock()
        gdb.close = mock.Mock()
        with mock.patch.object(GraphDatabase, "connect_read_only",
                               lambda p: gdb), \
             mock.patch.object(cr, "KuzuGraphSnapshot",
                               lambda g: _FakeSnapshot(ready=False)):
            r = _client(str(store)).get("/api/clusters")
        self.assertEqual(r.status_code, 503)
        self.assertIn("Session table", r.json()["detail"]["error"])


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class TestClustersEndpointPassesThroughVerbatim(unittest.TestCase):
    """D2: the endpoint reshapes nothing.

    A reshaping layer is where the limitations block and the provenance
    labels get quietly dropped, which FR-E exists to prevent.
    """

    def _get(self, snapshot):
        from session_analytics.embedding import cluster_reader as cr
        from session_analytics.graph.schema import GraphDatabase

        tmp = Path(tempfile.mkdtemp(prefix="cct-api-clusters-ok-"))
        store = tmp / "g"
        store.mkdir()
        gdb = mock.Mock()
        gdb.close = mock.Mock()
        with mock.patch.object(GraphDatabase, "connect_read_only",
                               lambda p: gdb), \
             mock.patch.object(cr, "KuzuGraphSnapshot", lambda g: snapshot):
            return _client(str(store)).get("/api/clusters")

    def _snapshot(self, nodes, edges):
        from session_analytics.tests.test_cluster_reader import _FakeSnapshot

        return _FakeSnapshot(nodes=nodes, edges=edges)

    def test_body_equals_the_readers_own_report(self) -> None:
        """THE pass-through discriminator: byte-for-byte, not 'similar'."""
        from session_analytics.embedding.cluster_reader import run_clusters

        nodes = {"a", "b", "c"}
        edges = (("a", "b", 0.9), ("b", "a", 0.9))
        r = self._get(self._snapshot(nodes, edges))
        self.assertEqual(r.status_code, 200)
        expected = run_clusters(self._snapshot(nodes, edges)).as_dict()
        self.assertEqual(r.json(), expected)

    def test_limitations_and_both_provenance_labels_survive(self) -> None:
        from session_analytics.embedding import cluster_reader as cr

        body = self._get(self._snapshot({"a", "b"}, (("a", "b", 0.9),))).json()
        self.assertEqual(body["membership_basis"], cr.MEMBERSHIP_BASIS_TEXT)
        self.assertEqual(body["inventory_basis"], cr.INVENTORY_BASIS_TEXT)
        self.assertEqual(body["limitations"], list(cr.LIMITATIONS_TEXT))
        self.assertEqual(body["basis"], cr.BASIS_EMBEDDING)

    def test_healthy_empty_is_200_not_an_error(self) -> None:
        r = self._get(self._snapshot({"a", "b"}, ()))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["cluster_count"], 0)
        self.assertEqual(r.json()["unclustered_sessions"], 2)

    def test_order_is_the_readers_order_not_the_endpoints(self) -> None:
        """The ordering discriminator (plan): a fixture whose
        size-descending and identity-ascending orders DIFFER, so a sort
        on either side changes the answer.

        Sizes 3, 2, 2 with identities 'm', 'a', 'p': size-descending
        puts 'm' first, identity-ascending would put 'a' first.
        """
        from session_analytics.embedding.cluster_reader import run_clusters

        nodes = {"m", "n", "o", "a", "b", "p", "q"}
        edges = (("m", "n", 0.9), ("n", "o", 0.9),
                 ("a", "b", 0.9), ("p", "q", 0.9))
        body = self._get(self._snapshot(nodes, edges)).json()
        identities = [c["identity"] for c in body["clusters"]]
        self.assertEqual(identities, ["m", "a", "p"])
        self.assertNotEqual(identities, sorted(identities),
                            "identity-ascending would be a DIFFERENT order")
        self.assertEqual(
            identities,
            [c.identity for c in run_clusters(self._snapshot(nodes, edges)).clusters])


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class TestSimilarEndpoint(unittest.TestCase):
    """FR-B: wraps `tools.similar_sessions`, reimplementing nothing."""

    def _get(self, result, session_id=1, limit=10):
        from session_analytics.api import server as srv

        calls = {}

        def _spy(db, path, sid, limit=10):
            calls["args"] = (path, sid, limit)
            return result

        tmp = Path(tempfile.mkdtemp(prefix="cct-api-similar-"))
        with mock.patch("session_analytics.mcp.tools.similar_sessions", _spy), \
             mock.patch.object(srv, "Database") as db_cls:
            db_cls.connect.return_value = mock.Mock()
            r = _client(str(tmp / "g")).get(
                f"/api/sessions/{session_id}/similar?limit={limit}")
        return r, calls

    def test_neighbours_pass_through_verbatim(self) -> None:
        payload = {"session_id": 1, "basis": "embedding",
                   "scores_are": "a snapshot of the last completed 'similar' pass",
                   "neighbors": [{"session_key": "claude-code:b", "score": 0.9}]}
        r, calls = self._get(payload, session_id=1, limit=3)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), payload)
        self.assertEqual(calls["args"][1:], (1, 3))

    def test_graph_prerequisite_becomes_503_with_the_same_shape(self) -> None:
        r, _ = self._get({"error": "session 1 has no graph node",
                          "prerequisite": "graph",
                          "guidance": "run './scripts/session-analytics graph'"})
        self.assertEqual(r.status_code, 503)
        detail = r.json()["detail"]
        self.assertEqual(detail["prerequisite"], "graph")
        self.assertIn("graph node", detail["error"])

    def test_unknown_session_is_404_not_a_prerequisite(self) -> None:
        r, _ = self._get({"error": "session 99 not found"})
        self.assertEqual(r.status_code, 404)
        self.assertIn("not found", r.json()["detail"]["error"])

    def test_an_unrecognised_error_is_not_collapsed_into_404(self) -> None:
        """`"error" in result` is the tool's error CHANNEL, not a
        synonym for "not found".

        Collapsing every condition it can carry into one code is the
        mirror of the FR-C failure this slice exists to prevent: N
        conditions, one answer. An unrecognised error is a 500 — honest
        — rather than a confident wrong 404. Concretely, if a range
        guard ever lands inside `similar_sessions`, a bad limit must not
        surface to a client as "session not found".
        """
        r, _ = self._get({"error": "limit must be >= 0, got -1"})
        self.assertEqual(r.status_code, 500)
        self.assertIn("limit", r.json()["detail"]["error"])


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class TestSimilarLimitIsRangeGuarded(unittest.TestCase):
    """FastAPI validates the TYPE from the annotation; range was open.

    `similar_sessions` has no range check of its own, so -1, 0 and 1e9
    all reached the query. The guard lives at the endpoint signature so
    this new public surface is bounded WITHOUT altering an existing tool
    contract — and FastAPI answers 422, the right code for client input.
    """

    def _call(self, qs: str):
        from session_analytics.api import server as srv

        tmp = Path(tempfile.mkdtemp(prefix="cct-api-limit-"))
        reached = {}

        def _spy(db, path, sid, limit=10):
            reached["limit"] = limit
            return {"session_id": sid, "basis": "embedding", "neighbors": []}

        with mock.patch("session_analytics.mcp.tools.similar_sessions", _spy), \
             mock.patch.object(srv, "Database") as db_cls:
            db_cls.connect.return_value = mock.Mock()
            r = _client(str(tmp / "g")).get(f"/api/sessions/1/similar?{qs}")
        return r, reached

    def test_negative_and_zero_are_refused_before_the_tool(self) -> None:
        for bad in ("limit=-1", "limit=0"):
            with self.subTest(qs=bad):
                r, reached = self._call(bad)
                self.assertEqual(r.status_code, 422)
                self.assertEqual(reached, {}, "the tool must not be reached")

    def test_absurdly_large_limit_is_refused(self) -> None:
        r, reached = self._call("limit=1000000000")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(reached, {})

    def test_non_integer_is_refused_by_the_annotation(self) -> None:
        r, reached = self._call("limit=abc")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(reached, {})

    def test_the_cap_and_the_values_below_it_are_accepted(self) -> None:
        from session_analytics import constants as C

        for good in (1, 10, C.SIMILAR_MAX_LIMIT):
            with self.subTest(limit=good):
                r, reached = self._call(f"limit={good}")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(reached["limit"], good)

    def test_one_over_the_cap_is_refused(self) -> None:
        from session_analytics import constants as C

        r, reached = self._call(f"limit={C.SIMILAR_MAX_LIMIT + 1}")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(reached, {})


if __name__ == "__main__":
    unittest.main()
