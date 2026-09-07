# Tests for the Kùzu knowledge-graph layer.
#
# Pure tests (DDL parsing) run everywhere. The live build test runs only when
# the optional ``kuzu`` package is importable; CI installs it for the graph
# job. Skips are logged, never silently passed.

from __future__ import annotations

import importlib.util
import unittest

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.graph import schema
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_KUZU = importlib.util.find_spec("kuzu") is not None


class TestGraphDDL(unittest.TestCase):
    def test_node_and_rel_ddl_loaded(self) -> None:
        nodes = schema.load_node_ddl()
        rels = schema.load_rel_ddl()
        self.assertEqual(len(nodes), 10)  # 10 node tables
        self.assertEqual(len(rels), 12)   # 12 rel tables
        self.assertTrue(all(s.startswith("CREATE NODE TABLE") for s in nodes))
        self.assertTrue(all(s.startswith("CREATE REL TABLE") for s in rels))

    def test_table_name_parse(self) -> None:
        self.assertEqual(
            schema._table_name("CREATE NODE TABLE IF NOT EXISTS Session(x STRING, PRIMARY KEY(x))"),
            "Session",
        )
        self.assertEqual(
            schema._table_name("CREATE REL TABLE IF NOT EXISTS HAS_TURN(FROM Session TO Turn)"),
            "HAS_TURN",
        )


class TestReadonlyGuard(unittest.TestCase):
    """The freeform Cypher IDE must reject mutating statements (no Kùzu needed)."""

    def test_rejects_mutations_without_trailing_space(self) -> None:
        from session_analytics.graph.query import assert_readonly

        for bad in (
            "CREATE(n:Foo)",
            "MATCH (n) SET\nn.x = 1",
            "MATCH (n) DELETE\nn",
            "MATCH (n) DETACH DELETE n",
            "drop table Session",
            "MATCH (n) REMOVE n.x",
            "MERGE (n:Foo {a:1})",
        ):
            with self.assertRaises(ValueError, msg=bad):
                assert_readonly(bad)

    def test_allows_read_queries(self) -> None:
        from session_analytics.graph.query import assert_readonly

        for ok in (
            "MATCH (s:Session) RETURN s.session_key LIMIT 10",
            "MATCH (n) RETURN n.createdAt AS created",   # 'create' substring is fine
            "MATCH (n) RETURN n.set_value",              # 'set' substring is fine
            "MATCH (i:ToolInvocation) RETURN count(i)",
        ):
            assert_readonly(ok)  # must not raise


@unittest.skipUnless(_KUZU, "kuzu not installed; live graph build skipped (covered in CI)")
class TestGraphBuildLive(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()

    def test_build_from_fixture(self) -> None:
        import tempfile
        from pathlib import Path

        from session_analytics.graph import query
        from session_analytics.graph.builder import build
        from session_analytics.graph.schema import GraphDatabase

        dsn = self.sqlite_dsn()
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)

        graph_dir = str(Path(tempfile.mkdtemp(prefix="cct-sa-kuzu-")) / "g")
        rel = Database.connect(dsn)
        try:
            stats = build(rel, graph_dir, rebuild=True)
        finally:
            rel.close()
        self.assertEqual(stats.sessions, 1)
        self.assertEqual(stats.turns, 6)
        self.assertEqual(stats.tools, 2)

        gdb = GraphDatabase.connect(graph_dir)
        try:
            counts = query.node_counts(gdb)
            failures = query.tool_failure_stats(gdb)
        finally:
            gdb.close()
        self.assertEqual(counts["Session"], 1)
        self.assertEqual(counts["Turn"], 6)
        self.assertEqual(counts["ToolInvocation"], 2)
        self.assertEqual(counts["FileNode"], 1)
        self.assertEqual(counts["ErrorNode"], 1)
        # The Read tool errored once in the fixture.
        read = next((f for f in failures if f["tool"] == "file_read"), None)
        self.assertIsNotNone(read)
        self.assertEqual(read["errors"], 1)

    def test_rebuild_is_idempotent(self) -> None:
        import tempfile
        from pathlib import Path

        from session_analytics.graph import query
        from session_analytics.graph.builder import build
        from session_analytics.graph.schema import GraphDatabase

        dsn = self.sqlite_dsn()
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        graph_dir = str(Path(tempfile.mkdtemp(prefix="cct-sa-kuzu-")) / "g")

        rel = Database.connect(dsn)
        try:
            build(rel, graph_dir, rebuild=True)
            build(rel, graph_dir, rebuild=True)  # second pass
        finally:
            rel.close()

        gdb = GraphDatabase.connect(graph_dir)
        try:
            counts = query.node_counts(gdb)
        finally:
            gdb.close()
        self.assertEqual(counts["Session"], 1)
        self.assertEqual(counts["Turn"], 6)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(_KUZU, "kuzu not installed; live graph build skipped (covered in CI)")
class TestBulkBuild(RegistryResetTestCase):
    """#311: the COPY FROM rebuild path."""

    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)

    def _graph_dir(self) -> str:
        import tempfile
        from pathlib import Path

        return str(Path(tempfile.mkdtemp(prefix="cct-sa-kuzu-")) / "g")

    def _counts(self, graph_dir: str) -> dict:
        from session_analytics.graph import query
        from session_analytics.graph.schema import GraphDatabase

        gdb = GraphDatabase.connect(graph_dir)
        try:
            counts = dict(query.node_counts(gdb))
            for rel in ("HAS_TURN", "FOLLOWED_BY", "INVOKED", "ACCESSED_FILE",
                        "PRODUCED_ERROR", "RAN_ON", "BY_DEVELOPER", "USED_MODEL", "IN_WORKSPACE"):
                res = gdb.execute(f"MATCH ()-[r:{rel}]->() RETURN count(r)")
                counts[rel] = int(res.get_next()[0])
            return counts
        finally:
            gdb.close()

    def test_csv_escaping_round_trips(self) -> None:
        # The one real gotcha: a quote, a comma, a backslash and a newline
        # in a value must survive CSV → COPY (newlines become spaces —
        # Kùzu's parallel reader refuses quoted newlines).
        from session_analytics.graph.builder import build
        from session_analytics.graph.schema import GraphDatabase

        nasty = 'He said "no", then\nleft \\ quietly'
        rel = Database.connect(self.dsn)
        try:
            rel.execute("UPDATE copilot_error SET error_type = ?", (nasty,))
            rel.commit()
            graph_dir = self._graph_dir()
            build(rel, graph_dir, rebuild=True)
        finally:
            rel.close()
        gdb = GraphDatabase.connect(graph_dir)
        try:
            res = gdb.execute("MATCH (e:ErrorNode) RETURN e.error_type")
            value = res.get_next()[0]
        finally:
            gdb.close()
        self.assertEqual(value, 'He said "no", then left \\ quietly')

    def test_incremental_build_matches_bulk(self) -> None:
        from session_analytics.graph.builder import build

        rel = Database.connect(self.dsn)
        try:
            bulk_dir, inc_dir = self._graph_dir(), self._graph_dir()
            bulk = build(rel, bulk_dir, rebuild=True)
            sid = int(rel.query_one("SELECT id FROM copilot_session")[0])
            inc = build(rel, inc_dir, session_ids=[sid])
        finally:
            rel.close()
        self.assertEqual(bulk.as_dict(), inc.as_dict())
        self.assertEqual(self._counts(bulk_dir), self._counts(inc_dir))
        self.assertGreater(self._counts(bulk_dir)["FOLLOWED_BY"], 0)

    def test_noise_can_be_left_out(self) -> None:
        from session_analytics.config import NoiseConfig
        from session_analytics.graph.builder import build

        rel = Database.connect(self.dsn)
        try:
            rel.execute(
                "INSERT INTO copilot_session (copilot, session_id, project_path, turn_count, "
                "tool_call_count, error_count, duration_seconds, developer_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (C.COPILOT_CLAUDE_CODE, "probe-1", "/tmp/cct-probe.x", 2, 0, 0, 3,
                 C.DEFAULT_DEVELOPER_ID),
            )
            rel.commit()
            everything = build(rel, self._graph_dir(), rebuild=True)
            kept = build(
                rel, self._graph_dir(), rebuild=True,
                noise=NoiseConfig(min_turns=3, min_duration_seconds=0, path_patterns=("/cct-probe",)),
            )
        finally:
            rel.close()
        self.assertEqual(everything.sessions, 2)   # parity: every session by default
        self.assertEqual(kept.sessions, 1)
