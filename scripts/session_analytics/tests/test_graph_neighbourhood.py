# The Graph page's neighbourhoods and query catalogue: a session and a
# project with every relationship named, the drill-ins behind a tool
# and a file, and the catalogue (data) with parameters bound.

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_KUZU = importlib.util.find_spec("kuzu") is not None
_FASTAPI = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("httpx") is not None


class TestCatalogueData(unittest.TestCase):
    def test_every_entry_is_well_formed(self) -> None:
        from session_analytics.graph.query import RENDER_KINDS, catalogue, catalogue_entry

        entries = catalogue()
        self.assertGreaterEqual(len(entries), 10)
        ids = [e["id"] for e in entries]
        self.assertEqual(len(ids), len(set(ids)))
        for e in entries:
            self.assertIn(e["intent"], ("search", "detail", "pattern"), e["id"])
            self.assertIn(e["render"], RENDER_KINDS, e["id"])
            self.assertTrue(e["name"] and e["question"], e["id"])
            self.assertNotIn("cypher", e)  # the Studio never sees the Cypher through the index
            full = catalogue_entry(e["id"])
            self.assertIn("MATCH", full["cypher"])
            for p in e["params"]:
                self.assertIn(f"${p['name']}", full["cypher"], f"{e['id']}: ${p['name']} unused")
                self.assertIn(p["type"], ("session", "project", "text"))
        self.assertIsNone(catalogue_entry("nope"))

    def test_elements_from_rows(self) -> None:
        from session_analytics.graph.query import elements_from_rows

        a = {"_id": {"table": 5, "offset": 0}, "_label": "Session", "session_key": "c:a", "model": "m"}
        b = {"_id": {"table": 5, "offset": 1}, "_label": "Session", "session_key": "c:b"}
        r = {"_id": {"table": 9, "offset": 0}, "_label": "SIMILAR_TO", "_src": {"table": 5, "offset": 0},
             "_dst": {"table": 5, "offset": 1}, "score": 0.8}
        dangling = {"_id": {"table": 9, "offset": 1}, "_label": "SIMILAR_TO", "_src": {"table": 5, "offset": 0},
                    "_dst": {"table": 5, "offset": 99}, "score": 0.5}
        el = elements_from_rows([{"a": a, "r": r, "b": b}, {"a": a, "r": dangling, "b": None}])
        self.assertEqual([n["id"] for n in el["nodes"]], ["Session:c:a", "Session:c:b"])
        self.assertEqual(el["nodes"][0]["props"], {"session_key": "c:a", "model": "m"})
        self.assertEqual(el["edges"], [{"source": "Session:c:a", "target": "Session:c:b", "rel": "SIMILAR_TO",
                                        "props": {"score": 0.8}}])


@unittest.skipUnless(_KUZU, "kuzu not installed")
class TestNeighbourhoodLive(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        from session_analytics.graph.builder import build
        from session_analytics.graph.schema import GraphDatabase

        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.graph = str(Path(tempfile.mkdtemp(prefix="cct-sa-nb-")) / "g")
        self.rel = Database.connect(self.dsn)
        self.addCleanup(self.rel.close)
        build(self.rel, self.graph, rebuild=True)
        self.gdb = GraphDatabase.connect_read_only(self.graph)
        self.addCleanup(self.gdb.close)
        self.sid = int(self.rel.query_one("SELECT id FROM copilot_session")[0])

    def test_session_neighbourhood_names_every_relationship(self) -> None:
        from session_analytics.graph import neighbourhood as nb

        n = nb.session_neighbourhood(self.gdb, self.rel, self.sid)
        self.assertEqual(n["kind"], "session")
        self.assertEqual(n["centre"]["id"], self.sid)
        rels = {c["rel"] for c in n["context"]}
        self.assertTrue({"IN_WORKSPACE", "RAN_ON", "BY_DEVELOPER"} <= rels, rels)
        self.assertTrue(n["tools"])
        self.assertEqual(sum(t["calls"] for t in n["tools"]), n["centre"]["tool_call_count"])
        self.assertTrue(any(t["errors"] > 0 for t in n["tools"]))  # the fixture has one tool error
        self.assertTrue(n["errors"])
        self.assertTrue(n["files"])
        self.assertEqual(n["similar"], [])  # no similarity pass ran
        self.assertIn("INVOKED", n["relationships"]["tools"])
        self.assertNotIn("retries", n)  # no producer writes RETRIED; nothing is claimed
        # every capped list carries its total, so the page can say "N of M"
        self.assertEqual(n["totals"]["tools"], len(n["tools"]))
        self.assertEqual(n["totals"]["files"], len(n["files"]))
        self.assertEqual(n["totals"]["similar"], 0)
        self.assertEqual(n["totals"]["errors"], sum(e["count"] for e in n["errors"]))
        self.assertEqual(n["limits"], {"tools": nb.TOP_TOOLS, "files": nb.TOP_FILES, "similar": nb.TOP_SIMILAR})
        self.assertIsNone(nb.session_neighbourhood(self.gdb, self.rel, 99999))

    def test_drill_ins_and_project(self) -> None:
        from session_analytics.graph import neighbourhood as nb

        n = nb.session_neighbourhood(self.gdb, self.rel, self.sid)
        tool = n["tools"][0]["tool"]
        tt = nb.tool_turns(self.gdb, self.rel, self.sid, tool)
        # one row per CALL, with a call identity; turns counted separately
        self.assertEqual(len(tt["calls"]), n["tools"][0]["calls"])
        self.assertEqual(len({c["call_key"] for c in tt["calls"]}), len(tt["calls"]))
        self.assertEqual(tt["turns"], len({c["sequence_num"] for c in tt["calls"]}))
        self.assertLessEqual(tt["turns"], len(tt["calls"]))
        path = n["files"][0]["path"]
        fs = nb.file_sessions(self.gdb, self.rel, path)
        self.assertEqual([s["id"] for s in fs["sessions"]], [self.sid])
        self.assertEqual((fs["total"], fs["limit"]), (1, nb.FILE_SESSIONS))
        project = n["centre"]["project_path"]
        p = nb.project_neighbourhood(self.gdb, self.rel, project)
        self.assertEqual([s["id"] for s in p["sessions"]], [self.sid])
        self.assertTrue(p["models"] and p["tools"] and p["files"])
        self.assertEqual(p["totals"]["sessions"], 1)
        self.assertEqual(p["totals"]["tools"], len(p["tools"]))
        self.assertEqual(nb.project_paths(self.gdb), [{"path": project, "sessions": 1}])

    def test_two_calls_of_one_tool_in_one_turn_are_two_rows(self) -> None:
        # The fixture has one call per turn; this adds a second call of
        # the same tool to a turn and expects two rows, not one (the
        # grouped-by-turn query collapsed them, or split a turn in two).
        from session_analytics.graph import neighbourhood as nb
        from session_analytics.graph.builder import build
        from session_analytics.graph.schema import GraphDatabase

        n = nb.session_neighbourhood(self.gdb, self.rel, self.sid)
        tool = n["tools"][0]["tool"]
        turn = self.rel.query_one(
            "SELECT t.id, t.sequence_num FROM copilot_turn t JOIN copilot_tool_call c ON c.turn_id = t.id "
            "WHERE c.tool_name = ? LIMIT 1", (tool,))
        self.rel.execute(
            "INSERT INTO copilot_tool_call (turn_id, tool_use_id, tool_name, tool_name_raw, sequence_num) "
            "VALUES (?, ?, ?, ?, ?)", (turn[0], "extra-call", tool, tool, 99))
        self.rel.commit()
        self.gdb.close()
        build(self.rel, self.graph, rebuild=True)
        self.gdb = GraphDatabase.connect_read_only(self.graph)
        tt = nb.tool_turns(self.gdb, self.rel, self.sid, tool)
        same_turn = [c for c in tt["calls"] if c["sequence_num"] == int(turn[1])]
        self.assertEqual(len(same_turn), 2)
        self.assertEqual(len({c["call_key"] for c in same_turn}), 2)

    def test_catalogue_refuses_a_mutating_entry(self) -> None:
        # The catalogue is data: an edited entry must not turn the
        # read-only page into a writer. Same guard as the raw editor.
        from unittest import mock

        from session_analytics.graph import query as gq

        bad = {"id": "evil", "name": "x", "question": "x", "params": [], "render": "table",
               "cypher": "MATCH (s:Session) DELETE s"}
        with mock.patch.object(gq, "catalogue_entry", lambda _id: bad):
            with self.assertRaises(ValueError):
                gq.run_catalogue(self.gdb, "evil", {})
        self.assertGreater(len(list(gq._rows(self.gdb.execute("MATCH (s:Session) RETURN s")))), 0)

    def test_catalogue_runs_and_binds_parameters(self) -> None:
        from session_analytics.graph import neighbourhood as nb
        from session_analytics.graph.query import catalogue, run_catalogue

        key = nb.session_key_for(self.rel, self.sid)
        for e in catalogue():
            params = {p["name"]: (key if p["type"] == "session" else "") for p in e["params"]}
            if any(p["type"] == "project" and p["required"] for p in e["params"]):
                params = {p["name"]: "/repo/demo" for p in e["params"]}
            out = run_catalogue(self.gdb, e["id"], params)
            self.assertEqual(out["render"], e["render"], e["id"])
            if e["render"] == "graph":
                self.assertIn("elements", out)
            else:
                self.assertIsInstance(out["rows"], list)
        with self.assertRaises(ValueError):
            run_catalogue(self.gdb, "similar-to-session", {})
        with self.assertRaises(ValueError):
            run_catalogue(self.gdb, "nope", {})
        # nothing in the catalogue asks about RETRIED: no producer writes it
        from session_analytics.graph.query import catalogue_entry
        for e in catalogue():
            self.assertNotIn("RETRIED", catalogue_entry(e["id"])["cypher"], e["id"])
        # a graph-rendered answer over the fixture: the session and its context
        out = run_catalogue(self.gdb, "session-context", {"session": key})
        self.assertGreaterEqual(len(out["elements"]["nodes"]), 4)
        self.assertTrue({e["rel"] for e in out["elements"]["edges"]} >= {"IN_WORKSPACE", "RAN_ON"})


@unittest.skipUnless(_KUZU and _FASTAPI, "kuzu/fastapi not installed")
class TestGraphRoutes(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        from session_analytics._register import register_all
        from session_analytics.graph.builder import build

        register_all()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.graph = str(Path(tempfile.mkdtemp(prefix="cct-sa-nbapi-")) / "g")
        rel = Database.connect(self.dsn)
        try:
            build(rel, self.graph, rebuild=True)
            self.sid = int(rel.query_one("SELECT id FROM copilot_session")[0])
        finally:
            rel.close()
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        self.client = TestClient(create_app(self.dsn, kuzu_path=self.graph), base_url="http://127.0.0.1:8765")

    def test_routes(self) -> None:
        n = self.client.get(f"/api/graph/session/{self.sid}")
        self.assertEqual(n.status_code, 200, n.text)
        body = n.json()
        self.assertEqual(body["kind"], "session")
        tool = body["tools"][0]["tool"]
        self.assertEqual(self.client.get(f"/api/graph/session/{self.sid}/tool/{tool}").status_code, 200)
        self.assertEqual(self.client.get("/api/graph/file", params={"path": body["files"][0]["path"]}).json()["sessions"][0]["id"], self.sid)
        self.assertEqual(self.client.get("/api/graph/project", params={"path": body["centre"]["project_path"]}).json()["kind"], "project")
        self.assertEqual(len(self.client.get("/api/graph/projects").json()["projects"]), 1)
        self.assertEqual(self.client.get("/api/graph/session/99999").status_code, 404)
        cat = self.client.get("/api/graph/catalogue").json()["queries"]
        self.assertTrue(cat and "cypher" not in cat[0])
        r = self.client.post("/api/graph/catalogue/sessions-per-workspace", json={"params": {}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["render"], "bar")
        self.assertEqual(self.client.post("/api/graph/catalogue/similar-to-session", json={"params": {}}).status_code, 400)
        self.assertEqual(self.client.post("/api/graph/catalogue/nope").status_code, 400)

    def test_absent_graph_is_a_prerequisite_and_stays_absent(self) -> None:
        # The Graph page only READS: a GET on an absent store path must
        # answer 503 and must not create the store or its directory (the
        # old opener did both). Every route, including node counts,
        # query and expand, goes through the same non-creating open.
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        parent = Path(tempfile.mkdtemp(prefix="cct-sa-nbempty-")) / "never"
        absent = str(parent / "g")
        client = TestClient(create_app(self.dsn, kuzu_path=absent), base_url="http://127.0.0.1:8765")
        for method, url, body in (
            ("GET", f"/api/graph/session/{self.sid}", None),
            ("GET", "/api/graph/projects", None),
            ("GET", "/api/graph/node-counts", None),
            ("GET", "/api/graph/expand?label=Session&key_field=session_key&key_value=x", None),
            ("POST", "/api/graph/query", {"cypher": "MATCH (s:Session) RETURN s LIMIT 1"}),
            ("POST", "/api/graph/catalogue/sessions-per-workspace", {"params": {}}),
        ):
            r = client.get(url) if method == "GET" else client.post(url, json=body)
            self.assertEqual(r.status_code, 503, f"{url}: {r.text}")
            self.assertEqual(r.json()["detail"]["prerequisite"], "graph", url)
        self.assertFalse(parent.exists(), "a read created the store's directory")
        self.assertFalse(Path(absent).exists(), "a read created the store")


if __name__ == "__main__":
    unittest.main()
